<template>
  <div class="page">
    <h2>MCP Server <span class="text-muted">（MCP-01/02/03，scope mcp:manage）</span></h2>
    <div class="toolbar">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 注册 Server</el-button>
      <el-select v-model="statusFilter" clearable placeholder="状态" style="width:150px" @change="load">
        <el-option v-for="s in ['online','offline','unreachable','disabled']" :key="s" :label="s" :value="s" />
      </el-select>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="url" label="URL" min-width="220">
        <template #default="{ row }"><span class="mono">{{ row.url }}</span></template>
      </el-table-column>
      <el-table-column prop="transport" label="传输" width="130" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="平台内置" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.is_platform" type="warning" size="small">内置</el-tag>
          <span v-else class="text-muted">否</span>
        </template>
      </el-table-column>
      <el-table-column label="API 头" width="90">
        <template #default="{ row }">
          <el-tag :type="row.auth_headers_set ? 'success' : 'info'" size="small">{{ row.auth_headers_set ? '已设' : '未设' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="usable_tool_count" label="可用工具" width="90" />
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="goTools(row)">工具</el-button>
          <el-button size="small" @click="onRefresh(row)" :disabled="row.is_platform">刷新</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)" :disabled="row.is_platform">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="注册 MCP Server" width="520px">
      <el-form :model="form" label-width="110px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="URL"><el-input v-model="form.url" placeholder="http://host:port/mcp" /></el-form-item>
        <el-form-item label="传输">
          <el-select v-model="form.transport">
            <el-option label="streamable_http" value="streamable_http" />
            <el-option label="sse" value="sse" />
          </el-select>
        </el-form-item>
        <el-form-item label="Auth 头">
          <el-input v-model="form.auth_headers" type="textarea" :rows="3"
            placeholder='JSON，如 {"Authorization":"Bearer ***"}' />
        </el-form-item>
        <p class="text-muted">注册即同步（MCP-01/DECISION-010）：立即 tools/list 探测 + 工具全量 upsert；探测失败 → server 保留 unreachable（不丢注册）。</p>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">注册</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/mcp'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const statusFilter = ref('')
const dialog = ref(false)
const form = ref({ name: '', url: '', transport: 'streamable_http', auth_headers: '' })

function statusType(s) {
  return s === 'online' ? 'success' : s === 'disabled' ? 'info' : s === 'unreachable' ? 'danger' : 'warning'
}
async function load() {
  loading.value = true
  try {
    const params = {}
    if (statusFilter.value) params.status = statusFilter.value
    const res = await api.listServers(params)
    rows.value = res.data?.items || []
  } finally { loading.value = false }
}
function openCreate() {
  form.value = { name: '', url: '', transport: 'streamable_http', auth_headers: '' }
  dialog.value = true
}
async function onSave() {
  saving.value = true
  try {
    const body = { name: form.value.name, url: form.value.url, transport: form.value.transport }
    if (form.value.auth_headers) {
      try { body.auth_headers = JSON.parse(form.value.auth_headers) } catch { return ElMessage.warning('Auth 头须为合法 JSON') }
    }
    const res = await api.createServer(body)
    const ok = res.data?.ok
    ElMessage[ok ? 'success' : 'warning'](ok ? '注册成功并同步工具' : `注册成功但探测失败: ${res.data?.error || 'unreachable'}`)
    dialog.value = false
    load()
  } catch (e) {} finally { saving.value = false }
}
async function onRefresh(row) {
  const res = await api.refreshServer(row.id)
  const ok = res.data?.ok
  ElMessage[ok ? 'success' : 'warning'](ok ? `刷新完成，工具 ${res.data?.tool_count}` : `刷新失败: ${res.data?.error || ''}`)
  load()
}
async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`删除 ${row.name}？（有 agent 引用且 confirm=false → 409 + 清单）`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteServer(row.id, true)
  ElMessage.success('已删除')
  load()
}
function goTools(row) {
  router.push(`/mcp/servers/${row.id}/tools`)
}
onMounted(load)
</script>
