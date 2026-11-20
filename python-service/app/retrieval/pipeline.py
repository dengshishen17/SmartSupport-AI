# -*- coding: utf-8 -*-
"""检索统一入口：按配置选择召回策略，调用方（agent / workflow / main / eval）只需调 `retrieve()`。

策略由 config.RETRIEVAL_MODE 控制：
    dense     仅向量召回（默认，与改造前行为一致）
    bm25      仅 BM25 召回
    hybrid    向量 + BM25 混合召回（RRF 融合）
    rerank    向量召回 + 规则式重排

新增策略一律走 feature flag，不改变默认行为，保证生产不受影响。
"""
from __future__ import annotations

from .base import Document
from .bm25 import BM25Retriever
from .dense import DenseRetriever
from .hybrid import HybridRetriever
from .rerank import RuleReranker

_retrievers: dict[str, object] = {}


def _get(name: str):
    """按名字取（并缓存）召回器实例。"""
    if name in _retrievers:
        return _retrievers[name]

    if name == "dense":
        inst = DenseRetriever()
    elif name == "bm25":
        inst = BM25Retriever(k1=_cfg_float("BM25_K1", 1.5), b=_cfg_float("BM25_B", 0.75))
    elif name == "hybrid":
        inst = HybridRetriever(
            [
                DenseRetriever(),
                BM25Retriever(k1=_cfg_float("BM25_K1", 1.5), b=_cfg_float("BM25_B", 0.75)),
            ],
            fusion="rrf",
        )
    elif name == "rerank":
        from .rerank import RuleReranker

        inst = RuleReranker(DenseRetriever(top_k_multiplier=_cfg_int("RERANK_CANDIDATE_MULTIPLIER", 4)))
    else:
        raise ValueError(f"未知检索模式：{name}")

    _retrievers[name] = inst
    return inst


def _cfg_float(key: str, default: float) -> float:
    from .. import config

    return float(getattr(config, key, default))


def _cfg_int(key: str, default: int) -> int:
    from .. import config

    return int(getattr(config, key, default))


def get_retriever(name: str | None = None):
    """按名称获取召回器；name 为空时用 config.RETRIEVAL_MODE。"""
    if name is None:
        from .. import config

        name = getattr(config, "RETRIEVAL_MODE", "dense")
    return _get(name)


def retrieve(
    query: str,
    top_k: int = 5,
    threshold: float = 0.0,
    mode: str | None = None,
) -> list[dict]:
    """统一检索入口，返回与原 `vectorstore.similarity_search()` 兼容的字典列表。

    参数
    ----
    query     查询串
    top_k     返回条数
    threshold 相似度阈值（仅 dense 路径生效；混合路径按 dense 分量过滤）
    mode      检索模式，为空取 config.RETRIEVAL_MODE

    返回
    ----
    [{content, metadata, distance, score}, ...]
    """
    retr = get_retriever(mode)

    if isinstance(retr, RuleReranker):
        # 召回候选池放大后再精排
        docs: list[Document] = retr.rerank(query, retr.base.recall(query, top_k * retr.base.top_k_multiplier), top_k)
    else:
        docs = retr.recall(query, top_k)

    if threshold > 0:
        docs = [d for d in docs if (d.dense_score is None or d.dense_score >= threshold)]

    return [d.to_dict() for d in docs[:top_k]]
