<template>
  <!--
    统计卡片：数值 + 标签 + 图标 + 强调色。
    替换 TicketView 里的 .stat-row / .stat-item 硬编码写法。
  -->
  <div class="stat-card" :class="`stat-card--${tone}`">
    <div class="stat-main">
      <span class="ss-stat-value stat-value">{{ value }}</span>
      <span class="ss-stat-label">{{ label }}</span>
    </div>
    <span class="stat-icon">
      <el-icon><component :is="icon" /></el-icon>
    </span>
  </div>
</template>

<script setup>
defineProps({
  value: { type: [Number, String], default: 0 },
  label: { type: String, required: true },
  // Element Plus 图标组件名
  icon: { type: String, default: 'Tickets' },
  // neutral / primary / warning / success / danger
  tone: { type: String, default: 'neutral' },
})
</script>

<style scoped>
.stat-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ss-space-3);
  padding: 14px var(--ss-space-4);
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
  transition: color var(--ss-dur) var(--ss-ease);
}

.stat-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--ss-bg-hover);
  color: var(--ss-text-tertiary);
  font-size: 17px;
  transition: all var(--ss-dur) var(--ss-ease);
}

/* ---------- 色调 ---------- */
.stat-card--primary .stat-value {
  color: var(--ss-info);
}

.stat-card--primary .stat-icon {
  background: var(--ss-primary-soft);
  color: var(--ss-primary);
}

.stat-card--warning .stat-value {
  color: var(--ss-warning);
}

.stat-card--warning .stat-icon {
  background: var(--ss-warning-soft);
  color: var(--ss-warning);
}

.stat-card--success .stat-value {
  color: var(--ss-success);
}

.stat-card--success .stat-icon {
  background: var(--ss-success-soft);
  color: var(--ss-success);
}

.stat-card--danger .stat-value {
  color: var(--ss-danger);
}

.stat-card--danger .stat-icon {
  background: var(--ss-danger-soft);
  color: var(--ss-danger);
}
</style>
