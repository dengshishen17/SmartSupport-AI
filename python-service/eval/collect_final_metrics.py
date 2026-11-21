# -*- coding: utf-8 -*-
"""汇总所有评测结果，输出写简历要用的最终数字。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EVAL = Path(__file__).parent

out = {}

# ---- 1. 检索评测（75 条可答 + 15 条越界）----
p = EVAL / "eval-retrieval-result.json"
if p.exists():
    d = json.loads(p.read_text(encoding="utf-8"))
    out["retrieval"] = {
        "topK": d.get("topK"), "caseSet": d.get("caseSet"),
        "modes": [{k: v for k, v in r.items() if k not in ("cases", "oos", "perCategory")}
                  for r in d.get("results", [])],
    }

# ---- 2. Agent 轨迹评测（114 条）----
p = EVAL / "eval-agent-result-react.json"
if p.exists():
    d = json.loads(p.read_text(encoding="utf-8"))
    s = d["summary"]
    out["agent"] = {
        "total": s.get("total"), "success": s.get("success"),
        "passAt1": s.get("passAt1"), "passAt3": s.get("passAt3"),
        "faithfulRate": s.get("faithfulRate"),
        "avgSteps": s.get("avgSteps"), "totalToolCalls": s.get("totalToolCalls"),
        "invalidCalls": s.get("invalidCalls"), "wastedCalls": s.get("wastedCalls"),
        "avgLatencyMs": s.get("avgLatencyMs"),
        "degradedToolCalls": s.get("degradedToolCalls"),
        "tokenUsage": s.get("tokenUsage"),
        "failureTaxonomy": s.get("failureTaxonomy"),
        "stepsDistribution": s.get("stepsDistribution"),
        "perCategory": s.get("perCategory"),
    }

# ---- 3. Prompt 回归比对 ----
p = EVAL / "eval-prompt-regression-result.json"
if p.exists():
    d = json.loads(p.read_text(encoding="utf-8"))
    out["promptRegression"] = {
        "baseline": d.get("baseline"), "candidate": d.get("candidate"),
        "rounds": d.get("rounds"),
        "metrics": d.get("metrics"), "summary": d.get("summary"),
    }

# ---- 4. Trace span 统计 ----
p = Path(__file__).resolve().parents[1] / "ops.db"
if p.exists():
    import sqlite3
    conn = sqlite3.connect(str(p))
    try:
        rows = conn.execute(
            "SELECT span_type, COUNT(*), AVG(duration_ms), MAX(duration_ms),"
            " SUM(status='error') FROM trace_spans GROUP BY span_type").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM trace_spans").fetchone()[0]
        out["trace"] = {"totalSpans": total,
                        "byType": {r[0]: {"count": r[1], "avgMs": round(r[2] or 0, 2),
                                          "maxMs": round(r[3] or 0, 2), "errors": r[4] or 0}
                                   for r in rows}}
    finally:
        conn.close()

# ---- 5. 上下文压缩实测：从 trace 里找 context_compress span ----
if p.exists():
    import sqlite3
    conn = sqlite3.connect(str(p))
    try:
        rows = conn.execute(
            "SELECT attributes FROM trace_spans WHERE name='context_compress'").fetchall()
        if rows:
            saved = []
            for (a,) in rows:
                try:
                    d = json.loads(a)
                    if d.get("originalTokens") and d.get("finalTokens"):
                        saved.append((d["originalTokens"], d["finalTokens"]))
                except Exception:
                    pass
            if saved:
                orig = sum(x[0] for x in saved)
                fin = sum(x[1] for x in saved)
                out["contextCompression"] = {
                    "samples": len(saved),
                    "origTokens": orig, "finalTokens": fin,
                    "savedTokens": orig - fin,
                    "savedRatio": round((orig - fin) / orig, 4) if orig else 0,
                }
    finally:
        conn.close()

print(json.dumps(out, ensure_ascii=False, indent=2))
(EVAL / "eval-final-metrics.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nsaved: {EVAL / 'eval-final-metrics.json'}")
