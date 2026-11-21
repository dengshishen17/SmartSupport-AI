"""LangGraph ReAct Agent：检索工具 + 3 个业务工具 + 1 个保修测算工具，统一交由模型规划调用。
与固定管线（先检索再生成）不同，这里模型自主决定调哪些工具、调几次，
对应 JD 里的 Agent 架构 / 任务规划 / 工具调用 / 执行链路。

可靠性
------
工具执行经由 app.tool_runtime.ToolExecutor 包装，提供：
- 超时控制（asyncio.wait_for）：单次调用超时按降级话术返回，不拖垮请求
- 指数退避重试：瞬时失败自动重试
- 熔断降级（CircuitBreaker）：连续失败达阈值后快速失败，故障期不放大压力
- 并发限流（asyncio.Semaphore）：限制同时执行的工具数
工具失败时返回可读的中文降级话术而非抛异常，让模型能看到失败信息并自行决定转人工。
"""
from contextlib import contextmanager
from contextvars import ContextVar

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from . import config, context, memory, retrieval, tool_runtime, tools, trace, vectorstore

_llm = ChatOpenAI(api_key=config.DEEPSEEK_API_KEY or "dummy",
                  base_url=config.DEEPSEEK_BASE_URL,
                  model=config.DEEPSEEK_MODEL, temperature=0.7)


@tool("searchPolicyKnowledge",
      description="检索售后政策知识库（退款/退货/物流/保修规则）。政策类问题先调本工具查条文，再依据条文回答；不要编造条款。")
def search_policy_tool(query: str) -> str:
    tr = _current_trace.get()
    with (tr.span("retrieval", "retrieval") if tr is not None else _null_span()) as sp:
        try:
            docs = retrieval.retrieve(query, top_k=config.RAG_TOP_K, threshold=config.RAG_THRESHOLD)
        except Exception as e:
            if sp is not None:
                sp.fail(e)
            return f"知识库暂时不可用（{e}）。"
        if sp is not None:
            sp.set("query", query[:120])
            sp.set("count", len(docs))
            sp.set("sections", [d.get("section") for d in docs[:5]])

    if not docs:
        return "知识库中没有检索到相关条文，请如实说明无法确认、建议转人工，不要编造。"
    # ---- 上下文预算：检索片段按 Token 预算整段裁剪，避免超预算 ----
    plan = context.plan_budget(
        total_budget=config.CONTEXT_TOKEN_BUDGET,
        reserve_output=config.CONTEXT_RESERVE_OUTPUT,
        history_ratio=config.CONTEXT_HISTORY_RATIO,
        system_ratio=config.CONTEXT_SYSTEM_RATIO,
    )
    kept, stats = context.compress_context(
        docs,
        budget_tokens=plan.max_context,
        max_chunk_chars=config.CONTEXT_MAX_CHUNK_CHARS,
    )
    if tr is not None:
        tr.record("context_compress", "context",
                  originalTokens=stats.original_tokens,
                  finalTokens=stats.final_tokens,
                  droppedChunks=stats.dropped_chunks,
                  keptChunks=stats.kept_chunks)
    if not kept:
        return "知识库中没有检索到相关条文，请如实说明无法确认、建议转人工，不要编造。"
    parts = []
    for i, d in enumerate(kept):
        sec = vectorstore.section_of(d["content"]) or f"片段{i+1}"
        parts.append(f"【{sec}】(score={d['score']:.3f})\n{d['content']}")
    return "\n\n---\n\n".join(parts)


_REACT_TOOLS = [search_policy_tool, tools.query_order_tool, tools.query_refund_tool,
                tools.query_ticket_tool, tools.query_warranty_tool]

# 工具名 -> 底层执行函数（纯函数，不含可靠性逻辑）
_TOOL_FNS = {
    "searchPolicyKnowledge": lambda args: search_policy_tool.invoke(args),
    "queryOrderByOrderNo": lambda args: tools.query_order_text(args.get("orderNo", "")),
    "queryRefundByOrderNo": lambda args: tools.query_refund_text(args.get("orderNo", "")),
    "queryTicketByOrderNo": lambda args: tools.query_ticket_text(args.get("orderNo", "")),
    "queryWarrantyByOrderNo": lambda args: tools.query_warranty_text(args.get("orderNo", "")),
}

# 工具名 -> 最近一次执行记录（耗时、是否降级），供轨迹采集使用
_LAST_CALL: dict[str, dict] = {}

# 当前请求的 Trace（线程/协程内共享）。
# FastAPI 的同步端点跑在 threadpool、异步端点跑在 event loop，
# 用 ContextVar 隔离不同请求的 trace 上下文，避免并发串写。
_current_trace: ContextVar[trace.Trace | None] = ContextVar("current_trace", default=None)

_system = ("你是企业售后客服。政策类问题先调用 searchPolicyKnowledge 查条文，只依据条文回答；"
           "涉及具体订单号时调用订单/退款/工单/保修工具查真实数据；知识中没有就明说无法确认、建议转人工，"
           "不要编造。使用纯文本中文回答，250 字以内。")

# --------------------------------------------------------------------------
# 可靠性包装
#
# LangGraph 的 ToolNode 会直接调用 tool.invoke()，绕过我们在外面加的任何装饰，
# 因此可靠性必须包在「工具自身」上。
#
# 两种包装方式：
# 1. wrap_tool_call：LangChain 1.x 的官方机制，在工具执行前后拦截
# 2. 自建 ToolNode：完全自控
#
# 这里用第 1 种 —— 改动小、与 LangGraph 版本解耦、不影响 create_react_agent 的内部图结构。
# 包装器负责：超时控制、指数退避重试、熔断降级、并发限流、耗时记录。
# --------------------------------------------------------------------------
_call_seq = 0


async def _guarded_wrapper(request, execute):
    """awrap_tool_call 包装器：把工具执行纳入可靠性层。

    签名（LangGraph ToolNode 约定）：
        async def wrapper(request: ToolCallRequest, execute) -> ToolMessage | Command

    request 提供 tool_call（含 name/args/id）、tool、state、runtime。
    execute 是原始执行入口，可调用多次以实现重试。

    这里不直接调 execute，而是绕过它改用可靠性层，
    以便统一施加超时、重试、熔断与并发限流。
    """
    global _call_seq
    _call_seq += 1
    seq = _call_seq

    tool_call = getattr(request, "tool_call", None) or {}
    tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else ""
    call_id = tool_call.get("id", "") if isinstance(tool_call, dict) else ""
    args = tool_call.get("args", {}) or {} if isinstance(tool_call, dict) else {}

    fn = _TOOL_FNS.get(tool_name)
    if fn is None:
        # 未知工具：交给 LangGraph 原生处理（它会给出未注册工具的错误）
        return await execute(request)

    tr = _current_trace.get()
    span_cm = tr.span("tool", "tool") if tr is not None else _null_span()
    with span_cm as sp:
        if sp is not None:
            sp.set("toolName", tool_name)
            sp.set("args", args)
        result = await _executor.execute(tool_name, args, lambda a: fn(a))
        if sp is not None:
            sp.set("durationMs", result.duration_ms)
            sp.set("ok", result.ok)
            sp.set("degraded", result.degraded)
            sp.set("attempts", result.attempts)
            if result.error:
                sp.set("error", result.error)

    _LAST_CALL[call_id or str(seq)] = {
        "durationMs": result.duration_ms,
        "ok": result.ok,
        "degraded": result.degraded,
        "attempts": result.attempts,
        "error": result.error,
    }

    from langchain_core.messages import ToolMessage

    return ToolMessage(
        content=result.result,
        tool_call_id=call_id,
        name=tool_name,
        status="error" if not result.ok else "success",
    )


@contextmanager
def _null_span():
    """无 Trace 上下文时的空实现（避免各处 if 判断）。"""
    yield None


# 进程级共享的执行器（熔断状态需要跨请求保持）
_executor = tool_runtime.ToolExecutor(
    timeout=config.TOOL_TIMEOUT,
    retries=config.TOOL_RETRIES,
    backoff=config.TOOL_RETRY_BACKOFF,
    max_concurrency=config.TOOL_MAX_CONCURRENCY,
    breaker=tool_runtime.CircuitBreaker(
        threshold=config.TOOL_BREAKER_THRESHOLD,
        cooldown_seconds=config.TOOL_BREAKER_COOLDOWN,
    ),
)

# 自建 ToolNode 并注入可靠性包装器。
# create_react_agent 接受 ToolNode 实例，此时它不会重建节点，
# 因此我们的 awrap_tool_call 一定生效（LangGraph 内置路径会绕过外部装饰）。
from langgraph.prebuilt.tool_node import ToolNode  # noqa: E402

_tool_node = ToolNode(_REACT_TOOLS, awrap_tool_call=_guarded_wrapper)

_react = create_react_agent(_llm, _tool_node, prompt=_system)


async def run_react(question: str, session_id: str,
                    tr: "trace.Trace | None" = None) -> tuple[str, list[dict], dict]:
    """跑一轮 ReAct。

    返回 (reply, tool_events, usage)
    - tool_events: 逐步工具事件，含 durationMs / ok / degraded / attempts
    - usage: {prompt_tokens, completion_tokens, total_tokens, steps}
    """
    if tr is None:
        tr = trace.Trace("react_chat", session_id=session_id, mode="react")
    token = _current_trace.set(tr)
    try:
        return await _run_react_inner(question, session_id, tr)
    finally:
        _current_trace.reset(token)


async def _run_react_inner(question: str, session_id: str,
                           tr: "trace.Trace") -> tuple[str, list[dict], dict]:
    hist = memory.load(session_id)

    # ---- 上下文预算控制：按 Token 预算裁剪历史消息 ----
    # 检索片段由 searchPolicyKnowledge 工具在 Agent 自主决策时注入，
    # 那里同样走 compress_context（见 search_policy_tool）。
    plan = context.plan_budget(
        total_budget=config.CONTEXT_TOKEN_BUDGET,
        reserve_output=config.CONTEXT_RESERVE_OUTPUT,
        history_ratio=config.CONTEXT_HISTORY_RATIO,
        system_ratio=config.CONTEXT_SYSTEM_RATIO,
    )
    kept_hist, dropped_hist = context.build_history(
        hist,
        max_messages=config.CONTEXT_MAX_HISTORY_MESSAGES,
        budget_tokens=plan.max_history,
    )

    with tr.span("context", "context") as sp:
        messages = [{"role": m["role"], "content": m["content"]} for m in kept_hist]
        messages.append({"role": "user", "content": question})
        sp.set("budget", plan.total_budget)
        sp.set("historyKept", len(kept_hist))
        sp.set("historyDropped", dropped_hist)
        sp.set("historyTokens", context.count_message_tokens(kept_hist))
        sp.set("questionTokens", context.count_tokens(question))
        sp.set("systemTokens", context.count_tokens(_system))

    with tr.span("agent", "agent") as sp:
        result = await _react.ainvoke({"messages": messages})
        sp.set("messageCount", len(result.get("messages", [])))
    out_msgs = result["messages"]

    # ---- Token 用量统计：累加各轮 LLM 调用的 usage_metadata ----
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    llm_rounds = 0
    for m in out_msgs:
        um = getattr(m, "usage_metadata", None)
        if um:
            llm_rounds += 1
            usage["prompt_tokens"] += int(um.get("input_tokens", 0) or 0)
            usage["completion_tokens"] += int(um.get("output_tokens", 0) or 0)
            usage["total_tokens"] += int(um.get("total_tokens", 0) or 0)
    usage["llmRounds"] = llm_rounds

    # ---- 工具事件重建：从消息流还原 start/result，并补上耗时与降级标记 ----
    tool_events: list[dict] = []
    pending: dict[str, dict] = {}
    reply = ""

    for m in out_msgs:
        mtype = getattr(m, "type", "")
        if mtype == "ai":
            for tc in (getattr(m, "tool_calls", None) or []):
                name = tc.get("name", "")
                args = tc.get("args", {}) or {}
                call_id = tc.get("id", "") or ""
                ev = {"stage": "start", "toolName": name, "args": args}
                tool_events.append(ev)
                pending[call_id] = ev
        elif mtype == "tool":
            name = getattr(m, "name", "")
            content = getattr(m, "content", "") or ""
            call_id = getattr(m, "tool_call_id", "") or ""
            ev = pending.pop(call_id, None)
            if ev is not None:
                ev_result = {"stage": "result", "toolName": name, "result": content}
                # 可靠性层记录的执行信息（耗时 / 是否降级 / 重试次数）
                rec = _LAST_CALL.get(call_id)
                if rec:
                    ev_result.update({
                        "durationMs": round(rec.get("durationMs", 0.0), 1),
                        "ok": rec.get("ok", True),
                        "degraded": rec.get("degraded", False),
                        "attempts": rec.get("attempts", 1),
                    })
                    if rec.get("error"):
                        ev_result["error"] = rec["error"]
                # response metadata 里可能带执行耗时（作为兜底）
                meta = getattr(m, "response_metadata", None) or {}
                dur = meta.get("duration") or meta.get("elapsed") or meta.get("execution_time")
                if "durationMs" not in ev_result and isinstance(dur, (int, float)):
                    ev_result["durationMs"] = round(float(dur) * 1000, 1) if dur < 1000 else round(float(dur), 1)
                tool_events.append(ev_result)
        if mtype == "ai" and getattr(m, "content", ""):
            reply = m.content

    # 取最后一条 AI 回复
    for m in reversed(out_msgs):
        if getattr(m, "type", "") == "ai" and getattr(m, "content", ""):
            reply = m.content
            break

    reply = reply or "暂时无法确认，建议转人工客服。"
    memory.save_turn(session_id, question, reply)
    usage["toolCalls"] = sum(1 for e in tool_events if e.get("stage") == "start")

    # ---- 上下文预算统计（供评测与 trace 消费）----
    hist_tokens = context.count_message_tokens(kept_hist)
    usage["context"] = {
        "budget": plan.total_budget,
        "available": plan.available,
        "historyKept": len(kept_hist),
        "historyDropped": dropped_hist,
        "historyTokens": hist_tokens,
        "questionTokens": context.count_tokens(question),
        "promptTokensEstimated": hist_tokens + context.count_tokens(question) + context.count_tokens(_system),
        "maxHistory": plan.max_history,
    }
    return reply, tool_events, usage


async def execute_tool_guarded(name: str, args: dict) -> tool_runtime.ToolCallResult:
    """受保护的单个工具执行入口（超时/重试/熔断/限流）。

    供自建执行路径与测试使用；LangGraph 内置的 ToolNode 路径不经过这里。
    """
    fn = _TOOL_FNS.get(name)
    if fn is None:
        return tool_runtime.ToolCallResult(
            name=name, args=args, result=f"未知工具 {name}", ok=False,
            degraded=True, error="unknown_tool")
    return await _executor.execute(name, args, fn)


def executor_stats() -> dict:
    """工具执行器统计（总调用数、降级率、熔断器状态）。"""
    return _executor.stats
