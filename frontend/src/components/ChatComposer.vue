<template>
  <!--
    聊天输入区：悬浮式圆角容器 + 发送按钮 + 底部提示。
    纯受控组件：v-model 绑定输入内容，事件交给父组件处理。
    Enter 发送 / Shift+Enter 换行的行为在此保持不变。
  -->
  <footer class="chat-input">
    <div class="composer-wrap">
      <!-- 悬浮圆角容器 -->
      <div class="input-shell" :class="{ 'input-shell--focused': focused }">
        <el-input
          :model-value="modelValue"
          type="textarea"
          :rows="1"
          resize="none"
          :autosize="{ minRows: 1, maxRows: 8 }"
          placeholder="请输入您的问题…"
          @update:model-value="onInput"
          @focus="focused = true"
          @blur="focused = false"
          @keydown.enter.exact.prevent="$emit('send')"
        />

        <div class="input-actions">
          <span class="input-kbd-hint">Enter 发送 · Shift+Enter 换行</span>
          <el-button
            type="primary"
            class="send-btn"
            :loading="loading"
            :disabled="!modelValue || !modelValue.trim()"
            circle
            @click="$emit('send')"
          >
            <el-icon v-if="!loading"><Promotion /></el-icon>
          </el-button>
        </div>
      </div>

      <p class="input-hint">回答由 AI 生成，订单与工单数据均来自实时业务库</p>
    </div>
  </footer>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'send'])

// 聚焦态：容器边框变为主色，用于视觉聚焦反馈
const focused = ref(false)

function onInput(val) {
  emit('update:modelValue', val)
}
</script>

<style scoped>
.chat-input {
  flex: none;
  padding: var(--ss-space-3) var(--ss-space-6) var(--ss-space-4);
  background: linear-gradient(to bottom, rgba(247, 248, 251, 0), var(--ss-bg) 42%);
}

.composer-wrap {
  max-width: var(--ss-content-max);
  margin: 0 auto;
}

/* ---------- 悬浮圆角容器 ---------- */
.input-shell {
  display: flex;
  align-items: flex-end;
  gap: var(--ss-space-3);
  padding: 10px 10px 10px var(--ss-space-4);
  border: 1px solid var(--ss-border);
  border-radius: var(--ss-radius-xl);
  background: var(--ss-bg-elevated);
  box-shadow: var(--ss-shadow);
  transition: border-color var(--ss-dur) var(--ss-ease), box-shadow var(--ss-dur) var(--ss-ease);
}

.input-shell:hover {
  border-color: var(--ss-border-strong);
}

.input-shell--focused {
  border-color: var(--ss-primary-border);
  box-shadow: var(--ss-shadow), var(--ss-ring-primary);
}

.input-shell :deep(.el-textarea) {
  flex: 1;
  min-width: 0;
}

.input-shell :deep(.el-textarea__inner) {
  background: transparent;
  border: none;
  box-shadow: none !important;
  padding: 4px 0;
  font-family: var(--ss-font);
  font-size: var(--ss-fs-base);
  line-height: 1.7;
  color: var(--ss-text);
  min-height: 26px !important;
}

.input-shell :deep(.el-textarea__inner::placeholder) {
  color: var(--ss-text-disabled);
}

/* ---------- 右侧操作区 ---------- */
.input-actions {
  display: flex;
  align-items: center;
  gap: var(--ss-space-3);
  flex: none;
  padding-bottom: 1px;
}

.input-kbd-hint {
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-disabled);
  white-space: nowrap;
}

.send-btn {
  width: 34px;
  height: 34px;
}

.send-btn :deep(.el-icon) {
  font-size: var(--ss-icon-md);
}

/* ---------- 底部提示 ---------- */
.input-hint {
  margin: var(--ss-space-2) 0 0;
  text-align: center;
  font-size: var(--ss-fs-xs);
  color: var(--ss-text-disabled);
}

@media (max-width: 720px) {
  .chat-input {
    padding-left: 16px;
    padding-right: 16px;
  }
  .input-kbd-hint {
    display: none;
  }
}
</style>
