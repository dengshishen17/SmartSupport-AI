"""pgvector 检索：与 Java 版 PgVectorStore 同一表、同一距离口径。
表 public.vector_store(content text, metadata jsonb, embedding vector(1024))。
Spring AI 阈值语义：WHERE distance < (1 - threshold)，score = 1 - distance。
"""
import json
import socket
import psycopg
from . import config, embeddings


def pg_available(timeout: float = 1.0) -> bool:
    """PG 端口快速预检：不通则直接抛错，跳过 embedding 调用（省一次出网耗时）。"""
    try:
        s = socket.create_connection((config.PG_HOST, config.PG_PORT), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _conn():
    return psycopg.connect(host=config.PG_HOST, port=config.PG_PORT,
                           user=config.PG_USER, password=config.PG_PASSWORD, dbname=config.PG_DB,
                           connect_timeout=3)


def similarity_search(query: str, top_k: int = 5, threshold: float = 0.0):
    if not pg_available():
        raise ConnectionError(f"pgvector 不可用（{config.PG_HOST}:{config.PG_PORT} 端口不通），请先启动 Docker Compose")
    qvec = embeddings.embed(query)
    max_distance = 1.0 - threshold
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT content, metadata, (embedding <=> %s::vector) AS distance
               FROM public.vector_store
               WHERE (embedding <=> %s::vector) < %s
               ORDER BY embedding <=> %s::vector
               LIMIT %s""",
            (str(qvec), str(qvec), max_distance, str(qvec), top_k),
        )
        rows = cur.fetchall()
    out = []
    for content, metadata, distance in rows:
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        out.append({"content": content, "metadata": metadata or {},
                    "distance": float(distance), "score": 1.0 - float(distance)})
    return out


def section_of(content: str) -> str | None:
    if not content:
        return None
    for line in content.split("\n"):
        t = line.strip()
        if t.startswith("## "):
            return t[3:].strip()
    return None
