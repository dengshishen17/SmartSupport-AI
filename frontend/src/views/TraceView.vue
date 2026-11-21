<template>
  <div class="trace-page ss-scroll">
    <PageHeader
      title="Trace 观测"
      subtitle="Python 双栈全链路追踪：单次请求按 agent → retrieval / context / tool → llm 展开为嵌套 span"
    />

    <div class="content">
      <!-- ① 顶部指标卡 -->
      <div class="stat-row">
        <div v-for="s in statCards" :key="s.label" class="stat-card">
          <div class="stat-main">
            <span class="stat-value">{{ s.value }}</span>
            <span class="stat-label">{{ s.label }}</span>
            <span class="stat-hint">{{ s.hint }}</span>
          </div>
          <span class="stat-icon">
            <el-icon><component :is="s.icon" /></el-icon>
          </span>
        </div>
      </div>

      <div class="split">
        <!-- ② Trace 列表 -->
        <section class="ss-card list-card">
          <SectionHeader title="最近 Trace" :badge="traces.length">
            <template #actions>
              <el-button link type="primary" class="head-action" :loading="loadingList" @click="loadTraces">
                <el-icon><Refresh /></el-icon>
                <span>刷新</span>
              </el-button>
            </template>
          </SectionHeader>

          <div v-loading="loadingList" class="trace-list">
            <div
              v-for="t in traces"
              :key="t.traceId"
              class="trace-item"
              :class="{ active: t.traceId === currentTraceId }"
              @click="selectTrace(t.traceId)"
            >
              <div class="trace-item-head">
                <span class="trace-mode" :class="t.mode">{{ t.mode === 'react' ? 'ReAct' : 'RAG' }}</span>
                <span class="trace-name">{{ t.name || 'agent' }}</span>
                <code class="trace-id">{{ shortId(t.traceId) }}</code>
              </div>
              <div class="trace-item-meta">
                <span>{{ t.spanCount }} span</span>
                <span class="dot">·</span>
                <span>{{ formatMs(t.durationMs) }}</span>
              </div>
            </div>
            <el-empty v-if="!loadingList && !traces.length" description="暂无 trace，请先发起一次问答请求" :image-size="60" />
          </div>
        </section>

        <!-- ③ Span 调用链 -->
        <section class="ss-card chain-card">
          <SectionHeader title="Span 调用链" :badge="spans.length">
            <template #actions>
              <span v-if="currentTraceId" class="head-note">
                <code>{{ currentTraceId }}</code>
              </span>
            </template>
          </SectionHeader>

          <div v-loading="loadingChain" class="chain-body">
            <div v-for="node in tree" :key="node.span.spanId" class="span-node">
              <div class="span-row" :style="{ paddingLeft: node.depth * 22 + 'px' }">
                <span class="span-connector" v-if="node.depth > 0"></span>
                <span class="span-name" :class="node.span.type">{{ node.span.name }}</span>
                <span class="span-type">{{ node.span.type }}</span>
                <span class="span-ms" :class="msClass(node.span.durationMs)">
                  {{ formatMs(node.span.durationMs) }}
                </span>
                <el-tag v-if="node.span.status === 'error'" type="danger" size="small" effect="plain">error</el-tag>
              </div>
              <div
                v-if="node.span.attributes && Object.keys(node.span.attributes).length"
                class="span-attrs"
                :style="{ paddingLeft: (node.depth * 22 + 14) + 'px' }"
              >
                <span v-for="(v, k) in node.span.attributes" :key="k" class="attr" :title="formatAttr(v)">
                  <em>{{ k }}</em>
                  <code>{{ attrText(v) }}</code>
                </span>
              </div>
            </div>
            <el-empty v-if="!loadingChain && !spans.length" description="选择左侧一条 Trace 查看调用链" :image-size="60" />
          </div>
        </section>
      </div>

      <!-- ④ 慢 span 排行 -->
      <section class="ss-card block">
        <SectionHeader title="慢 Span 排行" :badge="slowSpans.length">
          <template #actions>
            <span class="head-note">阈值 {{ thresholdMs }}ms · 用于定位瓶颈在检索、上下文组装还是模型生成</span>
          </template>
        </SectionHeader>

        <el-table
          :data="slowSpans"
          v-loading="loadingSlow"
          size="default"
          empty-text="暂无超过阈值的 span"
          class="slow-table"
        >
          <el-table-column label="Span" width="150">
            <template #default="{ row }">
              <span class="span-name" :class="row.type || row.spanType">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="120" align="right">
            <template #default="{ row }">
              <span class="span-ms" :class="msClass(row.durationMs)">{{ formatMs(row.durationMs) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="traceId" label="Trace" width="180">
            <template #default="{ row }">
              <code class="trace-id">{{ shortId(row.traceId) }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="mode" label="链路" width="100" align="center">
            <template #default="{ row }">
              <span class="trace-mode" :class="row.mode">{{ row.mode === 'react' ? 'ReAct' : 'RAG' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'error' ? 'danger' : 'success'" size="small" effect="plain">
                {{ row.status || 'ok' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import SectionHeader from '../components/SectionHeader.vue'
import { fetchSlowSpans, fetchTrace, fetchTraceStats, fetchTraces } from '../api/trace'
const traces = ref([])
const spans = ref([])
const slowSpans = ref([])
const traceStats = ref({})
const currentTraceId = ref('')
const thresholdMs = ref(200)

const loadingList = ref(false)
const loadingChain = ref(false)
const loadingSlow = ref(false)

/** 把扁平的 span 列表还原成树（按 parentSpanId） */
const tree = computed(() => {
  const children = new Map()
  for (const s of spans.value) {
    const key = s.parentSpanId || '__root__'
    if (!children.has(key)) children.set(key, [])
    children.get(key).push(s)
  }
  const out = []
  const walk = (key, depth) => {
    for (const s of children.get(key) || []) {
      out.push({ span: s, depth })
      walk(s.spanId, depth + 1)
    }
  }
  walk('__root__', 0)
  return out
})

/** 顶部指标卡（从 trace-stats 聚合） */
const statCards = computed(() => {
  const st = traceStats.value || {}
  const entries = Object.entries(st).filter(([k]) => k !== 'step')
  const totalSpans = entries.reduce((a, [, v]) => a + (v.count || 0), 0)
  const avgMs = entries.length
    ? entries.reduce((a, [, v]) => a + (v.avgMs || 0), 0) / entries.length
    : 0
  const errors = entries.reduce((a, [, v]) => a + (v.errors || 0), 0)
  const types = entries.length
  return [
    { label: 'Span 类型', value: String(types), hint: 'retrieval / context / tool / llm', icon: 'Connection' },
    { label: 'Span 总数', value: String(totalSpans), hint: '已落库 trace_spans 表', icon: 'Files' },
    { label: '平均耗时', value: formatMs(avgMs), hint: '按 span 类型平均', icon: 'Timer' },
    { label: '异常 Span', value: String(errors), hint: errors === 0 ? '无异常' : '需排查', icon: 'Warning' },
  ]
})

function shortId(id) {
  return id ? String(id).slice(0, 12) : '-'
}

function formatMs(ms) {
  const v = Number(ms || 0)
  if (v >= 1000) return (v / 1000).toFixed(2) + 's'
  return v.toFixed(1) + 'ms'
}

/** 慢 span 用暖色标注，方便一眼看出瓶颈 */
function msClass(ms) {
  const v = Number(ms || 0)
  if (v >= 1000) return 'slow'
  if (v >= 300) return 'warm'
  return ''
}

function formatAttr(v) {
  if (Array.isArray(v)) return v.join(' / ')
  if (typeof v === 'object' && v !== null) return JSON.stringify(v)
  return String(v)
}

/** 属性值可能很长（如召回章节数组），截断避免撑破布局 */
function attrText(v) {
  const s = formatAttr(v)
  return s.length > 60 ? s.slice(0, 60) + '…' : s
}

async function loadTraces() {
  loadingList.value = true
  try {
    const { list } = await fetchTraces(20)
    traces.value = list.map((t) => ({
      traceId: t.traceId,
      name: t.name,
      mode: t.mode,
      spanCount: t.spanCount ?? t.spans?.length ?? 0,
      durationMs: t.totalSpanMs ?? t.durationMs ?? 0,
    }))
    if (!currentTraceId.value && traces.value.length) {
      await selectTrace(traces.value[0].traceId)
    }
  } catch (e) {
    traces.value = []
    console.error('[TraceView] loadTraces 失败:', e)
  } finally {
    loadingList.value = false
  }
}

async function selectTrace(traceId) {
  currentTraceId.value = traceId
  loadingChain.value = true
  try {
    const { spans: list } = await fetchTrace(traceId)
    spans.value = list
  } catch (e) {
    spans.value = []
    console.error('[TraceView] selectTrace 失败:', e)
  } finally {
    loadingChain.value = false
  }
}

async function loadSlow() {
  loadingSlow.value = true
  try {
    const { list } = await fetchSlowSpans(thresholdMs.value, 20)
    slowSpans.value = list.map((s) => ({
      name: s.name,
      type: s.type || s.spanType,
      durationMs: s.durationMs,
      traceId: s.traceId,
      mode: s.mode,
      status: s.status,
    }))
  } catch (e) {
    slowSpans.value = []
    console.error('[TraceView] loadSlow 失败:', e)
  } finally {
    loadingSlow.value = false
  }
}

async function loadStats() {
  try {
    traceStats.value = await fetchTraceStats()
  } catch (e) {
    traceStats.value = {}
    console.error('[TraceView] loadStats 失败:', e)
  }
}

onMounted(async () => {
  await Promise.all([loadTraces(), loadSlow(), loadStats()])
})
</script>

<style scoped>
.trace-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.content {
  flex: 1;
  min-height: 0;
  padding: 18px 22px 28px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  flex: none;
}

.stat-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--ss-border);
  border-radius: var(--ss-radius-lg);
  background: var(--ss-bg-elevated);
  box-shadow: var(--ss-shadow-xs);
}

.stat-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.stat-value {
  font-size: 22px;
  font-weight: 650;
  line-height: 1.15;
  color: var(--ss-text);
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: 13px;
  color: var(--ss-text-secondary);
}

.stat-hint {
  font-size: 11px;
  color: var(--ss-text-tertiary);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--ss-primary-soft);
  color: var(--ss-primary-text);
  font-size: 17px;
}

.split {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  flex: none;
}

.block {
  flex: none;
}

.list-card,
.chain-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.head-note {
  font-size: 12px;
  color: var(--ss-text-tertiary);
}

.head-note code {
  font-size: 11px;
  color: var(--ss-text-secondary);
}

/* ---- Trace 列表 ---- */
.trace-list {
  padding: 6px;
  max-height: 420px;
  overflow-y: auto;
}

.trace-item {
  padding: 9px 11px;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.15s, border-color 0.15s;
}

.trace-item:hover {
  background: var(--ss-bg-hover);
}

.trace-item.active {
  background: var(--ss-primary-soft);
  border-color: var(--ss-primary-border);
}

.trace-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.trace-mode {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 5px;
  background: var(--ss-bg-code);
  color: var(--ss-text-secondary);
}

.trace-mode.react {
  background: var(--ss-primary-soft);
  color: var(--ss-primary-text);
}

.trace-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--ss-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-id {
  font-size: 11px;
  color: var(--ss-text-tertiary);
  font-family: Consolas, Monaco, monospace;
}

.trace-item-meta {
  margin-top: 3px;
  font-size: 12px;
  color: var(--ss-text-secondary);
}

.dot {
  margin: 0 5px;
  color: var(--ss-text-disabled);
}

/* ---- Span 调用链 ---- */
.chain-body {
  padding: 10px 14px 16px;
  min-height: 200px;
  max-height: 460px;
  overflow-y: auto;
}

.span-node {
  padding: 4px 0;
}

.span-row {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 26px;
}

.span-connector {
  width: 12px;
  height: 12px;
  border-left: 1px solid var(--ss-border-strong);
  border-bottom: 1px solid var(--ss-border-strong);
  border-bottom-left-radius: 4px;
  margin-right: 2px;
  flex: none;
}

.span-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ss-text);
}

.span-name.agent { color: var(--ss-primary-text); }
.span-name.retrieval { color: #0d9488; }
.span-name.context { color: #d97706; }
.span-name.tool { color: #7c3aed; }
.span-name.llm { color: #dc2626; }

.span-type {
  font-size: 11px;
  color: var(--ss-text-tertiary);
  background: var(--ss-bg-code);
  padding: 1px 6px;
  border-radius: 4px;
}

.span-ms {
  margin-left: auto;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  color: var(--ss-text-secondary);
  font-family: Consolas, Monaco, monospace;
}

.span-ms.warm { color: #d97706; }
.span-ms.slow { color: #dc2626; font-weight: 600; }

.span-attrs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 3px;
  max-width: 100%;
  overflow: hidden;
}

.attr {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--ss-text-secondary);
  background: var(--ss-bg-subtle);
  border: 1px solid var(--ss-border-light);
  padding: 1px 6px;
  border-radius: 4px;
  max-width: 100%;
  min-width: 0;
}

.attr em {
  font-style: normal;
  color: var(--ss-text-tertiary);
  flex: none;
}

.attr code {
  font-family: Consolas, Monaco, monospace;
  color: var(--ss-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.slow-table {
  width: 100%;
}
</style>
