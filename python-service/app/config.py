"""SmartSupport Python 服务配置：与 Java 版共用同一批环境变量。

优先级：真实环境变量 > 项目根目录 .env 文件 > 内置默认值。
.env 文件路径为「本文件上溯两级到仓库根」，即 D:\\SmartSupport AI 企业智能售后助手\\.env，
自动向上查找最近的 .env（找不到 .git 也不会报错，直接回退到纯环境变量模式）。
"""
import os

_ENV_LOADED = False


def _load_dotenv() -> None:
    """读取仓库根目录的 .env 注入 os.environ。

    已存在的真实环境变量优先，不被 .env 覆盖。
    解析规则：忽略空行与 # 注释行；支持 KEY=VALUE、export KEY=VALUE；
    VALUE 两侧引号会去掉；行尾 # 注释会剥离（仅当 # 前有空白时）。
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(here)), ".env"),
        os.path.join(os.path.dirname(here), ".env"),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    if line.startswith("export "):
                        line = line[len("export "):].strip()
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if value and value[0] in ("'", '"') and value[-1] == value[0]:
                        value = value[1:-1]
                    elif " #" in value:
                        value = value.split(" #", 1)[0].strip()
                    if key and value and not os.environ.get(key):
                        os.environ[key] = value
        except OSError:
            continue
        return


_load_dotenv()


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

# ---- 检索层策略（feature flag）----
# dense    仅向量召回
# bm25     仅 BM25 召回
# hybrid   向量 + BM25 混合召回（RRF 融合）
# rerank   向量召回 + 规则式重排（默认）
#
# 默认从 dense 改为 rerank：语料扩充到 24 chunk 后实测（75 条标注用例）
#   dense   Hit@1 81.3%  Hit@3 97.3%  MRR 0.8878
#   rerank  Hit@1 89.3%  Hit@3 100%   MRR 0.9378   ← 全面更优
# 可用 RETRIEVAL_MODE=dense 回退到纯向量。
RETRIEVAL_MODE = getenv("RETRIEVAL_MODE", default="rerank")
# BM25 参数
BM25_K1 = float(getenv("BM25_K1", default="1.5"))
BM25_B = float(getenv("BM25_B", default="0.75"))
# 重排候选池放大倍数（先召回 N 倍候选再精排）
RERANK_CANDIDATE_MULTIPLIER = int(getenv("RERANK_CANDIDATE_MULTIPLIER", default="4"))

# ---- 工具执行可靠性 ----
# 单次工具调用超时（秒）
TOOL_TIMEOUT = float(getenv("TOOL_TIMEOUT", default="8.0"))
# 瞬时失败重试次数（不含首次）
TOOL_RETRIES = int(getenv("TOOL_RETRIES", default="2"))
# 重试退避基数（秒），实际等待 = backoff * 第几次
TOOL_RETRY_BACKOFF = float(getenv("TOOL_RETRY_BACKOFF", default="0.3"))
# 同时执行的工具调用数上限
TOOL_MAX_CONCURRENCY = int(getenv("TOOL_MAX_CONCURRENCY", default="8"))
# 熔断阈值：连续失败达该次数后熔断
TOOL_BREAKER_THRESHOLD = int(getenv("TOOL_BREAKER_THRESHOLD", default="3"))
# 熔断冷却时间（秒），到期后半开探测
TOOL_BREAKER_COOLDOWN = float(getenv("TOOL_BREAKER_COOLDOWN", default="30.0"))

# ---- 上下文工程（Token 预算控制）----
# 单次请求的总 prompt 预算（token）。超预算时按「历史 → 检索片段」顺序裁剪，
# 系统提示词不裁（角色设定被裁会直接破坏回答质量）。
CONTEXT_TOKEN_BUDGET = int(getenv("CONTEXT_TOKEN_BUDGET", default="4096"))
# 为模型输出预留的 token（不计入输入预算）
CONTEXT_RESERVE_OUTPUT = int(getenv("CONTEXT_RESERVE_OUTPUT", default="512"))
# 历史消息最多占可用预算的比例
CONTEXT_HISTORY_RATIO = float(getenv("CONTEXT_HISTORY_RATIO", default="0.25"))
# 系统提示词最多占可用预算的比例（仅作参考统计，系统提示词本身不裁）
CONTEXT_SYSTEM_RATIO = float(getenv("CONTEXT_SYSTEM_RATIO", default="0.30"))
# 单个检索片段的最大字符数
CONTEXT_MAX_CHUNK_CHARS = int(getenv("CONTEXT_MAX_CHUNK_CHARS", default="600"))
# 历史消息窗口条数上限（与 MEMORY_MAX_MESSAGES 独立：前者是存储，后者是上下文裁剪）
CONTEXT_MAX_HISTORY_MESSAGES = int(getenv("CONTEXT_MAX_HISTORY_MESSAGES", default="20"))
