<template>
  <div class="ticket-page ss-scroll">
    <PageHeader title="售后工单" subtitle="客服确认客户诉求后创建工单，跟踪售后处理进度">
      <template #actions>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          <span>新建工单</span>
        </el-button>
      </template>
    </PageHeader>

    <div class="content">
      <section class="ss-card table-card">
        <!-- 统计概览 -->
        <div class="stat-row">
          <StatCard :value="tickets.length" label="工单总数" icon="Tickets" tone="neutral" />
          <StatCard
            :value="countByStatus('待处理')"
            label="待处理"
            icon="Clock"
            tone="primary"
          />
          <StatCard
            :value="countByStatus('处理中')"
            label="处理中"
            icon="Loading"
            tone="warning"
          />
          <StatCard
            :value="countByStatus('已完成')"
            label="已完成"
            icon="CircleCheck"
            tone="success"
          />
        </div>

        <el-table
          :data="tickets"
          v-loading="loading"
          stripe
          empty-text="暂无工单，点击右上角新建"
          class="ticket-table"
        >
          <el-table-column prop="id" label="工单号" width="90">
            <template #default="{ row }">
              <span class="ticket-id">#{{ row.id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="orderNo" label="订单编号" width="120">
            <template #default="{ row }">
              <span class="order-no">{{ row.orderNo }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="problemType" label="问题类型" width="130">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="problemTypeTag(row.problemType)">
                {{ row.problemType }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="问题描述" min-width="200" show-overflow-tooltip />
          <el-table-column prop="solution" label="处理方案" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="createTime" label="创建时间" width="180">
            <template #default="{ row }">
              <span class="create-time">{{ formatTime(row.createTime) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <!-- 新建工单抽屉 -->
    <el-drawer v-model="dialogVisible" title="新建售后工单" size="460px" @closed="resetForm">
      <p class="drawer-sub">填写工单信息后可同步 AI 客服给出的处理建议</p>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="ticket-form">
        <el-form-item label="订单编号" prop="orderNo">
          <el-input v-model="form.orderNo" placeholder="例如：10001" />
        </el-form-item>
        <el-form-item label="问题类型" prop="problemType">
          <el-select v-model="form.problemType" placeholder="请选择" style="width: 100%">
            <el-option v-for="t in problemTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="问题描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="客户遇到的具体问题"
          />
        </el-form-item>
        <el-form-item label="处理方案" prop="solution">
          <el-input
            v-model="form.solution"
            type="textarea"
            :rows="3"
            placeholder="可参考 AI 客服给出的处理建议"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="doCreate">
          <el-icon><CircleCheck /></el-icon>
          <span>提交工单</span>
        </el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createTicket, listTickets } from '../api/ticket'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'

const loading = ref(false)
const tickets = ref([])

const dialogVisible = ref(false)
const submitting = ref(false)
const formRef = ref()

// 与需求文档示例对齐：售后类型如"商品质量问题"
const problemTypes = ['商品质量问题', '物流问题', '退款问题', '换货需求', '其他']

const defaultForm = () => ({ orderNo: '', problemType: '', description: '', solution: '' })
const form = reactive(defaultForm())

const rules = {
  orderNo: [{ required: true, message: '请输入订单编号', trigger: 'blur' }],
  problemType: [{ required: true, message: '请选择问题类型', trigger: 'change' }],
  description: [{ required: true, message: '请输入问题描述', trigger: 'blur' }],
}

// 各状态工单数量
function countByStatus(status) {
  return tickets.value.filter((t) => t.status === status).length
}

async function loadTickets() {
  loading.value = true
  try {
    tickets.value = await listTickets()
  } catch (e) {
    ElMessage.error('加载工单失败：' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialogVisible.value = true
}

function resetForm() {
  Object.assign(form, defaultForm())
  formRef.value?.clearValidate()
}

async function doCreate() {
  await formRef.value.validate()
  submitting.value = true
  try {
    await createTicket({ ...form })
    ElMessage.success('工单创建成功（状态：待处理）')
    dialogVisible.value = false
    await loadTickets()
  } catch (e) {
    ElMessage.error('创建失败：' + (e.message || '未知错误'))
  } finally {
    submitting.value = false
  }
}

// 待处理/处理中/已完成 → 标签颜色
function statusType(status) {
  if (status === '已完成') return 'success'
  if (status === '处理中') return 'warning'
  return 'info'
}

// 问题类型 → 标签颜色
function problemTypeTag(type) {
  if (type === '商品质量问题') return 'danger'
  if (type === '物流问题') return 'warning'
  if (type === '退款问题') return 'primary'
  if (type === '换货需求') return 'success'
  return 'info'
}

// 后端返回 LocalDateTime 数组或 ISO 字符串，统一展示为 yyyy-MM-dd HH:mm
function formatTime(t) {
  if (!t) return ''
  if (Array.isArray(t)) {
    const [y, mo, d, h, mi] = t
    const pad = (n) => String(n).padStart(2, '0')
    return `${y}-${pad(mo)}-${pad(d)} ${pad(h)}:${pad(mi)}`
  }
  return String(t).replace('T', ' ').slice(0, 16)
}

onMounted(loadTickets)
</script>

<style scoped>
.ticket-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--ss-bg);
}

.content {
  padding: 0 var(--ss-pad-page) var(--ss-pad-page);
}

.table-card {
  padding: 0;
  overflow: hidden;
}

/* ---------- 统计概览 ---------- */
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--ss-gap);
  padding: var(--ss-space-5) var(--ss-space-6);
  border-bottom: 1px solid var(--ss-border);
}

/* ---------- 表格 ---------- */
.ticket-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.ticket-id {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ss-text-tertiary);
  font-variant-numeric: tabular-nums;
}

.order-no {
  font-family: var(--ss-font-mono);
  font-size: 12.5px;
  color: var(--ss-text-secondary);
}

.create-time {
  font-size: 12.5px;
  color: var(--ss-text-tertiary);
  font-variant-numeric: tabular-nums;
}

/* ---------- 抽屉 ---------- */
.drawer-sub {
  margin: -8px 0 var(--ss-space-5);
  font-size: var(--ss-fs-base);
  color: var(--ss-text-tertiary);
}

.ticket-form :deep(.el-form-item__label) {
  font-size: 13px;
  font-weight: 550;
  color: var(--ss-text-secondary);
  padding-bottom: 6px;
}

@media (max-width: 720px) {
  .content {
    padding-left: 16px;
    padding-right: 16px;
  }
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--ss-space-3);
    padding: var(--ss-space-4);
  }
}
</style>
