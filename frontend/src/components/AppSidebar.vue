<template>
  <!--
    应用左侧导航栏：品牌区 + 主导航 + 可选扩展区 + 底部状态。
    聊天页通过 #extra 插槽把历史会话列表挂在这里，
    形成「导航 + 会话」合并的左栏，与中栏对话、右栏上下文组成三栏布局。
  -->
  <aside class="app-sidebar">
    <!-- 品牌区 -->
    <div class="brand">
      <BrandMark icon="Cpu" size="md" />
      <span class="brand-text">
        <span class="brand-name">SmartSupport</span>
        <span class="brand-sub">AI 智能售后</span>
      </span>
    </div>

    <!-- 主导航 -->
    <nav class="nav-list">
      <button
        v-for="item in items"
        :key="item.key"
        class="nav-item"
        :class="{ active: activeTab === item.key }"
        @click="$emit('update:activeTab', item.key)"
      >
        <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </nav>

    <!-- 扩展区：聊天页的历史会话列表 -->
    <div v-if="$slots.extra" class="sidebar-extra">
      <slot name="extra" />
    </div>

    <!-- 底部状态 -->
    <div class="sidebar-footer">
      <StatusDot tone="success" label="服务正常" pulse />
    </div>
  </aside>
</template>

<script setup>
import BrandMark from './BrandMark.vue'
import StatusDot from './StatusDot.vue'

defineProps({
  // 导航项：[{ key, label, icon }]，icon 为 Element Plus 图标组件名
  items: { type: Array, default: () => [] },
  activeTab: { type: String, default: '' },
})

defineEmits(['update:activeTab'])
</script>

<style scoped>
.app-sidebar {
  flex: none;
  width: var(--ss-sidebar-w);
  display: flex;
  flex-direction: column;
  padding: var(--ss-space-4) var(--ss-space-3) var(--ss-space-3);
  background: var(--ss-bg-sidebar);
  border-right: 1px solid var(--ss-border);
  z-index: var(--ss-z-sidebar);
}

/* ---------- 品牌 ---------- */
.brand {
  display: flex;
  align-items: center;
  gap: var(--ss-gap-sm);
  padding: var(--ss-space-1) var(--ss-space-2) var(--ss-space-4);
  min-width: 0;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  min-width: 0;
}

.brand-name {
  font-size: var(--ss-fs-md);
  font-weight: 650;
  letter-spacing: -0.01em;
  color: var(--ss-text);
  white-space: nowrap;
}

.brand-sub {
  font-size: 11px;
  color: var(--ss-text-tertiary);
  white-space: nowrap;
}

/* ---------- 导航 ---------- */
.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: none;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--ss-gap-sm);
  width: 100%;
  border: none;
  background: transparent;
  color: var(--ss-text-secondary);
  font-family: inherit;
  font-size: var(--ss-fs-sm);
  font-weight: 500;
  padding: 9px var(--ss-space-3);
  border-radius: var(--ss-radius);
  cursor: pointer;
  text-align: left;
  transition: background var(--ss-dur-fast) var(--ss-ease), color var(--ss-dur-fast) var(--ss-ease);
}

.nav-item:hover {
  background: var(--ss-bg-hover);
  color: var(--ss-text);
}

.nav-item.active {
  background: var(--ss-primary-soft);
  color: var(--ss-primary-text);
  font-weight: 600;
}

.nav-icon {
  flex: none;
  font-size: var(--ss-icon);
}

.nav-item.active .nav-icon {
  color: var(--ss-primary);
}

.nav-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ---------- 扩展区（会话列表） ---------- */
.sidebar-extra {
  flex: 1;
  min-height: 0;
  margin: var(--ss-space-3) calc(-1 * var(--ss-space-3)) 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-top: 1px solid var(--ss-border-light);
}

.sidebar-extra > :deep(*) {
  flex: 1;
  min-height: 0;
}

/* ---------- 底部状态 ---------- */
.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: var(--ss-space-2) var(--ss-space-3) 2px;
  font-size: var(--ss-fs-sm);
  color: var(--ss-text-tertiary);
  border-top: 1px solid var(--ss-border-light);
}

@media (max-width: 860px) {
  .app-sidebar {
    width: 60px;
    padding: var(--ss-space-4) var(--ss-space-2) var(--ss-space-3);
  }
  .brand {
    justify-content: center;
    padding: var(--ss-space-1) 0 var(--ss-space-4);
  }
  .brand-text {
    display: none;
  }
  .nav-item {
    justify-content: center;
    padding: 9px 0;
  }
  .nav-label {
    display: none;
  }
  .sidebar-footer {
    justify-content: center;
    padding: var(--ss-space-2) 0 2px;
  }
  /* 窄屏下隐藏会话列表，保留导航图标 */
  .sidebar-extra {
    display: none;
  }
}
</style>
