# -*- coding: utf-8 -*-
"""检索层基础类型：统一文档结构、召回器接口与重排器接口。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Document:
    """检索结果统一结构。

    兼容原 `vectorstore.similarity_search()` 的返回字典：
    content / metadata / score / distance，同时扩展多路召回所需的分项得分与最终排名。
    """

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0            # 最终得分（融合/重排后）
    distance: float = 0.0        # 向量距离（仅 dense 召回时有值）
    dense_score: float | None = None
    bm25_score: float | None = None
    rank: int = 0                # 最终排名，1 起

    @property
    def section(self) -> str | None:
        """从正文首行 `## xxx` 取章节标题（与原 vectorstore.section_of 同口径）。"""
        for line in (self.content or "").split("\n"):
            t = line.strip()
            if t.startswith("## "):
                return t[3:].strip()
        return None

    def to_dict(self) -> dict[str, Any]:
        """转成原调用方期望的字典结构，保证向后兼容。"""
        return {
            "content": self.content,
            "metadata": self.metadata or {},
            "distance": self.distance,
            "score": self.score,
        }


class Retriever(Protocol):
    """召回器协议：把一批文档召回到候选池。"""

    name: str

    def recall(self, query: str, top_k: int) -> list[Document]:
        """召回候选文档，按自身得分降序返回。"""
        ...


class Reranker(Protocol):
    """重排器协议：对候选池做二次精排。"""

    name: str

    def rerank(self, query: str, docs: list[Document], top_k: int) -> list[Document]:
        """返回重排后的前 top_k 个文档。"""
        ...
