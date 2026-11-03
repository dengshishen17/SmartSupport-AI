<template>
  <!--
    右侧上下文面板：展示与当前会话相关的**真实**信息。

    数据来源全部为真实数据，不做任何模拟：
      1. 会话概览   —— 来自当前 Vue 状态（sessionId / 消息数 / 工具调用数）
      2. 本轮查询   —— 来自 SSE 工具调用事件返回的真实查询结果
      3. 引用来源   —— 来自 SSE reference 事件返回的真实 RAG 来源
      4. 知识库文件 —— GET /ai/knowledge/files（真实已导入文件）
      5. 售后工单   —— GET /api/ticket/list（真实工单列表）

    折叠态只保留竖排图标条。
  -->
  <aside class="ss-panel" :class="{ 'ss-panel--collapsed': collapsed }">
    <!-- ===== 折叠态：竖排图标条 ===== -->
    <div v-if="collapsed" class="ss-panel-rail">
      <el-tooltip content="展开上下文" placement="left">
        <button type="button" class="rail-btn" @click="$emit('toggle-collapse')">
          <el-icon><Expand /></el-icon>
        </button>
      </el-tooltip>

      <el-tooltip content="会话概览" placement="left">
        <div class="rail-item">
          <el-icon><ChatDotRound /></el-icon>
          <span class="rail-badge">{{ messages.length }}</span>
        </div>
      </el-tooltip>

      <el-tooltip content="查询记录" placement="left">
        <div class="rail-item">
          <el-icon><Tools /></el-icon>
          <span v-if="allTools.length" class="rail-badge">{{ allTools.length }}</span>
        </div>
      </el-tooltip>

      <el-tooltip content="引用来源" placement="left">
        <div class="rail-item">
          <el-icon><Collection /></el-icon>
          <span v-if="allSources.length" class="rail-badge">{{ allSources.length }}</span>
        </div>
      </el-tooltip>
    </div>

    <!-- ===== 展开态 ===== -->
    <template v-else>
      <div class="ss-panel-head">
        <el-icon><InfoFilled /></el-icon>
        <span class="panel-title">上下文</span>
        <el-tooltip content="收起面板" placement="bottom">
          <button type="button" class="panel-collapse-btn" @click="$emit('toggle-collapse')">
            <el-icon><Fold /></el-icon>
          </button>
        </el-tooltip>
      </div>

      <div class="ss-panel-body">
        <!-- ① 会话概览 -->
        <section class="panel-section">
          <p class="ss-panel-section">会话概览</p>
          <div class="ss-kv">
            <span class="ss-kv-label">会话 ID</span>
            <span class="ss-kv-value ss-mono">{{ sessionId || '未开始' }}</span>
          </div>
          <div class="ss-kv">
            <span class="ss-kv-label">消息数</span>
            <span class="ss-kv-value">{{ messages.length }}</span>
          </div>
          <div class="ss-kv">
            <span class="ss-kv-label">工具调用</span>
            <span class="ss-kv-value">{{ allTools.length }}</span>
          </div>
          <div class="ss-kv">
            <span class="ss-kv-label">引用来源</span>
            <span class="ss-kv-value">{{ allSources.length }}</span>
          </div>
        </section>

        <!-- ② 本轮查询（真实工具调用结果） -->
        <section v-if="allTools.length" class="panel-section">
          <p class="ss-panel-section">查询记录</p>
          <div v-for="(t, ti) in allTools" :key="ti" class="ctx-tool">
            <div class="ctx-tool-head">
              <el-icon class="ctx-tool-icon" :class="t.tool.status">
                <Loading v-if="t.tool.status === 'running'" />
                <CircleCheck v-else />
              </el-icon>
              <span class="ctx-tool-label">{{ t.tool.label }}</span>
              <span v-if="t.tool.args && t.tool.args.orderNo" class="ctx-tool-order">
                {{ t.tool.args.orderNo }}
              </span>
            </div>
            <p v-if="t.tool.result" class="ctx-tool-result">{{ t.tool.result }}</p>
          </div>
        </section>

        <!-- ③ 引用来源（真实 RAG 来源） -->
        <section v-if="allSources.length" class="panel-section">
          <p class="ss-panel-section">引用来源</p>
          <div v-for="(s, si) in allSources" :key="si" class="ctx-source">
            <el-icon class="ctx-source-icon"><Document /></el-icon>
            <span class="ctx-source-name">{{ s }}</span>
          </div>
        </section>

        <!-- ④ 知识库文件（真实已导入） -->
        <section class="panel-section">
          <p class="ss-panel-section">
            知识库文件
            <span v-if="knowledgeLoading" class="ss-panel-section-hint">加载中…</span>
          </p>
          <div v-if="knowledgeError" class="ctx-note ctx-note--error">{{ knowledgeError }}</div>
          <div v-else-if="!knowledgeFiles.length && !knowledgeLoading" class="ctx-note">
            暂无已导入的知识文件
          </div>
          <div v-for="f in knowledgeFiles" :key="f.source" class="ctx-file">
            <el-icon class="ctx-file-icon"><FolderOpened /></el-icon>
            <span class="ctx-file-name">{{ f.source }}</span>
            <span class="ctx-file-chunks">{{ f.chunks }}</span>
          </div>
        </section>

        <!-- ⑤ 售后工单（真实工单） -->
        <section class="panel-section">
          <p class="ss-panel-section">
            售后工单
            <span v-if="ticketLoading" class="ss-panel-section-hint">加载中…</span>
          </p>
          <div v-if="ticketError" class="ctx-note ctx-note--error">{{ ticketError }}</div>
          <div v-else-if="!tickets.length && !ticketLoading" class="ctx-note">暂无工单记录</div>
          <div v-for="t in tickets.slice(0, 6)" :key="t.id" class="ctx-ticket">
            <div class="ctx-ticket-head">
              <span class="ctx-ticket-id">#{{ t.id }}</span>
              <el-tag size="small" :type="statusType(t.status)" effect="plain">{{ t.status }}</el-tag>
            </div>
            <div class="ctx-ticket-meta">
              <span class="ctx-ticket-order">{{ t.orderNo }}</span>
              <span class="ctx-ticket-type">{{ t.problemType }}</span>
            </div>
          </div>
          <p v-if="tickets.length > 6" class="ctx-note ctx-note--more">
            共 {{ tickets.length }} 条，仅显示最近 6 条
          </p>
        </section>
      </div>
    </template>
  </aside>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { listKnowledgeFiles } from '../api/knowledge'
import { listTickets } from '../api/ticket'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
  // 当前消息数组（只读，用于提取真实的工具调用与引用来源）
  messages: { type: Array, default: () => [] },
  // 当前会话 ID
  sessionId: { type: String, default: '' },
})

defineEmits(['toggle-collapse'])

/* ---------- 从真实消息流中提取工具调用与引用来源 ---------- */
const allTools = computed(() => {
  const out = []
  for (const m of props.messages) {
    if (m.role === 'assistant' && Array.isArray(m.tools)) {
      m.tools.forEach((tool) => out.push({ tool }))
    }
  }
  return out
})

const allSources = computed(() => {
  const set = new Set()
  for (const m of props.messages) {
    if (Array.isArray(m.sources)) m.sources.forEach((s) => set.add(s))
  }
  return [...set]
})

/* ---------- 真实业务数据：知识库文件 / 售后工单 ---------- */
const knowledgeFiles = ref([])
const knowledgeLoading = ref(false)
const knowledgeError = ref('')

const tickets = ref([])
const ticketLoading = ref(false)
const ticketError = ref('')

onMounted(async () => {
  // 知识库文件
  knowledgeLoading.value = true
  try {
    knowledgeFiles.value = await listKnowledgeFiles()
  } catch (e) {
    knowledgeError.value = e.message || '加载失败'
  } finally {
    knowledgeLoading.value = false
  }

  // 售后工单
  ticketLoading.value = true
  try {
    tickets.value = await listTickets()
  } catch (e) {
    ticketError.value = e.message || '加载失败'
  } finally {
    ticketLoading.value = false
  }
})

// 工单状态 → 标签类型（与 TicketView 保持一致）
function statusType(status) {
  if (status === '已完成') return 'success'
  if (status === '处理中') return 'warning'
  return 'info'
}
</script>

<style scoped>
/* ---------- 折叠态图标条 ---------- */
.rail-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--ss-radius);
  background: transparent;
  color: var(--ss-text-tertiary);
  cursor: pointer;
  transition: var(--ss-transition);
}

.rail-btn:hover {
  background: var(--ss-bg-hover);
  color: var(--ss-primary);
}

.rail-item {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--ss-radius);
  color: var(--ss-text-tertiary);
  font-size: var(--ss-icon);
}

.rail-badge {
  position: absolute;
  top: -2px;
  right: -2px;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: var(--ss-radius-pill);
  background: var(--ss-primary);
  color: var(--ss-text-inverse);
  font-size: 10px;
  font-weight: 650;
  line-height: 15px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

/* ---------- 面板头 ---------- */
.panel-title {
  font-weight: 620;
}

.panel-collapse-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--ss-radius-sm);
  background: transparent;
  color: var(--ss-text-tertiary);
  cursor: pointer;
  transition: var(--ss-transition);
}

.panel-collapse-btn:hover {
  background: var(--ss-bg-hover);
  color: var(--ss-primary);
}

/* ---------- 分节 ---------- */
.panel-section {
  margin-bottom: var(--ss-space-6);
}

.panel-section:last-child {
  margin-bottom: 0;
}

.ss-panel-section-hint {
  margin-left: 6px;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  color: var(--ss-text-disabled);
}

.ctx-note {
  padding: var(--ss-space-2) 0;
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-disabled);
}

.ctx-note--error {
  color: var(--ss-danger-text);
}

.ctx-note--more {
  padding-top: var(--ss-space-2);
}

/* ---------- 工具调用 ---------- */
.ctx-tool {
  margin-top: var(--ss-space-2);
  padding: var(--ss-space-3);
  border: 1px solid var(--ss-border);
  border-radius: var(--ss-radius);
  background: var(--ss-bg-subtle);
}

.ctx-tool-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ctx-tool-icon {
  flex: none;
  font-size: var(--ss-icon-xs);
}

.ctx-tool-icon.running {
  color: var(--ss-warning);
}

.ctx-tool-icon.done {
  color: var(--ss-success);
}

.ctx-tool-label {
  font-size: var(--ss-fs-xs);
  font-weight: 600;
  color: var(--ss-text);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.ctx-tool-order {
  margin-left: auto;
  flex: none;
  padding: 1px 6px;
  border-radius: var(--ss-radius-pill);
  background: var(--ss-bg-hover);
  font-family: var(--ss-font-mono);
  font-size: 10px;
  color: var(--ss-text-secondary);
}

.ctx-tool-result {
  margin: 6px 0 0;
  font-size: var(--ss-fs-xs);
  line-height: 1.65;
  color: var(--ss-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---------- 引用来源 ---------- */
.ctx-source {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--ss-border-light);
}

.ctx-source:last-child {
  border-bottom: none;
}

.ctx-source-icon {
  flex: none;
  color: var(--ss-primary);
  font-size: var(--ss-icon-xs);
}

.ctx-source-name {
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-secondary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* ---------- 知识库文件 ---------- */
.ctx-file {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
}

.ctx-file-icon {
  flex: none;
  color: var(--ss-text-tertiary);
  font-size: var(--ss-icon-xs);
}

.ctx-file-name {
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-secondary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.ctx-file-chunks {
  margin-left: auto;
  flex: none;
  padding: 1px 7px;
  border-radius: var(--ss-radius-pill);
  background: var(--ss-bg-hover);
  font-size: 10px;
  color: var(--ss-text-tertiary);
  font-variant-numeric: tabular-nums;
}

/* ---------- 工单 ---------- */
.ctx-ticket {
  padding: 8px 10px;
  margin-top: var(--ss-space-2);
  border: 1px solid var(--ss-border-light);
  border-radius: var(--ss-radius);
  background: var(--ss-bg-subtle);
}

.ctx-ticket-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ss-space-2);
}

.ctx-ticket-id {
  font-family: var(--ss-font-mono);
  font-size: var(--ss-fs-xs);
  font-weight: 600;
  color: var(--ss-text-tertiary);
}

.ctx-ticket-meta {
  display: flex;
  align-items: center;
  gap: var(--ss-space-2);
  margin-top: 3px;
}

.ctx-ticket-order {
  font-family: var(--ss-font-mono);
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-secondary);
}

.ctx-ticket-type {
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-tertiary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
</style>
