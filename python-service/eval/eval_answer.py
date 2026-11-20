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

# ------------------------------------------------------------------
# 事件循环管理（ReAct 模式）
#
# workflow._react 是模块级全局 create_react_agent 实例，内部持有与
# LLM 客户端绑定的异步资源。若每条用例都用 asyncio.run()，会反复创建
# 并关闭事件循环，第 2 条用例起就会抛 "Event loop is closed"。
# 因此这里改为：整个评测共用一个 loop，loop 在整个进程存活期内不关闭。
# ------------------------------------------------------------------
_loop = None


def get_loop():
    """返回进程级共享的事件循环（懒创建，不关闭）。"""
    global _loop
    if _loop is None or _loop.is_closed():
        import asyncio
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_coroutine(coro):
    """在共享 loop 上执行协程。loop 已关闭时重建一次。"""
    loop = get_loop()
    try:
        return loop.run_until_complete(coro)
    except RuntimeError as exc:
        if "Event loop is closed" not in str(exc):
            raise
        global _loop
        _loop = None
        loop = get_loop()
        return loop.run_until_complete(coro)

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


def _tool_rule_ok(case: dict, actual: list, mode: str) -> bool:
    """判断工具选型是否符合该用例在当前链路下的预期。

    两种链路的语义不同，不能用同一把尺子：
    - rag（固定管线）：先检索再生成，政策类问题由管线内部检索，
      不产生工具调用记录，所以 policy/colloquial 期望 actual 为空。
    - react（自主规划）：模型自己决定调什么工具。政策类问题调用
      searchPolicyKnowledge 是正确行为（不调也算对，模型可能直接凭知识回答），
      因此不能要求 actual 为空。

    规则：
      1. 用例声明了 expected_tool → 必须命中该工具
      2. policy / colloquial 类 → 允许且仅允许调用检索类工具
      3. out_of_scope 类 → 不应调用业务数据工具；
         调用检索工具是合理的「确认知识库确实没有」步骤，予以允许
         （越界场景真正要防的是订单/退款等真实数据被喂给模型）
    """
    exp = case.get("expected_tool", "")
    if exp:
        return exp in actual

    category = case.get("category", "")
    if category in ("policy", "colloquial"):
        if mode == "react":
            # 自主规划链路：调检索工具是正确行为，只禁止调业务数据工具
            return all(t == "searchPolicyKnowledge" for t in actual)
        # 固定管线链路：检索在管线内部完成，不应出现工具调用
        return len(actual) == 0

    # out_of_scope 及其它：禁止业务数据工具，允许检索工具（用于确认知识库无覆盖）
    return all(t == "searchPolicyKnowledge" for t in actual)


# ------------------------------------------------------------------
# 致命错误识别
#
# 余额不足 / Key 失效 / 限流 这类错误，继续跑剩余用例只会白白消耗请求
# 并让结果看起来像"模型能力不行"。遇到这类错误应立即中止整轮评测。
# ------------------------------------------------------------------
FATAL_MARKERS = (
    "Insufficient Balance",
    "insufficient balance",
    "402",
    "401",
    "invalid_api_key",
    "Authentication Fails",
    "429",
    "Rate Limit",
    "rate_limit",
)


def is_fatal_error(exc: Exception) -> bool:
    """判断异常是否为「继续跑也没用」的环境级致命错误。"""
    msg = str(exc)
    return any(m in msg for m in FATAL_MARKERS)


def _call_with_retry(fn, retries: int = 2, delay: float = 2.0):
    """调用 fn，遇瞬时错误（限流/网络抖动）退避重试。

    致命错误直接抛出，不重试。
    """
    import time as _t
    last = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if is_fatal_error(exc):
                raise
            if attempt < retries:
                _t.sleep(delay * (attempt + 1))
    raise last


def run_case(c: dict, mode: str):
    q, sid = c["question"], "eval-" + uuid.uuid4().hex[:8]
    t0 = time.time()
    try:
        if mode == "react":
            reply, tool_events = run_coroutine(workflow.run_react(q, sid))
            sources, rag_hit = [], True
        else:
            reply, sources, rag_hit, tool_events, _u = _call_with_retry(
                lambda: agent.chat_once(q, sid))
        dt = (time.time() - t0) * 1000
        actual = sorted({e.get("toolName", "") for e in tool_events if e.get("stage") == "start"})
        exp = c.get("expected_tool", "")
        tool_ok_rule = _tool_rule_ok(c, actual, mode)
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
                "error": str(e)[:300], "fatal": is_fatal_error(e),
                "latencyMs": round((time.time() - t0) * 1000, 1)}


def main():
    mode = "rag"
    for a in sys.argv[1:]:
        if a.startswith("--mode="):
            mode = a.split("=", 1)[1]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    print(f"answer-eval: mode={mode} cases={len(cases)}")
    rows = []
    aborted = False
    for c in cases:
        r = run_case(c, mode)
        rows.append(r)
        j = r.get("judge", {})
        print(f"{r['id']} ok={r.get('success')} faithful={j.get('faithful')} "
              f"toolRule={r.get('toolRuleOk')} refusedOk={r.get('refusedOk')} "
              f"lat={r.get('latencyMs')}ms tools={r.get('actualTools')}")
        # 致命错误（余额不足/Key 失效/限流）：立即中止，
        # 否则剩余用例只会继续失败，把环境问题伪装成模型能力问题。
        if r.get("fatal"):
            print(f"\n[FATAL] 用例 {r['id']} 触发致命错误：{r.get('error')}")
            print("[FATAL] 中止本轮评测，剩余 %d 条用例未执行。" % (len(cases) - len(rows)))
            aborted = True
            break
    ok_rows = [r for r in rows if r.get("success")]
    oos = [r for r in ok_rows if any(c["id"] == r["id"] and c.get("should_refuse") for c in cases)]
    summary = {
        "mode": mode,
        "total": len(cases),
        "executed": len(rows),
        "success": len(ok_rows),
        "aborted": aborted,
        "faithfulRate": round(sum(r.get("judge", {}).get("faithful", 0) for r in ok_rows) / max(len(ok_rows), 1), 4),
        "toolRuleRate": round(sum(1 for r in ok_rows if r.get("toolRuleOk")) / max(len(ok_rows), 1), 4),
        "refuseRate": round(sum(1 for r in oos if r.get("refusedOk")) / max(len(oos), 1), 4) if oos else None,
        "avgLatencyMs": round(sum(r.get("latencyMs", 0) for r in ok_rows) / max(len(ok_rows), 1), 1),
    }
    print("SUMMARY:", json.dumps(summary, ensure_ascii=False))
    if aborted:
        print("[WARN] 本轮结果不完整，不可用于基线对比。")
    # 按 mode 分别落盘：rag 是 README/简历引用的生产基线，
    # react 结果单独存，避免覆盖掉 rag 的基线数据。
    out = Path(__file__).with_name(
        "eval-answer-result.json" if mode == "rag" else f"eval-answer-result-{mode}.json")
    out.write_text(json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
