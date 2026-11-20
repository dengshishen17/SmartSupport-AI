# -*- coding: utf-8 -*-
"""eval_agent 轨迹解析与失败分类的离线单元测试。

不调用 LLM、不访问数据库，零 API 消耗，可随时运行：
    python -m eval.test_eval_agent
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.eval_agent import aggregate, build_trace, classify_failure  # noqa: E402


def _ev(tool, args, result=None):
    """构造一个工具事件序列。"""
    out = [{"stage": "start", "toolName": tool, "args": args}]
    if result is not None:
        out.append({"stage": "result", "toolName": tool, "result": result})
    return out


def test_normal_retrieval():
    t = build_trace(_ev("searchPolicyKnowledge", {"query": "退款"}, "【一、退款政策】..."), 8)
    assert len(t) == 1
    assert t[0]["status"] == "ok"


def test_empty_result():
    t = build_trace(_ev("searchPolicyKnowledge", {"query": "x"}, "知识库中没有检索到相关条文"), 8)
    assert t[0]["status"] == "empty_result"


def test_tool_error():
    t = build_trace(_ev("queryOrderByOrderNo", {"orderNo": "1"}, "订单库暂时不可用（boom）"), 8)
    assert t[0]["status"] == "error"


def test_policy_text_containing_异常_is_not_error():
    """知识库正文里的「异常」二字不能被误判为工具报错。

    回归用例：检索工具返回的政策原文里含「异常情况」，曾被 ERROR_HINTS 的
    「异常」锚点误判，导致 6 条用例被错标 TOOL_ERROR。
    """
    policy = "【一、退款政策】\n### 1.1 退款适用场景\n- 异常情况需转人工处理"
    t = build_trace(_ev("searchPolicyKnowledge", {"query": "退款"}, policy), 8)
    assert t[0]["status"] == "ok", t[0]["status"]


def test_not_found_is_empty_not_error():
    """业务工具「未找到订单」是空结果，不是执行报错。"""
    t = build_trace(_ev("queryOrderByOrderNo", {"orderNo": "99999"}, "未找到订单号为 99999 的订单"), 8)
    assert t[0]["status"] == "empty_result"


def test_missing_args():
    t = build_trace(_ev("queryOrderByOrderNo", {}, "x"), 8)
    assert t[0]["status"] == "invalid_args"


def test_unknown_tool():
    t = build_trace(_ev("queryNotExist", {"a": 1}, "x"), 8)
    assert t[0]["status"] == "unknown_tool"


def test_duplicate_call():
    t = build_trace(
        _ev("queryOrderByOrderNo", {"orderNo": "1"}, "订单号：10001")
        + _ev("queryOrderByOrderNo", {"orderNo": "1"}, "订单号：10001"),
        8,
    )
    assert t[0]["duplicate"] is False
    assert t[1]["duplicate"] is True
    assert t[1]["status"] == "duplicate"


def test_loop_detection():
    t = build_trace(
        _ev("searchPolicyKnowledge", {"query": "a"}, "r1")
        + _ev("searchPolicyKnowledge", {"query": "b"}, "r2")
        + _ev("searchPolicyKnowledge", {"query": "c"}, "r3"),
        8,
    )
    assert t[2]["in_loop"] is True
    assert t[2]["status"] == "loop"


def test_max_step_overrides_loop():
    """超步数优先级高于 loop：超步是更根本的失败原因。"""
    events = []
    for i in range(10):
        events += _ev("queryOrderByOrderNo", {"orderNo": str(i)}, "ok")
    t = build_trace(events, 8)
    assert "max_step" in [s["status"] for s in t]


def test_refusal_under_and_hallucination():
    """越界问题里调业务工具 -> REFUSAL_UNDER；裁判判不忠实 -> HALLUCINATION。"""
    case = {"id": "x", "should_refuse": True, "reference": "ref", "expected_tool": ""}
    trace = build_trace(_ev("queryOrderByOrderNo", {"orderNo": "1"}, "订单号：10001"), 8)
    failures = classify_failure(case, trace, "reply", {"faithful": 0, "refused": 0})
    assert "REFUSAL_UNDER" in failures
    assert "HALLUCINATION" in failures


def test_refusal_over():
    """知识库有答案却整段拒答 -> REFUSAL_OVER。"""
    case = {"id": "y", "should_refuse": False, "reference": "ref", "expected_tool": ""}
    failures = classify_failure(case, [], "无法确认", {"faithful": 1, "refused": 1})
    assert "REFUSAL_OVER" in failures


def test_trailing_handoff_is_not_refusal_over():
    """结尾附「建议转人工」兜底话术但已给出实质信息 -> 不算过度拒答。

    回归用例：模型正确回答了订单状态与金额，结尾加了一句
    「如需详细物流轨迹，建议转人工客服查询承运信息」，
    曾被判 REFUSAL_OVER（30 条里有 3 条误判）。
    """
    case = {"id": "z", "should_refuse": False,
            "reference": "订单状态：运输中；下单时间：2026-10-20", "expected_tool": ""}
    reply = ("订单10001（智能扫地机器人 X20，2999元）目前状态为“运输中”，"
             "下单时间是2026-10-20 10:15。系统未提供具体物流节点和预计送达时间，"
             "如需详细物流轨迹，建议转人工客服查询承运信息。")
    failures = classify_failure(case, [], reply, {"faithful": 1, "refused": 1})
    assert "REFUSAL_OVER" not in failures, failures


def test_pure_refusal_still_detected():
    """纯拒答（零实质信息）仍应被判过度拒答。"""
    case = {"id": "w", "should_refuse": False,
            "reference": "订单状态：运输中；下单时间：2026-10-20", "expected_tool": ""}
    failures = classify_failure(case, [], "抱歉，暂时无法确认，建议转人工客服。",
                                {"faithful": 1, "refused": 1})
    assert "REFUSAL_OVER" in failures


def test_aggregate():
    rows = [
        {"id": "a", "success": True, "category": "policy", "steps": 1, "passAt1": True,
         "passAt3": True, "faithful": True, "invalidCalls": 0, "wastedCalls": 0,
         "failures": [], "latencyMs": 100},
        {"id": "b", "success": True, "category": "policy", "steps": 3, "passAt1": False,
         "passAt3": True, "faithful": True, "invalidCalls": 1, "wastedCalls": 1,
         "failures": ["DUPLICATE_CALL"], "latencyMs": 200},
    ]
    agg = aggregate(rows)
    assert agg["passAt1"] == 0.5
    assert agg["passAt3"] == 1.0
    assert agg["avgSteps"] == 2.0
    assert agg["invalidCallRate"] == 0.25
    assert agg["failureTaxonomy"] == {"DUPLICATE_CALL": 1}
    assert agg["perCategory"]["policy"]["total"] == 2


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
