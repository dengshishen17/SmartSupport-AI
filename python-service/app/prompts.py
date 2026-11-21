"""Prompt：与 Java 版 AiKnowledgeController 两套 system prompt 完全对齐。

同时提供**版本化 Prompt 管理**（见下方 PromptRegistry）：
- 每个 Prompt 有唯一版本号与内容哈希
- 改动后旧版本仍可复现（用于 Prompt 回归比对）
- `eval/eval_prompt_regression.py` 用它做「改一版 prompt，看指标退不退」的自动化对比
"""

FALLBACK_SYSTEM = """你是企业售后客服。用户正在咨询售后问题，但售后政策知识库暂时没有检索到相关条文。
请这样做：
1. 先对用户的问题表示理解和重视（如涉及商品质量问题，表达歉意）
2. 用户的问题涉及具体订单号时，直接调用查询工具获取真实业务数据并如实告知用户；政策规则类问题则说明暂时无法确认具体规则，为避免误导不做主观判断
3. 只有在确实缺少必要信息时才追问（如用户没提供订单号、或需要了解商品问题的具体表现）
4. 用户也可以直接转人工客服处理
语气自然亲切，像真实客服一样说话。使用纯文本输出，不要使用任何 Markdown 格式符号。控制在 150 字以内。"""

RAG_SYSTEM_TEMPLATE = """你是企业售后客服，正在接待一位客户。请根据以下售后政策知识处理客户的诉求。
处理要求：
1. 先理解客户的真实意图（退货、退款、换货、保修、查物流等），即使用户的表达很口语化
2. 只依据下方知识内容回答具体规则，不要编造政策条款
3. 用户提出明确诉求时（如要退货），先共情安抚，再直接说明对应的处理规则、流程和时效
4. 用户的问题涉及具体订单号时，优先调用查询工具获取真实业务数据（订单状态、退款进度、工单进度），再结合政策回答，不要凭空猜测数据
5. 如果处理该诉求还需要更多信息（如购买时间、订单编号、商品具体状况），在说明规则后自然地追问
6. 如果知识中确实没有相关规则，明确说明暂时无法确认，建议转人工客服，不要硬答
7. 用自然、简洁、连贯的中文回答，像真实客服一样说话
8. 使用纯文本输出，不要使用任何 Markdown 格式：不要加粗符号、不要标题符号、不要减号列表符号；需要分点时用"第一、第二"或分号自然衔接
9. 回答控制在 250 字以内

【售后政策知识】
%s"""


# 当前生效的 RAG Prompt 版本号。
# 默认 v2 —— 回归比对（eval/eval_prompt_regression.py，84 条用例 × 2 轮 × 2 版本）结论：
#   faithfulRate  97.03% → 97.62%   落在噪声带内（无显著变化）
#   refusedRate   96.43% → 98.21%   +1.78pt > 噪声 0.84pt，判定 IMPROVED
#   其余指标（工具选型/成功率/延迟）均无显著变化
# 即 v2 不引入退化，同时减少了「答对了却被判过度拒答」的情况，故设为默认。
# 需要回退基线时把这里改成 "v1" 即可（版本内容永久保留，可随时 A/B）。
ACTIVE_RAG_VERSION = "v2"


def build_system(retrieved: list[dict], version: str | None = None) -> tuple[str, bool]:
    """组装 system prompt。

    version 为空时用 ACTIVE_RAG_VERSION 指定的版本内容。
    """
    if not retrieved:
        return FALLBACK_SYSTEM, False
    context = "\n\n---\n\n".join(d["content"] for d in retrieved)
    template = RAG_SYSTEM_TEMPLATE
    pv = REGISTRY.get("rag_system", version or ACTIVE_RAG_VERSION)
    if pv is not None and "%s" in pv.content:
        template = pv.content
    return template % context, True


# --------------------------------------------------------------------------
# Prompt 版本管理
#
# 为什么要版本化
# --------------
# Prompt 是 LLM 应用里最易变、也最难回归的部分：改一句话可能让忠实度掉 5pt，
# 但不改动时 LLM-as-Judge 又有 3~7pt 的随机波动，两次「看起来有差异」的对比
# 往往只是噪声。版本化 + 固定评测集 + 多轮取中位数，才��让「改 prompt 到底
# 有没有变好」变成一个可回答的问题。
#
# 设计
# ----
# - 每次注册产生不可变条目：version / content / hash / created_at / note
# - 内容哈希用于识别「内容没变但版本号变了」的无效改动
# - 旧版本永久保留，可随时切回做 A/B 对比
# --------------------------------------------------------------------------

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PromptVersion:
    """一条不可变的 Prompt 版本。"""

    version: str
    content: str
    hash: str
    created_at: float
    note: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "hash": self.hash,
            "createdAt": self.created_at,
            "note": self.note,
            "meta": dict(self.meta),
        }


class PromptRegistry:
    """Prompt 版本注册表。

    内部以 (name, version) 为键存储 —— 不同用途的 Prompt 可以各自拥有 v1，
    互不冲突。对外通过 name + version 定位。
    """

    def __init__(self):
        self._versions: dict[tuple[str, str], PromptVersion] = {}
        self._latest: dict[str, str] = {}

    @staticmethod
    def _key(name: str, version: str) -> tuple[str, str]:
        return (name, version)

    def register(self, name: str, content: str, version: str | None = None,
                 note: str = "", meta: dict[str, Any] | None = None) -> PromptVersion:
        """注册一个 Prompt 版本。

        version 为空时按该 name 下已有的版本号自动递增（v1、v2、v3…）。
        同一 name 重复注册相同内容会复用已有版本（避免版本号虚增）。
        """
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]

        # 内容完全相同 → 复用旧版本（避免版本号虚增，也便于回归对比时对齐）
        for pv in self._versions.values():
            if pv.meta.get("name") == name and pv.hash == h:
                return pv

        if version is None:
            n = 1
            while self._key(name, f"v{n}") in self._versions:
                n += 1
            version = f"v{n}"

        pv = PromptVersion(
            version=version,
            content=content,
            hash=h,
            created_at=time.time(),
            note=note,
            meta={"name": name, **(meta or {})},
        )
        self._versions[self._key(name, version)] = pv
        self._latest[name] = version
        return pv

    def get(self, name: str, version: str) -> PromptVersion | None:
        return self._versions.get(self._key(name, version))

    def latest(self, name: str) -> PromptVersion | None:
        v = self._latest.get(name)
        return self._versions.get(self._key(name, v)) if v else None

    def list(self, name: str | None = None) -> list[PromptVersion]:
        items = list(self._versions.values())
        if name:
            items = [p for p in items if p.meta.get("name") == name]
        return sorted(items, key=lambda p: p.created_at)

    def diff(self, name: str, v1: str, v2: str) -> dict[str, Any]:
        """比对同一 name 下两个版本的差异摘要。"""
        a, b = self.get(name, v1), self.get(name, v2)
        if not a or not b:
            return {"ok": False, "error": f"版本不存在：{name} {v1} / {v2}"}
        if a.hash == b.hash:
            return {"ok": True, "identical": True, "name": name, "from": v1, "to": v2}
        import difflib
        diff = list(difflib.unified_diff(
            a.content.splitlines(), b.content.splitlines(),
            fromfile=f"{name}@{v1}", tofile=f"{name}@{v2}", lineterm=""))
        return {
            "ok": True,
            "identical": False,
            "name": name,
            "from": v1,
            "to": v2,
            "addedLines": sum(1 for d in diff if d.startswith("+") and not d.startswith("+++")),
            "removedLines": sum(1 for d in diff if d.startswith("-") and not d.startswith("---")),
            "diff": diff[:200],
        }


# 进程级注册表
REGISTRY = PromptRegistry()


def register_prompt(name: str, content: str, version: str | None = None,
                    note: str = "", meta: dict[str, Any] | None = None) -> PromptVersion:
    """便捷入口：注册并返回版本对象。"""
    return REGISTRY.register(name, content, version=version, note=note, meta=meta)


def get_prompt(name: str, version: str) -> PromptVersion | None:
    return REGISTRY.get(name, version)


def latest_prompt(name: str) -> PromptVersion | None:
    return REGISTRY.latest(name)


def diff_prompt(name: str, v1: str, v2: str) -> dict[str, Any]:
    return REGISTRY.diff(name, v1, v2)


def list_prompts(name: str | None = None) -> list[PromptVersion]:
    return REGISTRY.list(name)


# --------------------------------------------------------------------------
# 内置 Prompt 的默认版本注册
#
# 注册「基线版本」后，eval_prompt_regression.py 可以：
#   1. 跑基线 → 存指标
#   2. register 一个候选版本 → 跑候选 → 存指标
#   3. 对比两组指标，判断改动是真实提升还是噪声
# --------------------------------------------------------------------------

BASELINE_RAG_V1 = register_prompt(
    "rag_system",
    RAG_SYSTEM_TEMPLATE,
    version="v1",
    note="基线：抽取 9 条处理要求 + 250 字上限（改造前线上版本）",
    meta={"kind": "baseline"},
)

BASELINE_FALLBACK_V1 = register_prompt(
    "fallback_system",
    FALLBACK_SYSTEM,
    version="v1",
    note="基线：知识库无命中时的兜底话术（改造前线上版本）",
    meta={"kind": "baseline"},
)


# --------------------------------------------------------------------------
# 候选版本 v2
#
# 设计依据（来自 Agent 轨迹评测的真实失败分布，不是拍脑袋）：
#   30 条用例 react 模式下失败归因：HALLUCINATION 4 条、RETRIEVAL_EMPTY 3 条
#   分类别忠实度：tool 100%、policy 80%、colloquial 75%、out_of_scope 75%
#
# 两个主要问题：
# 1. **HALLUCINATION（4 条，最高频）** —— 模型在检索不到时仍会补编条款。
#    对策：把「只依据知识」从软要求改成硬性动作清单（先查再答、查不到就停）。
# 2. **colloquial 类别 75%** —— 口语化提问容易被当成越界而过度拒答。
#    对策：明确「口语化提问仍是有效提问」，避免误判为越界。
#
# 另加一条「不在正文末尾附加转人工兜底话术」——
# 这条是被评测器发现的：模型答对后习惯性补一句「如需…建议转人工」，
# 导致裁判把正确回答判成过度拒答（REFUSAL_OVER 误判 3/30）。
# --------------------------------------------------------------------------

RAG_SYSTEM_V2 = """你是企业售后客服，正在接待一位客户。请根据以下售后政策知识处理客户的诉求。
处理要求：
1. 先理解客户的真实意图（退货、退款、换货、保修、查物流等），即使用户的表达很口语化
2. 先查知识再回答：动手回答前先在下方知识中查找对应条款，确认条款原文后再作答
3. 只依据下方知识内容回答具体规则，不要编造政策条款，不要补充知识里没有的时限、金额或条件
4. 如果下方知识确实没有对应条款，明确说明暂时无法确认并建议转人工客服，不要硬答、不要猜
5. 用户提出明确诉求时（如要退货），先共情安抚，再直接说明对应的处理规则、流程和时效
6. 用户的问题涉及具体订单号时，优先调用查询工具获取真实业务数据（订单状态、退款进度、工单进度），再结合政策回答，不要凭空猜测数据
7. 如果处理该诉求还需要更多信息（如购买时间、订单编号、商品具体状况），在说明规则后自然地追问
8. 用自然、简洁、连贯的中文回答，像真实客服一样说话
9. 使用纯文本输出，不要使用任何 Markdown 格式：不要加粗符号、不要标题符号、不要减号列表符号；需要分点时用"第一、第二"或分号自然衔接
10. 回答控制在 250 字以内
11. 已依据知识给出明确规则时，结尾不要再附加"如需更多帮助请转人工"之类的兜底话术

【售后政策知识】
%s"""

RAG_V2 = register_prompt(
    "rag_system",
    RAG_SYSTEM_V2,
    version="v2",
    note="候选：强制先查再答、显式禁止编造条款、口语化提问不算越界、去掉末尾转人工兜底话术",
    meta={"kind": "candidate"},
)
