<template>
  <!--
    会话侧栏：新建会话按钮 + 历史会话列表。
    纯展示组件，所有动作通过事件冒泡给父组件处理。
  -->
  <aside class="session-rail">
    <div class="rail-top">
      <el-button type="primary" class="new-btn" @click="$emit('new-session')">
        <el-icon><Plus /></el-icon>
        <span>新建会话</span>
      </el-button>
    </div>

    <div class="rail-label">
      <span>最近会话</span>
      <span v-if="sessions.length" class="rail-count">{{ sessions.length }}</span>
    </div>

    <div class="session-list">
      <EmptyState
        v-if="sessions.length === 0"
        icon="ChatLineSquare"
        title="暂无历史会话"
        description="发起一次对话后会自动保存在本地"
        size="sm"
      />
      <div
        v-for="s in sessions"
        :key="s.sessionId"
        class="session-item"
        :class="{ active: s.sessionId === currentSessionId }"
        @click="$emit('switch-session', s.sessionId)"
      >
        <el-icon class="session-icon"><ChatDotRound /></el-icon>
        <div class="session-info">
          <div class="session-title">{{ s.title }}</div>
          <div class="session-time">{{ formatTime(s.updatedAt) }}</div>
        </div>
        <span class="del-btn" title="删除会话" @click.stop="$emit('delete-session', s.sessionId)">
          <el-icon><Delete /></el-icon>
        </span>
      </div>
    </div>
  </aside>
</template>

<script setup>
import EmptyState from './EmptyState.vue'

defineProps({
  // 会话数组：[{ sessionId, title, messages, updatedAt }]
  sessions: { type: Array, default: () => [] },
  currentSessionId: { type: String, default: '' },
})

defineEmits(['new-session', 'switch-session', 'delete-session'])

/**
 * 会话时间展示：今天显示 HH:mm，其他日期显示 MM-DD HH:mm。
 * 与原 ChatView 中的 formatTime 行为完全一致。
 */
function formatTime(ts) {
  const d = new Date(ts)
  const now = new Date()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  if (d.toDateString() === now.toDateString()) return `${hh}:${mm}`
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const da = String(d.getDate()).padStart(2, '0')
  return `${mo}-${da} ${hh}:${mm}`
}
</script>

<style scoped>
.session-rail {
  display: flex;
  flex-direction: column;
  width: 100%;
  flex: 1;
  min-height: 0;
  background: transparent;
  overflow: hidden;
}

/* ---------- 顶部 ---------- */
.rail-top {
  padding: var(--ss-space-4) var(--ss-space-3) var(--ss-space-2);
}

.new-btn {
  width: 100%;
  height: 38px;
  border-radius: var(--ss-radius);
  font-weight: 550;
  gap: 6px;
}

/* ---------- 分组标签 ---------- */
.rail-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ss-space-2) var(--ss-space-4) 6px;
  font-size: var(--ss-fs-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ss-text-tertiary);
  text-transform: uppercase;
}

.rail-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 5px;
  border-radius: var(--ss-radius-pill);
  background: var(--ss-bg-hover);
  color: var(--ss-text-tertiary);
  font-size: 10px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

/* ---------- 列表 ---------- */
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--ss-space-1) var(--ss-space-2) var(--ss-space-3);
}

.session-item {
  display: flex;
  align-items: center;
  gap: var(--ss-space-2);
  padding: 9px 10px;
  margin-bottom: 3px;
  border-radius: var(--ss-radius);
  cursor: pointer;
  transition: background var(--ss-dur-fast) var(--ss-ease);
}

.session-item:hover {
  background: var(--ss-bg-hover);
}

.session-item.active {
  background: var(--ss-primary-soft);
}

.session-icon {
  flex: none;
  font-size: var(--ss-icon);
  color: var(--ss-text-tertiary);
}

.session-item.active .session-icon {
  color: var(--ss-primary);
}

.session-info {
  flex: 1;
  min-width: 0;
}

.session-title {
  font-size: var(--ss-fs-sm);
  color: var(--ss-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-item.active .session-title {
  color: var(--ss-primary-text);
  font-weight: 550;
}

.session-time {
  font-size: 11px;
  color: var(--ss-text-tertiary);
  margin-top: 1px;
}

.del-btn {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: var(--ss-radius-sm);
  color: var(--ss-text-tertiary);
  font-size: 13px;
  opacity: 0;
  transition: all var(--ss-dur-fast) var(--ss-ease);
}

.session-item:hover .del-btn {
  opacity: 1;
}

.del-btn:hover {
  background: var(--ss-danger-soft);
  color: var(--ss-danger);
}
</style>
