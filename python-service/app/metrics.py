"""可观测性：每次问答落库 SQLite，统计延迟/Token/成功率/工具调用。
DB 文件 python-service/ops.db，表 request_logs。失败也不影响主流程。
"""
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "ops.db"
_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS request_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            mode TEXT NOT NULL,
            session_id TEXT,
            question TEXT,
            latency_ms REAL,
            rag_hit INTEGER,
            tool_count INTEGER,
            success INTEGER,
            error TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            reply_chars INTEGER
        )"""
    )
    conn.commit()
    return conn


def log_call(mode: str, session_id: str, question: str, latency_ms: float,
             rag_hit: bool, tool_count: int, success: bool, error: str = "",
             prompt_tokens: int = 0, completion_tokens: int = 0, reply_chars: int = 0):
    try:
        with _lock:
            conn = _conn()
            try:
                conn.execute(
                    "INSERT INTO request_logs (ts, mode, session_id, question, latency_ms, rag_hit,"
                    " tool_count, success, error, prompt_tokens, completion_tokens, total_tokens, reply_chars)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (time.time(), mode, session_id, (question or "")[:200], latency_ms,
                     1 if rag_hit else 0, tool_count, 1 if success else 0, (error or "")[:300],
                     prompt_tokens, completion_tokens, prompt_tokens + completion_tokens, reply_chars),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass


def stats() -> dict:
    with _lock:
        conn = _conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM request_logs").fetchone()[0]
            if not total:
                return {"total": 0}
            ok = conn.execute("SELECT COUNT(*) FROM request_logs WHERE success=1").fetchone()[0]
            row = conn.execute(
                "SELECT AVG(latency_ms), AVG(total_tokens), SUM(total_tokens),"
                " AVG(tool_count), AVG(rag_hit) FROM request_logs").fetchone()
            lats = [r[0] for r in conn.execute(
                "SELECT latency_ms FROM request_logs ORDER BY latency_ms").fetchall()]
            toks = [r[0] for r in conn.execute(
                "SELECT total_tokens FROM request_logs ORDER BY total_tokens").fetchall()]

            def pct(arr, p):
                if not arr:
                    return 0
                i = min(len(arr) - 1, int(len(arr) * p / 100))
                return round(arr[i], 1)

            by_mode = {}
            for mode, n, avg_lat, succ in conn.execute(
                    "SELECT mode, COUNT(*), AVG(latency_ms),"
                    " SUM(success)*1.0/COUNT(*) FROM request_logs GROUP BY mode"):
                by_mode[mode] = {"count": n, "avgLatencyMs": round(avg_lat or 0, 1),
                                 "successRate": round((succ or 0), 4)}
            fails = conn.execute(
                "SELECT error, COUNT(*) c FROM request_logs WHERE success=0 AND error<>''"
                " GROUP BY error ORDER BY c DESC LIMIT 5").fetchall()
            return {
                "total": total,
                "successRate": round(ok / total, 4),
                "avgLatencyMs": round(row[0] or 0, 1),
                "p50LatencyMs": pct(lats, 50),
                "p95LatencyMs": pct(lats, 95),
                "avgTokens": round(row[1] or 0, 1),
                "totalTokens": int(row[2] or 0),
                "p95Tokens": pct(toks, 95),
                "avgToolCalls": round(row[3] or 0, 2),
                "ragHitRate": round(row[4] or 0, 4),
                "byMode": by_mode,
                "topErrors": [{"error": e, "count": c} for e, c in fails],
            }
        finally:
            conn.close()


def recent(limit: int = 20) -> list[dict]:
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT ts, mode, session_id, question, latency_ms, rag_hit, tool_count,"
                " success, error, total_tokens, reply_chars FROM request_logs"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [{"ts": ts, "mode": mode, "sessionId": sid, "question": q,
                     "latencyMs": round(lat or 0, 1), "ragHit": bool(rag),
                     "toolCount": tc, "success": bool(succ), "error": err,
                     "totalTokens": tok, "replyChars": rc}
                    for ts, mode, sid, q, lat, rag, tc, succ, err, tok, rc in rows]
        finally:
            conn.close()
