<template>
  <!--
    区块标题行：序号徽标 / 图标 + 标题 + 右侧操作插槽。
    统一 KnowledgeView 的 .block-head 写法。
  -->
  <div class="ss-section-head">
    <span v-if="badge" class="ss-step-badge">{{ badge }}</span>
    <span v-else-if="icon" class="ss-icon-tile">
      <el-icon><component :is="icon" /></el-icon>
    </span>
    <span class="ss-card-title">{{ title }}</span>
    <span v-if="note" class="ss-section-note">{{ note }}</span>
    <slot name="actions" />
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  // 步骤序号（1/2/3…），传入后优先于 icon
  badge: { type: [Number, String], default: '' },
  // Element Plus 图标组件名
  icon: { type: String, default: '' },
  note: { type: String, default: '' },
})
</script>

<style scoped>
.ss-section-head {
  margin-bottom: 16px;
}

.head-action {
  margin-left: auto;
  font-weight: 500;
}
</style>
