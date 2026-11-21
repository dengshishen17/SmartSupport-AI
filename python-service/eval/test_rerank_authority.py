# -*- coding: utf-8 -*-
"""rerank 来源权威度信号的离线单元测试。

覆盖：权威度分级判定、四信号加权、near-distractor 场景的排序改善。
不调用任何外部服务，零 API 消耗。

运行：python -m eval.test_rerank_authority
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval.base import Document  # noqa: E402
from app.retrieval.rerank import (  # noqa: E402
    RuleReranker,
    authority_of,
)


class _Base:
    """占位召回器：单测只关心 rerank 本身，不需要真实召回。"""

    def recall(self, q, k):
        return []


def test_authority_levels():
    # 政策正文：最高
    assert authority_of("一、退款政策") == 1.0
    assert authority_of("七、换货政策") == 1.0
    assert authority_of("十二、服务等级与响应时效") == 1.0
    # FAQ：最低
    assert authority_of("十一、常见问题 FAQ") == 0.35
    # 归纳性章节：中间
    assert authority_of("六、快速参考表") == 0.7
    assert authority_of("十五、常见误区澄清") == 0.7
    # 未知章节按正文处理
    assert authority_of("未知章节") == 1.0
    assert authority_of(None) == 1.0


def test_authority_detects_faq_by_qa_pattern():
    """FAQ 标题异常时，靠 Q/A 结构兜底识别。"""
    content = "### 11.1 退款相关\n- **Q：钱什么时候能退到我卡上？**\n  A：退款发起后 1-5 个工作日到账。"
    assert authority_of("某个奇怪章节", content) == 0.35


def test_rerank_authority_affects_ordering():
    """权威度参与排序：同等条件下权威章节应排在归纳章节之前。

    注意这里不构造「FAQ 与政策正文谁该排第一」的断言。
    FAQ 章节把用户口语问法原样复述，字面与语义都天然占优，
    这在检索上并非错误 —— FAQ 也是合法答案来源。
    本用例验证的是契约：**权威度确实是排序的有效输入**，
    而不是宣称某一方必然胜出。
    """
    query = "退款审核要多久"

    policy = Document(
        content="## 一、退款政策\n### 1.2 退款流程与状态流转\n审核中：客服审核退款申请，1-3 个工作日。",
        metadata={"section": "一、退款政策"},
        score=0.80, dense_score=0.80,
    )
    derived = Document(
        content="## 十五、常见误区澄清\n### 15.1 政策概念易混淆点\n概念对照表列出了退款时限的多种情形说明。",
        metadata={"section": "十五、常见误区澄清"},
        score=0.80, dense_score=0.80,
    )

    rr = RuleReranker(_Base())
    out = rr.rerank(query, [derived, policy], top_k=2)
    assert out[0].metadata["section"] == "一、退款政策", \
        f"同等条件下权威章节应优先，实际排第一的是 {out[0].metadata.get('section')}"
    assert out[0].score > out[1].score


def test_rerank_is_deterministic():
    """同一输入必须得到同一排序（可复现性是评测可信的前提）。"""
    query = "家电类保修多长时间"
    docs = [
        Document(content="## 四、保修规则\n家电类保修 24 个月。", metadata={"section": "四、保修规则"},
                 score=0.7, dense_score=0.7),
        Document(content="## 九、优惠券与活动规则\n优惠券 7 天有效。", metadata={"section": "九、优惠券与活动规则"},
                 score=0.6, dense_score=0.6),
    ]
    rr = RuleReranker(_Base())
    a = [d.metadata["section"] for d in rr.rerank(query, list(docs), top_k=2)]
    b = [d.metadata["section"] for d in rr.rerank(query, list(docs), top_k=2)]
    assert a == b, f"排序不确定: {a} vs {b}"


def test_rerank_keeps_high_similarity_when_no_competitor():
    """没有竞争者时，高相似度文档仍应排第一。"""
    query = "家电类商品保修多长时间"
    doc = Document(
        content="## 四、保修规则\n### 4.1 保修期\n家电类保修期 24 个月，起算时间为订单已完成之日。",
        metadata={"section": "四、保修规则"},
        score=0.9, dense_score=0.9,
    )
    other = Document(
        content="## 九、优惠券与活动规则\n优惠券有效期 7 天。",
        metadata={"section": "九、优惠券与活动规则"},
        score=0.2, dense_score=0.2,
    )
    rr = RuleReranker(_Base())
    out = rr.rerank(query, [other, doc], top_k=2)
    assert out[0].metadata["section"] == "四、保修规则"


def test_rerank_normalizes_scores():
    """得分应落在 [0,1] 区间（各分量归一化后加权）。"""
    docs = [
        Document(content="## 一、退款政策\n退款申请审核 1-3 个工作日。", metadata={"section": "一、退款政策"},
                 score=0.9, dense_score=0.9),
        Document(content="## 二、退货政策\n退货需签收后 7 天内。", metadata={"section": "二、退货政策"},
                 score=0.5, dense_score=0.5),
        Document(content="## 九、优惠券与活动规则\n满减活动自动减免。", metadata={"section": "九、优惠券与活动规则"},
                 score=0.1, dense_score=0.1),
    ]

    rr = RuleReranker(_Base())
    out = rr.rerank("退款审核要多久", docs, top_k=3)
    for d in out:
        assert 0.0 <= d.score <= 1.0, d.score
    assert out[0].metadata["section"] == "一、退款政策"


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
