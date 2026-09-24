<template>
  <div class="page">
    <h2>权限 (scope) <span class="text-muted">（BASE-03，平台级字典，scope iam:manage）</span></h2>
    <div class="toolbar">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 新建 scope</el-button>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>
    <p class="text-muted">
      内置 agent 访问控制 scope 语义：
      <code>agent:use:&lt;id&gt;</code>（精确）/ <code>agent:use:*</code>（通配，DECISION-004）。
      其余如 <code>iam:manage</code> / <code>kb:manage</code> / <code>llm:manage</code> / <code>rag:search</code> / <code>trace:read</code> 等。
    </p>
    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="name" label="scope 名" width="260" />
      <el-table-column prop="description" label="描述" min-width="220" />
      <el-table-column label="说明" width="140">
        <template #default="{ row }">
          <el-tag size="small" type="info" v-if="row.built_in">内置</el-tag>
          <span v-else class="text-muted">自定义</span>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="新建 scope" width="460px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="scope 名"><el-input v-model="form.name" placeholder="如 kb:manage" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/iam'

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const dialog = ref(false)
const form = ref({ name: '', description: '' })

async function load() {
  loading.value = true
  try {
    const res = await api.listScopes()
    rows.value = res.data?.items || res.data || []
  } finally { loading.value = false }
}
function openCreate() {
  form.value = { name: '', description: '' }
  dialog.value = true
}
async function onSave() {
  saving.value = true
  try {
    await api.createScope(form.value)
    ElMessage.success('已创建')
    dialog.value = false
    load()
  } catch (e) {} finally { saving.value = false }
}
onMounted(load)
</script>
