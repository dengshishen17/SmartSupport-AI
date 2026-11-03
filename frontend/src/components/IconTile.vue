<template>
  <!--
    浅色图标方块：次级功能入口的视觉锚点（上传、统计、文件列表等）。
    tone 决定底色/前景色，默认使用主色系。
  -->
  <span class="icon-tile" :class="[`icon-tile--${size}`, `icon-tile--${tone}`]">
    <el-icon><component :is="icon" /></el-icon>
  </span>
</template>

<script setup>
defineProps({
  // Element Plus 图标组件名
  icon: { type: String, required: true },
  // sm / md / lg
  size: { type: String, default: 'md' },
  // primary / neutral / success / warning / danger
  tone: { type: String, default: 'primary' },
})
</script>

<style scoped>
.icon-tile {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  border-radius: var(--ss-radius-sm);
  background: var(--ss-primary-soft);
  color: var(--ss-primary);
}

.icon-tile--sm {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  font-size: var(--ss-icon-sm);
}

.icon-tile--md {
  width: 34px;
  height: 34px;
  border-radius: var(--ss-radius);
  font-size: var(--ss-icon-md);
}

.icon-tile--lg {
  width: 44px;
  height: 44px;
  border-radius: 13px;
  font-size: var(--ss-icon-lg);
}

/* ---------- 色调 ---------- */
.icon-tile--neutral {
  background: var(--ss-bg-hover);
  color: var(--ss-text-tertiary);
}

.icon-tile--success {
  background: var(--ss-success-soft);
  color: var(--ss-success);
}

.icon-tile--warning {
  background: var(--ss-warning-soft);
  color: var(--ss-warning);
}

.icon-tile--danger {
  background: var(--ss-danger-soft);
  color: var(--ss-danger);
}
</style>
