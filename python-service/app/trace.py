# -*- coding: utf-8 -*-
"""全链路追踪：把一次问答拆成 span 树，落库 ops.db。

要解决的实际问题
----------------
当前 `app/metrics.py` 只记录**请求级**聚合数据（总延迟、Token、成功率），
出问题时无法回答这些问题：

- 这次 2000ms 花在哪？是检索慢、工具慢，还是 LLM 慢？
- 哪一步触发了重试 / 熔断降级？
- 检索召回了什么片段？最终注入 prompt 的是哪几段？被预算裁掉了多少？
- 这次请求的上下文里有多少 Token 被历史消息占掉？

本模块提供**跨度（span）级**追踪：

    trace (一次问答)
      ├── span: retrieval   检索耗时 / 召回数 / 命中章节
      ├── span: tool        工具名 / 耗时 / 是否降级 / 重试次数
      ├── span: context     上下文预算 / 裁剪统计 / Token 估算
      └── span: llm         模型名 / prompt & completion token / 耗时

数据落在 `ops.db` 的 `trace_spans` 表（与 `request_logs` 同库、同文件）。

设计原则
--------
1. **不侵入主流程**：用 context manager，异常安全；写库失败绝不影响回答。
2. **可关联**：同一个 trace 的所有 span 共享 trace_id。
3. **零依赖**：不引 OpenTelemetry，纯 SQLite 实现（本项目是单机部署，
   引入 OT collector 带来的运维成本大于收益）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(__file__).resolve().parents[1] / "ops.db"

_lock = threading.Lock()
_init_lock = threading.Lock()
_initialized = False


# --------------------------------------------------------------------------
# 表结构
# --------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    name TEXT NOT NULL,
    span_type TEXT,
    start_ms REAL NOT NULL,
    duration_ms REAL NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    attributes TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_spans_trace ON trace_spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_spans_name ON trace_spans(name);
CREATE INDEX IF NOT EXISTS idx_trace_spans_ts ON trace_spans(ts);
"""


def _ensure_schema() -> None:
    """首次调用时建表（进程内只做一次）。"""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        try:
            with _lock:
                conn = sqlite3.connect(str(DB_PATH), timeout=5)
                try:
                    conn.executescript(_SCHEMA)
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass  # 建表失败不影响主流程
        _initialized = True


def _write_span(row: tuple) -> None:
    """写入一条 span（失败静默）。"""
    try:
        _ensure_schema()
        with _lock:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            try:
                conn.execute(
                    "INSERT INTO trace_spans (trace_id, span_id, parent_span_id, name,"
                    " span_type, start_ms, duration_ms, status, error, attributes, ts)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    row,
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Span / Trace
# --------------------------------------------------------------------------


@dataclass
class Span:
    """一个操作跨度。"""

    name: str
    span_type: str = "step"
    parent_span_id: str | None = None
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    start_ms: float = 0.0
    duration_ms: float = 0.0
    status: str = "ok"
    error: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        """记录一个属性。"""
        self.attributes[key] = value

    def set_all(self, data: dict[str, Any]) -> None:
        self.attributes.update(data or {})

    def fail(self, error: str | BaseException) -> None:
        self.status = "error"
        self.error = str(error)[:300]

    def to_row(self, trace_id: str) -> tuple:
        return (
            trace_id,
            self.span_id,
            self.parent_span_id,
            self.name,
            self.span_type,
            self.start_ms,
            self.duration_ms,
            self.status,
            self.error[:300] if self.error else None,
            json.dumps(self.attributes, ensure_ascii=False, default=str),
            time.time(),
        )


class Trace:
    """一次请求的追踪上下文。

    用法::

        with Trace("chat", session_id=sid) as tr:
            with tr.span("retrieval", "retrieval") as sp:
                sp.set("hits", 3)
    """

    def __init__(self, name: str, session_id: str = "", mode: str = "",
                 trace_id: str | None = None, enabled: bool = True):
        self.name = name
        self.session_id = session_id
        self.mode = mode
        self.trace_id = trace_id or uuid.uuid4().hex[:16]
        self.enabled = enabled
        self.spans: list[Span] = []
        # 正在执行中的 span 栈（用于建立父子关系）。
        # 不能用 self.spans 取父节点 —— span 只在退出时才入列，
        # 嵌套时内层 span 看不到尚未退出的外层 span。
        self._stack: list[Span] = []
        self._lock = threading.Lock()
        self._start = time.perf_counter()

    # -- span 上下文管理 ---------------------------------------------------

    @contextmanager
    def span(self, name: str, span_type: str = "step") -> Iterator[Span]:
        """开一个 span；退出时自动记耗时并落库。"""
        sp = Span(name=name, span_type=span_type,
                  parent_span_id=self._stack[-1].span_id if self._stack else None)
        sp.start_ms = (time.perf_counter() - self._start) * 1000
        self._stack.append(sp)
        try:
            yield sp
        except BaseException as exc:  # noqa: BLE001
            sp.fail(exc)
            raise
        finally:
            sp.duration_ms = (time.perf_counter() - self._start) * 1000 - sp.start_ms
            if self._stack and self._stack[-1] is sp:
                self._stack.pop()
            with self._lock:
                self.spans.append(sp)
            if self.enabled:
                _write_span(sp.to_row(self.trace_id))

    # -- 便捷记录 ----------------------------------------------------------

    def record(self, name: str, span_type: str = "step", **attrs: Any) -> Span:
        """记录一个已完成、零耗时的 span（如统计类信息）。"""
        sp = Span(name=name, span_type=span_type)
        sp.set_all(attrs)
        with self._lock:
            self.spans.append(sp)
        if self.enabled:
            _write_span(sp.to_row(self.trace_id))
        return sp

    # -- 汇总 --------------------------------------------------------------

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000

    def summary(self) -> dict[str, Any]:
        """一次请求的 span 汇总（用于写 request_logs 与离线分析）。"""
        by_type: dict[str, dict[str, Any]] = {}
        for sp in self.spans:
            item = by_type.setdefault(sp.span_type, {"count": 0, "totalMs": 0.0, "errors": 0})
            item["count"] += 1
            item["totalMs"] += sp.duration_ms
            if sp.status == "error":
                item["errors"] += 1
        for item in by_type.values():
            item["totalMs"] = round(item["totalMs"], 2)
        return {
            "traceId": self.trace_id,
            "name": self.name,
            "mode": self.mode,
            "sessionId": self.session_id,
            "totalMs": round(self.total_ms, 2),
            "spanCount": len(self.spans),
            "byType": by_type,
            "errors": sum(1 for sp in self.spans if sp.status == "error"),
        }

    def __enter__(self) -> "Trace":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False  # 不吞异常


# --------------------------------------------------------------------------
# 查询接口（给运维接口 / 离线分析用）
# --------------------------------------------------------------------------


def get_trace(trace_id: str) -> dict[str, Any]:
    """取一个 trace 的完整 span 树。"""
    _ensure_schema()
    out: dict[str, Any] = {"traceId": trace_id, "spans": []}
    try:
        with _lock:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            try:
                rows = conn.execute(
                    "SELECT span_id, parent_span_id, name, span_type, start_ms,"
                    " duration_ms, status, error, attributes FROM trace_spans"
                    " WHERE trace_id=? ORDER BY start_ms", (trace_id,)).fetchall()
            finally:
                conn.close()
        for r in rows:
            try:
                attrs = json.loads(r[8]) if r[8] else {}
            except Exception:
                attrs = {}
            out["spans"].append({
                "spanId": r[0], "parentSpanId": r[1], "name": r[2], "type": r[3],
                "startMs": round(r[4], 2), "durationMs": round(r[5], 2),
                "status": r[6], "error": r[7], "attributes": attrs,
            })
    except Exception:
        pass
    return out


def recent_traces(limit: int = 20) -> list[dict[str, Any]]:
    """最近 N 条 trace 的汇总。"""
    _ensure_schema()
    out: list[dict[str, Any]] = []
    try:
        with _lock:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            try:
                rows = conn.execute(
                    "SELECT trace_id, name, span_type, MIN(start_ms),"
                    " SUM(duration_ms), COUNT(*), SUM(status='error')"
                    " FROM trace_spans GROUP BY trace_id"
                    " ORDER BY MIN(ts) DESC LIMIT ?", (limit,)).fetchall()
            finally:
                conn.close()
        for r in rows:
            out.append({
                "traceId": r[0], "name": r[1], "mode": r[2],
                "totalSpanMs": round(r[4] or 0, 2), "spanCount": r[5],
                "errors": r[6] or 0,
            })
    except Exception:
        pass
    return out


def slow_spans(threshold_ms: float = 500.0, limit: int = 20) -> list[dict[str, Any]]:
    """找出耗时超过阈值的 span（定位性能瓶颈用）。"""
    _ensure_schema()
    out: list[dict[str, Any]] = []
    try:
        with _lock:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            try:
                rows = conn.execute(
                    "SELECT trace_id, name, span_type, duration_ms, status, attributes"
                    " FROM trace_spans WHERE duration_ms >= ?"
                    " ORDER BY duration_ms DESC LIMIT ?", (threshold_ms, limit)).fetchall()
            finally:
                conn.close()
        for r in rows:
            try:
                attrs = json.loads(r[5]) if r[5] else {}
            except Exception:
                attrs = {}
            out.append({
                "traceId": r[0], "name": r[1], "type": r[2],
                "durationMs": round(r[3], 2), "status": r[4], "attributes": attrs,
            })
    except Exception:
        pass
    return out


def stats() -> dict[str, Any]:
    """按 span 类型聚合的耗时画像。"""
    _ensure_schema()
    try:
        with _lock:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            try:
                rows = conn.execute(
                    "SELECT span_type, COUNT(*), AVG(duration_ms), MAX(duration_ms),"
                    " SUM(status='error') FROM trace_spans GROUP BY span_type").fetchall()
            finally:
                conn.close()
        return {
            r[0]: {
                "count": r[1],
                "avgMs": round(r[2] or 0, 2),
                "maxMs": round(r[3] or 0, 2),
                "errors": r[4] or 0,
            } for r in rows
        }
    except Exception:
        return {}


def clear() -> None:
    """清空 span 表（测试用）。"""
    _ensure_schema()
    try:
        with _lock:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            try:
                conn.execute("DELETE FROM trace_spans")
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass
