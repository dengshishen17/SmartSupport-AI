# -*- coding: utf-8 -*-
"""检索质量指标：Hit@K / MRR / NDCG / MAP，含分级相关度（graded relevance）。

为什么需要 NDCG
--------------
Hit@K 与 MRR 都把「相关」当成 0/1 二值，但真实检索的��相关性是分级的：

- 命中**政策正文**（如「三、物流与配送」）—— 完全回答了问题
- 命中**归纳章节**（如「十二、常见误区澄清」）—— 部分有用
- 命中**FAQ 复述**（如「十一、常见问题 FAQ」）—— 口语化复述，内容对但表达冗余
- 命中**近义干扰章节**（如「七、换货政策」被问「退货」时）—— **不该算相关**

二进制指标无法区分这四种，NDCG 可以：用 gain = 2^rel - 1 的分级打分，
把「正文命中」和「FAQ 命中」的收益差开，同时对干扰章节给负相关度（惩罚）。

分级相关度赋值规则（基于本项目语料的实际结构）
------------------------------------------------
**关键认识**：扩展评测集里的 `distractor` 字段（如「退货(2.1)与换货(7.1)时限一致，
最易混淆」）描述的是**近义章节对**，而这两章在 expectedSections 里**都会被列出** ——
因为这类问题确实同时涉及两者，只是**其中一个更精确**。

因此不能简单地把「expected 之外」当干扰项，否则会把正确答案判成负分。

本模块采用的相关度规则：

| 情况                                        | rel | 说明                       |
|---------------------------------------------|-----|----------------------------|
| 命中 expectedSections[0]（首选章节）         | 3   | 最精确的答案               |
| 命中 expectedSections[1]（次选章节）         | 2   | 相关但不如首选精确         |
| 命中 expectedSections[2:]（第三及以后）       | 1   | 相关但优先级更低           |
| 命中 distractorSections（明确指定的干扰章节）| -1  | 惩罚：召回它说明被带偏     |
| 命中 FAQ / 归纳类章节                       | 1   | 复述型章节，收益低于正文   |
| 其他                                         | 0   | 无关                       |

这样 NDCG 同时反映两件事：
1. **排对没** —— 正文是否排在 FAQ 前面（排序质量）
2. **排准没** —— 近义章节中是否首选章节在前（精度）

指标定义
--------
DCG@K  = Σ_{i=1..K} (2^rel_i - 1) / log2(i + 1)
IDCG@K = 理想排序（按 rel 降序）的 DCG
NDCG@K = DCG@K / IDCG@K

MAP   = Σ_{i=1..R} P(i) × rel_i / R，其中 P(i) 是前 i 位中相关项的精确率

全部为纯本地计算，不调用 LLM，零 API 消耗，结果确定性可复现。
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

# 相关度等级常量
REL_PRIMARY = 3      # 首选期望章节：最精确的答案
REL_SECONDARY = 2    # 次选期望章节：相关但不如首选精确
REL_TERTIARY = 1     # 第三及以后的期望章节 / FAQ 归纳类
REL_DISTRACTOR = -1  # 明确指定的干扰章节：惩罚
REL_NONE = 0         # 无关


def dcg_at_k(relevances: Sequence[float], k: int) -> float:
    """DCG@K：按位置折损的累加增益。

    gain_i = 2^rel_i - 1，discount_i = 1 / log2(i + 1)
    rel <= 0 的项 gain 为 0（负相关度不加分，但在 NDCG 归一化里
    会拉低 IDCG，从而让「把干扰项排在前面」被惩罚）。
    """
    if k <= 0:
        return 0.0
    total = 0.0
    for i, rel in enumerate(relevances[:k]):
        if rel <= 0:
            continue
        gain = (2 ** rel) - 1
        total += gain / math.log2(i + 2)
    return total


def idcg_at_k(relevances: Sequence[float], k: int) -> float:
    """IDCG@K：把相关性降序排列后的理想 DCG。"""
    return dcg_at_k(sorted(relevances, reverse=True), k)


def ndcg_at_k(relevances: Sequence[float], k: int) -> float:
    """NDCG@K：归一化折损累积增益，取值 [0, 1]。

    IDCG 为 0（没有任何相关项）时返回 0.0。
    """
    idcg = idcg_at_k(relevances, k)
    if idcg <= 0:
        return 0.0
    return dcg_at_k(relevances, k) / idcg


def average_precision(relevances: Sequence[float]) -> float:
    """AP（Average Precision）。

    对 rel > 0 的项按位置计算精确率并累加，除以相关项总数。
    rel <= 0 的项不计入分母（干扰项不改变「相关项总数」，但会通过
    占据靠前位置拉低精确率，从而被间接惩罚）。
    """
    total_relevant = sum(1 for rel in relevances if rel > 0)
    if total_relevant == 0:
        return 0.0
    hits = 0
    prec_sum = 0.0
    for i, rel in enumerate(relevances):
        if rel > 0:
            hits += 1
            prec_sum += hits / (i + 1)
    return prec_sum / total_relevant


def mean_average_precision(all_relevances: Iterable[Sequence[float]]) -> float:
    """MAP：多条查询 AP 的平均。"""
    seqs = list(all_relevances)
    if not seqs:
        return 0.0
    return sum(average_precision(s) for s in seqs) / len(seqs)


def grade_relevance(
    section: str | None,
    expected_sections: Sequence[str],
    distractor_sections: Sequence[str] = (),
) -> float:
    """给单个召回结果打相关度分。

    参数
    ----
    section             召回片段的章节标题（None 表示解析不出来）
    expected_sections   该用例期望命中的章节，**按精确度降序**排列
    distractor_sections 该用例明确指定的干扰章节（命中应受惩罚）

    规则
    ----
    1. 命中 distractor → REL_DISTRACTOR (-1)
    2. 命中 expected[0] → REL_PRIMARY (3)
    3. 命中 expected[1] → REL_SECONDARY (2)
    4. 命中 expected[2:] → REL_TERTIARY (1)
    5. 命中 FAQ / 归纳类章节 → REL_TERTIARY (1)
    6. 其他 → 0
    """
    if not section:
        return REL_NONE

    sec = str(section).strip()
    expected = [str(s).strip() for s in (expected_sections or []) if str(s).strip()]
    distractors = [str(s).strip() for s in (distractor_sections or []) if str(s).strip()]

    # 1) 干扰章节优先判定（即使它同时出现在 expected 里也按干扰处理）
    for d in distractors:
        if d == sec or d in sec or sec in d:
            return REL_DISTRACTOR

    # 2~4) 期望章节：按在 expected 列表中的位置分级（列表已按精确度排序）
    for idx, e in enumerate(expected):
        if e == sec or e in sec or sec in e:
            if idx == 0:
                return REL_PRIMARY
            if idx == 1:
                return REL_SECONDARY
            return REL_TERTIARY

    # 5) 归纳 / FAQ / 误区澄清类章节 —— 内容相关但表达冗余，收益较低
    #    这类章节天然覆盖多个主题（FAQ 会复述物流、退货、保修等问题），
    #    因此只要该用例属于「可答」类，就应给最低一档正相关度。
    if expected and _is_secondary(sec):
        return REL_TERTIARY

    return REL_NONE


def _is_secondary(section: str) -> bool:
    """判断是否属于「归纳 / FAQ / 误区澄清」类章节。"""
    markers = ("FAQ", "常见问题", "误区", "澄清", "快速参考", "小结", "汇总")
    return any(m in section for m in markers)


def _same_topic(a: str, b: str) -> bool:
    """粗粒度主题判定：去掉序号前缀后是否有 2 字以上的公共子串。"""
    def norm(s: str) -> str:
        s = s.strip()
        # 去掉「一、」「1.」「（一）」等前缀
        for sep in ("、", ".", " ", "："):
            if sep in s:
                s = s.split(sep, 1)[1]
        return s
    na, nb = norm(a), norm(b)
    if na == nb:
        return True
    for i in range(len(na)):
        for j in range(i + 2, len(na) + 1):
            sub = na[i:j]
            if len(sub) >= 2 and sub in nb:
                return True
    return False


def _mentions_expected_topic(section: str, expected: Sequence[str]) -> bool:
    """章节文本里是否出现了期望章节的主题词（长度 >= 2）。"""
    for e in expected:
        if not e:
            continue
        topic = e.strip()
        for sep in ("、", ".", " ", "："):
            if sep in topic:
                topic = topic.split(sep, 1)[1]
        if len(topic) >= 2 and topic[:2] in section:
            return True
    return False


def evaluate_ranking(
    retrieved_sections: Sequence[str | None],
    expected_sections: Sequence[str],
    distractor_sections: Sequence[str] = (),
    k: int = 5,
) -> dict[str, Any]:
    """对一次检索结果算全套指标。

    返回
    ----
    {hitAt1, hitAt3, hitAtK, mrr, ndcgAtK, ap, relevances, grades}

    - mrr   : 第一个相关项（rel>0）的倒数排名
    - ndcgAtK : 分级 NDCG@K
    - ap    : Average Precision
    """
    relevances = [
        grade_relevance(s, expected_sections, distractor_sections)
        for s in retrieved_sections
    ]

    hit1 = hit3 = hitk = 0
    mrr = 0.0
    for i, rel in enumerate(relevances):
        if rel > 0:
            rank = i + 1
            mrr = 1.0 / rank
            hit1 += rank <= 1
            hit3 += rank <= 3
            hitk += rank <= k
            break

    return {
        "hitAt1": hit1,
        "hitAt3": hit3,
        "hitAtK": hitk,
        "mrr": mrr,
        "ndcgAtK": ndcg_at_k(relevances, k),
        "ap": average_precision(relevances),
        "relevances": relevances,
        "grades": [_grade_name(r) for r in relevances],
    }


def _grade_name(rel: float) -> str:
    if rel >= REL_PRIMARY:
        return "primary"
    if rel == REL_SECONDARY:
        return "secondary"
    if rel == REL_TERTIARY:
        return "tertiary"
    if rel == REL_DISTRACTOR:
        return "distractor"
    return "none"


def summarize(rows: list[dict[str, Any]], k: int = 5) -> dict[str, Any]:
    """汇总多条用例的指标均值。"""
    n = len(rows)
    if n == 0:
        return {}
    def avg(key: str) -> float:
        return sum(r.get(key, 0.0) for r in rows) / n
    return {
        "total": n,
        "hitRateAt1": round(avg("hitAt1"), 4),
        "hitRateAt3": round(avg("hitAt3"), 4),
        "hitRateAtK": round(avg("hitAtK"), 4),
        "mrr": round(avg("mrr"), 4),
        "ndcgAtK": round(avg("ndcgAtK"), 4),
        "map": round(avg("ap"), 4),
        "k": k,
    }
