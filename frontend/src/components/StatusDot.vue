<template>
  <!--
    状态指示点 + 文本：用于「服务正常」这类轻量状态展示。
    tone 控制圆点颜色，脉冲态表示连接活跃。
  -->
  <span class="status-chip">
    <span class="status-dot" :class="[`status-dot--${tone}`, { pulse }]" />
    <span v-if="label" class="status-label">{{ label }}</span>
  </span>
</template>

<script setup>
defineProps({
  // success / warning / danger / neutral / primary
  tone: { type: String, default: 'success' },
  label: { type: String, default: '' },
  // 呼吸动画，表示实时连接
  pulse: { type: Boolean, default: false },
})
</script>

<style scoped>
.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: var(--ss-fs-sm);
  color: var(--ss-text-tertiary);
}

.status-dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--ss-text-tertiary);
}

.status-dot--success {
  background: var(--ss-success);
  box-shadow: 0 0 0 3px var(--ss-success-soft);
}

.status-dot--warning {
  background: var(--ss-warning);
  box-shadow: 0 0 0 3px var(--ss-warning-soft);
}

.status-dot--danger {
  background: var(--ss-danger);
  box-shadow: 0 0 0 3px var(--ss-danger-soft);
}

.status-dot--primary {
  background: var(--ss-primary);
  box-shadow: 0 0 0 3px var(--ss-primary-soft);
}

.status-dot--neutral {
  background: var(--ss-text-tertiary);
  box-shadow: 0 0 0 3px var(--ss-bg-hover);
}

.status-dot.pulse {
  animation: ss-pulse 1.8s ease-in-out infinite;
}

@keyframes ss-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

@media (prefers-reduced-motion: reduce) {
  .status-dot.pulse {
    animation: none;
  }
}
</style>
