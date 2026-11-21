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

> **知识库构成**：现共 24 个 chunk，来自两份文档：
> - 《售后政策演示数据.md》—— 6 个 chunk（§1~§6：退款/退货/物流/保修/工单类型/快速参考表）
> - 《售后政策扩展数据.md》—— 18 个 chunk（§7~§15：换货/开票/优惠券/价保/FAQ/服务时效/客服规范/配送/误区澄清）
>
> 扩展文档刻意包含「退货 vs 换货」「保修 vs 价保」「退款 vs 优惠券」等
> 词面高度相似但语义不同的干扰章节，用于检验检索策略在近义干扰下的表现。
>
> > **注意**：`embeddings.embed_batch` 已按百炼 API 单批 ≤10 条自动分批
> > （`text-embedding-v4` 限制，语料少时不触发，扩充后必然触发）。

## 上下文工程与 Token 预算（app/context.py）

模型上下文是有限预算，RAG 场景下"检索回来的片段 + 多轮历史 + 系统提示"三者会互相挤占。
`app/context.py` 把这件事做成了**可分配、可观测**的预算器：

| 能力 | 说明 |
|---|---|
| `count_tokens(text)` | CJK / 拉丁混排启发式计数，不依赖 `tiktoken`（避免额外依赖与网络） |
| `compress_context(retrieved, budget_tokens)` | **按句**截断过长片段；预算不足时**整段丢弃**低相关度尾部片段，而不是从中间切断语义 |
| `build_history(messages, max_messages, budget_tokens)` | 保留最近若干轮，超预算时从最旧的历史往回收，且强制保留最后一轮 |
| `assemble(...)` | 统一入口：系统提示 / 历史 / 检索片段三段预算分配，返回组装结果 + `ContextStats` |

`ContextStats` 记录每段实际占用、压缩节省比例、丢弃片段数，可直接进 Trace 观测。

**接入点**：`workflow.py` 的 `run_react`（LangGraph ReAct）与 `agent.py` 的 `chat_once`（固定 RAG 管线）。
这解决了一个真实问题：超长历史 + 大量召回片段会让请求直接撞上模型上下文上限而报错。

## Prompt 版本管理与回归比对（app/prompts.py）

Prompt 是代码，却极易被"顺手改一句"破坏。`app/prompts.py` 把 Prompt 当**带版本的代码资产**管：

| 能力 | 说明 |
|---|---|
| `PromptRegistry` | 不可变注册表，按 `(name, version)` 命名空间存放，自动计算 SHA256 哈希 |
| `registry.diff(name, v1, v2)` | 输出统一 diff 文本 + 增删行数，用于 code review 式评审 Prompt 改动 |
| `ACTIVE_RAG_VERSION` | 当前生效版本；`v2` 已被回归比对验证并提升为默认 |

`eval/eval_prompt_regression.py` 做 A/B 回归：**多轮交错执行**（候选/基线轮换，避免后端状态漂移与 API 延迟偏差），
对 `faithfulRate` / `toolRuleRate` / `refusedRate` / `successRate` / `avgLatencyMs` 取中位数，
用**跨轮标准差**估计噪声带，超过噪声带才判定为 `IMPROVED` / `REGRESSED`。

> 实测：`rag_system:v1` vs `v2`，84 条用例 × 2 轮 —— 忠实度 97.0% → 97.6%（无退化），
> 拒答率 +1.78pt（> 0.84pt 噪声带）判定 `IMPROVED`，故 `v2` 提升为默认。

## 全链路 Trace 追踪（app/trace.py）

`ops.db` 原先只有"每次请求一行"的粗粒度日志，无法回答"到底是检索慢还是模型慢"。
`app/trace.py` 提供 **span 级别**追踪：

| 能力 | 说明 |
|---|---|
| `Trace` 上下文管理器 | 支持嵌套 `with tr.span("retrieval"):`，通过活跃执行栈自动串联父子关系 |
| `root_span()` | 开一个**根 span**（`rag_chat` / `react_chat`），本次请求内所有 span 挂在它下面 —— 这样才能算出「本次请求总共花了多久」，也便于 UI 按树形展开 |
| 落库 | SQLite `ops.db` → `trace_spans` 表，按 `trace_id` / `name` / `ts` 建索引 |
| span 类型 | `retrieval` / `context` / `tool` / `agent` / `llm`，各带耗时、状态与 JSON 属性 |
| 查询 | `get_trace(trace_id)` / `recent_traces(limit)` / `slow_spans(threshold_ms)` / `stats()` |

**接入点**：`agent.py`（`retrieval`→`context`→`tool`→`llm`）、`workflow.py`（`context`→`tool`→`agent`）、
`main.py`（生成 `traceId` 并回传，外层套 `tr.root_span("agent")`）。单条请求的完整调用链可以一次性拉出来看：

```text
react_chat  2148.6ms                          ← 根 span：本次请求总耗时
├─ context      0.1ms  budget=4096, historyKept=0
└─ agent     2124.6ms  messageCount=5        ← LangGraph ReAct 编排
   ├─ tool      36.5ms  queryOrderByOrderNo   ← 工具子 span
   └─ tool      23.4ms  queryRefundByOrderNo
```

> 🧪 **测试隔离**：`DB_PATH` 支持用环境变量 `SMART_OPS_DB` 覆盖，单测指向临时库，
> 避免单测写的假 span 污染生产观测数据（实测踩过：trace 列表全是 `name="a"` 的单测数据）。

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

## 工具执行可靠性（app/tool_runtime.py）

Agent 调工具时，工具可能卡住不返回、偶发失败、持续宕机。没有保护层，一次工具故障会拖垮整个请求。

`tool_runtime.ToolExecutor` 提供四层保护，**作用在 Agent 工具执行路径上，不改变 `tools.py` 里的纯函数**
（MCP server 直接复用那些纯函数，不能引入副作用）：

| 保护 | 实现 | 参数（config） |
|---|---|---|
| **超时控制** | `asyncio.wait_for` + 自管线程池 | `TOOL_TIMEOUT`（默认 8s） |
| **重试** | 指数退避 `backoff * 第几次` | `TOOL_RETRIES`（默认 2）、`TOOL_RETRY_BACKOFF`（默认 0.3s） |
| **熔断降级** | `CircuitBreaker`：CLOSED→OPEN→HALF_OPEN→CLOSED | `TOOL_BREAKER_THRESHOLD`（3）、`TOOL_BREAKER_COOLDOWN`（30s） |
| **并发限流** | `asyncio.Semaphore` | `TOOL_MAX_CONCURRENCY`（8） |

### 关键实现细节

**同步阻塞工具必须放线程池**。业务工具是阻塞式 MySQL 查询，直接调用会卡死事件循环，
`asyncio.wait_for` 完全无法中断它（实测 0.5s 超时实际跑了 3s）。

但**不能用 `asyncio.to_thread`** —— 它用 asyncio 默认线程池，事件循环关闭时会等待池内线程结束，
导致「超时后总耗时仍被拖长」。所以用自管 `ThreadPoolExecutor` + `loop.run_in_executor`，
超时后 `wait_for` 立即放弃等待并返回降级话术。

**失败必须返回字符串而不是抛异常**。模型需要看到「工具失败了，请转人工」才能正确处理；
抛异常会导致整条 ReAct 链路崩溃。

### 接入方式

LangGraph 的 `ToolNode` 会直接调用 `tool.invoke()`，绕过外部装饰。因此可靠性包在
`ToolNode` 的 `awrap_tool_call` 钩子上（`app/workflow.py` 的 `_guarded_wrapper`），
并把 `ToolNode` 实例直接传给 `create_react_agent`（该函数接受 ToolNode 实例，此时不会重建节点）。

```
LangGraph ToolNode → awrap_tool_call 钩子 → ToolExecutor（超时/重试/熔断/限流）→ 底层工具
```

### 降级话术

| 场景 | 返回给模型的话术 |
|---|---|
| 超时 | `工具 {name} 调用超时（超过 {limit}s），暂时无法获取数据，建议稍后重试或转人工客服。` |
| 执行失败 | `工具 {name} 执行失败（{err}），暂时无法获取数据，建议稍后重试或转人工客服。` |
| 熔断中 | `工具 {name} 当前处于熔断状态（连续失败次数达阈值），暂时不可用，建议转人工客服。` |

### 实测验证（`python -m eval.test_tool_runtime`，13/13 通过）

| 场景 | 结果 |
|---|---|
| 正常调用 | ok=true，耗时 35ms（订单查询）|
| 同步阻塞工具超时 | **503ms 返回降级话术**（工具本身要跑 3s），Agent 回复「系统超时…建议转人工」，**未编造数据** |
| 连续失败 | 第 1 次真实失败 → 第 2、3 次 `circuit_open` 快速失败，不再打 DB |
| 熔断恢复 | 冷却后进入 HALF_OPEN，探测成功即回到 CLOSED |
| 并行执行 | 5 个 300ms 工具并行耗时 < 1s（串行需 1.5s）|
| 并发限流 | 6 个工具、限流 2，观测到的并发峰值 = 2 |

### 工具执行耗时实测（30 条用例，27 次调用）

| 工具 | 调用数 | 平均耗时 | 最大 |
|---|---|---|---|
| queryOrderByOrderNo | 5 | 31.7ms | 38.0ms |
| queryRefundByOrderNo | 3 | 32.0ms | 38.5ms |
| queryTicketByOrderNo | 3 | 23.9ms | 34.0ms |
| queryWarrantyByOrderNo | 2 | 36.5ms | 36.5ms |
| **searchPolicyKnowledge** | 14 | **295.2ms** | **453.3ms** |

**检索比业务查询慢 9~12 倍** —— 差距来自 Embedding 调用（百炼 API）+ pgvector 查询。
业务工具是本地 MySQL，30ms 很快。

## Token 用量观测

ReAct 链路的 Token 用量此前全记 0（`metrics.log_call` 硬编码 0,0），可观测性对 react 链路失明。
现从 LangGraph 消息流的 `usage_metadata` 累加各轮 LLM 调用：

| 指标 | 值（30 条用例）|
|---|---|
| prompt tokens 总计 | 58303 |
| completion tokens 总计 | 3923 |
| 单请求平均 prompt | 1943 |
| 单请求平均 completion | 131 |
| 单请求平均 total | 2074 |
| LLM 轮次总计 / 平均 | 54 / 1.8 |

## 评测

```powershell
cd D:\SmartSupport AI 企业智能售后助手\python-service
python -m eval.eval_rag          # 检索评测：Hit@1/3/5+MRR+延迟，只读 vector_store
python -m eval.eval_retrieval     # 检索策略横向对比：dense/bm25/hybrid/rerank（无 LLM，零消耗）
                                  #   --cases=ext  仅扩展集(46条)  --cases=both 合并集(75条)
python -m eval.eval_prompt_regression  # Prompt A/B 回归：多轮交错 + 中位数 + 噪声带判定
                                  #   --rounds=2  --cases=both
python -m eval.tune_rerank_weight  # 重排权重调参（dev/test 分割，37 组网格，约 6 分钟）
python -m eval.eval_answer --mode=rag    # 端到端生成评估：LLM-as-Judge（忠实度/拒答率/工具选型）
python -m eval.eval_answer --mode=react  # 同上，测 ReAct 链路
python -m eval.eval_stability --rounds 3 --mode rag    # 同配置跑 N 轮，统计指标波动（中位数）
python -m eval.eval_agent --mode react   # Agent 轨迹级评测：pass@1/步数分布/无效调用率/失败归因/Token/工具耗时
python -m eval.test_eval_agent            # 轨迹解析与失败分类的离线单测（15/15，零 API 消耗）
python -m eval.test_tool_runtime          # 工具可靠性层离线单测（13/13，零 API 消耗）
python -m eval.test_rerank_authority      # 重排权威度信号离线单测（6/6，零 API 消耗）
python -m eval.test_context              # 上下文预算器离线单测（31/31，零 API 消耗）
python -m eval.test_prompt_version       # Prompt 版本注册表离线单测（22/22，零 API 消耗）
python -m eval.test_ndcg                 # NDCG/MAP 指标离线单测（41/41，零 API 消耗）
python -m eval.test_trace                # Trace span 离线单测（23/23，零 API 消耗）
```

> 离线单测合计 **151 个，全绿，零 API 消耗** —— 评测代码本身的质量也必须被测，
> 否则"评测结果不可信"这件事会一直藏着。

> **完整基线见 [`eval/baseline-report.md`](eval/baseline-report.md)** —— 后续所有改造的对照基准。
> **轨迹评测报告见 [`eval/eval-agent-report.md`](eval/eval-agent-report.md)**。
> **检索评测报告见 [`eval/retrieval-eval-report.md`](eval/retrieval-eval-report.md)**。

### 检索策略横向对比（75 条标注用例 + 15 条越界，topK=5）

知识库从 6 chunk 扩充到 24 chunk、评测集从 29 条扩到 75 条（含 8 条近义干扰用例）后：

| 策略 | Hit@1 | Hit@3 | Hit@5 | MRR | NDCG@5 | MAP | 平均延迟 |
|---|---|---|---|---|---|---|---|
| dense | 81.3% | 97.3% | 98.7% | 0.8878 | 0.8871 | **0.9092** | 286ms |
| bm25 | 76.0% | 92.0% | 93.3% | 0.8338 | 0.8919 | 0.8864 | **30ms** |
| hybrid | 81.3% | 94.7% | 100% | 0.8847 | 0.9002 | **0.9384** | 305ms |
| **rerank** | **89.3%** | 97.3% | **100%** | **0.9400** | **0.9048** | 0.8970 | 269ms |

> NDCG / MAP 由 `eval/metrics_ndcg.py` 计算，**采用分级相关性**（Primary=3 / Secondary=2 / Tertiary=1 /
> Distractor=-1 / None=0），而非二值命中。理由：二值指标无法区分"命中了正确章节"与
> "命中了近似干扰章节"，而后者恰恰是本场景最容易踩的坑。
>
> 一个有意思的现象：**MAP 与 NDCG 的排序不完全一致** —— `hybrid` 的 MAP 最高（0.9384），
> 但 `rerank` 的 Hit@1 / NDCG 最高（89.3% / 0.9048）。因为 MAP 衡量的是"整个有序列表上相关文档的平均位置"，
> 更看重**整体把相关文档排在前面**；NDCG 更看重**头部位置的精度**，并且给干扰文档负分。
> 面向用户的问答场景，**首条结果决定答案质量**，所以默认仍选 rerank。

**默认策略已从 dense 改为 rerank**（Hit@1 +8.0pt、MRR +0.052），
可用 `RETRIEVAL_MODE=dense` 回退。

**重要发现**：扩充前的「dense Hit@1 89.7%」是小语料造成的假象 ——
6 个 chunk 时四策略挤在 Hit@3=100% 的天花板上，没有区分度。
扩充后 rerank 从负收益（79.3%，低于 dense 10.4pt）变成正收益（89.3%，高于 dense 8.0pt）。
**没有足够的干扰语料，就无法证明优化有效。**

#### 重排器的四个信号

| 信号 | 权重 | 说明 |
|---|---|---|
| 向量相似度 | 0.55 | 语义相关性，**用绝对刻度**不做 min-max 拉伸 |
| 查询词命中率 | 0.20 | 字面命中，FAQ 会把口语问法原样复述，权重不能过高 |
| 章节匹配度 | 0.15 | 章节标题与查询的词汇重合度 |
| 来源权威度 | 0.10 | 政策正文 1.0 / 归纳章节 0.7 / FAQ 复述 0.35 |

权威度同时以**乘性折扣**参与排序：
```
final = (0.55·vec + 0.20·kw + 0.15·sec + 0.10·auth) × (0.85 + 0.15·auth)
```

> 向量分量改用绝对刻度是修复一个隐性 bug：min-max 会把「0.70 vs 0.66」这种
> 4pt 的真实差异拉伸成「1.0 vs 0.0」，等于把噪声放大成信号。

#### 避免过拟合：dev/test 分割调参

`eval/tune_rerank_weight.py` 按 id 哈希稳定二分（dev 36 / test 39），
只在 dev 上搜 37 组权重网格，选定后只看一次 test：

| 指标 | dev（调参集） | test（未见集） |
|---|---|---|
| Hit@1 | 91.7% | **87.2%** |
| MRR | 0.9583 | 0.9175 |

当前默认权重在同一 test 集上 Hit@1 87.2%（完全相同）、MRR 0.9231（略优）。
**结论：75 条规模上做权重微调收益落在噪声范围内，当前权重已接近最优。**
这比「又调出 0.5% 提升」更有价值 —— 说明该扩语料和用例，而不是继续调参。

### Agent 轨迹级评测（114 条用例全量）

`eval_answer.py` 只看结果，`eval_agent.py` 看**过程**：走了几步、调了哪些工具、
有没有无效调用、在哪一步失败、失败属于哪一类。

| 指标 | react 实测（114 条全量） |
|---|---|
| 执行成功率 | 114/114（100%） |
| pass@1 / pass@3 | **89.5%** / **96.5%** |
| 引用忠实度 | **96.5%** |
| 平均步数 / 最大步数 | 0.87 / 8 |
| 工具调用总数 | 99 |
| **无效调用率** | **0.0%** |
| **浪费调用率** | **0.0%** |
| **降级调用数** | **0** |
| 失败归类 | HALLUCINATION 4、RETRIEVAL_EMPTY 6，其余 7 类均为 0 |
| 平均单请求 Token | prompt 2096 / completion 144 / total 2240 |
| 平均延迟 | 2041ms |

分类别表现：

| 类别 | 条数 | pass@1 | 忠实度 |
|---|---|---|---|
| out_of_scope（越界） | 19 | **100%** | **100%** |
| colloquial（口语化） | 8 | **100%** | **100%** |
| policy（政策） | 63 | 90.5% | 93.7% |
| tool（业务工具） | 24 | 75.0% | **100%** |

> **重要：评测参考集质量决定评测结论的有效性。**
> 初版参考答案是"创建售后工单选退货，经审核后退货"这样的 1 句摘要，
> 而模型实际引用了完整的 7 天窗口与运费规则，裁判反而判为 `HALLUCINATION`，
> 导致 pass@1 一度只有 64.9%、35 条"幻觉"。这**不是模型的问题，是标准答案的问题**。
> 修复动作：① 参考答案升级为多条款原文（≤900 字，按查询关键词相关性挑选）；
> ② 裁判 Prompt 明确"参考为摘要，与政策语义一致的细节表述不算幻觉，除非明确矛盾"；
> ③ `load_sections()` 修复 —— 原本会丢弃没有 `##` 标题的续接 chunk（如 §1.3 退款计算规则）。
> 修复后 pass@1 89.5%、忠实度 96.5%，HALLUCINATION 从 35 降到 4。
>
> 另用 `_judge_stability.py` 复跑 12 条验证裁判稳定性，0/12 出现误判翻转。


失败归因 taxonomy 共 9 类：`RETRIEVAL_EMPTY` / `TOOL_ERROR` / `INVALID_ARGS` /
`DUPLICATE_CALL` / `LOOP` / `MAX_STEP` / `HALLUCINATION` / `REFUSAL_OVER` / `REFUSAL_UNDER`。

按类别看：业务工具类忠实度 100%、越界类 100% 且无数据泄漏（`REFUSAL_UNDER`=0）；
**政策类 70% / 口语化类 75% 是短板**，根因是知识库仅 6 个 chunk，召回覆盖不足。

> 完整分析见 [`eval/eval-agent-report.md`](eval/eval-agent-report.md)。
> 语料扩充到 24 chunk 后的检索层分析见 [`eval/retrieval-eval-report.md`](eval/retrieval-eval-report.md)。

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
| GET | `/py/ops/trace/{trace_id}` | 单次请求的**完整 span 调用链**（父子关系 + 各段耗时 + 属性） |
| GET | `/py/ops/traces?limit=20` | 最近的 trace 列表 |
| GET | `/py/ops/slow-spans?thresholdMs=500` | 慢 span 排行，用于定位"到底是哪一环慢" |
| GET | `/py/ops/trace-stats` | 按 span 类型聚合的耗时画像（哪类 span 占用总耗时最多） |

每次 `/py/knowledge/chat` 与 `/py/agent/chat` 自动记录：延迟、RAG命中、工具数、成功失败、
prompt/completion Token（ReAct 链路暂记 0）、回复长度。失败只记不抛，不影响主流程。

**span 级追踪**（`app/trace.py`）在此之上补充了细粒度视图：单次请求按
`agent → retrieval / context / tool → llm` 展开为嵌套 span，落库 `ops.db` 的 `trace_spans` 表。
回答"这次慢，是 Embedding 慢、pgvector 慢、还是模型慢"不再需要猜。

## MCP

```powershell
python -m app.mcp_server   # stdio 模式，暴露 4 个查询工具
```

Dify / Claude Desktop 以 stdio 方式接入即可。
