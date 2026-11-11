"""知识切分与入库：RecursiveCharacterTextSplitter(chunk 512/overlap 50) + 百炼 embedding 批量写入 pgvector。
写入格式与 Java 版 PgVectorStore 完全一致：id=uuid_generate_v4(), metadata 含 source/section/chunk_index。
"""
import re
import uuid

import psycopg
from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import config, embeddings

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=512, chunk_overlap=50,
    separators=["\n## ", "\n### ", "\n\n", "\n", "。", "；", " ", ""],
)


def split_markdown(content: str, source: str) -> list[dict]:
    """先按 ## 章节粗切（与 Java 版同口径），超长章节再按 512/50 细切。返回 [{text, metadata}]。"""
    sections = re.split(r"(?=\n## )", content)
    out: list[dict] = []
    for sec in sections:
        t = sec.strip()
        if not t:
            continue
        if t.startswith("# ") and "\n## " not in sec:
            continue  # 跳过文件开头前言
        m = re.match(r"##\s*(.+)", t)
        section_title = m.group(1).strip() if m else t[:30]
        pieces = _splitter.split_text(t) if len(t) > 512 else [t]
        for i, p in enumerate(pieces):
            out.append({"text": p, "metadata": {"source": source, "section": section_title,
                                                "chunk_index": i, "chunks_in_section": len(pieces)}})
    return out


def store_chunks(chunks: list[dict]):
    """批量 embedding + 写入 public.vector_store。返回写入条数。"""
    if not chunks:
        return 0
    vecs = embeddings.embed_batch([c["text"] for c in chunks])
    with psycopg.connect(host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
                         password=config.PG_PASSWORD, dbname=config.PG_DB,
                         connect_timeout=5) as conn, conn.cursor() as cur:
        for c, v in zip(chunks, vecs):
            cur.execute(
                "INSERT INTO public.vector_store (id, content, metadata, embedding) "
                "VALUES (uuid_generate_v4(), %s, %s::jsonb, %s::vector)",
                (c["text"], __import__("json").dumps(c["metadata"], ensure_ascii=False), str(v)),
            )
        conn.commit()
    return len(chunks)


def delete_by_source(source: str) -> int:
    with psycopg.connect(host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
                         password=config.PG_PASSWORD, dbname=config.PG_DB,
                         connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM public.vector_store WHERE metadata->>'source' = %s", (source,))
        n = cur.rowcount
        conn.commit()
    return n


def chunk_preview(content: str, source: str = "preview") -> list[dict]:
    """只切分不入库：返回每段长度与元数据，供调 chunk 参数用。"""
    chunks = split_markdown(content, source)
    return [{"index": i, "chars": len(c["text"]), "section": c["metadata"]["section"],
             "head": c["text"][:60]} for i, c in enumerate(chunks)]
