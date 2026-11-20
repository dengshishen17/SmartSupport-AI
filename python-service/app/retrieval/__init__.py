# -*- coding: utf-8 -*-
"""检索层抽象：把「召回」与「排序」解耦，支持 Dense / BM25 / 混合 / Rerank 组合。

设计目标
--------
原实现里 `vectorstore.similarity_search()` 同时做了「向量召回 + 阈值过滤 + 排序」，
要加 BM25 混合检索或 Rerank 就只能往里硬塞，调用方也无法做 A/B 对比。

本包把检索拆成可插拔的三段：
    召回(recall)  ->  融合(fusion)  ->  重排(rerank)

- Retriever：负责召回一批候选文档（DenseRetriever / BM25Retriever）
- Fusion：负责把多路召回结果合并打分（RRF / 加权归一化）
- Reranker：负责对候选做二次精排（规则式 / Cross-Encoder）

统一入口 `retrieve()`，通过 config.RETRIEVAL_MODE 切换策略，默认保持现有行为
（dense-only），保证不改变生产行为。
"""
from .base import Document, Retriever, Reranker
from .dense import DenseRetriever
from .bm25 import BM25Retriever
from .hybrid import HybridRetriever, reciprocal_rank_fusion
from .pipeline import retrieve, get_retriever

__all__ = [
    "Document",
    "Retriever",
    "Reranker",
    "DenseRetriever",
    "BM25Retriever",
    "HybridRetriever",
    "reciprocal_rank_fusion",
    "retrieve",
    "get_retriever",
]
