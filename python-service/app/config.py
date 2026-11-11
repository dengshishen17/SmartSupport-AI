"""SmartSupport Python 服务配置：与 Java 版共用同一批环境变量。"""
import os


def getenv(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


DEEPSEEK_API_KEY = getenv("DEEPSEEK_API_KEY", "DEEPSEEK-KEY")
DEEPSEEK_BASE_URL = getenv("DEEPSEEK_BASE_URL", default="https://api.deepseek.com/v1")
DEEPSEEK_MODEL = getenv("DEEPSEEK_MODEL", default="deepseek-chat")

ALIYUN_API_KEY = getenv("ALIYUN_API_KEY", "ALIYUN-KEY")
EMBED_BASE_URL = getenv("EMBED_BASE_URL", default="https://dashscope.aliyuncs.com/compatible-mode/v1")
EMBED_MODEL = getenv("EMBED_MODEL", default="text-embedding-v4")
EMBED_DIMS = int(getenv("EMBED_DIMS", default="1024"))

MYSQL_HOST = getenv("MYSQL_HOST", default="127.0.0.1")
MYSQL_PORT = int(getenv("MYSQL_PORT", default="3306"))
MYSQL_USER = getenv("MYSQL_USER", default="root")
MYSQL_PASSWORD = getenv("MYSQL_PASSWORD")
MYSQL_DB = getenv("MYSQL_DB", default="smart_support")

PG_HOST = getenv("PG_HOST", default="127.0.0.1")
PG_PORT = int(getenv("PG_PORT", default="5432"))
PG_USER = getenv("PG_USER", default="postgres")
PG_PASSWORD = getenv("PG_PASSWORD")
PG_DB = getenv("PG_DB", default="knowledge")

REDIS_HOST = getenv("REDIS_HOST", default="127.0.0.1")
REDIS_PORT = int(getenv("REDIS_PORT", default="6379"))

# RAG 生产参数：与 Java 版 AiKnowledgeController 对齐
RAG_TOP_K = int(getenv("RAG_TOP_K", default="5"))
RAG_THRESHOLD = float(getenv("RAG_THRESHOLD", default="0.0"))
MEMORY_TTL_SECONDS = 2 * 3600
MEMORY_MAX_MESSAGES = 20
MEMORY_KEY_PREFIX = "chat:memory:"
