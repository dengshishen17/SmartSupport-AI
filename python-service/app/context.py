# -*- coding: utf-8 -*-
"""上下文工程：Token 预算控制与上下文压缩。

要解决的实际问题
----------------
一次问答的 prompt 由三部分构成，三者都可能无节制膨胀：

1. **系统提示词**（固定文案 + 注入的检索片段）
2. **历史会话消息**（Redis 窗口 20 条，每条都可能是 250 字的长回答）
3. **检索片段**（topK=5，每段最长 600 字）

历史实测：ReAct 链路平均 prompt token 1825/条（30 条用例实测 54,759 token）。
其中系统提示词约 300-400 token，检索片段注入 3~5 段 × 400-600 字是最大头，
历史消息在多轮场景下线性累加。

本模块提供三类控制手段（全部离线可测，不调 LLM）：

- :func:`count_tokens`      轻量 Token 估算（不依赖 tiktoken，兼容国产模型）
- :func:`compress_context`  按预算压缩检索片段，**保序裁剪**而非粗暴截断
- :func:`build_history`     历史消息窗口裁剪，带**预算 + 轮次**双重约束

设计原则
--------
1. **不丢语义完整性**：裁剪片段时按「整段」边界切，不从中间劈开，避免半句话污染语义。
2. **保序优先**：检索得分已按相关度降序，裁剪时保留高相关的前 N 段。
3. **可观测**：每次压缩都产出统计（原始/压缩后 token、丢弃段数），供评测与 trace 消费。
4. **纯函数**：不依赖 DB / 网络，便于离线单测与确定性回归。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# Token 估算
#
# 不引 tiktoken：DeepSeek / Qwen 等国产模型的 BPE 与 GPT 系列不同，
# tiktoken 的 cl100k 对中文估算误差可达 ±30%，反而误导预算控制。
#
# 这里采用业界常用的字符启发式：
#   中文/全角字符 ≈ 1 token
#   英文单词 ≈ 1 token（按空格切分近似）
#   其他 ASCII ≈ 0.3 token（按 3~4 字符/token 折算）
#
# 相对误差约 ±10%，对「预算控制」这个用途足够（宁可略高估，
# 也不要超预算把请求打到上下文上限外）。
# --------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def count_tokens(text: str) -> int:
    """估算文本 Token 数（中文按字计，英文按词计，其余按 0.3/字符折算）。

    >>> count_tokens("你好") == 2
    >>> count_tokens("hello world") == 2
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    latin_words = len(_LATIN_WORD_RE.findall(text))
    # 非 CJK、非拉丁词字符（标点、空格、符号）
    others = max(0, len(text) - cjk - sum(len(w) for w in _LATIN_WORD_RE.findall(text)))
    return int(cjk + latin_words + others * 0.3)


def count_message_tokens(messages: list[dict]) -> int:
    """估算一组消息（role/content）的总 Token，含每条消息约 4 token 的协议开销。"""
    total = 0
    for m in messages or []:
        total += count_tokens(str(m.get("content", ""))) + 4
    return total


# --------------------------------------------------------------------------
# 检索片段压缩
# --------------------------------------------------------------------------


@dataclass
class ContextStats:
    """一次上下文组装的统计（用于评测与 trace）。"""

    original_tokens: int = 0
    final_tokens: int = 0
    dropped_chunks: int = 0
    dropped_history: int = 0
    kept_chunks: int = 0
    budget: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def saved_tokens(self) -> int:
        return max(0, self.original_tokens - self.final_tokens)

    @property
    def saved_ratio(self) -> float:
        if self.original_tokens <= 0:
            return 0.0
        return self.saved_tokens / self.original_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "originalTokens": self.original_tokens,
            "finalTokens": self.final_tokens,
            "savedTokens": self.saved_tokens,
            "savedRatio": round(self.saved_ratio, 4),
            "droppedChunks": self.dropped_chunks,
            "droppedHistory": self.dropped_history,
            "keptChunks": self.kept_chunks,
            "budget": self.budget,
            **({"detail": self.detail} if self.detail else {}),
        }


def compress_context(
    retrieved: list[dict],
    budget_tokens: int = 0,
    max_chunk_chars: int = 600,
    separator: str = "\n\n---\n\n",
) -> tuple[list[dict], ContextStats]:
    """按 Token 预算压缩检索片段。

    参数
    ----
    retrieved        检索结果列表（已按相关度降序），元素需含 content
    budget_tokens    片段总预算；<=0 表示不限制
    max_chunk_chars 单段最大字符数（超长按句子边界切，超出部分丢弃）
    separator        段间分隔符（用于统计拼接后的 token）

    返回
    ----
    (压缩后的片段列表, 统计)

    压缩策略
    --------
    1. **单段裁剪**：超长片段按中文句末标点切分，保留前 N 句；
       切不出句子边界时按字符硬切（最后手段）。
    2. **整段丢弃**：逐段累加预算，超预算的段落整段丢弃，
       不从段落中间截断（避免半句话进入 prompt）。
    3. **保序**：只从尾部丢弃，保留高相关度的前段。
    """
    stats = ContextStats(budget=budget_tokens)

    if not retrieved:
        stats.final_tokens = 0
        return [], stats

    # ---- 第零步：记录裁剪前的原始规模（用于统计真实节省量）----
    stats.original_tokens = count_tokens(separator.join(d.get("content", "") or "" for d in retrieved))

    # ---- 第一步：单段长度裁剪 ----
    trimmed: list[dict] = []
    for doc in retrieved:
        content = doc.get("content", "") or ""
        if len(content) > max_chunk_chars:
            content = _truncate_to_sentences(content, max_chunk_chars)
        if not content.strip():
            continue
        new_doc = dict(doc)
        new_doc["content"] = content
        trimmed.append(new_doc)

    stats.kept_chunks = len(trimmed)

    # ---- 第二步：整段预算裁剪 ----
    if budget_tokens <= 0:
        kept = trimmed
    else:
        kept = []
        used = 0
        for doc in trimmed:
            cost = count_tokens(doc["content"]) + count_tokens(separator)
            if used + cost > budget_tokens:
                break
            kept.append(doc)
            used += cost
        stats.dropped_chunks = len(trimmed) - len(kept)

    stats.final_tokens = count_tokens(separator.join(d["content"] for d in kept))
    return kept, stats


def _truncate_to_sentences(text: str, max_chars: int) -> str:
    """把长文本裁到 max_chars 以内，尽量在句子边界断开。"""
    if len(text) <= max_chars:
        return text

    # 优先在句末标点处断（中文优先，其次英文）
    for marks in ("。", "！", "？", "；", ".\n", "\n\n", "\n", ". ", "!", "?"):
        idx = text.rfind(marks, 0, max_chars)
        if idx > max_chars * 0.5:
            return text[: idx + len(marks)].rstrip()

    # 退而求其次：按逗号/顿号断
    for marks in ("，", ",", "、"):
        idx = text.rfind(marks, 0, max_chars)
        if idx > max_chars * 0.5:
            return text[: idx + len(marks)].rstrip()

    # 硬切
    return text[:max_chars].rstrip()


# --------------------------------------------------------------------------
# 历史消息窗口
# --------------------------------------------------------------------------


def build_history(
    messages: list[dict],
    max_messages: int = 20,
    budget_tokens: int = 0,
    keep_latest: int = 2,
) -> tuple[list[dict], int]:
    """裁剪历史消息窗口。

    参数
    ----
    messages       历史消息（role/content 列表），按时间升序
    max_messages   最大条数（对应 Redis 窗口）
    budget_tokens  历史部分总预算；<=0 表示不限制
    keep_latest    始终保留的最后 N 条（当前问题的直接上下文，优先保住）

    返回
    ----
    (裁剪后的消息列表, 被丢弃条数)

    裁剪策略：从最早的消息开始整轮丢弃（user+assistant 成对），
    直到满足条数与预算约束；最后 keep_latest 条永不丢弃。
    """
    msgs = list(messages or [])
    if not msgs:
        return [], 0

    # 条数约束
    if max_messages > 0 and len(msgs) > max_messages:
        # 保留最后 max_messages 条
        msgs = msgs[-max_messages:]

    if budget_tokens <= 0:
        return msgs, len(messages) - len(msgs)

    # 预算约束：从最旧的开始整条丢弃，但保底保留 keep_latest 条
    floor = max(0, len(msgs) - keep_latest)
    used = count_message_tokens(msgs)
    drop_from = 0
    while used > budget_tokens and drop_from < floor:
        used -= count_tokens(str(msgs[drop_from].get("content", ""))) + 4
        drop_from += 1

    kept = msgs[drop_from:]
    return kept, len(messages) - len(kept)


# --------------------------------------------------------------------------
# 统一预算组装
# --------------------------------------------------------------------------


@dataclass
class BudgetPlan:
    """预算分配方案。"""

    total_budget: int
    system_tokens: int = 0
    history_tokens: int = 0
    context_tokens: int = 0
    reserve_output: int = 512          # 为模型输出预留
    history_ratio: float = 0.25        # 历史最多占可用预算的比例
    system_ratio: float = 0.30         # 系统提示词最多占可用预算的比例

    @property
    def available(self) -> int:
        return max(0, self.total_budget - self.reserve_output)

    @property
    def max_history(self) -> int:
        return int(self.available * self.history_ratio)

    @property
    def max_system(self) -> int:
        return int(self.available * self.system_ratio)

    @property
    def max_context(self) -> int:
        return max(0, self.available - self.max_history - self.max_system)


def plan_budget(
    total_budget: int = 4096,
    reserve_output: int = 512,
    history_ratio: float = 0.25,
    system_ratio: float = 0.30,
) -> BudgetPlan:
    """按总预算分配给「历史 / 系统 / 检索片段」三部分。

    预算是**软上限**：系统提示词是固定文案不裁剪（宁可超一点也不能把
    角色设定裁掉），真正被裁的是历史消息与检索片段。
    """
    return BudgetPlan(
        total_budget=total_budget,
        reserve_output=reserve_output,
        history_ratio=history_ratio,
        system_ratio=system_ratio,
    )


def assemble(
    question: str,
    retrieved: list[dict],
    history: list[dict],
    system_template: str = "",
    budget: BudgetPlan | None = None,
    max_chunk_chars: int = 600,
    max_history_messages: int = 20,
) -> tuple[dict[str, Any], ContextStats]:
    """组装一次请求的完整上下文，返回可直接发给模型的消息列表 + 统计。

    参数
    ----
    question         当前用户问题
    retrieved        检索片段（相关度降序）
    history          历史消息
    system_template  系统提示词模板（含 %s 占位符，留空则不注入片段）
    budget           预算方案，None 时用默认 4096

    返回
    ----
    ({system, messages, context}, 统计)
    """
    plan = budget or plan_budget()
    stats = ContextStats(budget=plan.total_budget)

    # 1) 检索片段按 context 预算压缩
    ctx_budget = plan.max_context
    kept_chunks, ctx_stats = compress_context(
        retrieved, budget_tokens=ctx_budget, max_chunk_chars=max_chunk_chars)
    stats.original_tokens = ctx_stats.original_tokens
    stats.dropped_chunks = ctx_stats.dropped_chunks

    # 2) 历史消息按 history 预算裁剪
    kept_hist, dropped_hist = build_history(
        history, max_messages=max_history_messages, budget_tokens=plan.max_history)
    stats.dropped_history = dropped_hist

    # 3) 组装
    context_text = "\n\n---\n\n".join(d["content"] for d in kept_chunks)
    system = system_template % context_text if (system_template and "%s" in system_template) else (system_template or "")
    messages = [{"role": m["role"], "content": m["content"]} for m in kept_hist]
    messages.append({"role": "user", "content": question})

    stats.system_tokens = count_tokens(system)
    stats.history_tokens = count_message_tokens(kept_hist)
    stats.context_tokens = count_tokens(context_text)
    stats.kept_chunks = len(kept_chunks)
    stats.final_tokens = stats.system_tokens + stats.history_tokens + stats.context_tokens + count_tokens(question)

    stats.detail = {
        "maxContext": ctx_budget,
        "maxHistory": plan.max_history,
        "maxSystem": plan.max_system,
        "available": plan.available,
        "reserveOutput": plan.reserve_output,
    }

    return {
        "system": system,
        "messages": messages,
        "context": context_text,
        "chunks": kept_chunks,
    }, stats
