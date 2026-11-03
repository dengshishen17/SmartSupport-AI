<template>
  <!--
    单条消息：用户 / 助手两种形态。
    助手消息包含三部分（顺序与原实现一致）：
      1. 工具调用卡片组（tools）
      2. 回答正文（content，纯文本）
      3. RAG 引用来源（sources）

    折叠状态由父组件通过 isToolOpen(msgIdx, toolIdx) 判定，
    切换由父组件处理——本组件不持有任何业务状态。

    时间戳：消息对象结构不变（仍是 {role, content, tools[], sources[]}），
    时间由父组件通过 timestamp prop 单独传入，避免改动消息对象结构。
  -->
  <div class="ss-msg" :class="`ss-msg--${m.role}`">
    <!-- ============ 助手消息 ============ -->
    <template v-if="m.role === 'assistant'">
      <span class="ss-avatar ss-avatar--assistant">
        <el-icon><Cpu /></el-icon>
      </span>

      <div class="ss-msg-body">
        <!-- 工具调用过程 -->
        <div v-if="m.tools && m.tools.length" class="tool-list">
          <ToolCallCard
            v-for="(t, ti) in m.tools"
            :key="ti"
            :tool="t"
            :open="isToolOpen(msgIdx, ti)"
            @toggle="$emit('toggle-tool', ti)"
          />
        </div>

        <!-- 回答正文 -->
        <div v-if="m.content" class="ss-bubble ss-bubble--assistant">
          {{ m.content }}<span v-if="streaming" class="ss-caret" />
        </div>

        <!-- RAG 引用来源 -->
        <SourceChips :sources="uniqueSources(m.sources)" />

        <!-- 时间戳 -->
        <span v-if="timestamp" class="ss-msg-meta">
          <el-icon><Clock /></el-icon>
          {{ timestamp }}
        </span>
      </div>
    </template>

    <!-- ============ 用户消息 ============ -->
    <template v-else>
      <div class="ss-msg-body ss-msg-body--user">
        <div class="ss-bubble ss-bubble--user">{{ m.content }}</div>
        <span v-if="timestamp" class="ss-msg-meta">
          <el-icon><Clock /></el-icon>
          {{ timestamp }}
        </span>
      </div>
      <span class="ss-avatar ss-avatar--user">
        <el-icon><User /></el-icon>
      </span>
    </template>
  </div>
</template>

<script setup>
import SourceChips from './SourceChips.vue'
import ToolCallCard from './ToolCallCard.vue'

defineProps({
  // 消息对象：{ role, content, tools[], sources[] }
  m: { type: Object, required: true },
  // 该消息在 messages 数组中的下标（用于工具折叠状态的 key）
  msgIdx: { type: Number, required: true },
  // 判断某个工具卡片是否展开
  isToolOpen: { type: Function, required: true },
  // 显示时间（HH:mm），由父组件传入
  timestamp: { type: String, default: '' },
  // 是否正在流式输出（显示闪烁光标）
  streaming: { type: Boolean, default: false },
})

defineEmits(['toggle-tool'])

/**
 * 后端 topK 可能召回同一文件的多个段落，来源去重后展示。
 * 与原 ChatView 中的 uniqueSources 行为完全一致。
 */
function uniqueSources(sources) {
  return [...new Set(sources || [])]
}
</script>

<style scoped>
.tool-list {
  display: flex;
  flex-direction: column;
  gap: var(--ss-space-2);
  margin-bottom: var(--ss-space-1);
}
</style>
