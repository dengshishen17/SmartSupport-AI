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

配置统一放在**仓库根目录的 `.env`**（`app/config.py` 会自动加载，无需手动 export；
真实环境变量优先级更高，可覆盖 `.env`）。`.env` 已被 `.gitignore` 排除，不会提交。

```env
# D:\SmartSupport AI 企业智能售后助手\.env
DEEPSEEK_API_KEY=sk-...
ALIYUN_API_KEY=sk-...
MYSQL_PASSWORD=...
PG_PASSWORD=...
```

```powershell
pip install -r requirements.txt

cd D:\SmartSupport AI 企业智能售后助手\python-service
python -m uvicorn app.main:app --port 8001
```

依赖服务（Docker Desktop 装在 `D:\Docker`，不在默认 PATH）：

```powershell
Start-Process "D:\Docker\Docker Desktop.exe"
cd D:\SmartSupport AI 企业智能售后助手\backend
docker compose up -d      # smart-pgvector(5432) + smart-redis(6379)
```

MySQL 用本机 Windows 服务 `MySQL80`（3306），无需容器。

## 检索层（app/retrieval/）

检索被拆成可插拔的三段：**召回 → 融合 → 重排**，调用方统一走 `app.retrieval.retrieve()`，
策略由 `config.RETRIEVAL_MODE` 切换（feature flag，默认 `dense`，不改变既有行为）。

| 模块 | 职责 |
|---|---|
| `base.py` | 统一文档结构 `Document`、召回器/重排器协议 |
| `dense.py` | 向量召回（pgvector 余弦，包装原 `vectorstore.similarity_search`） |
| `bm25.py` | BM25 稀疏召回，**纯 Python 实现**（无 numpy / rank_bm25 依赖），分词优先 jieba、缺失时退化为中文 bigram |
| `hybrid.py` | 多路融合：RRF（Reciprocal Rank Fusion）与加权归一化两种策略 |
| `rerank.py` | 规则式重排，融合向量相似度 / 查询词覆盖率 / 章节匹配度三个信号 |
| `pipeline.py` | 统一入口 `retrieve()` + 策略工厂 |

### 检索策略实测对比（29 条可答 + 4 条越界，topK=5，确定性、无 LLM 参与）

| 模式 | Hit@1 | Hit@3 | Hit@5 | MRR | 平均延迟 | 越界样本 top score |
|---|---|---|---|---|---|---|
| dense（默认，生产） | **89.7%** | 100% | 100% | **0.9483** | 245ms | 0.4408 |
| bm25 | 75.9% | 89.7% | 89.7% | 0.8161 | **24ms** | 0.2263 |
| hybrid（RRF） | **89.7%** | 100% | 100% | **0.9483** | 330ms | 0.0164 |
| rerank（规则式） | 79.3% | 100% | 100% | 0.8966 | 249ms | 0.8956 |

结论：
- **当前 dense 已达 Hit@3=100% 天花板**，混合检索无提升空间，且延迟 +85ms，属于负收益
- BM25 单独使用在 6 chunk 小语料上明显更弱（Hit@1 -13.8pt），词面匹配会丢失语义
  （例：「七天无理由退货」被召回「五、售后工单问题类型汇总」，因该 chunk 含「退货」二字）
- **规则式重排在本场景是负优化**（Hit@1 89.7% → 79.3%），关键词覆盖信号压过了语义信号
- **融合后的 score 是排名倒数和，不能当相似度用**：hybrid 的越界样本 top score 为 0.0164，
  阈值判断必须用 `Document.dense_score`（`pipeline.retrieve()` 已按此过滤）

### 切换方式

```powershell
$env:RETRIEVAL_MODE="hybrid"   # dense(默认) | bm25 | hybrid | rerank
```

## 评测

```powershell
cd D:\SmartSupport AI 企业智能售后助手\python-service
python -m eval.eval_rag          # 检索评测：Hit@1/3/5+MRR+延迟，只读 vector_store
python -m eval.eval_retrieval     # 检索策略横向对比：dense/bm25/hybrid/rerank（无 LLM，零消耗）
python -m eval.eval_answer --mode=rag    # 端到端生成评估：LLM-as-Judge（忠实度/拒答率/工具选型）
python -m eval.eval_answer --mode=react  # 同上，测 ReAct 链路
python -m eval.eval_stability --rounds 3 --mode rag    # 同配置跑 N 轮，统计指标波动（中位数）
python -m eval.eval_agent --mode react   # Agent 轨迹级评测：pass@1/步数分布/无效调用率/失败归因
python -m eval.test_eval_agent            # 轨迹解析与失败分类的离线单测（15/15，零 API 消耗）
```

> **完整基线见 [`eval/baseline-report.md`](eval/baseline-report.md)** —— 后续所有改造的对照基准。
> **轨迹评测报告见 [`eval/eval-agent-report.md`](eval/eval-agent-report.md)**。

### Agent 轨迹级评测（P0-3）

`eval_answer.py` 只看结果，`eval_agent.py` 看**过程**：走了几步、调了哪些工具、
有没有无效调用、在哪一步失败、失败属于哪一类。

| 指标 | react 实测（30 条） |
|---|---|
| pass@1 / pass@3 | 80.0% / 83.3% |
| 平均步数 | 0.9（0 步 4 条、1 步 25 条、2 步 1 条） |
| 工具调用总数 | 27 |
| **无效调用率** | **0.0%** |
| **浪费调用率** | **0.0%** |
| 失败归类 | HALLUCINATION 5、RETRIEVAL_EMPTY 3，其余 7 类均为 0 |

失败归因 taxonomy 共 9 类：`RETRIEVAL_EMPTY` / `TOOL_ERROR` / `INVALID_ARGS` /
`DUPLICATE_CALL` / `LOOP` / `MAX_STEP` / `HALLUCINATION` / `REFUSAL_OVER` / `REFUSAL_UNDER`。

按类别看：业务工具类忠实度 100%、越界类 100% 且无数据泄漏（`REFUSAL_UNDER`=0）；
**政策类 70% / 口语化类 50% 是短板**，根因是知识库仅 6 个 chunk，召回覆盖不足。

- 检索：与 Java 版 `RagEvalService` 同一口径，ground truth=章节标题。
  已验证：生产参数 topK=5 下 Hit@1=89.7%、Hit@3=100%、MRR=0.9483（`eval/eval-py-result.json`）。
- 生成：30 条用例（政策10+工具12+越界4+口语4），裁判打 faithful / refused / tool_correct，
  输出引用忠实度、越界拒答率、工具选型准确率。
- 结果落盘按 mode 分文件，避免相互覆盖：
  `eval/eval-answer-result.json`（rag，生产基线）、`eval/eval-answer-result-react.json`（react）。

### 双链路实测结果（2026-11-20，各跑 3 轮取中位）

| 模式 | 成功率 | 引用忠实度 | 工具选型准确率 | 越界拒答率 | 平均延迟 |
|---|---|---|---|---|---|
| rag（固定管线） | 30/30 | 90.0% | 100% | 100% | 2206ms |
| react（LangGraph 自主规划） | 30/30 | 83.3% | 100% | 100% | 2148ms |

要点：
- react 链路调 `searchPolicyKnowledge` 属正常行为，工具选型规则按链路语义区分
  （policy/colloquial 允许检索工具、禁止业务数据工具；out_of_scope 同样禁止业务数据工具）。
- 忠实度存在裁判随机波动：rag 波动 3.3pt、react 波动 6.7pt，
  做版本对比时需同配置跑 3 次取中位数 → `python -m eval.eval_stability --rounds 3 --mode rag`。
- react 的越界拒答率波动 25pt，根因是越界用例只有 4 条（错 1 条即掉 25%），粒度太粗。
- 检索评测的 Hit@3=100% / MRR=0.9483 是确定性指标（纯向量 + 阈值，无 LLM 参与），可稳定复现。

### 错误处理

评测脚本对错误做了两级区分：

- **致命错误**（余额不足 / Key 失效 / 限流）：立即中止整轮并标注 `aborted=true`，
  不会把环境问题伪装成模型能力问题，也避免白白消耗剩余请求。
- **瞬时错误**（网络抖动等）：退避重试 2 次。

`summary` 中的 `executed` / `aborted` 字段用于判断一轮结果是否完整，
只有 `aborted=false` 且 `executed=total` 的结果才可用于基线对比。

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
