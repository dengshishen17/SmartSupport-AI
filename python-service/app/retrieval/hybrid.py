# -*- coding: utf-8 -*-
"""多路召回融合：RRF 与加权归一化两种策略。"""
from __future__ import annotations

from .base import Document


def _minmax_normalize(values: list[float]) -> list[float]:
    """把一组分数归一化到 [0, 1]。

    融合前必须归一化：dense 的 cosine score 落在 [0,1]，
    而 BM25 是无界正数（典型 0~15），直接相加会让 BM25 完全主导，
    融合权重失去意义。
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def reciprocal_rank_fusion(
    ranked_lists: list[list[Document]], k: int = 60
) -> list[Document]:
    """Reciprocal Rank Fusion（RRF）。

        score(d) = Σ_lists 1 / (k + rank_in_list(d))

    RRF 只看排名不看分数，天然规避了不同召回器分数量纲不一致的问题，
    是工业界最常用的融合方式之一。k=60 是原论文的经验值。

    融合后按最终得分降序，score 写入 Document.score，rank 从 1 开始。
    """
    fused: dict[int, Document] = {}
    scores: dict[int, float] = {}

    for docs in ranked_lists:
        for rank, doc in enumerate(docs, 1):
            key = id(doc)
            if key not in fused:
                fused[key] = doc
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

    merged = list(fused.values())
    for doc in merged:
        doc.score = scores.get(id(doc), 0.0)
    merged.sort(key=lambda d: d.score, reverse=True)
    for i, doc in enumerate(merged, 1):
        doc.rank = i
    return merged


def weighted_fusion(
    ranked_lists: list[list[Document]], weights: list[float]
) -> list[Document]:
    """加权归一化融合。

    先对每路召回的分数做 min-max 归一化，再按权重线性加权：
        score(d) = Σ_i  w_i · normalize_i(d)

    与 RRF 的区别：加权融合保留了分数的「强度」信息，
    置信度高的文档会得到更高的分；但对归一化更敏感。
    """
    if len(weights) != len(ranked_lists):
        raise ValueError("weights 数量必须与召回路数一致")

    # 同一文档可能出现在多路召回中，按内容+元数据去重合并
    merged_by_key: dict[tuple, Document] = {}
    order: list[tuple] = []

    for docs in ranked_lists:
        norm = _minmax_normalize([d.score for d in docs])
        for doc, n in zip(docs, norm):
            key = (doc.content[:200], doc.section or "")
            if key not in merged_by_key:
                merged_by_key[key] = doc
                order.append(key)
            else:
                existing = merged_by_key[key]
                # 保留更具体的分项得分
                if doc.dense_score is not None and existing.dense_score is None:
                    existing.dense_score = doc.dense_score
                if doc.bm25_score is not None and existing.bm25_score is None:
                    existing.bm25_score = doc.bm25_score

    for key in order:
        merged_by_key[key].score = 0.0

    for docs, w in zip(ranked_lists, weights):
        norm = _minmax_normalize([d.score for d in docs])
        for doc, n in zip(docs, norm):
            key = (doc.content[:200], doc.section or "")
            merged_by_key[key].score += w * n

    out = [merged_by_key[k] for k in order]
    out.sort(key=lambda d: d.score, reverse=True)
    for i, doc in enumerate(out, 1):
        doc.rank = i
    return out


class HybridRetriever:
    """混合召回器：多路召回 -> 融合。

    fusion="rrf"        使用 Reciprocal Rank Fusion（默认，稳健）
    fusion="weighted"   使用加权归一化融合
    """

    name = "hybrid"

    def __init__(
        self,
        retrievers,
        weights: list[float] | None = None,
        fusion: str = "rrf",
        rrf_k: int = 60,
    ):
        self.retrievers = list(retrievers)
        self.weights = weights
        self.fusion = fusion
        self.rrf_k = rrf_k

    def recall(self, query: str, top_k: int) -> list[Document]:
        lists = [r.recall(query, top_k) for r in self.retrievers]
        if self.fusion == "weighted":
            weights = self.weights or [1.0 / len(lists)] * len(lists)
            merged = weighted_fusion(lists, weights)
        else:
            merged = reciprocal_rank_fusion(lists, k=self.rrf_k)
        return merged[:top_k]
