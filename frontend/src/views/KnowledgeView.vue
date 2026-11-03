<template>
  <div class="knowledge-page ss-scroll">
    <PageHeader
      title="知识库管理"
      subtitle="上传售后政策文档（.md / .txt），AI 回答时会自动检索这些内容"
    />

    <div class="content">
      <!-- ① 上传区 -->
      <section class="ss-card block">
        <SectionHeader title="上传知识文件" :badge="1" />

        <el-upload
          ref="uploadRef"
          :auto-upload="false"
          :show-file-list="true"
          :limit="1"
          accept=".md,.txt"
          :on-change="onFileChange"
          :on-exceed="onExceed"
          drag
          class="upload-dragger"
        >
          <div class="drag-inner">
            <IconTile icon="Upload" size="lg" />
            <p class="drag-title">将文件拖到此处，或<em>点击选择</em></p>
            <p class="drag-tip">仅支持 .md / .txt，单文件不超过 10MB；文档按 ## 标题切分段落</p>
          </div>
        </el-upload>

        <div class="upload-actions">
          <el-button type="primary" :loading="uploading" :disabled="!selectedFile" @click="doUpload">
            <el-icon><Upload /></el-icon>
            <span>上传并入库</span>
          </el-button>
          <span v-if="selectedFile" class="selected-file">
            已选择：{{ selectedFile.name }}
          </span>
        </div>
      </section>

      <!-- ② 已导入文件列表 -->
      <section class="ss-card block">
        <SectionHeader title="已导入知识" :badge="2">
          <template #actions>
            <el-button link type="primary" class="head-action" :loading="loadingFiles" @click="loadFiles">
              <el-icon><Refresh /></el-icon>
              <span>刷新</span>
            </el-button>
          </template>
        </SectionHeader>

        <el-table
          :data="files"
          v-loading="loadingFiles"
          size="default"
          empty-text="暂无知识文件，请先上传或调用 import-policy 导入"
          class="file-table"
        >
          <el-table-column label="文件名（来源）" min-width="240">
            <template #default="{ row }">
              <div class="file-cell">
                <IconTile icon="Document" size="sm" />
                <span class="file-name">{{ row.source }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="chunks" label="切分段落数" width="130" align="center">
            <template #default="{ row }">
              <span class="chunk-count">{{ row.chunks }}</span>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <!-- ③ 检索测试区 -->
      <section class="ss-card block">
        <SectionHeader title="检索测试" :badge="3" note="不经过大模型，直接查看 pgvector 召回结果" />

        <div class="search-row">
          <el-input
            v-model="query"
            placeholder="例如：拆封了还能退吗 / 退款多久到账"
            clearable
            @keyup.enter="doSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-button type="primary" :loading="searching" @click="doSearch">
            <el-icon><Search /></el-icon>
            <span>检索</span>
          </el-button>
        </div>

        <div v-if="results.length" class="search-results">
          <div v-for="(r, i) in results" :key="i" class="result-item">
            <div class="result-head">
              <span class="result-rank">#{{ i + 1 }}</span>
              <span class="result-source">
                <el-icon><Folder /></el-icon>
                {{ (r.metadata && r.metadata.source) || '未知来源' }}
              </span>
              <div class="score-meter">
                <el-progress
                  :percentage="scorePercent(r.score)"
                  :stroke-width="5"
                  :show-text="false"
                  color="var(--ss-primary)"
                />
                <span class="score-value">{{ formatScore(r.score) }}</span>
              </div>
            </div>
            <div class="result-content">{{ r.content }}</div>
          </div>
        </div>

        <EmptyState
          v-else-if="searched"
          icon="FolderOpened"
          title="没有召回任何段落"
          description="请确认知识已导入，或换一种表述再试"
        />
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listKnowledgeFiles, searchKnowledge, uploadKnowledge } from '../api/knowledge'
import EmptyState from '../components/EmptyState.vue'
import IconTile from '../components/IconTile.vue'
import PageHeader from '../components/PageHeader.vue'
import SectionHeader from '../components/SectionHeader.vue'

const uploadRef = ref()
const selectedFile = ref(null)

const uploading = ref(false)
const loadingFiles = ref(false)
const files = ref([])

const query = ref('')
const searching = ref(false)
const searched = ref(false)
const results = ref([])

// el-upload 选中文件（auto-upload=false，仅暂存）
function onFileChange(uploadFile) {
  selectedFile.value = uploadFile.raw
}

function onExceed() {
  ElMessage.warning('一次只能选择一个文件，请先移除已选文件')
}

async function doUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  try {
    const data = await uploadKnowledge(selectedFile.value)
    ElMessage.success(`上传成功：${data.fileName}，导入 ${data.imported} 个段落`)
    selectedFile.value = null
    uploadRef.value?.clearFiles()
    await loadFiles()
  } catch (e) {
    ElMessage.error('上传失败：' + (e.message || '未知错误'))
  } finally {
    uploading.value = false
  }
}

async function loadFiles() {
  loadingFiles.value = true
  try {
    files.value = await listKnowledgeFiles()
  } catch (e) {
    ElMessage.error('加载文件列表失败：' + (e.message || '未知错误'))
  } finally {
    loadingFiles.value = false
  }
}

async function doSearch() {
  const q = query.value.trim()
  if (!q) {
    ElMessage.warning('请输入要检索的问题')
    return
  }
  searching.value = true
  searched.value = false
  try {
    results.value = await searchKnowledge(q)
    searched.value = true
  } catch (e) {
    ElMessage.error('检索失败：' + (e.message || '未知错误'))
  } finally {
    searching.value = false
  }
}

// pgvector 余弦相似度，分数转百分比展示
function formatScore(score) {
  const n = Number(score)
  if (Number.isNaN(n)) return '--'
  return (n * 100).toFixed(1) + '%'
}

// 相似度进度条百分比（用于 el-progress，需要 0-100 的整数）
function scorePercent(score) {
  const n = Number(score)
  if (Number.isNaN(n)) return 0
  return Math.max(0, Math.min(100, Math.round(n * 100)))
}

onMounted(loadFiles)
</script>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--ss-bg);
}

.content {
  padding: 0 var(--ss-pad-page) var(--ss-pad-page);
  max-width: 940px;
  width: 100%;
  box-sizing: border-box;
  align-self: center;
}

/* ---------- 卡片 ---------- */
.block {
  padding: var(--ss-pad-card);
  margin-bottom: var(--ss-gap);
}

.head-action {
  margin-left: auto;
  font-weight: 500;
}

/* ---------- 上传 ---------- */
.upload-dragger :deep(.el-upload),
.upload-dragger :deep(.el-upload-dragger) {
  width: 100%;
}

.drag-inner {
  padding: var(--ss-space-8) var(--ss-space-5);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.drag-title {
  margin: var(--ss-space-3) 0 var(--ss-space-2);
  font-size: var(--ss-fs-base);
  color: var(--ss-text-secondary);
}

.drag-title em {
  font-style: normal;
  color: var(--ss-primary);
  font-weight: 600;
}

.drag-tip {
  margin: 0;
  font-size: var(--ss-fs-sm);
  color: var(--ss-text-tertiary);
}

.upload-actions {
  display: flex;
  align-items: center;
  gap: var(--ss-space-3);
  margin-top: var(--ss-gap);
}

.upload-actions .el-button {
  gap: 6px;
}

.selected-file {
  font-size: var(--ss-fs-sm);
  color: var(--ss-text-tertiary);
}

/* ---------- 文件列表 ---------- */
.file-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.file-cell {
  display: flex;
  align-items: center;
  gap: var(--ss-space-2);
}

.file-name {
  color: var(--ss-text);
}

.chunk-count {
  display: inline-block;
  min-width: 30px;
  padding: 1px 9px;
  border-radius: var(--ss-radius-pill);
  background: var(--ss-bg-hover);
  color: var(--ss-text-secondary);
  font-size: var(--ss-fs-sm);
  font-variant-numeric: tabular-nums;
}

/* ---------- 检索 ---------- */
.search-row {
  display: flex;
  gap: var(--ss-gap-sm);
}

.search-row .el-input {
  flex: 1;
}

.search-row .el-button {
  gap: 6px;
}

.search-results {
  margin-top: var(--ss-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--ss-gap-sm);
}

.result-item {
  padding: 13px 15px;
  border: 1px solid var(--ss-border);
  border-left: var(--ss-border-w-accent) solid var(--ss-primary);
  border-radius: var(--ss-radius);
  background: var(--ss-bg-subtle);
  transition: box-shadow var(--ss-dur) var(--ss-ease);
}
.result-item:hover {
  box-shadow: var(--ss-shadow-sm);
}

.result-head {
  display: flex;
  align-items: center;
  gap: var(--ss-space-3);
  margin-bottom: var(--ss-space-2);
}

.result-rank {
  font-size: var(--ss-fs-sm);
  font-weight: 650;
  color: var(--ss-primary);
  font-variant-numeric: tabular-nums;
}

.result-source {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--ss-fs-sm);
  color: var(--ss-text-secondary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.score-meter {
  display: flex;
  align-items: center;
  gap: var(--ss-space-2);
  margin-left: auto;
  flex: none;
  width: 180px;
}
.score-meter :deep(.el-progress) {
  flex: 1;
}

.score-value {
  font-size: var(--ss-fs-sm);
  font-weight: 600;
  color: var(--ss-primary);
  font-variant-numeric: tabular-nums;
  min-width: 46px;
  text-align: right;
}

.result-content {
  font-size: 13px;
  color: var(--ss-text-secondary);
  line-height: var(--ss-lh-relaxed);
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 720px) {
  .content {
    padding: 0 16px 24px;
  }
  .score-meter {
    width: 120px;
  }
}
</style>
