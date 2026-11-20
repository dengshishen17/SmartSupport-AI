# -*- coding: utf-8 -*-
"""BM25 稀疏召回器（纯 Python 实现，无 numpy / rank_bm25 依赖）。

为什么自己实现
--------------
1. `rank_bm25` 依赖 numpy，在 Python 3.14 上安装/兼容存在风险；
2. 自己实现可以精确控制分词、索引与打分口径，便于在评测里做 A/B；
3. 不引入第三方依赖，README 里可以明确说明算法细节，面试时可讲清楚。

算法
----
BM25 打分公式（Robertson / Zaragoza 变体）：

    score(D, Q) = Σ_{t ∈ Q}  IDF(t) · ( f(t,D) · (k1 + 1) )
                             ─────────────────────────────────────
                             f(t,D) + k1 · (1 - b + b · |D| / avgdl)

    IDF(t) = ln( 1 + (N - df(t) + 0.5) / (df(t) + 0.5) )

- k1 控制词频饱和速度，默认 1.5
- b 控制文档长度归一化强度，默认 0.75
- N 为语料文档总数，df(t) 为包含词 t 的文档数

分词
----
优先使用 jieba（若已安装），否则退化为「中文按字 bigram + 英文按词 + 数字」的
启发式切分。两者都走同一个 `tokenize()` 入口，切换不影响上层。

语料来源
--------
BM25 需要一个可枚举的语料。生产向量库里的 chunk 就是语料，
因此直接复用 pgvector 的 `vector_store` 表内容（只读）。
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable

from .base import Document

# --------------------------------------------------------------------------
# 分词
# --------------------------------------------------------------------------

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ASCII_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

try:  # pragma: no cover - 依赖是否安装取决于运行环境
    import jieba

    _HAS_JIEBA = True
except Exception:  # pragma: no cover
    jieba = None
    _HAS_JIEBA = False


def tokenize(text: str) -> list[str]:
    """把文本切成检索词元。

    - jieba 可用：中文走 jieba 精确模式，英文/数字走正则单独抽取
    - jieba 不可用：中文取字符 bigram（相邻两字），对短中文查询效果接近词级
    """
    if not text:
        return []
    tokens: list[str] = []

    if _HAS_JIEBA:
        tokens.extend(t.strip() for t in jieba.cut(text) if t.strip())
    else:
        # 退化方案：中文 bigram
        cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
        for run in cjk_runs:
            if len(run) == 1:
                tokens.append(run)
            else:
                tokens.extend(run[i:i + 2] for i in range(len(run) - 1))

    tokens.extend(m.group(0).lower() for m in _ASCII_WORD.finditer(text))
    tokens.extend(m.group(0) for m in _NUMBER.finditer(text))
    return tokens


# --------------------------------------------------------------------------
# BM25 索引
# --------------------------------------------------------------------------


class BM25Index:
    """倒排索引 + BM25 打分。

    纯 Python dict 实现，语料规模在万级 chunk 以内完全够用。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._tf: list[dict[str, int]] = []          # 每篇文档的词频表
        self._len: list[int] = []                    # 每篇文档词元数
        self._df: dict[str, int] = {}                # 词 -> 文档频次
        self._postings: dict[str, list[tuple[int, int]]] = {}  # 词 -> [(doc_idx, tf)]
        self._docs: list[tuple[str, dict[str, Any]]] = []       # (content, metadata)
        self._avgdl: float = 0.0

    # -- 构建 ---------------------------------------------------------------

    def add(self, content: str, metadata: dict[str, Any] | None = None) -> None:
        toks = tokenize(content or "")
        idx = len(self._tf)
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        self._tf.append(tf)
        self._len.append(len(toks))
        self._docs.append((content or "", metadata or {}))
        for t, c in tf.items():
            self._df[t] = self._df.get(t, 0) + 1
            self._postings.setdefault(t, []).append((idx, c))

    def finalize(self) -> "BM25Index":
        n = max(len(self._tf), 1)
        self._avgdl = (sum(self._len) / n) if n else 0.0
        return self

    # -- 查询 ---------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self._tf)

    def idf(self, term: str) -> float:
        n = max(len(self._tf), 1)
        df = self._df.get(term, 0)
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """返回 [(doc_idx, score)]，按分数降序。"""
        if not self._tf:
            return []
        q_terms = tokenize(query)
        if not q_terms:
            return []

        scores: dict[int, float] = {}
        for term in set(q_terms):
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            for doc_idx, tf in postings:
                dl = self._len[doc_idx] or 1
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1.0))
                scores[doc_idx] = scores.get(doc_idx, 0.0) + idf * (tf * (self.k1 + 1)) / denom
        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]


# --------------------------------------------------------------------------
# Retriever
# --------------------------------------------------------------------------


class BM25Retriever:
    """BM25 召回器。

    语料默认从 pgvector 的 vector_store 表读取（只读），与 dense 召回同源，
    保证两路召回看到的是同一批文档，融合才有意义。
    """

    name = "bm25"

    def __init__(self, corpus_provider=None, k1: float = 1.5, b: float = 0.75):
        # corpus_provider: 可调用对象，返回 [(content, metadata), ...]
        self.corpus_provider = corpus_provider
        self.k1 = k1
        self.b = b
        self._index: BM25Index | None = None
        self._index_fingerprint: str | None = None

    # -- 语料 ---------------------------------------------------------------

    def _load_corpus(self) -> list[tuple[str, dict[str, Any]]]:
        if self.corpus_provider is not None:
            return list(self.corpus_provider())
        from .. import vectorstore

        return vectorstore.load_corpus()

    def _build(self) -> BM25Index:
        corpus = self._load_corpus()
        # 用内容指纹判断语料是否变化，避免每次查询都重建索引
        fingerprint = str(len(corpus)) + "|" + str(hash(tuple(c[0] for c in corpus)))
        if self._index is not None and self._index_fingerprint == fingerprint:
            return self._index
        idx = BM25Index(k1=self.k1, b=self.b)
        for content, metadata in corpus:
            idx.add(content, metadata)
        self._index = idx.finalize()
        self._index_fingerprint = fingerprint
        return self._index

    def recall(self, query: str, top_k: int) -> list[Document]:
        index = self._build()
        hits = index.search(query, top_k=top_k)
        docs = []
        for rank, (doc_idx, score) in enumerate(hits, 1):
            content, metadata = index._docs[doc_idx]
            d = Document(
                content=content,
                metadata=metadata,
                score=float(score),
                bm25_score=float(score),
                rank=rank,
            )
            docs.append(d)
        return docs
