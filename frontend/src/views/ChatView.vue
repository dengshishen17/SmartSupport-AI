<template>
  <div class="chat-layout">
    <!-- ============ 中栏：对话主区 ============ -->
    <section class="chat-main">
      <AppHeader title="智能售后客服" subtitle="基于企业售后政策库与实时业务数据解答">
        <template #lead>
          <span class="header-avatar">
            <el-icon><Cpu /></el-icon>
          </span>
        </template>
        <template #actions>
          <span class="session-id" v-if="currentSessionId">
            <el-icon><Position /></el-icon>
            会话 {{ shortSessionId }}
          </span>
          <!-- 小屏下用抽屉承载上下文面板 -->
          <el-button
            v-if="isNarrow"
            class="panel-open-btn"
            text
            @click="panelDrawer = true"
          >
            <el-icon><InfoFilled /></el-icon>
            <span>上下文</span>
          </el-button>
        </template>
      </AppHeader>

      <!-- 消息区 -->
      <ChatMessageList
        ref="listRef"
        :messages="messages"
        :is-welcome="isWelcome"
        :welcome-title="WELCOME_TITLE"
        :welcome-desc="WELCOME_DESC"
        :tags="CAPABILITY_TAGS"
        :suggestions="SUGGESTIONS"
        :timestamps="timestamps"
        :streaming-index="streamingIndex"
        :is-waiting-first-chunk="isWaitingFirstChunk"
        :is-tool-open="isToolOpen"
        @use-suggestion="useSuggestion"
        @toggle-tool="toggleTool"
      />

      <!-- 输入区 -->
      <ChatComposer
        v-model="input"
        :loading="loading"
        @send="send"
      />
    </section>

    <!-- ============ 右栏：上下文面板（宽屏） ============ -->
    <ChatContextPanel
      v-if="!isNarrow"
      class="chat-panel"
      :collapsed="panelCollapsed"
      :messages="messages"
      :session-id="currentSessionId"
      @toggle-collapse="panelCollapsed = !panelCollapsed"
    />

    <!-- ============ 右栏：上下文抽屉（小屏） ============ -->
    <el-drawer
      v-if="isNarrow"
      v-model="panelDrawer"
      title="上下文"
      direction="rtl"
      size="320px"
      :with-header="true"
    >
      <ChatContextPanel
        :collapsed="false"
        :messages="messages"
        :session-id="currentSessionId"
      />
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { knowledgeChatStream } from '../api/chat'
import AppHeader from '../components/AppHeader.vue'
import ChatComposer from '../components/ChatComposer.vue'
import ChatContextPanel from '../components/ChatContextPanel.vue'
import ChatMessageList from '../components/ChatMessageList.vue'

// 工具内部名 → 中文展示名（与后端 @Tool name 对应）
const TOOL_LABELS = {
  queryOrderByOrderNo: '查询订单',
  queryRefundByOrderNo: '查询退款记录',
  queryTicketByOrderNo: '查询售后工单',
}

const GREETING = '您好，我是 SmartSupport 智能客服助手。可以帮您查询订单进度、解答售后政策问题，请描述您的问题~'

// 欢迎态文案（展示用，与 isWelcome 判定用的 GREETING 相互独立）
const WELCOME_TITLE = '您好，我是 SmartSupport 智能客服助手'
const WELCOME_DESC = '可以帮您查询订单进度、退款与工单状态，也能解答售后政策问题。请描述您的问题~'

// 欢迎态能力标签（纯展示，帮助用户理解 AI 能做什么）
const CAPABILITY_TAGS = [
  { label: '订单查询', icon: 'Box' },
  { label: '退款进度', icon: 'Wallet' },
  { label: '售后政策', icon: 'Reading' },
  { label: '工单跟踪', icon: 'Tickets' },
]

// 欢迎态推荐问题：2×2 卡片，q 为实际发送内容，label 为卡片标题
const SUGGESTIONS = [
  { q: '什么情况下可以申请退款', label: '退款条件', icon: 'Wallet', tone: 'warning' },
  { q: '退货的运费由谁承担', label: '运费承担', icon: 'Van', tone: 'primary' },
  { q: '快递长时间没有更新应该怎么办', label: '物流停滞', icon: 'Clock', tone: 'danger' },
  { q: '家电类商品保修多长时间', label: '保修期限', icon: 'Reading', tone: 'success' },
]

// localStorage 键：会话列表 + 当前会话 ID
const STORE_KEY = 'smartsupport.chat.sessions'
const CURRENT_KEY = 'smartsupport.chat.current'

const messages = ref([{ role: 'assistant', content: GREETING }])
const input = ref('')
const loading = ref(false)
// 多轮对话的钥匙：首次请求后端返回 sessionId，之后每次请求原样带回
const currentSessionId = ref('')
// 历史会话列表（本地保存，含完整聊天记录，便于点击回看）
const sessions = ref([])
const listRef = ref(null)

// 工具调用结果默认展开状态：key = `${消息序号}-${工具序号}`
const openedTools = ref(new Set())

// 时间戳数组：与 messages 平行存放，不改动消息对象结构
const timestamps = ref([])
// 正在流式输出的消息下标（-1 表示无）
const streamingIndex = ref(-1)

// 右侧上下文面板：折叠状态 / 小屏抽屉开关
const panelCollapsed = ref(false)
const panelDrawer = ref(false)
// 是否为窄屏（窄屏时右侧栏改为抽屉）
const isNarrow = ref(false)

/**
 * 与左侧栏的共享通道（由 App.vue provide）。
 * 会话数据仍由本组件持有，这里只把列表同步过去并注册动作回调，
 * 让左侧栏的 SessionList 触发同样的行为，不改动任何业务逻辑。
 */
const chatContext = inject('chatContext', null)

watch(
  () => [sessions.value, currentSessionId.value],
  () => {
    if (!chatContext) return
    chatContext.sessions = sessions.value
    chatContext.currentSessionId = currentSessionId.value
  },
  { immediate: true, deep: true }
)

if (chatContext) {
  chatContext.onNew = () => newSession()
  chatContext.onSwitch = (id) => switchSession(id)
  chatContext.onDelete = (id) => deleteSession(id)
}

const shortSessionId = computed(() =>
  currentSessionId.value ? currentSessionId.value.slice(0, 8) + '...' : '未开始'
)

// 是否处于欢迎态（还没有真正开始对话）
const isWelcome = computed(() => {
  if (messages.value.length !== 1) return false
  const only = messages.value[0]
  return only && only.role === 'assistant' && only.content.includes(GREETING)
})

// 流式等待第一个 chunk 时显示"正在输入..."；
// 收到内容、或正在执行工具（已有工具卡片展示）时隐藏
const isWaitingFirstChunk = computed(() => {
  if (!loading.value) return false
  const last = messages.value[messages.value.length - 1]
  return last && last.role === 'assistant' && !last.content && (!last.tools || last.tools.length === 0)
})

// 工具结果折叠 / 展开
function toolKey(msgIdx, toolIdx) {
  return `${msgIdx}-${toolIdx}`
}
function isToolOpen(msgIdx, toolIdx) {
  return openedTools.value.has(toolKey(msgIdx, toolIdx))
}
function toggleTool(msgIdx, toolIdx) {
  const key = toolKey(msgIdx, toolIdx)
  const next = new Set(openedTools.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  openedTools.value = next
}

// 点击推荐问题：填入输入框并直接发送
function useSuggestion(q) {
  if (loading.value) return
  input.value = q
  send()
}

/* ---------- 窄屏检测 ---------- */
function updateViewport() {
  isNarrow.value = window.innerWidth < 1180
}
onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
})
onUnmounted(() => {
  window.removeEventListener('resize', updateViewport)
})

/* ---------- 本地存储读写 ---------- */
function loadStore() {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY)) || []
  } catch {
    return []
  }
}
function saveStore(list) {
  localStorage.setItem(STORE_KEY, JSON.stringify(list))
}

/**
 * 把「当前会话」落盘：以首条用户消息前 20 字作为标题，
 * 整段聊天记录一起存进 localStorage，方便下次点击回看。
 * 只有真正发过消息（存在 user 消息）的会话才保存，避免空会话占位。
 */
function persistCurrent() {
  const userMsgs = messages.value.filter((m) => m.role === 'user')
  if (!currentSessionId.value || userMsgs.length === 0) return
  const title = userMsgs[0].content.slice(0, 20)
  const list = sessions.value.filter((s) => s.sessionId !== currentSessionId.value)
  list.unshift({
    sessionId: currentSessionId.value,
    title,
    messages: [...messages.value],
    timestamps: [...timestamps.value],
    updatedAt: Date.now(),
  })
  list.sort((a, b) => b.updatedAt - a.updatedAt)
  sessions.value = list
  saveStore(list)
  localStorage.setItem(CURRENT_KEY, currentSessionId.value)
}

/* ---------- 交互 ---------- */
async function scrollToBottom() {
  await nextTick()
  // ChatMessageList 通过 defineExpose 暴露了内部滚动容器 listEl
  const el = listRef.value?.listEl
  if (el) el.scrollTop = el.scrollHeight
}

/** 当前时间 HH:mm */
function nowLabel() {
  const d = new Date()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

async function send() {
  const text = input.value.trim()
  if (!text || loading.value) return
  messages.value.push({ role: 'user', content: text })
  timestamps.value.push(nowLabel())
  input.value = ''
  // push 空 assistant 消息：content 逐字追加，tools 记录工具调用过程，sources 记录引用来源
  messages.value.push({ role: 'assistant', content: '', tools: [], sources: [] })
  const replyIndex = messages.value.length - 1
  timestamps.value.push('')
  streamingIndex.value = replyIndex
  loading.value = true
  scrollToBottom()

  // 节流保存：避免流式过程中频繁写 localStorage
  let lastSaveTs = 0
  let chunkCount = 0

  await knowledgeChatStream(text, currentSessionId.value, {
    onContent(delta) {
      // 用数组索引访问 reactive 代理，赋值才会触发 UI 响应式更新（逐字刷新）
      messages.value[replyIndex].content += delta
      chunkCount++
      const now = Date.now()
      // 每 800ms 或每 30 个 chunk 落盘一次，防止刷新丢历史
      if (now - lastSaveTs > 800 || chunkCount % 30 === 0) {
        lastSaveTs = now
        persistCurrent()
      }
      scrollToBottom()
    },
    onReference(rag, sources) {
      messages.value[replyIndex].sources = sources
    },
    onTool(stage, toolName, payload) {
      const reply = messages.value[replyIndex]
      if (stage === 'start') {
        // 新工具调用：状态 running，展示"正在查询..."
        reply.tools.push({
          name: toolName,
          label: TOOL_LABELS[toolName] || toolName,
          args: payload,
          status: 'running',
          result: '',
        })
      } else if (stage === 'result') {
        // 配对同名、仍在 running 的最后一次调用，标记完成并填结果
        const target = [...reply.tools].reverse().find((t) => t.name === toolName && t.status === 'running')
        if (target) {
          target.status = 'done'
          target.result = payload.result || ''
        }
      }
      scrollToBottom()
    },
    onDone(sessionId) {
      if (sessionId) currentSessionId.value = sessionId
      // 回答完成，给这条消息打上时间戳
      timestamps.value[replyIndex] = nowLabel()
      streamingIndex.value = -1
      // 流结束后落盘当前会话
      persistCurrent()
      loading.value = false
      scrollToBottom()
    },
    onError(message) {
      // 后端已把网络类异常翻译成中文提示；这里再兜底一层，
      // 避免把 "Connection reset" 这类底层网络术语直接展示给用户。
      const text = String(message || '未知错误')
      const friendly = /connection reset|network error|failed to fetch|socket|ECONNRESET|Load failed/i
        .test(text)
        ? '网络连接不稳定，请稍后重试'
        : text
      ElMessage.error('AI 回答出错：' + friendly)
      const reply = messages.value[replyIndex]
      // 如果一个字都没收到、也没工具调用，删掉占位的空 assistant 消息
      if (!reply.content && reply.tools.length === 0) {
        messages.value = messages.value.filter((_, i) => i !== replyIndex)
        timestamps.value = timestamps.value.filter((_, i) => i !== replyIndex)
        if (streamingIndex.value === replyIndex) streamingIndex.value = -1
      }
      // 流中断也保存一次，避免已收到的部分内容丢失
      persistCurrent()
      loading.value = false
      scrollToBottom()
    },
  })
}

function newSession() {
  persistCurrent()
  currentSessionId.value = ''
  localStorage.removeItem(CURRENT_KEY)
  messages.value = [{ role: 'assistant', content: '已开启新会话。' + GREETING }]
  timestamps.value = ['']
  input.value = ''
  streamingIndex.value = -1
  scrollToBottom()
}

function switchSession(sessionId) {
  if (sessionId === currentSessionId.value) return
  persistCurrent()
  const found = sessions.value.find((s) => s.sessionId === sessionId)
  if (!found) return
  currentSessionId.value = sessionId
  messages.value = [...found.messages]
  // 老版本落盘的会话没有 timestamps 字段，用空数组补齐，保证下标对齐
  timestamps.value = Array.isArray(found.timestamps) ? [...found.timestamps] : []
  localStorage.setItem(CURRENT_KEY, sessionId)
  streamingIndex.value = -1
  scrollToBottom()
}

function deleteSession(sessionId) {
  const list = sessions.value.filter((s) => s.sessionId !== sessionId)
  sessions.value = list
  saveStore(list)
  if (sessionId === currentSessionId.value) {
    currentSessionId.value = ''
    localStorage.removeItem(CURRENT_KEY)
    messages.value = [{ role: 'assistant', content: GREETING }]
    timestamps.value = ['']
    streamingIndex.value = -1
  }
}

/* ---------- 初始化：恢复上次会话 ---------- */
onMounted(() => {
  sessions.value = loadStore()
  const cur = localStorage.getItem(CURRENT_KEY)
  const found = sessions.value.find((s) => s.sessionId === cur)
  if (found) {
    currentSessionId.value = found.sessionId
    messages.value = [...found.messages]
    timestamps.value = Array.isArray(found.timestamps) ? [...found.timestamps] : []
    scrollToBottom()
  }
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100%;
  min-height: 0;
  background: var(--ss-bg);
}

/* ---------- 中栏 ---------- */
.chat-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--ss-bg);
}

.header-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex: none;
  border-radius: var(--ss-radius);
  background: var(--ss-primary-soft);
  color: var(--ss-primary);
  font-size: var(--ss-icon-md);
}

.session-id {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--ss-fs-sm);
  color: var(--ss-text-tertiary);
  padding: 4px 11px;
  border-radius: var(--ss-radius-pill);
  background: var(--ss-bg-hover);
}

.panel-open-btn {
  gap: 5px;
}
</style>
