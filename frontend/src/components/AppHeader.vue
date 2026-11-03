<template>
  <!--
    顶部条：页面标题 + 副标题 + 右侧操作插槽。
    替代原 App.vue 顶栏右侧的状态区 + 各页面自带的 header。
    前置图标通过 #lead 插槽注入（如会话页的助手头像）。
  -->
  <header class="app-header">
    <div class="header-text">
      <span v-if="$slots.lead" class="header-lead">
        <slot name="lead" />
      </span>
      <div class="header-copy">
        <h1 class="header-title">{{ title }}</h1>
        <span v-if="subtitle" class="header-sub">{{ subtitle }}</span>
      </div>
    </div>
    <div v-if="$slots.actions" class="header-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
})
</script>

<style scoped>
.app-header {
  flex: none;
  min-height: var(--ss-header-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ss-gap);
  padding: var(--ss-space-3) var(--ss-space-6);
  background: var(--ss-bg-elevated);
  border-bottom: 1px solid var(--ss-border);
  z-index: var(--ss-z-header);
}

.header-text {
  display: flex;
  align-items: center;
  gap: var(--ss-space-3);
  min-width: 0;
}

.header-lead {
  display: inline-flex;
  align-items: center;
  flex: none;
}

.header-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.header-title {
  margin: 0;
  font-size: var(--ss-fs-md);
  font-weight: 620;
  color: var(--ss-text);
  letter-spacing: -0.01em;
  white-space: nowrap;
}

.header-sub {
  font-size: var(--ss-fs-sm);
  color: var(--ss-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--ss-gap-sm);
}

@media (max-width: 720px) {
  .app-header {
    padding-left: 16px;
    padding-right: 16px;
  }
  .header-sub {
    display: none;
  }
}
</style>
