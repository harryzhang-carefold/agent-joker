<template>
  <div class="page">
    <h2>知识库 <span class="text-muted">（RAG-01，D-C 每库独立向量表，scope kb:manage）</span></h2>
    <div class="toolbar">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 建库</el-button>
      <el-select v-model="statusFilter" clearable placeholder="状态" style="width:140px" @change="load">
        <el-option label="active" value="active" />
        <el-option label="reindexing" value="reindexing" />
        <el-option label="disabled" value="disabled" />
      </el-select>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column label="官方 tag" width="110">
        <template #default="{ row }">
          <el-tag :type="row.tag === 'official' ? 'warning' : 'info'" size="small">{{ row.tag || '无' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="embedding_dim" label="向量维度" width="100" />
      <el-table-column label="向量表" min-width="200">
        <template #default="{ row }">
          <span class="mono">{{ row.vec_table || '-' }}</span>
          <el-tag v-if="!row.vec_table_exists" type="danger" size="small" style="margin-left:6px">未建</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="doc_count" label="文档数" width="90" />
      <el-table-column label="topK/阈值" width="120">
        <template #default="{ row }">{{ row.top_k_default || 5 }} / {{ row.score_threshold ?? 0.3 }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : row.status === 'reindexing' ? 'warning' : 'info'" size="small">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row, $event }">
          <el-button size="small" @click.stop="goDetail(row)">文档</el-button>
          <el-button size="small" @click.stop="onReindex(row)">换模型</el-button>
          <el-button size="small" type="danger" @click.stop="onDelete(row)">删库</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="建库" width="560px">
      <el-form :model="form" label-width="130px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" /></el-form-item>
        <el-form-item label="官方 tag (D-A)">
          <el-select v-model="form.tag" clearable placeholder="NULL=非官方">
            <el-option label="official" value="official" />
          </el-select>
        </el-form-item>
        <el-form-item label="Embedding 模型">
          <el-select v-model="form.embedding_model_id" filterable placeholder="选择 active embedding 模型">
            <el-option v-for="e in embeddings" :key="e.id" :label="`${e.name} (${e.dimensions}d)`" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Reranker 模型">
          <el-select v-model="form.reranker_model_id" clearable filterable placeholder="可选">
            <el-option v-for="r in rerankers" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="top_k_default">
          <el-input-number v-model="form.top_k_default" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="score_threshold">
          <el-input-number v-model="form.score_threshold" :min="0" :max="1" :step="0.05" />
        </el-form-item>
        <el-form-item label="默认切分策略">
          <el-select v-model="form.split_strategy_default">
            <el-option v-for="(s, k) in SPLIT_STRATEGIES" :key="k" :label="s.label" :value="k" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reindexDialog" title="换 Embedding 模型（全库重算，D-C 流程 c）" width="460px">
      <el-form label-width="120px">
        <el-form-item label="新模型">
          <el-select v-model="reindexModel" filterable>
            <el-option v-for="e in embeddings" :key="e.id" :label="`${e.name} (${e.dimensions}d)`" :value="e.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <p class="text-muted">异步执行：建影子表(新维度) → 全量重嵌入 → 切换 → DROP 旧表。期间检索走旧表。完成后 GET 查 status。</p>
      <template #footer>
        <el-button @click="reindexDialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onReindexConfirm">开始重算</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/rag'
import * as llm from '@/api/llm'
import { SPLIT_STRATEGIES, defaultParams } from '@/utils/rag'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const statusFilter = ref('')
const dialog = ref(false)
const form = ref({
  name: '', description: '', tag: '', embedding_model_id: '', reranker_model_id: '',
  top_k_default: 5, score_threshold: 0.3, split_strategy_default: 'fixed',
})
const embeddings = ref([])
const rerankers = ref([])
const reindexDialog = ref(false)
const reindexTarget = ref(null)
const reindexModel = ref('')

async function load() {
  loading.value = true
  try {
    const params = {}
    if (statusFilter.value) params.status = statusFilter.value
    const res = await api.listKbs({ page: 1, page_size: 200, ...params })
    rows.value = res.data?.items || []
  } finally { loading.value = false }
}
async function loadModels() {
  const [e, r] = await Promise.all([llm.listEmbeddings(), llm.listRerankers()])
  embeddings.value = (e.data?.items || []).filter((x) => x.status === 'active')
  rerankers.value = (r.data?.items || []).filter((x) => x.status === 'active')
}
function openCreate() {
  form.value = {
    name: '', description: '', tag: '', embedding_model_id: '', reranker_model_id: '',
    top_k_default: 5, score_threshold: 0.3, split_strategy_default: 'fixed',
  }
  dialog.value = true
}
async function onSave() {
  if (!form.value.name || !form.value.embedding_model_id) return ElMessage.warning('名称与 embedding 模型必填')
  saving.value = true
  try {
    const body = {
      name: form.value.name,
      embedding_model_id: form.value.embedding_model_id,
      top_k_default: form.value.top_k_default,
      score_threshold: form.value.score_threshold,
      split_strategy_default: form.value.split_strategy_default,
      split_params_default: defaultParams(form.value.split_strategy_default),
    }
    if (form.value.description) body.description = form.value.description
    if (form.value.tag) body.tag = form.value.tag
    if (form.value.reranker_model_id) body.reranker_model_id = form.value.reranker_model_id
    await api.createKb(body)
    ElMessage.success('建库成功（已建独立向量表）')
    dialog.value = false
    load()
  } catch (e) {} finally { saving.value = false }
}
async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`删库 ${row.name}？级联删文档/chunk + DROP 独立向量表（物理释放）`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteKb(row.id)
  ElMessage.success('已删库')
  load()
}
function onReindex(row) {
  reindexTarget.value = row
  reindexModel.value = ''
  reindexDialog.value = true
}
async function onReindexConfirm() {
  if (!reindexModel.value) return ElMessage.warning('选择新模型')
  saving.value = true
  try {
    await api.reindexKb(reindexTarget.value.id, { embedding_model_id: reindexModel.value })
    ElMessage.success('已触发换模型重算（异步，状态 reindexing）')
    reindexDialog.value = false
    load()
  } catch (e) {} finally { saving.value = false }
}
function goDetail(row) {
  router.push(`/rag/kbs/${row.id}`)
}
onMounted(() => { load(); loadModels() })
</script>
