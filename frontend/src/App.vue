<template>
  <div class="app-shell">
    <!-- 左侧栏：品牌 + 主导航 +（聊天页）历史会话 + 底部状态 -->
    <AppSidebar :items="NAV_ITEMS" :active-tab="activeTab" @update:active-tab="activeTab = $event">
      <!-- 聊天页专属：历史会话列表 -->
      <template v-if="activeTab === 'chat'" #extra>
        <SessionList
          :sessions="chatContext.sessions"
          :current-session-id="chatContext.currentSessionId"
          @new-session="chatContext.onNew && chatContext.onNew()"
          @switch-session="(id) => chatContext.onSwitch && chatContext.onSwitch(id)"
          @delete-session="(id) => chatContext.onDelete && chatContext.onDelete(id)"
        />
      </template>
    </AppSidebar>

    <main class="app-content">
      <ChatView v-if="activeTab === 'chat'" />
      <KnowledgeView v-else-if="activeTab === 'knowledge'" />
      <TicketView v-else />
    </main>
  </div>
</template>

<script setup>
import { reactive, provide, ref } from 'vue'
import AppSidebar from './components/AppSidebar.vue'
import SessionList from './components/SessionList.vue'
import ChatView from './views/ChatView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import TicketView from './views/TicketView.vue'

// 导航项配置：图标名对应 @element-plus/icons-vue 全局注册的组件名
const NAV_ITEMS = [
  { key: 'chat', label: '智能客服', icon: 'ChatDotRound' },
  { key: 'knowledge', label: '知识库管理', icon: 'Collection' },
  { key: 'ticket', label: '售后工单', icon: 'Tickets' },
]

const activeTab = ref('chat')

/**
 * 聊天页与左侧栏之间的共享通道。
 *
 * 会话数据本身仍由 ChatView 持有（业务逻辑不搬走），这里只做一层桥接：
 * ChatView 把会话列表同步进来，并注册三个动作回调，
 * App.vue 侧的 SessionList 通过它触发同样的行为。
 */
const chatContext = reactive({
  sessions: [],
  currentSessionId: '',
  onNew: null,
  onSwitch: null,
  onDelete: null,
})

provide('chatContext', chatContext)
</script>

<style scoped>
.app-shell {
  display: flex;
  height: 100vh;
  background: var(--ss-bg);
}

.app-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
</style>
