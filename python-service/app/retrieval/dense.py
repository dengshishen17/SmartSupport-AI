# -*- coding: utf-8 -*-
"""Dense 召回器：pgvector 余弦相似度检索。

包装原 `vectorstore.similarity_search()`，不改变其行为，
仅把返回值转成统一的 Document 结构，便于与其它召回器融合。
"""
from __future__ import annotations

from .base import Document


class DenseRetriever:
    """向量召回。score = 1 - cosine_distance，与原实现口径完全一致。"""

    name = "dense"

    def __init__(self, top_k_multiplier: int = 4):
        # 混合召回时 dense 侧要多召一些，作为 BM25 的补充候选池
        self.top_k_multiplier = top_k_multiplier

    def recall(self, query: str, top_k: int) -> list[Document]:
        from .. import vectorstore

        rows = vectorstore.similarity_search(
            query, top_k=top_k * self.top_k_multiplier, threshold=0.0
        )
        docs = []
        for r in rows:
            d = Document(
                content=r.get("content", ""),
                metadata=r.get("metadata", {}) or {},
                score=float(r.get("score", 0.0)),
                distance=float(r.get("distance", 0.0)),
                dense_score=float(r.get("score", 0.0)),
            )
            docs.append(d)
        return docs
