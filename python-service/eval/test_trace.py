# -*- coding: utf-8 -*-
"""app/trace.py 单测：span 记录、异常安全、父子关系、查询接口。

零 API 消耗（不调 LLM）。
    python python-service/eval/test_trace.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# ★ 必须在 import app.trace 之前设置：把单测的 span 写到临时库，
#   否则单测数据会污染生产 ops.db，观测面板上全是 name="a" 的脏数据。
_TMP_DB = Path(tempfile.gettempdir()) / "smartsupport-test-trace.db"
os.environ["SMART_OPS_DB"] = str(_TMP_DB)
if _TMP_DB.exists():
    _TMP_DB.unlink()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import trace as tr  # noqa: E402


# --------------------------------------------------------------------------
# Trace 基本行为
# --------------------------------------------------------------------------

def test_trace_generates_trace_id():
    t = tr.Trace("chat")
    assert len(t.trace_id) == 16
    assert t.trace_id


def test_trace_ids_are_unique():
    a = tr.Trace("chat")
    b = tr.Trace("chat")
    assert a.trace_id != b.trace_id


def test_trace_accepts_explicit_trace_id():
    t = tr.Trace("chat", trace_id="abc123")
    assert t.trace_id == "abc123"


def test_span_records_attributes():
    t = tr.Trace("chat")
    with t.span("retrieval", "retrieval") as sp:
        sp.set("hits", 3)
        sp.set("topK", 5)
    assert t.spans[0].attributes["hits"] == 3
    assert t.spans[0].attributes["topK"] == 5


def test_span_set_all():
    t = tr.Trace("chat")
    with t.span("s") as sp:
        sp.set_all({"a": 1, "b": 2})
    assert t.spans[0].attributes == {"a": 1, "b": 2}


def test_span_has_positive_duration():
    t = tr.Trace("chat")
    with t.span("slow"):
        time.sleep(0.01)
    assert t.spans[0].duration_ms >= 5


def test_nested_spans_have_parent():
    t = tr.Trace("chat")
    with t.span("outer", "step"):
        with t.span("inner", "step"):
            pass
    # span 在退出时才入列，所以内层先出现
    by_name = {sp.name: sp for sp in t.spans}
    outer, inner = by_name["outer"], by_name["inner"]
    assert inner.parent_span_id == outer.span_id
    assert outer.parent_span_id is None


def test_top_level_span_has_no_parent():
    t = tr.Trace("chat")
    with t.span("a"):
        pass
    assert t.spans[0].parent_span_id is None


def test_root_span_is_parent_of_all_children():
    """根 span 让整棵 span 树有根节点，否则各阶段 span 是平级孤儿。"""
    t = tr.Trace("rag_chat")
    with t.root_span("agent"):
        with t.span("retrieval", "retrieval"):
            pass
        with t.span("context", "context"):
            pass
        with t.span("llm", "llm"):
            pass
    by_name = {sp.name: sp for sp in t.spans}
    root = by_name["rag_chat"]
    assert root.parent_span_id is None
    for child in ("retrieval", "context", "llm"):
        assert by_name[child].parent_span_id == root.span_id


def test_root_span_records_duration_and_attributes():
    t = tr.Trace("rag_chat")
    with t.root_span("agent") as root:
        root.set("question", "运费谁承担")
        time.sleep(0.01)
    root = t.spans[-1]
    assert root.span_type == "agent"
    assert root.duration_ms > 0
    assert root.attributes["question"] == "运费谁承担"


def test_root_span_captures_child_error_and_reraises():
    t = tr.Trace("rag_chat")
    try:
        with t.root_span("agent"):
            with t.span("llm", "llm"):
                raise RuntimeError("boom")
    except RuntimeError:
        pass
    else:
        raise AssertionError("应向上抛出")
    root = t.spans[-1]
    assert root.status == "error"


def test_span_exception_marks_error_and_reraises():
    t = tr.Trace("chat")
    raised = False
    try:
        with t.span("boom") as sp:
            raise ValueError("坏了")
    except ValueError:
        raised = True
    assert raised, "异常必须继续向上抛，不能被 trace 吞掉"
    assert t.spans[0].status == "error"
    assert "坏了" in t.spans[0].error


def test_span_fail_helper():
    t = tr.Trace("chat")
    with t.span("x") as sp:
        sp.fail("手���标记失败")
    assert t.spans[0].status == "error"
    assert t.spans[0].error == "手���标记失败"


def test_record_creates_zero_duration_span():
    t = tr.Trace("chat")
    sp = t.record("info", "context", hits=5)
    assert sp.attributes["hits"] == 5
    assert t.spans[0].name == "info"


def test_summary_counts_by_type():
    t = tr.Trace("chat")
    with t.span("a", "retrieval"):
        pass
    with t.span("b", "retrieval"):
        pass
    with t.span("c", "llm"):
        pass
    s = t.summary()
    assert s["spanCount"] == 3
    assert s["byType"]["retrieval"]["count"] == 2
    assert s["byType"]["llm"]["count"] == 1
    assert s["errors"] == 0


def test_summary_counts_errors():
    t = tr.Trace("chat")
    try:
        with t.span("boom"):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    assert t.summary()["errors"] == 1


def test_disabled_trace_does_not_write_db():
    """enabled=False 时不落库，但内存里的 span 仍可统计。"""
    t = tr.Trace("chat", enabled=False)
    with t.span("x"):
        pass
    assert len(t.spans) == 1


def test_trace_context_manager_returns_self():
    with tr.Trace("chat") as t:
        assert isinstance(t, tr.Trace)


def test_trace_context_manager_does_not_swallow_exception():
    caught = False
    try:
        with tr.Trace("chat"):
            raise KeyError("k")
    except KeyError:
        caught = True
    assert caught


# --------------------------------------------------------------------------
# 落库与查询
# --------------------------------------------------------------------------

def test_spans_persist_and_are_queryable():
    t = tr.Trace("testpersist", mode="unit")
    with t.span("retrieval", "retrieval") as sp:
        sp.set("hits", 7)
    with t.span("llm", "llm"):
        pass

    got = tr.get_trace(t.trace_id)
    assert len(got["spans"]) == 2
    names = {s["name"] for s in got["spans"]}
    assert names == {"retrieval", "llm"}
    ret = [s for s in got["spans"] if s["name"] == "retrieval"][0]
    assert ret["attributes"]["hits"] == 7
    assert ret["type"] == "retrieval"


def test_get_trace_unknown_returns_empty():
    got = tr.get_trace("nonexistent_trace_id")
    assert got["spans"] == []


def test_error_span_persists_status():
    t = tr.Trace("testerror")
    try:
        with t.span("boom"):
            raise ValueError("数据库炸了")
    except ValueError:
        pass
    got = tr.get_trace(t.trace_id)
    sp = got["spans"][0]
    assert sp["status"] == "error"
    assert "数据库炸了" in sp["error"]


def test_recent_traces_includes_trace():
    t = tr.Trace("testrecent")
    with t.span("x"):
        pass
    ids = [x["traceId"] for x in tr.recent_traces(limit=50)]
    assert t.trace_id in ids


def test_slow_spans_finds_long_spans():
    t = tr.Trace("testslow")
    with t.span("slowspan", "retrieval"):
        time.sleep(0.05)
    found = tr.slow_spans(threshold_ms=20, limit=50)
    assert any(x["traceId"] == t.trace_id for x in found)


def test_stats_has_span_types():
    t = tr.Trace("teststats")
    with t.span("a", "retrieval"):
        pass
    s = tr.stats()
    assert "retrieval" in s
    assert s["retrieval"]["count"] >= 1
    assert s["retrieval"]["avgMs"] >= 0


def test_clear_empties_table():
    """clear() 清空后，新 trace 之前写入的记录应查不到。"""
    t = tr.Trace("beforeclear")
    with t.span("x"):
        pass
    assert len(tr.get_trace(t.trace_id)["spans"]) == 1

    tr.clear()
    assert tr.get_trace(t.trace_id)["spans"] == []

    # 清空后再写新 span 仍应正常
    t2 = tr.Trace("afterclear")
    with t2.span("y"):
        pass
    assert len(tr.get_trace(t2.trace_id)["spans"]) == 1


def _run_all():
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in fns:
        try:
            fn()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\ntest_trace: {passed} passed, {failed} failed (total {len(fns)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
