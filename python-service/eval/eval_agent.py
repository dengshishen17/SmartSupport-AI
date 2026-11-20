# -*- coding: utf-8 -*-
"""Agent 轨迹级评测：评估 ReAct Agent 的「过程质量」，而不只是最终回答质量。

与 eval_answer.py 的区别
------------------------
- eval_answer.py 只看**结果**：最终回答是否忠实、是否正确拒答、工具选型是否符合预期
- 本脚本看**过程**：Agent 走了几步、调了哪些工具、有没有无效调用、
  在哪一步失败、失败属于哪一类

为什么必须分开评估
------------------
只看结果会有「蒙对」与「走对」混为一谈：
一个 Agent 可能第一步检索为空、但模型凭知识答对了（结果对、过程错）；
也可能调了 5 次工具才凑出正确回答（结果对、过程低效）。
60% 的国内 AI JD 明确要求评测能力，这个层次的能力是区分「会调 API」和「会做 Agent」的关键。

指标体系
--------
任务级：
    pass@1        首轮即产出正确回答（LLM-as-Judge 判定忠实）
    pass@3        允许 3 步内收敛仍判正确
    avgSteps      平均工具调用步数
    stepsDist     步数分布直方图
调用级：
    totalCalls      工具调用总数
    validCalls      有效调用数（工具存在 + 参数合法 + 执行成功）
    invalidRate     无效调用率
    wastedCalls     无效/冗余调用数（重复调同工具同参数、越界问题调业务工具）
失败归类（taxonomy）：
    RETRIEVAL_EMPTY   检索为空
    TOOL_ERROR        工具执行报错
    INVALID_ARGS      参数非法或缺失
    DUPLICATE_CALL    同一工具同一参数重复调用
    LOOP              连续多次相似调用形成循环
    MAX_STEP          超出步数上限未收敛
    HALLUCINATION     编造政策条款或业务数据
    REFUSAL_OVER      知识库有答案却拒答（过度拒答）
    REFUSAL_UNDER     知识库无答案却硬答（该拒未拒）

用法：python -m eval.eval_agent [--mode react|rag] [--max-steps 8]
结果落盘 eval/eval-agent-result.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402

CASES_FILE = Path(__file__).with_name("answer-eval-cases.json")

# --------------------------------------------------------------------------
# 工具元信息：合法参数名、是否业务数据工具、是否检索工具
# --------------------------------------------------------------------------
TOOL_SPECS = {
    "searchPolicyKnowledge": {"params": ["query"], "kind": "retrieval"},
    "queryOrderByOrderNo": {"params": ["orderNo"], "kind": "business"},
    "queryRefundByOrderNo": {"params": ["orderNo"], "kind": "business"},
    "queryTicketByOrderNo": {"params": ["orderNo"], "kind": "business"},
    "queryWarrantyByOrderNo": {"params": ["orderNo"], "kind": "business"},
}

# 工具返回里表示「没查到」的固定话术，用于识别「有效调用但无结果」
EMPTY_HINTS = (
    "没有检索到相关条文",
    "未找到订单号",
    "未找到订单号为",
    "没有检索到",
)

# 工具返回里表示「执行报错」的固定话术。
# 注意：必须用「异常」这类不可能出现在正常业务文本里的词做锚点，
# 否则知识库正文里的「异常」二字会误判为工具报错（实测踩过这个坑）。
ERROR_HINTS = (
    "库暂时不可用",
    "Traceback",
    "Error code:",
    "OperationalError",
    "NameError",
    "KeyError",
    "TypeError",
)


# --------------------------------------------------------------------------
# 单步轨迹
# --------------------------------------------------------------------------


def _has_substantive_answer(reply: str, reference: str) -> bool:
    """判断回答是否给出了实质信息（而非纯粹拒答）。

    做法：提取参考答案里的「关键特征词」——数字、金额、状态词、专有名词，
    检查回答里是否命中任意一条。

    为什么不用整句匹配：模型表述与参考要点的措辞天然不同
    （参考写「订单状态：运输中」，回答写「目前状态为"运输中"」），
    整句匹配会漏判。因此改用「数字/金额/关键词」这类稳定特征。

    用于区分两种情况：
      - 「无法确认，建议转人工」 + 零信息 -> 真正的过度拒答
      - 「订单10001 状态运输中，金额2999…如需物流轨迹建议转人工」 -> 正常兜底话术，不算拒答
    """
    if not reply or not reference:
        return False

    hay = reply.replace(" ", "")

    # 1) 参考要点里的数字（含金额、日期、编号、期限）是最强的实质信号
    nums = set(re.findall(r"\d+(?:\.\d+)?", reference))
    for n in nums:
        if len(n) >= 2 and n in hay:
            return True

    # 2) 没有数字时，退化为匹配较长的中文关键词
    phrases = [p.strip() for p in re.split(r"[、，,；;/／|]", reference) if len(p.strip()) >= 3]
    for ph in phrases:
        needle = ph.replace(" ", "")
        probe = needle[:4] if len(needle) > 4 else needle
        if probe and probe in hay:
            return True

    # 3) 兜底：回答明显长于一句纯拒答（纯拒答通常 < 30 字）
    return len(hay) >= 60


def _arg_signature(tool_name: str, args: dict) -> str:
    """把工具调用参数转成可比较的签名，用于识别重复调用。"""
    try:
        payload = json.dumps(args, sort_keys=True, ensure_ascii=False)
    except Exception:
        payload = str(args)
    return f"{tool_name}({payload})"


def _classify_call(tool_name: str, args: dict, result: str) -> str:
    """判断单次工具调用的状态。

    返回值取值：ok / unknown_tool / invalid_args / error / empty_result
    """
    spec = TOOL_SPECS.get(tool_name)
    if spec is None:
        return "unknown_tool"

    if not isinstance(args, dict) or not args:
        return "invalid_args"
    missing = [p for p in spec["params"] if not args.get(p)]
    if missing:
        return "invalid_args"

    text = result or ""
    if any(h in text for h in ERROR_HINTS):
        return "error"
    if any(h in text for h in EMPTY_HINTS):
        return "empty_result"
    return "ok"


def build_trace(tool_events: list[dict], max_steps: int) -> list[dict]:
    """把 agent/workflow 产出的 tool_events 规整成逐步轨迹。

    tool_events 结构：
        {"stage": "start",  "toolName": str, "args": dict}
        {"stage": "result", "toolName": str, "result": str,
         "durationMs": float, "ok": bool, "degraded": bool, "attempts": int}
    后面几个字段由 app.tool_runtime 的可靠性层提供，缺失时为 None。
    """
    trace: list[dict] = []
    pending: dict | None = None

    for ev in tool_events:
        stage = ev.get("stage")
        if stage == "start":
            pending = {
                "step": len(trace) + 1,
                "tool": ev.get("toolName", ""),
                "args": ev.get("args", {}) or {},
                "result": "",
                "status": "ok",
                "durationMs": None,
                "ok": None,
                "degraded": False,
                "attempts": 1,
            }
            trace.append(pending)
        elif stage == "result" and pending is not None:
            pending["result"] = ev.get("result", "") or ""
            pending["status"] = _classify_call(
                pending["tool"], pending["args"], pending["result"]
            )
            # 可靠性层提供的执行元信息
            dur = ev.get("durationMs")
            pending["durationMs"] = float(dur) if isinstance(dur, (int, float)) else None
            pending["ok"] = ev.get("ok")
            pending["degraded"] = bool(ev.get("degraded", False))
            pending["attempts"] = int(ev.get("attempts", 1) or 1)

    # 标记循环与超步
    seen: Counter = Counter()
    for i, step in enumerate(trace):
        sig = _arg_signature(step["tool"], step["args"])
        seen[sig] += 1
        step["signature"] = sig
        step["duplicate"] = seen[sig] > 1
        if step["duplicate"] and step["status"] == "ok":
            step["status"] = "duplicate"

    # 连续 3 次同工具 -> 视为循环
    run = 0
    prev_tool = None
    for step in trace:
        if step["tool"] == prev_tool:
            run += 1
        else:
            run = 1
            prev_tool = step["tool"]
        step["in_loop"] = run >= 3
        if step["in_loop"] and step["status"] == "ok":
            step["status"] = "loop"

    # 超步数标记优先级高于 loop：超步数是更根本的失败原因，
    # 若被 loop 覆盖会丢失「Agent 未能收敛」这一关键信息。
    if len(trace) > max_steps:
        for step in trace[max_steps:]:
            if step["status"] in ("ok", "loop"):
                step["status"] = "max_step"

    return trace


# --------------------------------------------------------------------------
# 失败归类
# --------------------------------------------------------------------------


def classify_failure(
    case: dict, trace: list[dict], reply: str, judge: dict
) -> list[str]:
    """判定这条用例的失败类型（可多个）。"""
    failures: list[str] = []

    for step in trace:
        if step["status"] == "empty_result":
            failures.append("RETRIEVAL_EMPTY")
        elif step["status"] == "error":
            failures.append("TOOL_ERROR")
        elif step["status"] == "invalid_args":
            failures.append("INVALID_ARGS")
        elif step["status"] == "unknown_tool":
            failures.append("INVALID_ARGS")
        elif step["status"] == "duplicate":
            failures.append("DUPLICATE_CALL")
        elif step["status"] == "loop":
            failures.append("LOOP")
        elif step["status"] == "max_step":
            failures.append("MAX_STEP")

    # 业务数据工具被用于越界问题：真实数据不该进越界上下文
    if case.get("should_refuse"):
        for step in trace:
            if TOOL_SPECS.get(step["tool"], {}).get("kind") == "business":
                failures.append("REFUSAL_UNDER")

    # 幻觉：裁判判不忠实
    if judge.get("faithful") == 0:
        failures.append("HALLUCINATION")

    # 过度拒答：知识库有答案（用例非越界）却整段拒答。
    # 注意：不能只看裁判的 refused 标志 —— 很多正确回答会在结尾附一句
    # 「如需…建议转人工客服」作为兜底话术，这是正常客服行为，不算过度拒答。
    # 判定口径：裁判判拒答 **且** 回答中不含任何参考答案要点（实质信息量为零）。
    if not case.get("should_refuse") and judge.get("refused") == 1 and case.get("reference"):
        if not _has_substantive_answer(reply, case.get("reference", "")):
            failures.append("REFUSAL_OVER")

    # 去重保序
    seen = set()
    out = []
    for f in failures:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


# --------------------------------------------------------------------------
# 单条用例
# --------------------------------------------------------------------------


def run_agent_case(case: dict, max_steps: int, mode: str = "react") -> dict:
    """跑一条用例，采集轨迹并计算该条的结果指标。"""
    from eval import eval_answer  # 复用共享 event loop 与裁判

    q = case["question"]
    sid = "agent-eval-" + uuid.uuid4().hex[:8]
    t0 = time.time()

    try:
        if mode == "react":
            reply, tool_events, usage = eval_answer.run_coroutine(_run_react(q, sid))
            sources, rag_hit = [], True
        else:
            from app import agent as agent_mod

            reply, sources, rag_hit, tool_events, usage = agent_mod.chat_once(q, sid)
    except Exception as exc:
        return {
            "id": case["id"], "question": q, "success": False,
            "error": str(exc)[:300], "fatal": eval_answer.is_fatal_error(exc),
            "latencyMs": round((time.time() - t0) * 1000, 1),
            "trace": [], "failures": ["TOOL_ERROR"],
        }

    dt = (time.time() - t0) * 1000
    trace = build_trace(tool_events, max_steps)
    actual_tools = [s["tool"] for s in trace]
    judge = eval_answer.judge(
        reply, case.get("reference", ""), case.get("expected_tool", ""),
        sorted(set(actual_tools)), case.get("should_refuse", False),
    )

    failures = classify_failure(case, trace, reply, judge)

    # pass@k：k 步内是否产出忠实回答
    steps_used = len(trace)
    faithful = judge.get("faithful") == 1
    # pass@1：没有工具调用（直接答）也算首轮产出
    pass_at_1 = faithful and steps_used <= 1
    pass_at_3 = faithful and steps_used <= 3

    # 无效调用：状态非 ok 的调用 + 越界问题里的业务工具调用
    invalid_calls = sum(
        1 for s in trace
        if s["status"] not in ("ok", "empty_result")
    )
    wasted_calls = sum(1 for s in trace if s.get("duplicate") or s.get("in_loop"))
    if case.get("should_refuse"):
        wasted_calls += sum(
            1 for s in trace if TOOL_SPECS.get(s["tool"], {}).get("kind") == "business"
        )

    return {
        "id": case["id"],
        "question": q,
        "category": case.get("category", ""),
        "expectedTool": case.get("expected_tool", ""),
        "reply": reply,
        "success": True,
        "latencyMs": round(dt, 1),
        "steps": steps_used,
        "tools": actual_tools,
        "trace": trace,
        "usage": usage or {},
        "judge": judge,
        "faithful": faithful,
        "passAt1": pass_at_1,
        "passAt3": pass_at_3,
        "invalidCalls": invalid_calls,
        "wastedCalls": wasted_calls,
        "failures": failures,
    }


async def _run_react(question: str, session_id: str):
    from app import workflow

    return await workflow.run_react(question, session_id)


# --------------------------------------------------------------------------
# 指标聚合
# --------------------------------------------------------------------------


def aggregate(rows: list[dict]) -> dict:
    """把逐条结果聚合成指标。"""
    ok = [r for r in rows if r.get("success")]
    n = len(ok)

    total_calls = sum(r["steps"] for r in ok)
    invalid_calls = sum(r["invalidCalls"] for r in ok)
    wasted_calls = sum(r["wastedCalls"] for r in ok)

    steps_dist = Counter(r["steps"] for r in ok)
    fail_counter: Counter = Counter()
    for r in ok:
        for f in r["failures"]:
            fail_counter[f] += 1

    per_category: dict[str, dict] = defaultdict(lambda: {"total": 0, "passAt1": 0, "passAt3": 0, "faithful": 0})
    for r in ok:
        c = per_category[r.get("category", "unknown")]
        c["total"] += 1
        c["passAt1"] += int(r["passAt1"])
        c["passAt3"] += int(r["passAt3"])
        c["faithful"] += int(r["faithful"])

    # ---- Token 用量（react 链路现在能拿到真实数据）----
    prompt_tokens = sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in ok)
    completion_tokens = sum((r.get("usage") or {}).get("completion_tokens", 0) for r in ok)
    total_tokens = sum((r.get("usage") or {}).get("total_tokens", 0) for r in ok)
    llm_rounds = sum((r.get("usage") or {}).get("llmRounds", 0) for r in ok)

    # ---- 工具执行耗时与降级统计 ----
    tool_durations: list[float] = []
    degraded_calls = 0
    per_tool_calls: Counter = Counter()
    per_tool_duration: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        for s in r.get("trace", []):
            if s.get("durationMs") is not None:
                tool_durations.append(float(s["durationMs"]))
                per_tool_duration[s["tool"]].append(float(s["durationMs"]))
            per_tool_calls[s["tool"]] += 1
            # 降级调用：可靠性层判定为失败/熔断/超时，或显式标记 degraded
            if s.get("degraded") or (s.get("ok") is False) or s["status"] not in ("ok", "empty_result"):
                degraded_calls += 1

    def rate(x, d):
        return round(x / d, 4) if d else None

    return {
        "total": len(rows),
        "executed": len(rows),
        "success": len(ok),
        "passAt1": rate(sum(1 for r in ok if r["passAt1"]), n),
        "passAt3": rate(sum(1 for r in ok if r["passAt3"]), n),
        "faithfulRate": rate(sum(1 for r in ok if r["faithful"]), n),
        "avgSteps": round(total_calls / n, 2) if n else 0,
        "maxSteps": max((r["steps"] for r in ok), default=0),
        "totalToolCalls": total_calls,
        "invalidCalls": invalid_calls,
        "invalidCallRate": rate(invalid_calls, total_calls),
        "wastedCalls": wasted_calls,
        "wastedCallRate": rate(wasted_calls, total_calls),
        "avgLatencyMs": round(sum(r.get("latencyMs", 0) for r in ok) / n, 1) if n else 0,
        # Token 用量
        "tokenUsage": {
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "totalTokens": total_tokens,
            "avgPromptTokens": round(prompt_tokens / n, 1) if n else 0,
            "avgCompletionTokens": round(completion_tokens / n, 1) if n else 0,
            "avgTotalTokens": round(total_tokens / n, 1) if n else 0,
            "llmRounds": llm_rounds,
            "avgLlmRounds": round(llm_rounds / n, 2) if n else 0,
        },
        # 工具执行耗时
        "toolLatency": {
            "avgMs": round(sum(tool_durations) / len(tool_durations), 1) if tool_durations else None,
            "maxMs": round(max(tool_durations), 1) if tool_durations else None,
            "perTool": {
                t: {
                    "calls": per_tool_calls[t],
                    "avgMs": round(sum(v) / len(v), 1) if v else None,
                    "maxMs": round(max(v), 1) if v else None,
                }
                for t, v in sorted(per_tool_duration.items())
            },
        },
        "degradedToolCalls": degraded_calls,
        "stepsDistribution": {str(k): v for k, v in sorted(steps_dist.items())},
        "failureTaxonomy": dict(fail_counter.most_common()),
        "perCategory": {
            k: {
                "total": v["total"],
                "passAt1": rate(v["passAt1"], v["total"]),
                "passAt3": rate(v["passAt3"], v["total"]),
                "faithful": rate(v["faithful"], v["total"]),
            }
            for k, v in sorted(per_category.items())
        },
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="react", choices=["react", "rag"])
    ap.add_argument("--max-steps", type=int, default=8)
    args = ap.parse_args()

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    print(f"agent-eval: mode={args.mode} maxSteps={args.max_steps} cases={len(cases)}")

    rows = []
    aborted = False
    for c in cases:
        r = run_agent_case(c, args.max_steps, args.mode)
        rows.append(r)
        print(
            f"{r['id']:<16} ok={r.get('success')} steps={r.get('steps')} "
            f"p@1={r.get('passAt1')} p@3={r.get('passAt3')} "
            f"faithful={r.get('faithful')} invalid={r.get('invalidCalls')} "
            f"failures={r.get('failures')} tools={r.get('tools')}"
        )
        if r.get("fatal"):
            print(f"\n[FATAL] {r['id']}: {str(r.get('error'))[:150]}")
            aborted = True
            break

    summary = aggregate(rows)
    summary["mode"] = args.mode
    summary["maxSteps"] = args.max_steps
    summary["aborted"] = aborted

    print("\n=== Agent 轨迹指标 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    out = Path(__file__).with_name(f"eval-agent-result-{args.mode}.json")
    out.write_text(json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
