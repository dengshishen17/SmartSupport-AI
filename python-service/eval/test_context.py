# -*- coding: utf-8 -*-
"""app/context.py 离线单测：Token 估算、片段压缩、历史裁剪、预算组装。

零 API 消耗，可重复运行。
    python -m pytest python-service/eval/test_context.py -q
或
    python python-service/eval/test_context.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context  # noqa: E402


# --------------------------------------------------------------------------
# Token 估算
# --------------------------------------------------------------------------

def test_count_tokens_empty():
    assert context.count_tokens("") == 0
    assert context.count_tokens(None) == 0


def test_count_tokens_chinese():
    # 中文按字计
    assert context.count_tokens("你好") == 2
    assert context.count_tokens("退款政策") == 4


def test_count_tokens_latin_words():
    # 英文按词计
    assert context.count_tokens("hello world") == 2
    assert context.count_tokens("RAG") == 1


def test_count_tokens_mixed_is_monotonic():
    short = context.count_tokens("退款政策")
    long = context.count_tokens("退款政策说明如下：七天内可退")
    assert long > short


def test_count_message_tokens_adds_overhead():
    msgs = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "您好"}]
    # 2 条消息各 4 token 协议开销 + 2+2 文本
    assert context.count_message_tokens(msgs) == 12


def test_count_message_tokens_empty():
    assert context.count_message_tokens([]) == 0


# --------------------------------------------------------------------------
# 片段压缩
# --------------------------------------------------------------------------

def test_compress_context_no_docs():
    kept, stats = context.compress_context([])
    assert kept == []
    assert stats.final_tokens == 0
    assert stats.dropped_chunks == 0


def test_compress_context_no_budget_keeps_all():
    docs = [{"content": f"片段{i}内容"} for i in range(5)]
    kept, stats = context.compress_context(docs, budget_tokens=0)
    assert len(kept) == 5
    assert stats.dropped_chunks == 0


def test_compress_context_respects_budget():
    # 每段约 10 token，预算 25 token → 最多保留 2 段
    docs = [{"content": "退货政策：七天内无理由退货"} for _ in range(5)]
    kept, stats = context.compress_context(docs, budget_tokens=25)
    assert len(kept) < 5
    assert stats.dropped_chunks == 5 - len(kept)
    assert stats.final_tokens <= 25 + 10  # 允许分隔符开销


def test_compress_context_keeps_order():
    docs = [{"content": "第一段"}, {"content": "第二段"}, {"content": "第三段"}]
    kept, _ = context.compress_context(docs, budget_tokens=0)
    assert [d["content"] for d in kept] == ["第一段", "第二段", "第三段"]


def test_compress_context_drops_from_tail():
    """预算不足时应丢尾部（低相关度），保留头部（高相关度）。"""
    docs = [{"content": "重要政策条款" * 3}, {"content": "次要说明" * 3}, {"content": "尾部内容" * 3}]
    kept, _ = context.compress_context(docs, budget_tokens=40)
    assert kept[0]["content"] == docs[0]["content"]
    assert len(kept) < 3


def test_compress_context_truncates_long_chunk_at_sentence_boundary():
    long_text = "第一句话内容比较长。" * 40 + "结尾。"
    docs = [{"content": long_text}]
    kept, stats = context.compress_context(docs, budget_tokens=0, max_chunk_chars=100)
    assert len(kept[0]["content"]) <= 110  # 允许句末标点溢出 1 字
    assert kept[0]["content"].endswith("。")


def test_compress_context_never_splits_mid_sentence_when_possible():
    text = "第一句。第二句。第三句。第四句。第五句。"
    kept, _ = context.compress_context([{"content": text}], budget_tokens=0, max_chunk_chars=12)
    # 应在句号处结束，而不是从句子中间截断
    assert kept[0]["content"].endswith("。")


def test_compress_context_skips_blank_docs():
    docs = [{"content": "   "}, {"content": "有效内容"}]
    kept, _ = context.compress_context(docs, budget_tokens=0)
    assert len(kept) == 1
    assert kept[0]["content"] == "有效内容"


def test_compress_context_preserves_other_fields():
    docs = [{"content": "内容", "score": 0.87, "metadata": {"source": "policy.md"}}]
    kept, _ = context.compress_context(docs, budget_tokens=0)
    assert kept[0]["score"] == 0.87
    assert kept[0]["metadata"]["source"] == "policy.md"


def test_compress_context_stats_saved_ratio():
    # 预算充足 → 保留全部，节省为 0
    docs = [{"content": "很长的内容" * 30}]
    kept, stats = context.compress_context(docs, budget_tokens=1000, max_chunk_chars=600)
    assert len(kept) == 1
    assert stats.saved_tokens == 0
    assert stats.saved_ratio == 0.0

    # 预算不足 → 整段丢弃，节省率上升
    docs2 = [{"content": "很长的内容" * 30}, {"content": "第二段" * 30}]
    kept2, stats2 = context.compress_context(docs2, budget_tokens=100, max_chunk_chars=600)
    assert stats2.saved_tokens > 0
    assert 0 < stats2.saved_ratio <= 1.0


# --------------------------------------------------------------------------
# 历史窗口
# --------------------------------------------------------------------------

def test_build_history_empty():
    kept, dropped = context.build_history([])
    assert kept == []
    assert dropped == 0


def test_build_history_max_messages():
    msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"消息{i}"}
            for i in range(30)]
    kept, dropped = context.build_history(msgs, max_messages=20)
    assert len(kept) == 20
    assert dropped == 10
    assert kept[-1]["content"] == "消息29"


def test_build_history_keeps_latest_under_budget():
    msgs = [{"role": "user", "content": "很长的问题" * 20} for _ in range(5)]
    kept, dropped = context.build_history(msgs, max_messages=20, budget_tokens=50, keep_latest=2)
    assert len(kept) == 2, "预算极紧时也应保住最后 keep_latest 条"
    assert dropped == 3


def test_build_history_drops_oldest_first():
    msgs = [{"role": "user", "content": f"第{i}条内容"} for i in range(10)]
    kept, dropped = context.build_history(msgs, max_messages=20, budget_tokens=30, keep_latest=1)
    assert kept[-1]["content"] == "第9条内容"
    assert dropped > 0


def test_build_history_no_budget_keeps_all():
    msgs = [{"role": "user", "content": "x"} for _ in range(5)]
    kept, dropped = context.build_history(msgs, max_messages=20, budget_tokens=0)
    assert len(kept) == 5
    assert dropped == 0


# --------------------------------------------------------------------------
# 预算方案
# --------------------------------------------------------------------------

def test_plan_budget_allocations():
    plan = context.plan_budget(total_budget=4096, reserve_output=512)
    assert plan.available == 3584
    assert plan.max_history == int(3584 * 0.25)
    assert plan.max_system == int(3584 * 0.30)
    assert plan.max_context == 3584 - plan.max_history - plan.max_system


def test_plan_budget_context_is_largest_slice():
    plan = context.plan_budget(total_budget=4096)
    assert plan.max_context > plan.max_history
    assert plan.max_context > plan.max_system


def test_plan_budget_zero_total_is_safe():
    plan = context.plan_budget(total_budget=0)
    assert plan.available == 0
    assert plan.max_context == 0


# --------------------------------------------------------------------------
# 统一组装
# --------------------------------------------------------------------------

def test_assemble_injects_context_into_template():
    docs = [{"content": "退货政策：七天内可退"}]
    out, stats = context.assemble(
        question="怎么退货", retrieved=docs, history=[],
        system_template="你是客服。\n【知识】\n%s")
    assert "退货政策" in out["system"]
    assert out["messages"][-1]["role"] == "user"
    assert out["messages"][-1]["content"] == "怎么退货"
    assert stats.kept_chunks == 1


def test_assemble_without_template():
    out, _ = context.assemble(question="你好", retrieved=[], history=[], system_template="")
    assert out["system"] == ""
    assert len(out["messages"]) == 1


def test_assemble_respects_budget_and_reports_stats():
    docs = [{"content": "政策内容片段，" * 50} for _ in range(8)]
    history = [{"role": "user", "content": "历史问题" * 30} for _ in range(6)]
    plan = context.plan_budget(total_budget=2048)
    out, stats = context.assemble(
        question="当前问题", retrieved=docs, history=history,
        system_template="系统提示\n%s", budget=plan)
    assert stats.dropped_chunks > 0
    assert stats.dropped_history > 0
    assert stats.final_tokens <= stats.original_tokens + stats.system_tokens + 500


def test_assemble_context_never_exceeds_context_budget():
    docs = [{"content": "内容" * 100} for _ in range(10)]
    plan = context.plan_budget(total_budget=1024)
    _, stats = context.assemble(question="q", retrieved=docs, history=[], budget=plan)
    assert stats.context_tokens <= plan.max_context + 50


def test_assemble_keeps_latest_history():
    history = [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"}]
    out, _ = context.assemble(question="新问题", retrieved=[], history=history,
                              system_template="s")
    assert out["messages"][-1]["content"] == "新问题"
    assert any(m["content"] == "旧问题" for m in out["messages"])


def test_context_stats_to_dict_shape():
    stats = context.ContextStats(original_tokens=100, final_tokens=60, dropped_chunks=2)
    d = stats.to_dict()
    for key in ("originalTokens", "finalTokens", "savedTokens", "savedRatio",
                "droppedChunks", "droppedHistory", "keptChunks", "budget"):
        assert key in d


def test_truncate_to_sentences_hard_cut_fallback():
    # 无句末标点的长文本应走硬切
    text = "无标点" * 100
    out = context._truncate_to_sentences(text, 50)
    assert len(out) <= 50


# --------------------------------------------------------------------------
# 独立运行器（不依赖 pytest）
# --------------------------------------------------------------------------

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
    print(f"\ntest_context: {passed} passed, {failed} failed (total {len(fns)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
