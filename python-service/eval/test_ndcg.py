# -*- coding: utf-8 -*-
"""eval/metrics_ndcg.py 单测：DCG / NDCG / AP / 分级相关度。

零 API 消耗。
    python python-service/eval/test_ndcg.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval import metrics_ndcg as m  # noqa: E402


# --------------------------------------------------------------------------
# DCG
# --------------------------------------------------------------------------

def test_dcg_empty():
    assert m.dcg_at_k([], 5) == 0.0


def test_dcg_k_zero():
    assert m.dcg_at_k([3, 2, 1], 0) == 0.0


def test_dcg_single_primary():
    # gain = 2^3 - 1 = 7, discount = 1/log2(2) = 1
    assert abs(m.dcg_at_k([3], 1) - 7.0) < 1e-9


def test_dcg_position_discount():
    # 同一个 rel=3 放在第1位 vs 第2位，第1位得分更高
    d1 = m.dcg_at_k([3], 1)
    d2 = m.dcg_at_k([0, 3], 2)
    assert d1 > d2


def test_dcg_ignores_non_positive_relevance():
    assert m.dcg_at_k([0, 0, 0], 3) == 0.0
    assert m.dcg_at_k([-1, -1], 2) == 0.0


def test_dcg_k_truncates():
    assert m.dcg_at_k([3, 3, 3, 3], 2) == m.dcg_at_k([3, 3], 2)


def test_idcg_sorts_descending():
    assert m.idcg_at_k([1, 3, 2], 3) == m.idcg_at_k([3, 2, 1], 3)


def test_idcg_of_all_zero_is_zero():
    assert m.idcg_at_k([0, 0], 2) == 0.0


# --------------------------------------------------------------------------
# NDCG
# --------------------------------------------------------------------------

def test_ndcg_perfect_ranking_is_one():
    assert abs(m.ndcg_at_k([3, 2, 1], 3) - 1.0) < 1e-9


def test_ndcg_reversed_is_less_than_one():
    v = m.ndcg_at_k([1, 2, 3], 3)
    assert 0 < v < 1


def test_ndcg_zero_when_no_relevant():
    assert m.ndcg_at_k([0, 0, 0], 3) == 0.0


def test_ndcg_all_equal_is_one():
    assert abs(m.ndcg_at_k([3, 3, 3], 3) - 1.0) < 1e-9


def test_ndcg_penalizes_distractor_before_relevant():
    """把干扰项排在相关项前面，NDCG 应显著低于反向排序。"""
    good = m.ndcg_at_k([3, -1], 2)
    bad = m.ndcg_at_k([-1, 3], 2)
    assert good > bad


def test_ndcg_favors_primary_over_secondary():
    """同等位置下，正文(3) 的 NDCG 应高于 FAQ(1)。"""
    a = m.ndcg_at_k([3, 1], 2)
    b = m.ndcg_at_k([1, 3], 2)
    assert a > b


def test_ndcg_single_item():
    assert abs(m.ndcg_at_k([3], 1) - 1.0) < 1e-9


# --------------------------------------------------------------------------
# Average Precision
# --------------------------------------------------------------------------

def test_ap_no_relevant_is_zero():
    assert m.average_precision([0, 0]) == 0.0


def test_ap_perfect_is_one():
    assert abs(m.average_precision([3, 2, 1]) - 1.0) < 1e-9


def test_ap_first_position_hit_is_one():
    assert abs(m.average_precision([3, 0, 0]) - 1.0) < 1e-9


def test_ap_second_position_hit():
    # P(1) = 1/2, 分母 1 → AP = 0.5
    assert abs(m.average_precision([0, 3]) - 0.5) < 1e-9


def test_ap_penalizes_distractor_occupying_top():
    """干扰项占首位会拉低 AP。"""
    good = m.average_precision([3, -1, 0])
    bad = m.average_precision([-1, 3, 0])
    assert good > bad


def test_map_average():
    assert abs(m.mean_average_precision([[3, 0], [0, 3]]) - 0.75) < 1e-9


def test_map_empty_is_zero():
    assert m.mean_average_precision([]) == 0.0


# --------------------------------------------------------------------------
# 分级相关度
# --------------------------------------------------------------------------

def test_grade_primary_hit():
    rel = m.grade_relevance("三、物流与配送", ["三、物流与配送"])
    assert rel == m.REL_PRIMARY


def test_grade_secondary_for_second_expected():
    """第二个期望章节应低于首选、高于无关。"""
    rel = m.grade_relevance("七、换货政策", ["二、退货政策", "七、换货政策"])
    assert rel == m.REL_SECONDARY


def test_grade_tertiary_for_third_expected():
    rel = m.grade_relevance("十五、常见误区澄清", ["二、退货政策", "七、换货政策", "十五、常见误区澄清"])
    assert rel == m.REL_TERTIARY


def test_grade_tertiary_for_faq():
    rel = m.grade_relevance("十一、常见问题 FAQ", ["三、物流与配送"])
    assert rel == m.REL_TERTIARY


def test_grade_none_for_unrelated():
    rel = m.grade_relevance("九、优惠券与活动规则", ["三、物流与配送"])
    assert rel == m.REL_NONE


def test_grade_distractor_is_penalized():
    rel = m.grade_relevance("七、换货政策", ["二、退货政策"], distractor_sections=["七、换货政策"])
    assert rel == m.REL_DISTRACTOR


def test_grade_distractor_takes_priority_over_expected():
    """同时出现在 expected 与 distractor 里时按干扰处理（防止被当成正确命中）。"""
    rel = m.grade_relevance("七、换货政策", ["七、换货政策"], distractor_sections=["七、换货政策"])
    assert rel == m.REL_DISTRACTOR


def test_grade_none_section_is_zero():
    assert m.grade_relevance(None, ["三、物流与配送"]) == m.REL_NONE


def test_grade_empty_section_is_zero():
    assert m.grade_relevance("", ["三、物流与配送"]) == m.REL_NONE


def test_grade_no_expected_is_zero():
    assert m.grade_relevance("三、物流与配送", []) == m.REL_NONE


def test_grade_partial_match_counts_primary():
    rel = m.grade_relevance("物流与配送", ["三、物流与配送"])
    assert rel == m.REL_PRIMARY


# --------------------------------------------------------------------------
# 端到端
# --------------------------------------------------------------------------

def test_evaluate_ranking_perfect():
    r = m.evaluate_ranking(
        ["二、退货政策", "七、换货政策"],
        expected_sections=["二、退货政策"],
        distractor_sections=["七、换货政策"],
        k=5)
    assert r["hitAt1"] == 1
    assert r["hitAt3"] == 1
    assert r["mrr"] == 1.0
    assert r["ndcgAtK"] > 0.5
    assert r["grades"][0] == "primary"
    assert r["grades"][1] == "distractor"


def test_evaluate_ranking_miss():
    r = m.evaluate_ranking(["九、优惠券"], ["二、退货政策"], k=5)
    assert r["hitAt1"] == 0
    assert r["hitAt3"] == 0
    assert r["mrr"] == 0.0
    assert r["ndcgAtK"] == 0.0


def test_evaluate_ranking_hit_at_3():
    r = m.evaluate_ranking(["九、优惠券", "八、开票政策", "二、退货政策"], ["二、退货政策"], k=5)
    assert r["hitAt1"] == 0
    assert r["hitAt3"] == 1
    assert abs(r["mrr"] - 1 / 3) < 1e-9


def test_evaluate_ranking_prefers_first_expected():
    """首选章节在前应比次选章节在前有更高 NDCG。"""
    good = m.evaluate_ranking(["二、退货政策", "七、换货政策"],
                              expected_sections=["二、退货政策", "七、换货政策"], k=2)
    bad = m.evaluate_ranking(["七、换货政策", "二、退货政策"],
                             expected_sections=["二、退货政策", "七、换货政策"], k=2)
    assert good["ndcgAtK"] > bad["ndcgAtK"], "首选章节排前应获得更高 NDCG"


def test_evaluate_ranking_faq_before_primary_scores_lower():
    """FAQ 复述排在正文前面，NDCG 应更低。"""
    good = m.evaluate_ranking(["二、退货政策", "十一、常见问题 FAQ"], ["二、退货政策"], k=2)
    bad = m.evaluate_ranking(["十一、常见问题 FAQ", "二、退货政策"], ["二、退货政策"], k=2)
    assert good["ndcgAtK"] > bad["ndcgAtK"]


def test_evaluate_ranking_respects_k():
    r = m.evaluate_ranking(["二、退货政策"], ["二、退货政策"], k=0)
    assert r["hitAtK"] == 0


def test_summarize_computes_averages():
    rows = [
        {"hitAt1": 1, "hitAt3": 1, "hitAtK": 1, "mrr": 1.0, "ndcgAtK": 1.0, "ap": 1.0},
        {"hitAt1": 0, "hitAt3": 1, "hitAtK": 1, "mrr": 0.5, "ndcgAtK": 0.5, "ap": 0.5},
    ]
    s = m.summarize(rows, k=5)
    assert s["total"] == 2
    assert s["hitRateAt1"] == 0.5
    assert s["mrr"] == 0.75
    assert s["ndcgAtK"] == 0.75


def test_summarize_empty():
    assert m.summarize([]) == {}


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
    print(f"\ntest_ndcg: {passed} passed, {failed} failed (total {len(fns)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
