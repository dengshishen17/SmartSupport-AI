<template>
  <!--
    RAG 引用来源展示。
    后端 topK 可能召回同一文件的多个段落，由父组件去重后传入。

    展示形态：一行「引用来源」标签 + 可点击展开的来源清单，
    让用户明确知道回答依据了哪些知识文件。
  -->
  <div v-if="sources && sources.length" class="ref-sources">
    <button type="button" class="ref-trigger" @click="expanded = !expanded">
      <el-icon class="ref-icon"><Collection /></el-icon>
      <span class="ref-label">引用来源</span>
      <span class="ref-count">{{ sources.length }}</span>
      <el-icon class="ref-caret" :class="{ open: expanded }">
        <ArrowDown />
      </el-icon>
    </button>

    <!-- 展开后的来源清单 -->
    <div class="ref-panel" :class="{ open: expanded }">
      <div class="ref-panel-inner">
        <div v-for="(s, si) in sources" :key="si" class="ref-item" :title="s">
          <el-icon class="ref-item-icon"><Document /></el-icon>
          <span class="ref-item-name">{{ s }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  // 已去重的来源文件名数组
  sources: { type: Array, default: () => [] },
})

// 展开状态纯本地，不影响任何业务数据
const expanded = ref(false)
</script>

<style scoped>
.ref-sources {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--ss-space-1);
}

/* ---------- 触发器 ---------- */
.ref-trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border: 1px solid var(--ss-border);
  border-radius: var(--ss-radius-pill);
  background: var(--ss-bg-subtle);
  font-family: inherit;
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-tertiary);
  cursor: pointer;
  transition: var(--ss-transition);
}

.ref-trigger:hover {
  border-color: var(--ss-primary-border);
  background: var(--ss-primary-softer);
  color: var(--ss-primary-text);
}

.ref-trigger:focus-visible {
  outline: none;
  box-shadow: var(--ss-ring);
}

.ref-icon {
  font-size: var(--ss-icon-xs);
}

.ref-label {
  font-weight: 550;
}

.ref-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 5px;
  border-radius: var(--ss-radius-pill);
  background: var(--ss-primary-soft);
  color: var(--ss-primary-text);
  font-size: 10px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.ref-caret {
  font-size: 10px;
  transition: transform var(--ss-dur) var(--ss-ease);
}

.ref-caret.open {
  transform: rotate(180deg);
}

/* ---------- 展开清单 ---------- */
.ref-panel {
  display: grid;
  grid-template-rows: 0fr;
  width: 100%;
  transition: grid-template-rows var(--ss-dur-slow) var(--ss-ease);
}

.ref-panel.open {
  grid-template-rows: 1fr;
}

.ref-panel-inner {
  overflow: hidden;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ref-item {
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 6px 10px;
  border-radius: var(--ss-radius);
  background: var(--ss-bg-subtle);
  border: 1px solid var(--ss-border-light);
  transition: var(--ss-transition);
}

.ref-item:hover {
  background: var(--ss-primary-softer);
  border-color: var(--ss-primary-border);
}

.ref-item-icon {
  flex: none;
  color: var(--ss-primary);
  font-size: var(--ss-icon-xs);
}

.ref-item-name {
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-secondary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

@media (prefers-reduced-motion: reduce) {
  .ref-panel {
    transition: none;
  }
}
</style>
