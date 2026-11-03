<template>
  <!--
    消息流容器：欢迎态 + 消息列表 + 首 chunk 等待动画。
    滚动容器由父组件通过 ref 持有（父组件负责 scrollToBottom），
    因此这里通过 expose 暴露 scroll 元素给父组件绑定。
  -->
  <div class="chat-list" ref="listEl">
    <!-- 欢迎态：仅有一条欢迎语时展示 -->
    <ChatWelcome
      v-if="isWelcome"
      :title="welcomeTitle"
      :description="welcomeDesc"
      :tags="tags"
      :suggestions="suggestions"
      @use-suggestion="$emit('use-suggestion', $event)"
    />

    <!-- 消息列表 -->
    <template v-else>
      <ChatMessageItem
        v-for="(m, i) in messages"
        :key="i"
        :m="m"
        :msg-idx="i"
        :is-tool-open="isToolOpen"
        :timestamp="timestamps[i] || ''"
        :streaming="isStreaming(i)"
        @toggle-tool="(ti) => $emit('toggle-tool', i, ti)"
      />
    </template>

    <!-- 等待首个 chunk -->
    <div v-if="isWaitingFirstChunk" class="ss-msg ss-msg--assistant">
      <span class="ss-avatar ss-avatar--assistant">
        <el-icon><Cpu /></el-icon>
      </span>
      <div class="ss-msg-body">
        <div class="ss-bubble ss-bubble--assistant ss-bubble--loading">
          <span class="ss-typing-dot"></span>
          <span class="ss-typing-dot"></span>
          <span class="ss-typing-dot"></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import ChatMessageItem from './ChatMessageItem.vue'
import ChatWelcome from './ChatWelcome.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  isWelcome: { type: Boolean, default: false },
  welcomeTitle: { type: String, default: '' },
  welcomeDesc: { type: String, default: '' },
  // 能力标签：[{ label, icon }]
  tags: { type: Array, default: () => [] },
  // 快捷提问：[{ q, label, icon, tone }]
  suggestions: { type: Array, default: () => [] },
  isWaitingFirstChunk: { type: Boolean, default: false },
  isToolOpen: { type: Function, required: true },
  // 与 messages 等长的时间戳数组（与消息对象分开存储，不改动消息结构）
  timestamps: { type: Array, default: () => [] },
  // 正在流式输出的消息下标
  streamingIndex: { type: Number, default: -1 },
})

defineEmits(['use-suggestion', 'toggle-tool'])

// 暴露滚动容器元素给父组件，用于 scrollToBottom
const listEl = ref(null)
defineExpose({ listEl })

// 该消息是否处于流式输出中（显示闪烁光标）
function isStreaming(idx) {
  return props.streamingIndex === idx
}
</script>

<style scoped>
.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--ss-space-8) 0 var(--ss-space-5);
}

@media (max-width: 720px) {
  .chat-list {
    padding-top: var(--ss-space-5);
  }
}
</style>
