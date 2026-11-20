# -*- coding: utf-8 -*-
"""重排器（Rerank）：对召回候选做二次精排。

为什么不用 Cross-Encoder
-----------------------
Cross-Encoder（如 bge-reranker）效果最好，但需要额外下载模型权重、
引入 torch/transformers 依赖，在本项目的轻量部署目标下不合适。

本模块实现**可解释的规则式重排**，融合三个信号：
    1. 向量相似度       —— 语义相关性
    2. 查询词命中率     —— 关键词是否真的出现在正文中
    3. 章节匹配度       —— 命中的章节标题与查询的词汇重合度

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


class RuleReranker:
    """规则式重排器。

    最终得分（各分量先归一化到 [0,1] 再加权）：
        final = w_vec · vec_norm + w_kw · keyword_norm + w_sec · section_norm
    """

    name = "rule_rerank"

    def __init__(
        self,
        base,
        w_vector: float = 0.6,
        w_keyword: float = 0.25,
        w_section: float = 0.15,
    ):
        self.base = base
        self.w_vector = w_vector
        self.w_keyword = w_keyword
        self.w_section = w_section

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
        if not values:
            return []
        lo, hi = min(values), max(values)
        if hi - lo < 1e-12:
            return [1.0 for _ in values]
        return [(v - lo) / (hi - lo) for v in values]

    # -- 主流程 -------------------------------------------------------------

    def rerank(self, query: str, docs: list[Document], top_k: int) -> list[Document]:
        if not docs:
            return []

        vec_raw = [d.dense_score if d.dense_score is not None else d.score for d in docs]
        kw_raw = [self._keyword_coverage(query, d.content) for d in docs]
        sec_raw = [self._section_match(query, d.section) for d in docs]

        vec_n = self._norm(vec_raw)
        kw_n = self._norm(kw_raw)
        sec_n = self._norm(sec_raw)

        for d, v, k, s in zip(docs, vec_n, kw_n, sec_n):
            d.score = self.w_vector * v + self.w_keyword * k + self.w_section * s

        out = sorted(docs, key=lambda d: d.score, reverse=True)[:top_k]
        for i, d in enumerate(out, 1):
            d.rank = i
        return out
