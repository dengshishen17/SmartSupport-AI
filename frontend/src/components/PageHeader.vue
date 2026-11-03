<template>
  <!--
    统一页头：标题 + 副标题 + 右侧操作插槽。
    替换 KnowledgeView / TicketView 各自写的 header 样式。
  -->
  <header class="ss-page-header" :class="{ 'ss-page-header--compact': compact }">
    <div class="page-header-text">
      <h2>{{ title }}</h2>
      <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-header-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  // compact: 上下留白更小，用于内容较满的页面
  compact: { type: Boolean, default: false },
})
</script>

<style scoped>
.ss-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ss-gap);
  padding: var(--ss-space-6) var(--ss-pad-page) var(--ss-space-4);
}

.ss-page-header--compact {
  padding: var(--ss-space-5) var(--ss-pad-page) var(--ss-space-3);
}

.page-header-text {
  min-width: 0;
}

.ss-page-header h2 {
  margin: 0 0 var(--ss-space-1);
  font-size: var(--ss-fs-xl);
  font-weight: 650;
  letter-spacing: -0.01em;
  color: var(--ss-text);
}

.ss-page-header .subtitle {
  margin: 0;
  font-size: var(--ss-fs-sm);
  color: var(--ss-text-tertiary);
}

.page-header-actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--ss-gap-sm);
}

.page-header-actions :deep(.el-button) {
  gap: 6px;
}

@media (max-width: 720px) {
  .ss-page-header {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>
