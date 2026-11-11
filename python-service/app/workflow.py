"""LangGraph ReAct Agent：检索工具 + 3 个业务工具 + 1 个保修测算工具，统一交由模型规划调用。
与固定管线（先检索再生成）不同，这里模型自主决定调哪些工具、调几次，
对应 JD 里的 Agent 架构 / 任务规划 / 工具调用 / 执行链路。
"""
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from . import config, memory, tools, vectorstore

_llm = ChatOpenAI(api_key=config.DEEPSEEK_API_KEY or "dummy",
                  base_url=config.DEEPSEEK_BASE_URL,
                  model=config.DEEPSEEK_MODEL, temperature=0.7)


@tool("searchPolicyKnowledge",
      description="检索售后政策知识库（退款/退货/物流/保修规则）。政策类问题先调本工具查条文，再依据条文回答；不要编造条款。")
def search_policy_tool(query: str) -> str:
    try:
        docs = vectorstore.similarity_search(query, top_k=config.RAG_TOP_K, threshold=config.RAG_THRESHOLD)
    except Exception as e:
        return f"知识库暂时不可用（{e}）。"
    if not docs:
        return "知识库中没有检索到相关条文，请如实说明无法确认、建议转人工，不要编造。"
    parts = []
    for i, d in enumerate(docs):
        sec = vectorstore.section_of(d["content"]) or f"片段{i+1}"
        parts.append(f"【{sec}】(score={d['score']:.3f})\n{d['content'][:600]}")
    return "\n\n---\n\n".join(parts)


_REACT_TOOLS = [search_policy_tool, tools.query_order_tool, tools.query_refund_tool,
                tools.query_ticket_tool, tools.query_warranty_tool]

_system = ("你是企业售后客服。政策类问题先调用 searchPolicyKnowledge 查条文，只依据条文回答；"
           "涉及具体订单号时调用订单/退款/工单/保修工具查真实数据；知识中没有就明说无法确认、建议转人工，"
           "不要编造。使用纯文本中文回答，250 字以内。")

_react = create_react_agent(_llm, _REACT_TOOLS, prompt=_system)


async def run_react(question: str, session_id: str) -> tuple[str, list[dict]]:
    """跑一轮 ReAct，返回 (reply, tool_events)。记忆沿用同一 Redis key 口径。"""
    hist = memory.load(session_id)
    messages = [{"role": m["role"], "content": m["content"]} for m in hist]
    messages.append({"role": "user", "content": question})
    result = await _react.ainvoke({"messages": messages})
    out_msgs = result["messages"]
    tool_events: list[dict] = []
    reply = ""
    for m in out_msgs:
        if getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                tool_events.append({"stage": "start", "toolName": tc.get("name", ""),
                                    "args": tc.get("args", {})})
        t = getattr(m, "type", "")
        if t == "tool":
            tool_events.append({"stage": "result", "toolName": getattr(m, "name", ""),
                                "result": getattr(m, "content", "")})
        if getattr(m, "type", "") == "ai" and getattr(m, "content", ""):
            reply = m.content
    # 取最后一条 AI 回复
    for m in reversed(out_msgs):
        if getattr(m, "type", "") == "ai" and getattr(m, "content", ""):
            reply = m.content
            break
    memory.save_turn(session_id, question, reply or "")
    return reply or "暂时无法确认，建议转人工客服。", tool_events
