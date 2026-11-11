"""Redis 会话记忆：与 Java 版 RedisChatMemoryRepository 同一 key 与口径。
key=chat:memory:{sessionId} value=[{role,content}] JSON，TTL 2h，只存纯文本问答对，窗口 20 条。
"""
import json
import socket
import redis
from . import config

_rdb = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, decode_responses=True,
                   socket_connect_timeout=2, socket_timeout=2)


def redis_available(timeout: float = 1.0) -> bool:
    try:
        s = socket.create_connection((config.REDIS_HOST, config.REDIS_PORT), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def key_of(session_id: str) -> str:
    return f"{config.MEMORY_KEY_PREFIX}{session_id}"


def load(session_id: str) -> list[dict]:
    if not redis_available():
        return []
    try:
        raw = _rdb.get(key_of(session_id))
    except Exception:
        return []
    if not raw:
        return []
    try:
        msgs = json.loads(raw)
        return [m for m in msgs if m.get("role") in ("user", "assistant") and m.get("content")]
    except Exception:
        return []


def save_turn(session_id: str, user_text: str, assistant_text: str):
    msgs = load(session_id)
    msgs.append({"role": "user", "content": user_text})
    if assistant_text:
        msgs.append({"role": "assistant", "content": assistant_text})
    msgs = msgs[-config.MEMORY_MAX_MESSAGES:]
    if not redis_available():
        return
    try:
        _rdb.set(key_of(session_id), json.dumps(msgs, ensure_ascii=False), ex=config.MEMORY_TTL_SECONDS)
    except Exception:
        pass
