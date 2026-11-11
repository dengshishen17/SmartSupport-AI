"""Embedding：阿里云百炼 OpenAI 兼容接口 text-embedding-v4，1024 维。"""
from openai import OpenAI
from . import config

_client = OpenAI(api_key=config.ALIYUN_API_KEY or "dummy", base_url=config.EMBED_BASE_URL,
                  timeout=10.0, max_retries=0)


def embed(text: str) -> list[float]:
    resp = _client.embeddings.create(model=config.EMBED_MODEL, input=text, dimensions=config.EMBED_DIMS)
    return resp.data[0].embedding


def embed_batch(texts: list[str]) -> list[list[float]]:
    resp = _client.embeddings.create(model=config.EMBED_MODEL, input=texts, dimensions=config.EMBED_DIMS)
    return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
