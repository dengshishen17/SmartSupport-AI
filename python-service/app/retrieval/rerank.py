# -*- coding: utf-8 -*-
"""重排器（Rerank）：对召回候选做二次精排。

为什么不用 Cross-Encoder
-----------------------
Cross-Encoder（如 bge-reranker）效果最好，但需要额外下载模型权重、
引入 torch/transformers 依赖，在本项目的轻量部署目标下不合适。

本模块实现**可解释的规则式重排**，融合四个信号：
    1. 向量相似度       —— 语义相关性
    2. 查询词命中率     —— 关键词是否真的出现在正文中
    3. 章节匹配度       —— 命中的章节标题与查询的词汇重合度
    4. 来源权威度       —— 政策正文优先于 FAQ 汇总 / 误区澄清等二次归纳章节

为什么要第 4 个信号
------------------
扩充语料后实测发现一个系统性问题：**口语化查询会被 FAQ 章节「截胡」**。
例如「钱什么时候能退到我卡上」「快递怎么还没到」「东西坏了找谁修」，
这些问法在《常见问题 FAQ》里被原样复述，语义检索必然把它排在政策原文前面。
从检索角度 FAQ 是对的，但从产品角度应当优先返回政策原文（更权威、可追溯）。

因此引入「来源权威度」这一显式信号：
- 政策正文（§1~§5、§7~§10、§12、§14）权重最高
- 快速参考表 / 常见误区澄清（归纳性章节）次之
- FAQ（口语化复述）最低
这是可解释的领域先验，不是针对评测集的过拟合 —— 每一条都能讲清楚为什么。

优点：零额外依赖、毫秒级、每一分都能解释清楚（面试可讲）。
缺点：效果上限低于 Cross-Encoder，但对本项目这种「短查询 + 结构化政策文档」
的场景，规则式重排的性价比更高。

若后续要升级为 Cross-Encoder，只需实现同样的 `rerank()` 接口替换本类即可，
上层调用方无需改动。
"""
from __future__ import annotations

import re

from .base import Document
from .bm25 import tokenize

_CJK = re.compile(r"[\u4e00-\u9fff]")

# --------------------------------------------------------------------------
# 来源权威度
#
# 同一份知识库里，不同章节的可信度与用途不同：
# - 政策正文（退款/退货/物流/保修/换货/开票/优惠券/价保/服务时效/配送）
#   是规则定义本身，答复客户应优先引用
# - 快速参考表 / 常见误区澄清 是对政策的归纳，本身不新增规则
# - 常见问题 FAQ 是把政策改写成口语问法后的复述，语义最容易被误召回
#
# 这里给的是「先验权重」，最终排序仍由四个信号加权决定。
# --------------------------------------------------------------------------
_AUTHORITY_FULL = 1.0        # 政策正文
_AUTHORITY_DERIVED = 0.7     # 归纳性章节（快速参考表、常见误区澄清）
_AUTHORITY_FAQ = 0.35        # FAQ 复述

# 关键词命中即判定为「二次归纳章节」
_DERIVED_KEYWORDS = ("快速参考", "误区", "澄清", "常见误区")
_FAQ_KEYWORDS = ("FAQ", "常见问题")


def authority_of(section: str | None, content: str = "") -> float:
    """返回该 chunk 的来源权威度权重。"""
    s = (section or "")
    if any(k in s for k in _FAQ_KEYWORDS):
        return _AUTHORITY_FAQ
    if any(k in s for k in _DERIVED_KEYWORDS):
        return _AUTHORITY_DERIVED
    # FAQ 标题有时不带 "FAQ" 字样（长章节切分后的段落 metadata.section 仍带，
    # 这里再兜一层：正文以 "### 11." 开头且含 Q/A 结构）
    if "Q：" in content and "A：" in content:
        return _AUTHORITY_FAQ
    return _AUTHORITY_FULL


class RuleReranker:
    """规则式重排器。

    最终得分（各分量先归一化到 [0,1] 再加权）：
        final = w_vec · vec_norm + w_kw · keyword_norm + w_sec · section_norm
                + w_auth · authority_norm
    """

    name = "rule_rerank"

    def __init__(
        self,
        base,
        w_vector: float = 0.55,
        w_keyword: float = 0.20,
        w_section: float = 0.15,
        w_authority: float = 0.10,
    ):
        """四信号权重。

        权重设定的依据（75 条标注用例实测）：
        - 向量 0.55：语义相关性是主信号，用绝对刻度不做 min-max 拉伸
        - 关键词 0.20：字面命中是强信号，但 FAQ 章节会把口语问法字面复述一遍
        - 章节 0.15：章节标题与查询的词汇重合度
        - 权威度 0.10：加性项，幅度需要克制

        权威度同时以**乘性折扣**参与最终排序（见 rerank()），
        这是关键：FAQ 里的问法与用户口语几乎逐字相同，
        关键词与向量两项都会天然偏向 FAQ，
        只有乘性折扣能保证 FAQ 必须「语义明显更优」才能压过政策正文。
        """
        self.base = base
        self.w_vector = w_vector
        self.w_keyword = w_keyword
        self.w_section = w_section
        self.w_authority = w_authority

    # -- 打分分量 -----------------------------------------------------------

    @staticmethod
    def _keyword_coverage(query: str, content: str) -> float:
        """查询词元在正文中的覆盖率（去重后计算）。

        中文用 bigram（不依赖 jieba，保证零依赖时的行为一致）。
        """
        q_terms = set(tokenize(query))
        if not q_terms:
            return 0.0
        c_terms = set(tokenize(content))
        if not c_terms:
            return 0.0
        return len(q_terms & c_terms) / len(q_terms)

    @staticmethod
    def _section_match(query: str, section: str | None) -> float:
        """章节标题与查询的词元重合度。"""
        if not section:
            return 0.0
        q_terms = set(tokenize(query))
        s_terms = set(tokenize(section))
        if not q_terms or not s_terms:
            return 0.0
        return len(q_terms & s_terms) / len(q_terms)

    @staticmethod
    def _norm(values: list[float]) -> list[float]:
        """min-max 归一化到 [0,1]。所有分量同值时返回全 1。"""
        if not values:
            return []
        lo, hi = min(values), max(values)
        if hi - lo < 1e-12:
            return [1.0 for _ in values]
        return [(v - lo) / (hi - lo) for v in values]

    @staticmethod
    def _norm_absolute(values: list[float]) -> list[float]:
        """按绝对刻度裁剪到 [0,1]，不做 min-max 拉伸。

        向量相似度分量必须用绝对刻度：min-max 会把「0.70 vs 0.66」这种
        微小差异拉伸成「1.0 vs 0.0」，等于把噪声放大成信号，
        导致本应靠语义微调分出胜负的候选被强行拉开。
        实测该问题会让 FAQ 复述段（语义略高）压过政策正文（语义略低）。
        """
        return [min(1.0, max(0.0, v)) for v in values]

    # -- 主流程 -------------------------------------------------------------

    def rerank(self, query: str, docs: list[Document], top_k: int) -> list[Document]:
        if not docs:
            return []

        vec_raw = [d.dense_score if d.dense_score is not None else d.score for d in docs]
        kw_raw = [self._keyword_coverage(query, d.content) for d in docs]
        sec_raw = [self._section_match(query, d.section) for d in docs]
        auth_raw = [authority_of(d.section, d.content) for d in docs]

        # 向量分量用绝对刻度（0~1 相似度本身就是有意义的绝对值），
        # 其余分量在候选池内做相对归一化（对比度才有意义）。
        vec_n = self._norm_absolute(vec_raw)
        kw_n = self._norm(kw_raw)
        sec_n = self._norm(sec_raw)
        auth_n = self._norm_absolute(auth_raw)

        for d, v, k, s, a in zip(docs, vec_n, kw_n, sec_n, auth_n):
            base_score = (self.w_vector * v + self.w_keyword * k + self.w_section * s)
            # 权威度以乘性折扣参与：FAQ 里的问法与用户口语几乎逐字相同，
            # 关键词与向量两项都会天然偏向 FAQ，
            # 只有乘性折扣才能保证 FAQ 必须「语义明显更优」才能压过政策正文。
            d.score = (base_score + self.w_authority * a) * (0.85 + 0.15 * a)

        out = sorted(docs, key=lambda d: d.score, reverse=True)[:top_k]
        for i, d in enumerate(out, 1):
            d.rank = i
        return out
