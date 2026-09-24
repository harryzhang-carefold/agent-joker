<template>
  <div class="page">
    <h2>Agent 维护 <span class="text-muted">（AGENT-01，scope agents:manage）</span></h2>
    <div class="toolbar">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 新建 Agent</el-button>
      <el-select v-model="typeFilter" clearable placeholder="类型" style="width:150px" @change="load">
        <el-option label="simple" value="simple" />
        <el-option label="third_party" value="third_party" />
      </el-select>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="name" label="名称 (=OpenAI model)" min-width="180" />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag :type="row.type === 'simple' ? 'primary' : 'warning'" size="small">{{ row.type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="session_count" label="会话数" width="90" />
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="goChat(row)">对话</el-button>
          <el-button size="small" @click="goConfig(row)">配置</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="新建 Agent" width="560px">
      <el-form :model="form" label-width="140px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="租户内唯一（=OpenAI model 标识）" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type">
            <el-option label="simple (LangChain SAR)" value="simple" />
            <el-option label="third_party (URL 代理)" value="third_party" />
          </el-select>
        </el-form-item>
        <el-form-item label="第三方 URL" v-if="form.type === 'third_party'">
          <el-input v-model="form.third_party_url" placeholder="http://host/chat/completions" />
        </el-form-item>
        <el-form-item label="系统提示词">
          <el-input v-model="form.system_prompt" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="max_tool_rounds">
          <el-input-number v-model="form.max_tool_rounds" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="默认显示引用">
          <el-switch v-model="form.show_citations_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/agents'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const typeFilter = ref('')
const dialog = ref(false)
const form = ref({
  name: '', type: 'simple', third_party_url: '', system_prompt: '',
  max_tool_rounds: 8, show_citations_default: false,
})

async function load() {
  loading.value = true
  try {
    const params = {}
    if (typeFilter.value) params.type = typeFilter.value
    const res = await api.listAgents(params)
    rows.value = res.data?.items || []
  } finally { loading.value = false }
}
function openCreate() {
  form.value = {
    name: '', type: 'simple', third_party_url: '', system_prompt: '',
    max_tool_rounds: 8, show_citations_default: false,
  }
  dialog.value = true
}
async function onSave() {
  saving.value = true
  try {
    const body = {
      name: form.value.name,
      type: form.value.type,
      system_prompt: form.value.system_prompt,
      max_tool_rounds: form.value.max_tool_rounds,
      show_citations_default: form.value.show_citations_default,
    }
    if (form.value.type === 'third_party') body.third_party_url = form.value.third_party_url
    const res = await api.createAgent(body)
    ElMessage.success('已创建（自动 upsert agent:use scope + 角色）')
    const id = res.data?.id
    dialog.value = false
    load()
    if (id) router.push(`/agents/${id}/config`)
  } catch (e) {} finally { saving.value = false }
}
async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`删除 ${row.name}？（软删，会话/消息保留；级联清理 scope/角色）`, '确认', { type: 'warning' })
  } catch { return }
  await api.deleteAgent(row.id)
  ElMessage.success('已删除')
  load()
}
function goChat(row) { router.push(`/agents/${row.id}/chat`) }
function goConfig(row) { router.push(`/agents/${row.id}/config`) }
onMounted(load)
</script>
