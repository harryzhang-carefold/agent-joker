<template>
  <div class="page" v-loading="kbLoading">
    <div class="toolbar" style="margin-bottom:8px">
      <el-button @click="back"><el-icon><ArrowLeft /></el-icon> 知识库列表</el-button>
      <span v-if="kb" class="flex-1">
        <b>{{ kb.name }}</b>
        <el-tag :type="kb.tag === 'official' ? 'warning' : 'info'" size="small" style="margin-left:8px">{{ kb.tag || '非官方' }}</el-tag>
        <span class="text-muted mono" style="margin-left:8px">{{ kb.vec_table }} · dim {{ kb.embedding_dim }} · {{ kb.status }}</span>
      </span>
    </div>

    <div class="toolbar">
      <el-upload :show-file-list="false" :before-upload="onUpload"
        accept=".txt,.md,.docx,.xlsx,.pdf,.png,.jpg" :disabled="!!uploadingDoc">
        <el-button type="primary" :loading="!!uploadingDoc"><el-icon><Upload /></el-icon> 上传文档</el-button>
      </el-upload>
      <el-select v-model="docStatus" clearable placeholder="状态" style="width:140px" @change="loadDocs">
        <el-option v-for="s in ['uploaded','parsing','splitting','embedded','ready','failed']" :key="s" :label="s" :value="s" />
      </el-select>
      <el-button @click="loadDocs"><el-icon><Refresh /></el-icon> 刷新</el-button>
      <span class="text-muted">文档状态机: uploaded→parsing→splitting→embedded→ready / failed</span>
    </div>

    <el-table :data="docs" v-loading="loading" stripe border>
      <el-table-column prop="file_name" label="文件名" min-width="220" />
      <el-table-column prop="doc_type" label="类型" width="90" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="parse_method" label="解析方式" width="110" />
      <el-table-column prop="chunk_count" label="chunk 数" width="90" />
      <el-table-column label="切分策略" width="130">
        <template #default="{ row }">{{ strategyLabel(row.split_strategy) }}</template>
      </el-table-column>
      <el-table-column label="tag (D-A)" width="100">
        <template #default="{ row }">
          <el-tag :type="row.tag === 'official' ? 'warning' : 'info'" size="small">{{ row.tag || '继承库级' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="错误" min-width="160">
        <template #default="{ row }">
          <span class="mono text-muted" :title="row.error_message">{{ row.error_message || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="goCompare(row)" :disabled="row.status !== 'ready' && row.status !== 'embedded'">对比</el-button>
          <el-button size="small" @click="onResplit(row)">重切分</el-button>
          <el-button size="small" @click="onRetry(row)" :disabled="row.status !== 'failed'">重试</el-button>
          <el-button size="small" type="danger" @click="onDeleteDoc(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 重切分对话框 -->
    <el-dialog v-model="resplitDialog" title="重切分 (RAG-04 验收 2)" width="480px">
      <el-form label-width="110px">
        <el-form-item label="切分策略">
          <el-select v-model="resplitForm.strategy">
            <el-option v-for="(s, k) in SPLIT_STRATEGIES" :key="k" :label="s.label" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item v-for="f in currentStrategyFields" :key="f.key" :label="f.label">
          <el-input-number v-model="resplitForm.params[f.key]" :min="0" :step="f.step || 1" />
        </el-form-item>
        <p class="text-muted">省略参数=用当前文档/库配置。重切分删旧 chunk + 重建向量（异步，完成后 ready）。</p>
      </el-form>
      <template #footer>
        <el-button @click="resplitDialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onResplitConfirm">重切分</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/rag'
import { SPLIT_STRATEGIES, strategyLabel, defaultParams } from '@/utils/rag'

const route = useRoute()
const router = useRouter()
const kbId = route.params.kbId

const kb = ref(null)
const kbLoading = ref(false)
const loading = ref(false)
const saving = ref(false)
const docs = ref([])
const docStatus = ref('')
const uploadingDoc = ref(false)
const resplitDialog = ref(false)
const resplitTarget = ref(null)
const resplitForm = reactive({ strategy: 'fixed', params: {} })
const currentStrategyFields = computed(() => SPLIT_STRATEGIES[resplitForm.strategy]?.fields || [])

function statusType(s) {
  return s === 'ready' || s === 'embedded' ? 'success' : s === 'failed' ? 'danger' : 'warning'
}
function back() { router.push('/rag/kbs') }

async function loadKb() {
  kbLoading.value = true
  try {
    const res = await api.getKb(kbId)
    kb.value = res.data
  } finally { kbLoading.value = false }
}
async function loadDocs() {
  loading.value = true
  try {
    const params = { page: 1, page_size: 100 }
    if (docStatus.value) params.status = docStatus.value
    const res = await api.listDocs(kbId, params)
    docs.value = res.data?.items || []
  } finally { loading.value = false }
}
function goCompare(row) {
  router.push(`/rag/kbs/${kbId}/docs/${row.id}/compare`)
}
async function onUpload(file) {
  uploadingDoc.value = file.name
  try {
    await api.uploadDoc(kbId, file)
    ElMessage.success(`已上传 ${file.name}（入队解析流水线）`)
    setTimeout(loadDocs, 1200)
  } catch (e) {} finally { uploadingDoc.value = false }
  return false
}
function onResplit(row) {
  resplitTarget.value = row
  resplitForm.strategy = row.split_strategy || 'fixed'
  resplitForm.params = { ...defaultParams(resplitForm.strategy) }
  resplitDialog.value = true
}
async function onResplitConfirm() {
  saving.value = true
  try {
    await api.resplitDoc(kbId, resplitTarget.value.id, {
      split_strategy: resplitForm.strategy,
      split_params: resplitForm.params,
    })
    ElMessage.success('已触发重切分（异步，状态 splitting→ready）')
    resplitDialog.value = false
    setTimeout(loadDocs, 1500)
  } catch (e) {} finally { saving.value = false }
}
async function onRetry(row) {
  await api.retryDoc(kbId, row.id)
  ElMessage.success('已重新入队')
  loadDocs()
}
async function onDeleteDoc(row) {
  try {
    await ElMessageBox.confirm(`删除文档 ${row.file_name}？级联物理删 chunk`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteDoc(kbId, row.id)
  ElMessage.success('已删除')
  loadDocs()
}
onMounted(() => { loadKb(); loadDocs() })
</script>
