# SmartSupport Python Service（FastAPI + LangChain + LangGraph + MCP）

与 Java 版 `backend` 共用同一批中间件与 Key：MySQL / Redis / PostgreSQL+pgvector / DeepSeek / 百炼 embedding。
端口 **8001**。

## 两条问答链路

| 链路 | 接口 | 说明 |
|---|---|---|
| 固定 RAG 管线（与 Java 版同语义） | `POST /py/knowledge/chat` / `/py/knowledge/chat/stream` | 先检索(topK=5)再生成；tool_calls→执行→回传→二次生成；两套 system prompt |
| LangGraph ReAct Agent | `POST /py/agent/chat` / `/py/agent/chat/stream` | 模型自主规划：检索工具 + 订单/退款/工单/保修 4 工具，按需调用多轮 |

请求体：`{"question": "...", "sessionId": "可选，续聊时传上次返回的"}`

## 知识库管理（切分 512/overlap 50）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/py/knowledge/search?query=&topK=3` | 向量检索测试 |
| POST | `/py/knowledge/preview-split` | 只切分不入库，预览 chunk 效果 |
| POST | `/py/knowledge/import-text` | 文本切分→embedding→pgvector 入库（replace 清同 source 旧数据） |
| POST | `/py/knowledge/upload` | 上传 .md/.txt 并入库（multipart，字段名 file） |

写入格式与 Java 版 `PgVectorStore` 一致：`id=uuid_generate_v4()`，metadata 含 `source/section/chunk_index`。

## 工具清单（LangChain + MCP 共用）

`queryOrderByOrderNo` / `queryRefundByOrderNo` / `queryTicketByOrderNo` / `queryWarrantyByOrderNo`（保修测算：按§4.1 保修期表推算在保/过保）。
返回裁掉 `userId`；生产应从登录态校验，绝不让模型传 userId。

## 运行

```powershell
pip install -r requirements.txt

$env:DEEPSEEK_API_KEY="sk-..."   # 或 DEEPSEEK-KEY
$env:ALIYUN_API_KEY="sk-..."     # 或 ALIYUN-KEY
$env:MYSQL_PASSWORD="..."
$env:PG_PASSWORD="..."

cd D:\SmartSupport AI 企业智能售后助手\python-service
python -m uvicorn app.main:app --port 8001
```

## 评测

```powershell
cd D:\SmartSupport AI 企业智能售后助手\python-service
python -m eval.eval_rag          # 检索评测：Hit@1/3/5+MRR+延迟，只读 vector_store
python -m eval.eval_answer --mode=rag    # 端到端生成评估：LLM-as-Judge（忠实度/拒答率/工具选型）
python -m eval.eval_answer --mode=react  # 同上，测 ReAct 链路
```

- 检索：与 Java 版 `RagEvalService` 同一口径，ground truth=章节标题。
  已验证：生产参数 topK=5 下 Hit@1=89.7%、Hit@3=100%、MRR=0.9483（`eval/eval-py-result.json`）。
- 生成：30 条用例（政策10+工具12+越界4+口语4），裁判打 faithful / refused / tool_correct，
  输出引用忠实度、越界拒答率、工具选型准确率（`eval/eval-answer-result.json`）。

## 可观测性（ops.db 落库）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/py/ops/stats` | 调用量/成功率/延迟p50/p95/Token均值与总量/工具均值/RAG命中率/分链路统计/Top错误 |
| GET | `/py/ops/recent?limit=20` | 最近调用明细（含问题、延迟、Token、工具数） |

每次 `/py/knowledge/chat` 与 `/py/agent/chat` 自动记录：延迟、RAG命中、工具数、成功失败、
prompt/completion Token（ReAct 链路暂记 0）、回复长度。失败只记不抛，不影响主流程。

## MCP

```powershell
python -m app.mcp_server   # stdio 模式，暴露 4 个查询工具
```

Dify / Claude Desktop 以 stdio 方式接入即可。
