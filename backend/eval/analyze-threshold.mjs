#!/usr/bin/env node
/**
 * 阈值扫描结果分析：找出「可答用例不空返」与「越界问题被挡住」之间的权衡点。
 *
 * 关键点：服务对空结果返回 topScore=0.0（不是 null），所以「被挡住」的判据是
 * topScore === 0，而不是 null。之前的 PowerShell 分析用 null 判断，结果全错。
 */
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const file = process.argv[2] || join(__dirname, 'eval-threshold-scan.json');

// 去掉 UTF-8 BOM，否则 JSON.parse 会失败
const raw = readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
const parsed = JSON.parse(raw);
// 兼容两种落盘格式：整个响应体 {code,message,data} 或直接 data
const j = parsed.data && parsed.data.configs ? parsed.data : parsed;

console.log('configs=' + j.configs.length);
console.log('');

const header = ['th', 'HR@1', 'HR@3', 'MRR', 'avgRet', 'ansEmpty', 'ansNotTop1', 'OOSblocked', 'OOSmeanTop1'];
console.log(header.map((h) => h.padEnd(11)).join(''));

for (const c of j.configs) {
  const oosRows = c.outOfScopeProbe.rows || [];
  const oosBlocked = oosRows.filter((r) => r.topScore === 0).length;
  const oosScores = oosRows.map((r) => r.topScore).filter((s) => s > 0);
  const oosMean = oosScores.length
    ? oosScores.reduce((a, b) => a + b, 0) / oosScores.length
    : 0;

  const ansEmpty = c.cases.filter((x) => x.returnedCount === 0).length;
  const ansNotTop1 = c.cases.filter((x) => x.firstHitRank !== 1).length;

  const vals = [
    String(c.similarityThreshold),
    c.metrics.hitRateAt1.toFixed(4),
    c.metrics.hitRateAt3.toFixed(4),
    c.metrics.mrr.toFixed(4),
    c.metrics.avgReturnedChunks.toFixed(2),
    `${ansEmpty}/29`,
    `${ansNotTop1}/29`,
    `${oosBlocked}/${oosRows.length}`,
    oosMean.toFixed(4),
  ];
  console.log(vals.map((v) => String(v).padEnd(11)).join(''));
}

// 找出：可答用例 0 空返 的前提下，最多能挡住多少越界
console.log('\n--- 最优权衡点（要求 ansEmpty=0，即没有可答问题被误伤）---');
const safe = j.configs.filter((c) => c.cases.every((x) => x.returnedCount > 0));
for (const c of safe) {
  const oosBlocked = (c.outOfScopeProbe.rows || []).filter((r) => r.topScore === 0).length;
  console.log(
    `th=${c.similarityThreshold}  OOSblocked=${oosBlocked}/4  HR@1=${c.metrics.hitRateAt1.toFixed(4)}  HR@3=${c.metrics.hitRateAt3.toFixed(4)}  MRR=${c.metrics.mrr.toFixed(4)}`
  );
}
