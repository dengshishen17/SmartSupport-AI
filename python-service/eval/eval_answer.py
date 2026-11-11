"""端到端生成质量评估：LLM-as-Judge。
30 条用例 = 政策问答(10) + 业务工具(12) + 越界拒答(4) + 口语化(4)。
指标：引用忠实度(是否编造)、拒答率(越界是否拒答)、工具选型准确率、平均延迟。
用法：python -m eval.eval_answer [--mode rag|react]  （需 MySQL/PG/DeepSeek/百炼全可用）
结果落盘 eval/eval-answer-result.json
"""
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openai import OpenAI  # noqa: E402
from app import agent, config, workflow  # noqa: E402

CASES_FILE = Path(__file__).with_name("answer-eval-cases.json")

_judge = OpenAI(api_key=config.DEEPSEEK_API_KEY or "dummy",
                base_url=config.DEEPSEEK_BASE_URL, timeout=60.0, max_retries=0)

JUDGE_PROMPT = """你是问答质量裁判。只输出一行 JSON，不要解释。
待评回答：【{reply}】
参考要点：{reference}
期望工具：{expected_tool}；实际调用工具：{actual_tools}

按下面规则打分：
- faithful: 1=回答内容被参考要点/工具结果支撑、无编造政策条款或数据；0=出现参考中没有的政策数字、编造订单状态/金额/时间
- refused: 1=明确说无法确认/建议转人工且没有编造；0=其他（仅当 should_refuse=1 时有意义，否则记 0）
- tool_correct: 1=该调工具时调对了(期望工具在实际调用中)、不该调时没调；0=否则

输出格式：{{"faithful": 0/1, "refused": 0/1, "tool_correct": 0/1}}
"""


def judge(reply: str, reference: str, expected_tool: str, actual_tools: list, should_refuse: bool) -> dict:
    prompt = JUDGE_PROMPT.format(reply=(reply or "")[:800], reference=reference,
                                 expected_tool=expected_tool or "无",
                                 actual_tools=",".join(actual_tools) or "无")
    try:
        r = _judge.chat.completions.create(model=config.DEEPSEEK_MODEL,
                                           messages=[{"role": "user", "content": prompt}],
                                           temperature=0.0, max_tokens=120)
        txt = (r.choices[0].message.content or "").strip()
        s, e = txt.find("{"), txt.rfind("}")
        d = json.loads(txt[s:e + 1])
        return {"faithful": int(d.get("faithful", 0)), "refused": int(d.get("refused", 0)),
                "tool_correct": int(d.get("tool_correct", 0))}
    except Exception as ex:
        return {"faithful": 0, "refused": 0, "tool_correct": 0, "judge_error": str(ex)[:200]}


def run_case(c: dict, mode: str):
    q, sid = c["question"], "eval-" + uuid.uuid4().hex[:8]
    t0 = time.time()
    try:
        if mode == "react":
            import asyncio
            reply, tool_events = asyncio.run(workflow.run_react(q, sid))
            sources, rag_hit = [], True
        else:
            reply, sources, rag_hit, tool_events, _u = agent.chat_once(q, sid)
        dt = (time.time() - t0) * 1000
        actual = sorted({e.get("toolName", "") for e in tool_events if e.get("stage") == "start"})
        exp = c.get("expected_tool", "")
        if exp:
            tool_ok_rule = exp in actual
        else:
            tool_ok_rule = len(actual) == 0
        j = judge(reply, c.get("reference", ""), exp, actual, c.get("should_refuse", False))
        # 越界用例：拒答以裁判为准；非越界：拒答项不计分
        refused_ok = (j["refused"] == 1) if c.get("should_refuse") else True
        return {"id": c["id"], "question": q, "reply": reply,
                "sources": sources, "ragHit": rag_hit,
                "actualTools": actual, "toolRuleOk": tool_ok_rule,
                "judge": j, "refusedOk": refused_ok,
                "latencyMs": round(dt, 1), "success": True}
    except Exception as e:
        return {"id": c["id"], "question": q, "reply": "", "success": False,
                "error": str(e)[:300], "latencyMs": round((time.time() - t0) * 1000, 1)}


def main():
    mode = "rag"
    for a in sys.argv[1:]:
        if a.startswith("--mode="):
            mode = a.split("=", 1)[1]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    print(f"answer-eval: mode={mode} cases={len(cases)}")
    rows = []
    for c in cases:
        r = run_case(c, mode)
        rows.append(r)
        j = r.get("judge", {})
        print(f"{r['id']} ok={r.get('success')} faithful={j.get('faithful')} "
              f"toolRule={r.get('toolRuleOk')} refusedOk={r.get('refusedOk')} "
              f"lat={r.get('latencyMs')}ms tools={r.get('actualTools')}")
    ok_rows = [r for r in rows if r.get("success")]
    oos = [r for r in ok_rows if any(c["id"] == r["id"] and c.get("should_refuse") for c in cases)]
    summary = {
        "mode": mode,
        "total": len(cases),
        "success": len(ok_rows),
        "faithfulRate": round(sum(r.get("judge", {}).get("faithful", 0) for r in ok_rows) / max(len(ok_rows), 1), 4),
        "toolRuleRate": round(sum(1 for r in ok_rows if r.get("toolRuleOk")) / max(len(ok_rows), 1), 4),
        "refuseRate": round(sum(1 for r in oos if r.get("refusedOk")) / max(len(oos), 1), 4) if oos else None,
        "avgLatencyMs": round(sum(r.get("latencyMs", 0) for r in ok_rows) / max(len(ok_rows), 1), 1),
    }
    print("SUMMARY:", json.dumps(summary, ensure_ascii=False))
    out = Path(__file__).with_name("eval-answer-result.json")
    out.write_text(json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
