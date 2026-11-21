"""Embedding：阿里云百炼 OpenAI 兼容接口 text-embedding-v4，1024 维。"""
from openai import OpenAI
from . import config

_client = OpenAI(api_key=config.ALIYUN_API_KEY or "dummy", base_url=config.EMBED_BASE_URL,
                  timeout=10.0, max_retries=0)

# 百炼 text-embedding-v4 单次请求的 input 条数上限
_MAX_BATCH = 10


def embed(text: str) -> list[float]:
    resp = _client.embeddings.create(model=config.EMBED_MODEL, input=text, dimensions=config.EMBED_DIMS)
    return resp.data[0].embedding


def embed_batch(texts: list[str]) -> list[list[float]]:
    """批量 embedding，自动按 API 上限分批。

    百炼 text-embedding-v4 限制单次 input 不超过 10 条，超出会返回
    400 InvalidParameter: batch size is invalid。
    原实现没有分批，知识库只有 6 个 chunk 时未暴露；
    语料扩充到 18 个 chunk 后必然触发，因此在这里统一处理。
    """
    if not texts:
        return []

    out: list[list[float]] = []
    for i in range(0, len(texts), _MAX_BATCH):
        chunk = texts[i:i + _MAX_BATCH]
        resp = _client.embeddings.create(
            model=config.EMBED_MODEL, input=chunk, dimensions=config.EMBED_DIMS)
        out.extend(d.embedding for d in sorted(resp.data, key=lambda x: x.index))
    return out
