<template>
  <div class="page">
    <h2>{{ title }} <span class="text-muted">（scope llm:manage，平台级共享）</span></h2>
    <div class="toolbar">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 新建</el-button>
      <el-select v-model="statusFilter" clearable placeholder="状态" style="width:140px" @change="load">
        <el-option label="active" value="active" />
        <el-option label="disabled" value="disabled" />
      </el-select>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column prop="base_url" label="Base URL" min-width="220">
        <template #default="{ row }"><span class="mono">{{ row.base_url || '-' }}</span></template>
      </el-table-column>
      <el-table-column prop="model" label="模型" min-width="160">
        <template #default="{ row }"><span class="mono">{{ row.model || '-' }}</span></template>
      </el-table-column>
      <el-table-column v-if="kind==='embedding'" prop="dimensions" label="维度" width="90" />
      <el-table-column v-if="kind==='embedding'" prop="provider" label="Provider" width="110" />
      <el-table-column label="API Key" width="90">
        <template #default="{ row }">
          <el-tag :type="row.api_key_set ? 'success' : 'info'" size="small">{{ row.api_key_set ? '已设' : '未设' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="kind==='endpoint'" label="视觉" width="90">
        <template #default="{ row }">
          <el-tag :type="row.supports_vision ? 'success' : 'info'" size="small">{{ row.supports_vision ? '支持' : '否' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近探测" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.last_test_at" :type="row.last_test_result === 'ok' ? 'success' : 'danger'" size="small">
            {{ row.last_test_result }}
          </el-tag>
          <span v-else class="text-muted">未测</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="onTest(row)" :loading="row._testing">连通性</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editing ? '编辑' : '新建' + title" width="560px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="名称" v-if="!editing"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="Base URL"><el-input v-model="form.base_url" /></el-form-item>
        <el-form-item label="模型"><el-input v-model="form.model" /></el-form-item>
        <el-form-item v-if="kind==='embedding'" label="维度 (dimensions)">
          <el-input-number v-model="form.dimensions" :min="1" :max="8192" />
        </el-form-item>
        <el-form-item v-if="kind==='embedding'" label="Provider">
          <el-select v-model="form.provider">
            <el-option label="api" value="api" />
            <el-option label="local (fallback)" value="local" />
          </el-select>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password
            :placeholder="editing ? '留空=不变，填新值=替换' : '可选'" />
        </el-form-item>
        <el-form-item v-if="kind==='endpoint'" label="视觉支持">
          <el-switch v-model="form.supports_vision" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status">
            <el-option label="active" value="active" />
            <el-option label="disabled" value="disabled" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/llm'

const props = defineProps({
  kind: { type: String, required: true }, // endpoint | embedding | reranker
  title: { type: String, required: true },
})

const listMap = { endpoint: api.listEndpoints, embedding: api.listEmbeddings, reranker: api.listRerankers }
const createMap = { endpoint: api.createEndpoint, embedding: api.createEmbedding, reranker: api.createReranker }
const updateMap = { endpoint: api.updateEndpoint, embedding: api.updateEmbedding, reranker: api.updateReranker }
const deleteMap = { endpoint: api.deleteEndpoint, embedding: api.deleteEmbedding, reranker: api.deleteReranker }
const testMap = { endpoint: api.testEndpoint, embedding: api.testEmbedding, reranker: api.testReranker }

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const statusFilter = ref('')
const dialog = ref(false)
const editing = ref(null)
const form = reactive({
  name: '', base_url: '', model: '', dimensions: 256, provider: 'api',
  api_key: '', supports_vision: false, status: 'active',
})

async function load() {
  loading.value = true
  try {
    const params = {}
    if (statusFilter.value) params.status = statusFilter.value
    const res = await listMap[props.kind](params)
    rows.value = (res.data?.items || []).map((r) => ({ ...r, _testing: false }))
  } finally { loading.value = false }
}

function openCreate() {
  editing.value = null
  Object.assign(form, {
    name: '', base_url: '', model: '', dimensions: 256, provider: 'api',
    api_key: '', supports_vision: false, status: 'active',
  })
  dialog.value = true
}
function openEdit(row) {
  editing.value = row
  Object.assign(form, {
    name: row.name,
    base_url: row.base_url || '',
    model: row.model || '',
    dimensions: row.dimensions ?? 256,
    provider: row.provider || 'api',
    api_key: '',
    supports_vision: !!row.supports_vision,
    status: row.status || 'active',
  })
  dialog.value = true
}

async function onSave() {
  saving.value = true
  try {
    if (editing.value) {
      const body = {
        base_url: form.base_url, model: form.model, status: form.status,
      }
      if (props.kind === 'embedding') { body.dimensions = form.dimensions; body.provider = form.provider }
      if (props.kind === 'endpoint') body.supports_vision = form.supports_vision
      if (form.api_key) body.api_key = form.api_key
      await updateMap[props.kind](editing.value.id, body)
    } else {
      const body = { name: form.name, base_url: form.base_url, model: form.model, status: form.status }
      if (props.kind === 'embedding') { body.dimensions = form.dimensions; body.provider = form.provider }
      if (props.kind === 'endpoint') body.supports_vision = form.supports_vision
      if (form.api_key) body.api_key = form.api_key
      await createMap[props.kind](body)
    }
    ElMessage.success('已保存')
    dialog.value = false
    load()
  } catch (e) {} finally { saving.value = false }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`删除 ${row.name}？（被引用将 409 + 清单）`, '确认', { type: 'warning' })
  } catch { return }
  await deleteMap[props.kind](row.id)
  ElMessage.success('已删除')
  load()
}

async function onTest(row) {
  row._testing = true
  try {
    const res = await testMap[props.kind](row.id)
    const ok = res.data?.ok
    ElMessage[ok ? 'success' : 'error'](`探测结果: ${ok ? '可用' : '不可用'} — ${res.data?.summary || ''}`)
    load()
  } catch (e) {} finally { row._testing = false }
}

onMounted(load)
</script>
