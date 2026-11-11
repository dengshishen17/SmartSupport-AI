"""Agent 循环：DeepSeek tool_calls → 后端执行工具 → 结果回传 → 二次生成。
与 Java 版 ChatClient + @Tool 链路同语义，支持同步与流式两种。
"""
import json
from openai import OpenAI
from . import config, memory, prompts, tools, vectorstore

_client = OpenAI(api_key=config.DEEPSEEK_API_KEY or "dummy", base_url=config.DEEPSEEK_BASE_URL,
                  timeout=60.0, max_retries=1)


def _messages(system: str, session_id: str, question: str):
    msgs = [{"role": "system", "content": system}]
    for m in memory.load(session_id):
        msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": question})
    return msgs


def chat_once(question: str, session_id: str, top_k: int = 5, threshold: float = 0.0):
    """同步 RAG 问答：检索 → 组 prompt → tool loop → 存记忆。返回 (reply, sources, rag_hit, tool_events)。"""
    try:
        retrieved = vectorstore.similarity_search(question, top_k=top_k, threshold=threshold)
    except Exception:
        retrieved = []  # 向量库不可用时降级为无知识回答，与 Java 版 stream 版一致
    system, rag_hit = prompts.build_system(retrieved)
    sources = [d["metadata"].get("source", "unknown") for d in retrieved]
    msgs = _messages(system, session_id, question)
    tool_events: list[dict] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}

    for _round in range(5):  # 最多 5 轮工具调用，防模型死循环
        resp = _client.chat.completions.create(
            model=config.DEEPSEEK_MODEL, messages=msgs,
            tools=tools.OPENAI_TOOL_SCHEMAS, tool_choice="auto", temperature=0.7)
        u = getattr(resp, "usage", None)
        if u is not None:
            usage["prompt_tokens"] += getattr(u, "prompt_tokens", 0) or 0
            usage["completion_tokens"] += getattr(u, "completion_tokens", 0) or 0
        msg = resp.choices[0].message
        if not msg.tool_calls:
            reply = msg.content or ""
            memory.save_turn(session_id, question, reply)
            return reply, sources, rag_hit, tool_events, usage
        # 有工具调用：拼 assistant tool_calls 消息 → 执行 → 拼 tool 结果 → 下一轮
        msgs.append({"role": "assistant", "content": msg.content,
                     "tool_calls": [t.model_dump() for t in msg.tool_calls]})
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            order_no = str(args.get("orderNo", args.get("order_no", "")))
            tool_events.append({"stage": "start", "toolName": name, "args": args})
            fn = tools.DISPATCH.get(name)
            result = fn(order_no) if fn else f"未知工具 {name}"
            tool_events.append({"stage": "result", "toolName": name, "result": result})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    reply = "查询次数过多，已停止，请提供更明确的订单号后重试。"
    memory.save_turn(session_id, question, reply)
    return reply, sources, rag_hit, tool_events, usage


def chat_stream(question: str, session_id: str, top_k: int = 5, threshold: float = 0.0):
    """流式：先做非流式 tool loop 拿到最终回复意图，再对最终回复做流式生成。
    简化但语义保真：tool 事件先推，content 再逐块推（与 Java 版事件顺序一致）。"""
    try:
        retrieved = vectorstore.similarity_search(question, top_k=top_k, threshold=threshold)
    except Exception:
        retrieved = []
    system, rag_hit = prompts.build_system(retrieved)
    sources = [d["metadata"].get("source", "unknown") for d in retrieved]
    msgs = _messages(system, session_id, question)
    tool_events: list[dict] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}

    for _round in range(5):
        resp = _client.chat.completions.create(
            model=config.DEEPSEEK_MODEL, messages=msgs,
            tools=tools.OPENAI_TOOL_SCHEMAS, tool_choice="auto", temperature=0.7)
        u = getattr(resp, "usage", None)
        if u is not None:
            usage["prompt_tokens"] += getattr(u, "prompt_tokens", 0) or 0
            usage["completion_tokens"] += getattr(u, "completion_tokens", 0) or 0
        msg = resp.choices[0].message
        if not msg.tool_calls:
            break
        msgs.append({"role": "assistant", "content": msg.content,
                     "tool_calls": [t.model_dump() for t in msg.tool_calls]})
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            order_no = str(args.get("orderNo", args.get("order_no", "")))
            tool_events.append({"stage": "start", "toolName": name, "args": args})
            fn = tools.DISPATCH.get(name)
            result = fn(order_no) if fn else f"未知工具 {name}"
            tool_events.append({"stage": "result", "toolName": name, "result": result})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    else:
        msgs.append({"role": "assistant", "content": "请提供更明确的订单号后重试。"})

    # 最终轮流式生成全文
    stream = _client.chat.completions.create(
        model=config.DEEPSEEK_MODEL, messages=msgs, temperature=0.7, stream=True)
    full: list[str] = []

    def gen():
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full.append(delta)
                yield delta
        memory.save_turn(session_id, question, "".join(full))

    return system, rag_hit, sources, tool_events, gen()
