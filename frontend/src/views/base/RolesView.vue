<template>
  <div class="page">
    <h2>角色管理 <span class="text-muted">（BASE-02，scope iam:manage）</span></h2>
    <div class="toolbar">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 新建角色</el-button>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>
    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="name" label="角色名" width="180" />
      <el-table-column prop="description" label="描述" min-width="220" />
      <el-table-column label="Scope" min-width="280">
        <template #default="{ row }">
          <el-tag v-for="s in row.scope_names || row.scopes || []" :key="s" size="small" type="info" style="margin:2px">
            {{ s }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editing ? '编辑角色' : '新建角色'" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="角色名" v-if="!editing"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" /></el-form-item>
        <el-form-item label="Scope">
          <el-select v-model="form.scope_names" multiple filterable allow-create default-first-option
            placeholder="选择或输入 scope（如 kb:manage / agent:use:*）">
            <el-option v-for="s in allScopes" :key="s.name" :label="s.name" :value="s.name" />
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
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/iam'

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const dialog = ref(false)
const editing = ref(null)
const form = ref({ name: '', description: '', scope_names: [] })
const allScopes = ref([])

async function load() {
  loading.value = true
  try {
    const res = await api.listRoles()
    rows.value = res.data?.items || res.data || []
  } finally { loading.value = false }
}
async function loadScopes() {
  const res = await api.listScopes()
  allScopes.value = res.data?.items || res.data || []
}
function openCreate() {
  editing.value = null
  form.value = { name: '', description: '', scope_names: [] }
  dialog.value = true
}
function openEdit(row) {
  editing.value = row
  form.value = {
    name: row.name,
    description: row.description || '',
    scope_names: (row.scope_names || row.scopes || []).map((s) => (typeof s === 'string' ? s : s.name)),
  }
  dialog.value = true
}
async function onSave() {
  saving.value = true
  try {
    if (editing.value) {
      await api.updateRole(editing.value.id, { name: form.value.name, description: form.value.description, scope_names: form.value.scope_names })
    } else {
      await api.createRole(form.value)
    }
    ElMessage.success('已保存')
    dialog.value = false
    load()
  } catch (e) {} finally { saving.value = false }
}
async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`删除角色 ${row.name}？（有用户占用将 409）`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteRole(row.id)
  ElMessage.success('已删除')
  load()
}
onMounted(() => { load(); loadScopes() })
</script>
