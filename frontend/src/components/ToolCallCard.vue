<template>
  <!--
    工具调用卡片：展示 AI 调用的后端查询工具（订单 / 退款 / 工单）。
    纯展示组件，展开状态由父组件通过 open prop 控制，
    折叠/展开由父组件触发 toggle 事件——保持原有交互行为不变。

    三种工具用不同图标与色调区分：
      queryOrderByOrderNo    订单 → 主色
      queryRefundByOrderNo   退款 → 警告色
      queryTicketByOrderNo   工单 → 成功色
  -->
  <div class="tool-card" :class="[`tool-card--${tone}`, { 'tool-card--open': open }]">
    <!-- ===== 卡片头：点击展开/折叠 ===== -->
    <button type="button" class="tool-head" @click="$emit('toggle')">
      <span class="tool-icon" :class="tool.status">
        <el-icon v-if="tool.status === 'running'"><Loading /></el-icon>
        <el-icon v-else><component :is="toolIcon" /></el-icon>
      </span>

      <span class="tool-label">{{ tool.label }}</span>

      <span v-if="tool.args && tool.args.orderNo" class="tool-args">
        <span class="tool-args-label">订单号</span>
        <span class="tool-args-value">{{ tool.args.orderNo }}</span>
      </span>

      <span v-if="tool.status === 'running'" class="tool-running">
        <span class="tool-spinner"></span>
        查询中
      </span>

      <span v-else class="tool-caret" :class="{ open }">
        <el-icon><ArrowDown /></el-icon>
      </span>
    </button>

    <!-- ===== 展开体：真实查询结果 ===== -->
    <div v-if="tool.result" class="tool-panel" :class="{ open }">
      <div class="tool-panel-inner">
        <p class="tool-panel-title">查询结果</p>
        <p class="tool-result">{{ tool.result }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // 工具对象：{ name, label, args, status: 'running'|'done', result }
  tool: { type: Object, required: true },
  // 当前是否展开
  open: { type: Boolean, default: false },
})

defineEmits(['toggle'])

/** 工具名 → 图标，与后端 @Tool name 对应 */
const TOOL_ICONS = {
  queryOrderByOrderNo: 'Box',
  queryRefundByOrderNo: 'Wallet',
  queryTicketByOrderNo: 'Tickets',
}

/** 工具名 → 色调 */
const TOOL_TONES = {
  queryOrderByOrderNo: 'primary',
  queryRefundByOrderNo: 'warning',
  queryTicketByOrderNo: 'success',
}

const toolIcon = computed(() => TOOL_ICONS[props.tool.name] || 'Tools')
const tone = computed(() => TOOL_TONES[props.tool.name] || 'neutral')
</script>

<style scoped>
.tool-card {
  border: 1px solid var(--ss-border);
  border-radius: var(--ss-radius-lg);
  background: var(--ss-bg-elevated);
  overflow: hidden;
  box-shadow: var(--ss-shadow-xs);
  transition: var(--ss-transition);
}

.tool-card:hover {
  border-color: var(--ss-border-strong);
  box-shadow: var(--ss-shadow-sm);
}

/* 展开时左边缘出现色调标识 */
.tool-card--open {
  box-shadow: var(--ss-shadow-sm);
}

.tool-card--primary {
  border-left: 3px solid var(--ss-primary);
}

.tool-card--warning {
  border-left: 3px solid var(--ss-warning);
}

.tool-card--success {
  border-left: 3px solid var(--ss-success);
}

.tool-card--neutral {
  border-left: 3px solid var(--ss-border-strong);
}

/* ---------- 卡片头 ---------- */
.tool-head {
  display: flex;
  align-items: center;
  gap: var(--ss-space-2);
  width: 100%;
  padding: 10px 13px;
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: var(--ss-fs-sm);
  color: var(--ss-text);
  cursor: pointer;
  text-align: left;
  transition: background var(--ss-dur-fast) var(--ss-ease);
}

.tool-head:hover {
  background: var(--ss-bg-subtle);
}

.tool-head:focus-visible {
  outline: none;
  box-shadow: var(--ss-ring);
}

/* ---------- 图标 ---------- */
.tool-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: var(--ss-radius-sm);
  font-size: var(--ss-icon-sm);
}

.tool-icon.running {
  background: var(--ss-warning-soft);
  color: var(--ss-warning);
}

.tool-icon.done {
  background: var(--ss-primary-soft);
  color: var(--ss-primary);
}

.tool-card--warning .tool-icon.done {
  background: var(--ss-warning-soft);
  color: var(--ss-warning);
}

.tool-card--success .tool-icon.done {
  background: var(--ss-success-soft);
  color: var(--ss-success);
}

.tool-icon.running .el-icon {
  animation: ss-rotate 1.1s linear infinite;
}

@keyframes ss-rotate {
  to {
    transform: rotate(360deg);
  }
}

/* ---------- 文本 ---------- */
.tool-label {
  font-weight: 600;
  color: var(--ss-text);
  white-space: nowrap;
}

.tool-args {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: var(--ss-radius-pill);
  background: var(--ss-bg-hover);
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-tertiary);
}

.tool-args-label {
  opacity: 0.75;
}

.tool-args-value {
  font-family: var(--ss-font-mono);
  font-weight: 600;
  color: var(--ss-text-secondary);
}

.tool-running {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ss-warning);
  font-size: var(--ss-fs-xs);
  font-weight: 500;
}

.tool-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid var(--ss-warning-soft);
  border-top-color: var(--ss-warning);
  border-radius: 50%;
  animation: ss-rotate 0.8s linear infinite;
}

.tool-caret {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: none;
  border-radius: var(--ss-radius-sm);
  background: var(--ss-bg-hover);
  color: var(--ss-text-tertiary);
  font-size: var(--ss-icon-xs);
  transition: transform var(--ss-dur) var(--ss-ease), background var(--ss-dur) var(--ss-ease);
}

.tool-caret:hover {
  background: var(--ss-bg-active);
}

.tool-caret.open {
  transform: rotate(180deg);
  background: var(--ss-primary-soft);
  color: var(--ss-primary);
}

/* ---------- 展开体 ---------- */
.tool-panel {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows var(--ss-dur-slow) var(--ss-ease);
}

.tool-panel.open {
  grid-template-rows: 1fr;
}

.tool-panel-inner {
  overflow: hidden;
  min-height: 0;
}

.tool-panel-title {
  margin: 0;
  padding: 10px 13px 0;
  font-size: var(--ss-fs-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ss-text-tertiary);
  text-transform: uppercase;
}

.tool-result {
  margin: 0;
  padding: 6px 13px 12px;
  font-size: var(--ss-fs-sm);
  line-height: var(--ss-lh-relaxed);
  color: var(--ss-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

@media (prefers-reduced-motion: reduce) {
  .tool-panel {
    transition: none;
  }
}
</style>
