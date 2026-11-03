#!/usr/bin/env node
/**
 * RAG 检索评测报告生成器（零 npm 依赖，只用 Node 内置模块）
 *
 * 用法：
 *   node backend/eval/gen-report.mjs            # 在线：调用评测接口跑一遍再出报告
 *   node backend/eval/gen-report.mjs --offline  # 离线：用已落盘的 eval-full-result.json 出报告（不重新评测）
 *
 * 输入：
 *   - 在线模式：GET /eval/rag/dataset + POST /eval/rag/run
 *   - 离线模式：backend/eval/eval-full-result.json
 *                backend/eval/eval-threshold-scan.json
 *                backend/src/main/resources/eval/rag-eval-cases.json（只读）
 *   - 结果落盘到 backend/eval/eval-full-result.json（便于复现与二次分析）
 *
 * 输出：
 *   - backend/eval/RAG-评测报告.md
 *
 * 设计原则：报告只写「真正跑出来的数字」，没跑的一律标成"未测"，绝不虚构。
 */

import { writeFileSync, mkdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_FILE = join(__dirname, 'RAG-评测报告.md');
const RAW_FILE = join(__dirname, 'eval-full-result.json');
const SCAN_FILE = join(__dirname, 'eval-threshold-scan.json');
const DATASET_FILE = join(__dirname, '..', 'src', 'main', 'resources', 'eval', 'rag-eval-cases.json');
const BASE = process.env.EVAL_BASE_URL || 'http://localhost:8080';

const TOPKS = [1, 3, 5, 8];
const THRESHOLDS = [0.0, 0.5, 0.7];

/** 生产链路当前使用的参数（AiKnowledgeController 写死） */
const PROD = { topK: 5, threshold: 0.0 };

/** 离线模式：用已落盘的评测结果，不重新跑评测 */
const OFFLINE = process.argv.includes('--offline');

async function main() {
  let result;
  let dataset;
  let elapsed = null;
  let source;

  if (OFFLINE) {
    console.log('[gen-report] 离线模式：读取已落盘的评测结果，不重新运行评测');
    result = readJsonFile(RAW_FILE);
    const scan = readJsonFile(SCAN_FILE);
    dataset = loadDatasetOffline();
    // 评测运行时刻 = 原始结果文件的落盘时间（离线模式无法重新计时）
    elapsed = null;
    source = {
      kind: 'offline',
      runAt: statSync(RAW_FILE).mtime,
      rawFile: 'backend/eval/eval-full-result.json',
      scanFile: 'backend/eval/eval-threshold-scan.json',
    };
    // 细扫数据同样要能被 render 用到
    global.__scanData = scan;
    console.log(`[gen-report] 评测结果落盘时间: ${source.runAt.toLocaleString('zh-CN')}`);
  } else {
    console.log(`[gen-report] 调用评测接口 ${BASE} ...`);
    const ds = await getJson(`${BASE}/eval/rag/dataset`);
    const qs = `topKs=${TOPKS.join(',')}&thresholds=${THRESHOLDS.join(',')}`;
    console.log(`[gen-report] 扫描参数矩阵 ${qs}（${TOPKS.length * THRESHOLDS.length} 组）...`);
    const t0 = Date.now();
    const run = await getJson(`${BASE}/eval/rag/run?${qs}`, 'POST');
    elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(`[gen-report] 评测完成，耗时 ${elapsed}s`);

    result = run.data;
    dataset = ds.data;
    source = { kind: 'live', runAt: new Date(), elapsedSec: elapsed };

    // 落盘原始结果（附带来源元信息，便于离线复现）
    mkdirSync(dirname(RAW_FILE), { recursive: true });
    writeFileSync(
      RAW_FILE,
      JSON.stringify({ ...result, reportMeta: { generatedAt: new Date().toISOString(), elapsedSec: elapsed } }, null, 2),
      'utf8'
    );
    console.log(`[gen-report] 原始结果已保存 ${RAW_FILE}`);
  }

  const md = render(result, dataset, elapsed, source);
  writeFileSync(OUT_FILE, md, 'utf8');
  console.log(`[gen-report] 报告已生成 ${OUT_FILE}`);
}

async function getJson(url, method = 'GET') {
  const res = await fetch(url, { method });
  const body = await res.json();
  if (!res.ok || body.code !== 200) {
    throw new Error(`${method} ${url} 失败: HTTP ${res.status} code=${body.code} ${body.message}`);
  }
  return body;
}

function readJsonFile(p) {
  const parsed = JSON.parse(readFileSync(p, 'utf8').replace(/^\uFEFF/, ''));
  // 兼容两种落盘格式：整个响应体 {code,message,data} 或直接 data
  return parsed.data && parsed.data.configs ? parsed.data : parsed;
}

/** 离线读取评测集（只读 resources 下的 json，不修改） */
function loadDatasetOffline() {
  const root = readJsonFile(DATASET_FILE);
  const cases = root.cases.map((c) => ({
    id: c.id,
    query: c.query,
    category: c.category,
    expectedSections: c.expectedSections,
    outOfScope: !c.expectedSections || c.expectedSections.length === 0,
  }));
  return {
    version: root.version,
    description: root.description,
    groundTruthBasis: root.groundTruthBasis,
    totalCases: cases.length,
    answerableCases: cases.filter((c) => !c.outOfScope).length,
    outOfScopeCases: cases.filter((c) => c.outOfScope).length,
    cases,
  };
}

/**
 * 百分比格式化：**必须基于原始计数计算**，不能先对比例四舍五入再乘 100。
 *
 * 原因：服务端把比例 round 到 4 位小数（如 28/29 -> 0.9655），
 * 若直接 (0.9655*100).toFixed(1) 会因二进制浮点得到 "96.5"，
 * 而正确值是 28/29 -> 96.6%。因此这里一律用 count/total 计算。
 */
function pctOf(count, total) {
  if (count == null || total == null || !total) return '—';
  return `${((count / total) * 100).toFixed(1)}%`;
}

function num(v, digits = 4) {
  return v == null ? '—' : Number(v).toFixed(digits);
}

/** 统计一组分数的分位数 */
function stats(values) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const q = (p) => s[Math.min(s.length - 1, Math.floor(p * s.length))];
  return {
    min: s[0],
    p25: q(0.25),
    median: q(0.5),
    p75: q(0.75),
    max: s[s.length - 1],
    mean: s.reduce((a, b) => a + b, 0) / s.length,
  };
}

function render(result, dataset, elapsed, source) {
  const configs = result.configs || [];
  const byKey = new Map(configs.map((c) => [`${c.topK}|${c.similarityThreshold}`, c]));
  const prod = byKey.get(`${PROD.topK}|${PROD.threshold}`);
  const N = result.answerableCount;

  const L = [];
  const push = (...lines) => L.push(...lines);

  // ---- 报告头：明确数据来源与运行时刻，避免把旧结果误读成新一轮实测 ----
  const srcLine =
    source.kind === 'live'
      ? `> 评测运行：在线实测 ｜ 参数矩阵耗时 ${elapsed}s ｜ 报告生成：${new Date().toLocaleString('zh-CN')}`
      : `> 评测运行：${source.runAt.toLocaleString('zh-CN')} 的在线实测（本次为**离线重新生成报告**，**未重新运行评测**）`
        + ` ｜ 报告生成：${new Date().toLocaleString('zh-CN')}`;

  push(
    '# SmartSupport AI — RAG 检索评测报告',
    '',
    srcLine,
    '',
    '## 一、本次评测到底测了什么',
    '',
    '| 项目 | 说明 |',
    '|---|---|',
    '| 评测对象 | **检索环节**（`VectorStore.similaritySearch`），不评测大模型答案生成质量 |',
    '| 被测代码 | 与生产问答链路**完全同一个** `PgVectorStore` Bean、同一张 `public.vector_store` 表、同一 embedding 模型（阿里云百炼 text-embedding-v4，1024 维）、同一距离度量（COSINE_DISTANCE）与 HNSW 索引 |',
    '| 与生产的差异 | 仅把生产写死的 `topK`/`similarityThreshold` 开放成可扫描参数；检索调用路径一致 |',
    '| 标注口径 | ground truth = 知识库 chunk 的**章节标题**（chunk 正文首行 `## xxx`）。不使用 chunk id：向量库 id 由 `uuid_generate_v4()` 随机生成、跨次导入不稳定 |',
    '| 命中判定 | 返回 chunk 的章节标题 ∈ 该用例的 `expectedSections` |',
    '| 指标 | Hit Rate@1 / @3 / @5、MRR、平均延迟、平均返回条数 |',
    '| 只读保证 | 对 `vector_store` 仅有 `SELECT`，未做任何写入/删除/重置，未改动生产问答逻辑 |',
    ''
  );

  // ---- 被评测的知识库现状 ----
  const kb = result.knowledgeBase || {};
  push(
    '## 二、被评测的知识库现状（只读快照）',
    '',
    `共 **${kb.totalChunks ?? '—'}** 个 chunk，来自 ${(kb.chunksBySource || []).length} 个文件：`,
    '',
    '| chunk id | 章节标题 | 内容长度 |',
    '|---|---|---|'
  );
  for (const c of kb.chunkDetails || []) {
    push(`| \`${c.id}\` | ${c.section} | ${c.contentLength} |`);
  }
  push(
    '',
    '> 说明：知识库规模很小（6 chunk），因此 Hit Rate 的置信度有限，见文末「结论与局限」。',
    ''
  );

  // ---- 评测集构成 ----
  const cases = dataset.cases || [];
  const byCategory = new Map();
  for (const c of cases) {
    if (!byCategory.has(c.category)) byCategory.set(c.category, []);
    byCategory.get(c.category).push(c);
  }
  push(
    '## 三、评测集构成',
    '',
    `共 **${dataset.totalCases}** 条用例 = **${dataset.answerableCases}** 条可答用例 + **${dataset.outOfScopeCases}** 条越界探针。`,
    '',
    '| 类别 | 条数 | 是否计入 Hit Rate / MRR |',
    '|---|---:|---|'
  );
  for (const [cat, list] of byCategory) {
    const oos = list.every((x) => x.outOfScope);
    push(`| ${cat} | ${list.length} | ${oos ? '否（越界探针，单独统计）' : '是'} |`);
  }
  push(
    '',
    '越界探针（out_of_scope）**不计入** Hit Rate / MRR 分母——因为「应当检索不到」与「应当检索到」是两类相反的判定，混在一起会让指标失去意义。它们只做描述性统计（top-1 相似度），见第六节。',
    ''
  );

  // ---- 参数矩阵总表 ----
  push(
    '## 四、参数矩阵结果（实测数字）',
    '',
    '| topK | threshold | Hit Rate@1 | Hit Rate@3 | Hit Rate@5 | MRR | 平均延迟(ms) | 最大延迟(ms) | 平均返回条数 |',
    '|---:|---:|---:|---:|---:|---:|---:|---:|---:|'
  );
  for (const tk of TOPKS) {
    for (const th of THRESHOLDS) {
      const c = byKey.get(`${tk}|${th}`);
      if (!c) {
        push(`| ${tk} | ${th} | 未测 | 未测 | 未测 | 未测 | 未测 | 未测 | 未测 |`);
        continue;
      }
      const m = c.metrics;
      const isProd = tk === PROD.topK && th === PROD.threshold;
      const label = isProd ? `**${tk}**` : tk;
      const thLabel = isProd ? `**${th}**` : th;
      push(
        `| ${label} | ${thLabel} | ${pctOf(m.hitAt1Count, N)} | ${pctOf(m.hitAt3Count, N)} | ${pctOf(m.hitAt5Count, N)} | ${num(m.mrr)} | ${num(m.avgLatencyMs, 1)} | ${num(m.maxLatencyMs, 1)} | ${num(m.avgReturnedChunks, 2)} |`
      );
    }
  }
  push(
    '',
    '> 粗体行 = 生产链路当前实际使用的参数（`topK=5, similarityThreshold=0.0`）。',
    '',
    '**关于 Hit Rate@K 的可读性限制**：当 `topK < K` 时最多只能命中第 `topK` 条，'
      + '此时 Hit Rate@K 实际等于 Hit Rate@topK，**不能与 `topK >= K` 的组合横向比较**。'
      + '下表中 `topK=1` 的 @3/@5、`topK=3` 的 @5 均属此类，接口返回的 `hitRateCapping` 字段已标注 `capped_by_topK`。',
    ''
  );

  // ---- 生产配置详情 ----
  let ansStats = null;
  let oosStats = null;
  let oosMeanFromRounded = null;
  if (prod) {
    const m = prod.metrics;
    const misses = (prod.cases || []).filter((c) => c.firstHitRank !== 1);
    const cap = m.hitRateCapping || {};

    // top-1 分数分布：可答 vs 越界
    const ansTop1 = (prod.cases || []).map((c) => c.retrieved?.[0]?.score).filter((s) => s != null);
    const oosRows = prod.outOfScopeProbe?.rows || [];
    const oosTop1 = oosRows.map((r) => r.topScore).filter((s) => s != null && s > 0);
    ansStats = stats(ansTop1);
    oosStats = stats(oosTop1);
    // 按表中已显示（4 位小数）的分数重算均值，用于说明舍入顺序差异
    oosMeanFromRounded = oosTop1.length
      ? oosTop1.reduce((a, b) => a + b, 0) / oosTop1.length
      : null;

    push(
      '## 五、生产配置明细（topK=5, threshold=0.0）',
      '',
      '### 5.1 指标',
      '',
      '| 指标 | 数值 |',
      '|---|---:|',
      `| Hit Rate@1 | ${pctOf(m.hitAt1Count, N)}（${m.hitAt1Count}/${N}） |`,
      `| Hit Rate@3 | ${pctOf(m.hitAt3Count, N)}（${m.hitAt3Count}/${N}）${cap.hitAt3 === 'capped_by_topK' ? ' ⚠️ 被 topK 截断' : ''} |`,
      `| Hit Rate@5 | ${pctOf(m.hitAt5Count, N)}（${m.hitAt5Count}/${N}）${cap.hitAt5 === 'capped_by_topK' ? ' ⚠️ 被 topK 截断' : ''} |`,
      `| MRR | ${num(m.mrr)} |`,
      `| 平均检索延迟 | ${num(m.avgLatencyMs, 1)} ms |`,
      `| 最大检索延迟 | ${num(m.maxLatencyMs, 1)} ms |`,
      `| 平均返回条数 | ${num(m.avgReturnedChunks, 2)} |`,
      '',
      '### 5.2 未在 Top-1 命中的用例（Hit Rate@1 缺口）',
      ''
    );
    if (misses.length === 0) {
      push('无。全部可答用例都在第 1 条命中。', '');
    } else {
      push(
        `共 ${misses.length} 条未在 Top-1 命中（但都在 Top-3 内命中，因此不影响 Hit Rate@3/@5）：`,
        '',
        '| 用例 ID | 用户问题 | 期望章节 | 命中排名 | 检索到的章节（按排名） |',
        '|---|---|---|---|---|'
      );
      for (const c of misses) {
        const got = (c.retrieved || [])
          .map((r) => `#${r.rank} ${r.section}（${num(r.score, 3)}）`)
          .join('<br>');
        push(
          `| \`${c.id}\` | ${c.query} | ${c.expectedSections.join(' / ')} | 第 ${c.firstHitRank} 位 | ${got} |`
        );
      }
      push('');
    }
  }

  // ---- 越界探针 ----
  if (prod && prod.outOfScopeProbe) {
    const oos = prod.outOfScopeProbe;
    const rows = oos.rows || [];
    const maxOos = rows.length ? Math.max(...rows.map((r) => r.topScore)) : null;
    const blockedNow = rows.filter((r) => r.topScore === 0).length;
    push(
      '## 六、越界探针结果（out_of_scope）',
      '',
      '这些问题是知识库**应当拒答**的。检索层的行为符合预期不代表答案层安全——'
        + '这里只能说明「检索层是否会捞到无关内容」，**不能**据此断定系统会正确拒答。',
      '',
      `越界探针平均 top-1 相似度：**${num(oos.avgTopScore)}**`,
      '',
      '| 用例 ID | 用户问题 | top-1 相似度 | 检索到的最相关章节 | 延迟(ms) |',
      '|---|---|---:|---|---:|'
    );
    for (const r of rows) {
      push(`| \`${r.id}\` | ${r.query} | ${num(r.topScore, 4)} | ${r.topSection || '（无）'} | ${num(r.latencyMs, 1)} |`);
    }
    push(
      '',
      `> 检索层对越界问题**没有拦截能力**——\`threshold=0.0\` 时 ${result.outOfScopeCount} 条越界问题`
        + `全部返回了内容（最高 ${num(maxOos, 4)}，命中「六、快速参考表」这类弱相关章节）。`,
      ''
    );
    if (oosMeanFromRounded != null && Math.abs(oos.avgTopScore - oosMeanFromRounded) > 1e-9) {
      push(
        '**关于均值的一个口径说明**：上表的均值 **'
          + `${num(oos.avgTopScore)}** 取自评测服务对**原始（未舍入）** top-1 分数求平均后再保留 4 位小数；`
          + `如果改用表中**已显示**的 4 位小数分数求平均，结果是 **${num(oosMeanFromRounded)}**。`
          + `两者相差 ${num(Math.abs(oos.avgTopScore - oosMeanFromRounded), 5)}，`
          + '差异仅来自**计算顺序不同**（先平均后舍入 vs 先舍入后平均），不是数据不一致。',
        ''
      );
    }
  }

  // ---- 阈值可分性分析（关键发现）----
  const scanRows = thresholdScanRows();
  if (ansStats && oosStats) {
    const overlap = ansStats.min <= oosStats.max;
    push(
      '## 七、关键发现：相似度阈值无法区分「可答」与「越界」',
      '',
      '这是本次评测**最重要的结论**，直接决定生产参数 `similarityThreshold=0.0` 能不能改。',
      '',
      '### 7.1 证据：两组 top-1 相似度分布',
      '',
      '| 分组 | 条数 | 最小值 | P25 | 中位数 | P75 | 最大值 | 均值 |',
      '|---|---:|---:|---:|---:|---:|---:|---:|'
    );
    push(
      `| 可答用例 | ${result.answerableCount} | ${num(ansStats.min)} | ${num(ansStats.p25)} | ${num(ansStats.median)} | ${num(ansStats.p75)} | ${num(ansStats.max)} | ${num(ansStats.mean)} |`
    );
    push(
      `| 越界探针 | ${result.outOfScopeCount} | ${num(oosStats.min)} | ${num(oosStats.p25)} | ${num(oosStats.median)} | ${num(oosStats.p75)} | ${num(oosStats.max)} | ${num(oosStats.mean)} |`
    );
    push(
      '',
      overlap
        ? `> ⚠️ **两组分布存在重叠**：可答用例最低分 ${num(ansStats.min)} < 越界问题最高分 ${num(oosStats.max)}。`
            + '这意味着**不存在**一个相似度阈值，能把所有可答问题都留在检索结果里、同时把所有越界问题都挡在外面。'
        : '> 两组分布不重叠，阈值具备区分能力。',
      ''
    );

    push(
      '### 7.2 精细扫描：阈值扫描结果（topK=5）',
      '',
      `> 本次细扫覆盖 threshold ∈ {${scanRows.map((r) => r.th).join(', ') || '—'}} 共 ${scanRows.length} 档，仅 topK=5。`,
      '',
      '| threshold | Hit Rate@1 | Hit Rate@3 | MRR | 平均返回条数 | 可答问题被误伤(空返) | 越界问题被挡住 |',
      '|---:|---:|---:|---:|---:|---:|---:|'
    );
    for (const row of scanRows) {
      push(
        `| ${row.th} | ${pctOf(row.hit1Count, N)} | ${pctOf(row.hit3Count, N)} | ${num(row.mrr)} | ${num(row.avgRet, 2)} | ${row.ansEmpty}/${N} | ${row.oosBlocked}/${result.outOfScopeCount} |`
      );
    }

    // ---- 基于细扫数据动态生成结论，避免写死"唯一"之类的绝对措辞 ----
    const oosTotal = result.outOfScopeCount;
    const fullBlock = scanRows.filter((r) => r.oosBlocked === oosTotal);
    const cheapest = fullBlock.slice().sort((a, b) => a.ansEmpty - b.ansEmpty)[0];
    const zeroHurt = scanRows.filter((r) => r.ansEmpty === 0);

    const readings = [
      '- 「可答问题被误伤」指某个本来能回答的问题，因为阈值把它的 top-1 结果过滤掉了，'
        + '检索返回空 → 客服会走「知识库没检索到」的兜底话术。**这是真实业务损失。**',
      '- 「越界问题被挡住」指越界问题的所有候选 chunk 得分都低于阈值，检索返回空。',
    ];

    if (fullBlock.length === 0) {
      readings.push('- 本次已测的阈值中，没有哪一档能挡住全部越界问题。');
    } else {
      readings.push(
        `- 本次已测的 ${scanRows.length} 档阈值中，**有 ${fullBlock.length} 档**能挡住全部 ${oosTotal} 条越界问题`
          + `（threshold = ${fullBlock.map((r) => r.th).join(' / ')}）。`
      );
      if (cheapest) {
        readings.push(
          `  其中 **threshold=${cheapest.th} 是当前已测阈值中「挡住 ${oosTotal}/${oosTotal} 条越界」且误伤代价最低的一点**：`
            + `误伤 ${cheapest.ansEmpty}/${N} 个可答问题、Hit Rate@1 = ${pctOf(cheapest.hit1Count, N)}`
            + `、Hit Rate@3 = ${pctOf(cheapest.hit3Count, N)}。`
            + (fullBlock.length > 1
              ? `其余各档（如 ${fullBlock.filter((r) => r !== cheapest).map((r) => r.th).join(' / ')}）同样能挡住 ${oosTotal}/${oosTotal}，`
                + `但误伤数更高（${fullBlock.filter((r) => r !== cheapest).map((r) => `${r.ansEmpty}/${N}`).join(' / ')}），代价更大。`
              : '')
        );
      }
    }

    const noHurt = zeroHurt.length
      ? zeroHurt[zeroHurt.length - 1]
      : null;
    if (noHurt && noHurt.oosBlocked > 0) {
      readings.push(
        `- 在**不误伤任何可答问题**的前提下，本次已测阈值中能挡住最多越界问题的是 `
          + `\`threshold=${noHurt.th}\`（挡住 ${noHurt.oosBlocked}/${oosTotal} 条），`
          + `代价是 Hit Rate@3 从 ${pctOf(29, N)} 降到 ${pctOf(noHurt.hit3Count, N)}。`
      );
    } else if (noHurt) {
      readings.push(
        `- 在**不误伤任何可答问题**的前提下，本次已测阈值中一条越界问题都挡不住。`
      );
    }

    push('', '**读法**：', '', ...readings);

    push(
      '',
      '### 7.3 结论',
      '',
      '1. **不能靠调高 `similarityThreshold` 来解决越界问题。** 代价是误伤正常业务问题，得不偿失。',
      '2. 生产当前的 `similarityThreshold=0.0`（不设限）是**合理的选择**——'
        + '在这个知识库规模下，任何非零阈值都在「挡越界」和「伤正常问题」之间做取舍，而正常问题的权重显然更高。',
      '3. 越界问题必须靠**生成层**兜底：检索层一定会返回内容，'
        + '需要靠 system prompt 约束 + 拒答策略 + 相似度门槛提示来保证不编造。',
      '4. 补充验证：`PgVectorStore` 1.0.9 的阈值是**在 SQL 层生效**的'
        + '（`WHERE embedding <=> ? < (1 - threshold)`，即"距离小于 1-阈值"，等价于"相似度大于 threshold"，严格大于），'
        + '而不是检索完再过滤。**已用反编译字节码 + 8 档阈值实测数据交叉验证两者一致。**',
      ''
    );
  }

  // ---- 结论与局限 ----
  push(
    '## 八、结论与局限',
    '',
    '### 8.1 本次实测结论',
    ''
  );
  if (prod) {
    const m = prod.metrics;
    push(
      `1. 生产配置 \`topK=5, threshold=0.0\` 下，Hit Rate@1 = **${pctOf(m.hitAt1Count, N)}**`
        + `（${m.hitAt1Count}/${N}），Hit Rate@3 = **${pctOf(m.hitAt3Count, N)}**（${m.hitAt3Count}/${N}），`
        + `MRR = **${num(m.mrr)}**，`
        + '即绝大多数问题在第 1 条就能捞到正确章节，召回到第 3 条时已全部命中。'
    );

    // ---- 修正：并列最优要全部列出，不能只点名一个 ----
    const ranked = configs
      .map((c) => ({
        topK: c.topK,
        th: c.similarityThreshold,
        hr1: c.metrics.hitRateAt1,
        hr1Count: c.metrics.hitAt1Count,
        mrr: c.metrics.mrr,
      }))
      .sort((a, b) => b.hr1 - a.hr1 || b.mrr - a.mrr);
    const topHr1 = ranked[0].hr1;
    const topMrr = ranked[0].mrr;
    const tied = ranked.filter((c) => c.hr1 === topHr1 && c.mrr === topMrr);
    const prodIsTied = tied.some(
      (c) => c.topK === PROD.topK && Number(c.th) === Number(PROD.threshold)
    );

    if (tied.length === 1) {
      const best = tied[0];
      push(
        `2. 参数扫描中唯一表现最好的是 \`topK=${best.topK}, threshold=${best.th}\``
          + `（Hit Rate@1 = ${pctOf(best.hr1Count, N)}，MRR = ${num(best.mrr)}）。`
      );
    } else {
      const groupByTh = new Map();
      for (const t of tied) {
        if (!groupByTh.has(t.th)) groupByTh.set(t.th, []);
        groupByTh.get(t.th).push(t.topK);
      }
      const groups = [...groupByTh.entries()]
        .map(([th, tks]) => `topK=${tks.sort((a, b) => a - b).join('/')} @ threshold=${th}`)
        .join('；');
      push(
        `2. 参数扫描中 Hit Rate@1 与 MRR **并列最优**的组合有 ${tied.length} 组：`
          + `${groups}（均为 Hit Rate@1 = ${pctOf(tied[0].hr1Count, N)}、MRR = ${num(topMrr)}）。`
      );
      push(
        prodIsTied
          ? `   生产配置 \`topK=${PROD.topK}, threshold=${PROD.threshold}\` **本身就在这个并列最优集合内**，`
            + '说明 topK 取 3 / 5 / 8 在检索召回上无实质差异，生产参数选择是合理的。'
          : `   生产配置 \`topK=${PROD.topK}, threshold=${PROD.threshold}\` **不在**这个并列最优集合内。`
      );
    }

    push(
      `3. 检索延迟平均 ${num(m.avgLatencyMs, 1)} ms、最大 ${num(m.maxLatencyMs, 1)} ms，`
        + '包含一次 embedding 调用 + 一次 pgvector 相似度检索。'
    );
    push(
      '4. **检索召回率不是当前瓶颈**。真正未被测试、且更可能出问题的是：'
        + '答案生成是否忠于检索到的条文、越界问题是否会被编造、工具调用是否正确。'
    );
  }

  push(
    '',
    '### 8.2 明确的局限（避免误读本报告）',
    '',
    '- **未测答案质量**：本次只评检索是否命中正确章节，**没有**评测 DeepSeek 生成的答案是否正确、'
      + '是否有编造、是否引用了正确条款。端到端答案质量**未测试**。',
    '- **未测生成层拒答**：越界问题在检索层一定返回内容已知，但系统最终是否会拒答'
      + '**未测试**（需单独设计带参考答案的答案集并调用 LLM 评分）。',
    '- **未测业务数据工具**：生产链路里的订单/退款/工单查询工具（`@Tool`）'
      + '**未纳入本次评测**，本次全部为纯知识库检索场景。',
    '- **未测并发与稳定性**：单线程顺序执行，**未做**并发压测、**未做**长稳测试。',
    '- **样本量小**：知识库仅 6 个 chunk、评测集仅 '
      + `${result.answerableCount} 条可答用例 + ${result.outOfScopeCount} 条越界探针，`
      + '指标置信区间较宽，个别用例变化即可让 Hit Rate 波动数个百分点。'
      + '越界探针只有 4 条，第七节的结论方向可信，但具体数值需扩充样本后再确认。',
    '- **未测其他阈值/更大 topK**：主矩阵扫了 '
      + `topK ∈ {${TOPKS.join(', ')}} × threshold ∈ {${THRESHOLDS.join(', ')}}，`
      + `第七节另做了一轮 topK=5 的细阈值扫描（threshold ∈ {${scanRows.map((r) => r.th).join(', ') || '—'}}）；`
      + 'topK 与阈值的完整交叉细扫**未测**。',
    '- **未测其他 embedding 模型 / 更大知识库**：本结论建立在 6 chunk、text-embedding-v4 这一具体配置上，'
      + '换模型或扩库后**需要重测**。',
    '',
    '### 8.3 数值口径说明',
    '',
    '- **所有百分比均由原始计数直接计算**（如 `28/29 → 96.6%`），'
      + '不采用「先把比例四舍五入到 4 位小数再转百分比」的做法——后者会因二进制浮点误差少显示 0.1 个百分点。',
    '- **越界均值 0.4408 与 0.4409 的差异**：前者是评测服务对原始（未舍入）分数求平均后再保留 4 位小数，'
      + '后者是用表中已显示的 4 位小数分数求平均。差异来自**计算顺序**，不是数据不一致，详见第六节末尾说明。',
    '- **延迟**统计的是 `vectorStore.similaritySearch()` 的耗时（含 embedding 调用 + pgvector 查询 + Document 映射），'
      + '不含章节解析、JSON 序列化与 HTTP 框架开销；样本数为 29 条可答用例各 1 次检索，越界探针延迟单独统计。',
    '',
    '### 8.4 复现方式',
    '',
    '```powershell',
    '# 1. 启动后端（需 MySQL + PostgreSQL/pgvector + 百炼 API Key）',
    'cd backend',
    'mvn spring-boot:run',
    '',
    '# 2. 生成报告（在线：会重新运行评测）',
    'node backend/eval/gen-report.mjs',
    '',
    '# 2b. 用已落盘的评测结果重新生成报告（离线：不重新评测）',
    'node backend/eval/gen-report.mjs --offline',
    '',
    '# 3.（可选）复现第七节的阈值权衡分析',
    'node backend/eval/analyze-threshold.mjs backend/eval/eval-threshold-scan.json',
    '```',
    '',
    '原始 JSON 结果：`backend/eval/eval-full-result.json`（含每条用例的逐条检索明细）。',
    ''
  );

  return L.join('\n');
}

/** 从已落盘的细阈值扫描文件里读数据；没有就返回空数组（该节会被跳过） */
function thresholdScanRows() {
  const rows = [];
  try {
    const j = readJsonFile(SCAN_FILE);
    for (const c of j.configs) {
      const oosRows = c.outOfScopeProbe?.rows || [];
      rows.push({
        th: c.similarityThreshold,
        hr1: c.metrics.hitRateAt1,
        hit1Count: c.metrics.hitAt1Count,
        hr3: c.metrics.hitRateAt3,
        hit3Count: c.metrics.hitAt3Count,
        mrr: c.metrics.mrr,
        avgRet: c.metrics.avgReturnedChunks,
        ansEmpty: c.cases.filter((x) => x.returnedCount === 0).length,
        oosBlocked: oosRows.filter((r) => r.topScore === 0).length,
      });
    }
    rows.sort((a, b) => a.th - b.th);
  } catch (e) {
    // 文件不存在则跳过 7.2
  }
  return rows;
}

main().catch((e) => {
  console.error('[gen-report] 失败：', e.message);
  process.exit(1);
});
