"""FastAPI 入口：与 Java 版 /ai/knowledge/* 对齐，端口 8001。
外加 /py/agent/*（LangGraph ReAct）与 /py/knowledge/* 知识管理（切分/入库预览）。
"""
import json
import uuid
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import agent, config, ingest, metrics, vectorstore, workflow

app = FastAPI(title="SmartSupport Python RAG Service")


def ok(data):
    return {"code": 200, "message": "success", "data": data}


def fail(msg: str):
    return {"code": 500, "message": msg, "data": None}


class ChatReq(BaseModel):
    question: str = ""
    sessionId: str | None = None


@app.get("/health")
def health():
    return ok({"status": "up", "service": "python-rag"})


@app.get("/py/knowledge/search")
def search(query: str, topK: int = 3):
    try:
        docs = vectorstore.similarity_search(query, top_k=topK, threshold=0.0)
        return ok([{"content": d["content"], "score": d["score"], "metadata": d["metadata"]} for d in docs])
    except Exception as e:
        return JSONResponse(status_code=200, content=fail(f"搜索失败：{e}"))


@app.post("/py/knowledge/chat")
def chat(req: ChatReq):
    if not req.question or not req.question.strip():
        return JSONResponse(status_code=200, content=fail("question 不能为空"))
    session_id = req.sessionId or str(uuid.uuid4())
    import time
    t0 = time.time()
    try:
        reply, sources, rag_hit, tool_events, usage = agent.chat_once(
            req.question, session_id, top_k=config.RAG_TOP_K, threshold=config.RAG_THRESHOLD)
        metrics.log_call("rag", session_id, req.question, (time.time() - t0) * 1000,
                         rag_hit, len(tool_events) // 2, True, "",
                         usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                         len(reply or ""))
        return ok({"reply": reply, "sources": sources, "rag": rag_hit, "sessionId": session_id})
    except Exception as e:
        metrics.log_call("rag", session_id, req.question, (time.time() - t0) * 1000,
                         False, 0, False, str(e)[:300])
        return JSONResponse(status_code=200, content=fail(f"知识问答失败：{e}"))


@app.post("/py/knowledge/chat/stream")
async def chat_stream(req: ChatReq):
    if not req.question or not req.question.strip():
        async def err():
            yield {"event": "message", "data": json.dumps({"type": "error", "message": "question 不能为空"}, ensure_ascii=False)}
        return EventSourceResponse(err())
    session_id = req.sessionId or str(uuid.uuid4())

    async def gen():
        try:
            _sys, rag_hit, sources, tool_events, streamer = agent.chat_stream(
                req.question, session_id, top_k=config.RAG_TOP_K, threshold=config.RAG_THRESHOLD)
        except Exception as e:
            yield {"event": "message", "data": json.dumps({"type": "error", "message": f"检索失败：{e}"}, ensure_ascii=False)}
            return
        yield {"event": "message", "data": json.dumps({"type": "reference", "rag": rag_hit, "sources": sources}, ensure_ascii=False)}
        for ev in tool_events:
            yield {"event": "message", "data": json.dumps(
                {"type": "tool", "stage": ev["stage"], "toolName": ev["toolName"],
                 "args": ev.get("args", {}), "result": ev.get("result", "")}, ensure_ascii=False)}
        try:
            for chunk in streamer:
                if chunk:
                    yield {"event": "message", "data": json.dumps({"type": "content", "content": chunk}, ensure_ascii=False)}
        except Exception as e:
            yield {"event": "message", "data": json.dumps({"type": "error", "code": "LLM_ERROR", "message": str(e)}, ensure_ascii=False)}
            return
        yield {"event": "message", "data": json.dumps({"type": "done", "sessionId": session_id}, ensure_ascii=False)}

    return EventSourceResponse(gen(), headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache, no-transform"})


class ImportTextReq(BaseModel):
    source: str = ""
    content: str = ""
    replace: bool = True


@app.post("/py/agent/chat")
async def agent_chat(req: ChatReq):
    """LangGraph ReAct Agent 问答：模型自主规划调用检索/订单/退款/工单/保修工具。"""
    if not req.question or not req.question.strip():
        return JSONResponse(status_code=200, content=fail("question 不能为空"))
    session_id = req.sessionId or str(uuid.uuid4())
    import time
    t0 = time.time()
    try:
        reply, tool_events = await workflow.run_react(req.question, session_id)
        metrics.log_call("react", session_id, req.question, (time.time() - t0) * 1000,
                         True, len(tool_events) // 2, True, "", 0, 0, len(reply or ""))
        return ok({"reply": reply, "toolEvents": tool_events, "sessionId": session_id, "mode": "react"})
    except Exception as e:
        metrics.log_call("react", session_id, req.question, (time.time() - t0) * 1000,
                         False, 0, False, str(e)[:300])
        return JSONResponse(status_code=200, content=fail(f"Agent 问答失败：{e}"))


@app.post("/py/agent/chat/stream")
async def agent_chat_stream(req: ChatReq):
    if not req.question or not req.question.strip():
        async def err():
            yield {"event": "message", "data": json.dumps({"type": "error", "message": "question 不能为空"}, ensure_ascii=False)}
        return EventSourceResponse(err())
    session_id = req.sessionId or str(uuid.uuid4())

    async def gen():
        try:
            reply, tool_events = await workflow.run_react(req.question, session_id)
        except Exception as e:
            yield {"event": "message", "data": json.dumps({"type": "error", "message": f"Agent 失败：{e}"}, ensure_ascii=False)}
            return
        for ev in tool_events:
            yield {"event": "message", "data": json.dumps(
                {"type": "tool", "stage": ev["stage"], "toolName": ev["toolName"],
                 "args": ev.get("args", {}), "result": ev.get("result", "")}, ensure_ascii=False)}
        # ReAct 结果整体一次性是文本：按 20 字切片模拟流式，保持前端同一渲染链路
        for i in range(0, len(reply), 20):
            yield {"event": "message", "data": json.dumps({"type": "content", "content": reply[i:i+20]}, ensure_ascii=False)}
        yield {"event": "message", "data": json.dumps({"type": "done", "sessionId": session_id}, ensure_ascii=False)}

    return EventSourceResponse(gen(), headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache, no-transform"})


@app.post("/py/knowledge/preview-split")
def preview_split(req: ImportTextReq):
    """只切分不入库：调 chunk 512/overlap 50 的效果预览。"""
    if not req.content or not req.content.strip():
        return JSONResponse(status_code=200, content=fail("content 不能为空"))
    try:
        return ok({"chunks": ingest.chunk_preview(req.content, req.source or "preview"),
                   "chunkSize": 512, "chunkOverlap": 50})
    except Exception as e:
        return JSONResponse(status_code=200, content=fail(f"切分失败：{e}"))


@app.post("/py/knowledge/import-text")
def import_text(req: ImportTextReq):
    """文本入库：切分(512/50) → 百炼 embedding → pgvector，replace=True 时先清同 source 旧数据。"""
    if not req.content or not req.content.strip():
        return JSONResponse(status_code=200, content=fail("content 不能为空"))
    source = req.source or "upload.txt"
    try:
        removed = ingest.delete_by_source(source) if req.replace else 0
        chunks = ingest.split_markdown(req.content, source)
        stored = ingest.store_chunks(chunks)
        return ok({"source": source, "removed": removed, "imported": stored})
    except Exception as e:
        return JSONResponse(status_code=200, content=fail(f"导入失败：{e}"))


@app.post("/py/knowledge/upload")
async def upload_knowledge(file: UploadFile = File(...), replace: bool = True):
    name = file.filename or "upload.md"
    lower = name.lower()
    if not (lower.endswith(".md") or lower.endswith(".txt")):
        return JSONResponse(status_code=200, content=fail("仅支持 .md / .txt"))
    try:
        raw = await file.read()
        content = raw.decode("utf-8", errors="ignore")
        removed = ingest.delete_by_source(name) if replace else 0
        chunks = ingest.split_markdown(content, name)
        if not chunks:
            return JSONResponse(status_code=200, content=fail("未切出任何段落（至少需要一个 ## 章节）"))
        stored = ingest.store_chunks(chunks)
        return ok({"fileName": name, "removed": removed, "imported": stored})
    except Exception as e:
        return JSONResponse(status_code=200, content=fail(f"上传导入失败：{e}"))


@app.get("/py/ops/stats")
def ops_stats():
    """可观测性：调用量/成功率/延迟分位/Token/工具/RAG命中。数据来自 ops.db。"""
    try:
        return ok(metrics.stats())
    except Exception as e:
        return JSONResponse(status_code=200, content=fail(f"统计失败：{e}"))


@app.get("/py/ops/recent")
def ops_recent(limit: int = 20):
    try:
        return ok({"logs": metrics.recent(max(1, min(limit, 100)))})
    except Exception as e:
        return JSONResponse(status_code=200, content=fail(f"查询失败：{e}"))
