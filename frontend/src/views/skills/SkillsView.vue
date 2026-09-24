<template>
  <div class="page">
    <h2>Skill 管理 <span class="text-muted">（SKILL-01/02，scope skills:manage）</span></h2>
    <div class="toolbar">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 内联创建</el-button>
      <el-upload :show-file-list="false" :before-upload="onUpload" accept=".md,.txt,.py,.json">
        <el-button><el-icon><Upload /></el-icon> 多文件上传</el-button>
      </el-upload>
      <el-select v-model="sourceFilter" clearable placeholder="来源" style="width:140px" @change="load">
        <el-option label="manual" value="manual" />
        <el-option label="upload" value="upload" />
      </el-select>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column prop="description" label="描述" min-width="220" />
      <el-table-column prop="source" label="来源" width="100" />
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column prop="file_count" label="文件数" width="90" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" @click="onViewFiles(row)">文件</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editing ? '编辑 Skill' : '内联创建 Skill'" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="名称" v-if="!editing"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" /></el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="8" placeholder="skill 主内容（Markdown 等）" />
        </el-form-item>
        <el-form-item label="状态" v-if="editing">
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

    <el-dialog v-model="filesDialog" title="Skill 文件" width="520px">
      <el-table :data="files" stripe size="small" border>
        <el-table-column prop="file_name" label="文件名" min-width="200" />
        <el-table-column prop="role" label="角色" width="90" />
        <el-table-column prop="size_bytes" label="大小" width="100" />
        <el-table-column prop="content_type" label="类型" min-width="140" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/skills'

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const sourceFilter = ref('')
const dialog = ref(false)
const editing = ref(null)
const form = ref({ name: '', description: '', content: '', status: 'active' })
const filesDialog = ref(false)
const files = ref([])

async function load() {
  loading.value = true
  try {
    const params = { page: 1, page_size: 200 }
    if (sourceFilter.value) params.source = sourceFilter.value
    const res = await api.listSkills(params)
    rows.value = res.data?.items || []
  } finally { loading.value = false }
}
function openCreate() {
  editing.value = null
  form.value = { name: '', description: '', content: '', status: 'active' }
  dialog.value = true
}
function openEdit(row) {
  editing.value = row
  form.value = { name: row.name, description: row.description || '', content: row.content || '', status: row.status || 'active' }
  dialog.value = true
}
async function onSave() {
  saving.value = true
  try {
    if (editing.value) {
      const body = { description: form.value.description, content: form.value.content, status: form.value.status }
      if (form.value.name && form.value.name !== editing.value.name) body.name = form.value.name
      await api.updateSkill(editing.value.id, body)
    } else {
      await api.createSkill({ name: form.value.name, description: form.value.description, content: form.value.content })
    }
    ElMessage.success('已保存')
    dialog.value = false
    load()
  } catch (e) {} finally { saving.value = false }
}
async function onUpload(file) {
  try {
    await api.uploadSkill([file])
    ElMessage.success(`已上传 ${file.name}`)
    load()
  } catch (e) {}
  return false
}
async function onViewFiles(row) {
  const res = await api.getSkill(row.id)
  files.value = res.data?.files || []
  filesDialog.value = true
}
async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`删除 ${row.name}？（软删 + 物理删主/资产文件）`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteSkill(row.id)
  ElMessage.success('已删除')
  load()
}
onMounted(load)
</script>
