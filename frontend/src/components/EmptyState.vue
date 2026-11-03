<template>
  <!--
    空状态：图标 + 主文案 + 补充说明 + 可选操作。
    统一替代各页面里手写的 .empty-tip / .no-result / .ss-empty。
  -->
  <div class="empty-state">
    <span class="empty-icon" :class="`empty-icon--${size}`">
      <el-icon><component :is="icon" /></el-icon>
    </span>
    <p class="empty-title">{{ title }}</p>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-action">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  // Element Plus 图标组件名
  icon: { type: String, default: 'FolderOpened' },
  // 主文案
  title: { type: String, default: '暂无数据' },
  // 补充说明
  description: { type: String, default: '' },
  // sm / md / lg
  size: { type: String, default: 'md' },
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ss-space-2);
  padding: var(--ss-space-8) 0 var(--ss-space-5);
  text-align: center;
  color: var(--ss-text-tertiary);
}

.empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  border-radius: var(--ss-radius);
  background: var(--ss-bg-hover);
  color: var(--ss-text-tertiary);
}

.empty-icon--sm {
  width: 32px;
  height: 32px;
  font-size: var(--ss-icon-md);
}

.empty-icon--md {
  width: 44px;
  height: 44px;
  border-radius: 13px;
  font-size: var(--ss-icon-lg);
}

.empty-icon--lg {
  width: 56px;
  height: 56px;
  border-radius: var(--ss-radius-lg);
  font-size: var(--ss-icon-xl);
  background: var(--ss-primary-soft);
  color: var(--ss-primary);
}

.empty-title {
  margin: 0;
  font-size: var(--ss-fs-base);
  color: var(--ss-text-secondary);
}

.empty-desc {
  margin: 0;
  font-size: var(--ss-fs-sm);
  max-width: 360px;
}

.empty-action {
  margin-top: var(--ss-space-2);
}
</style>
