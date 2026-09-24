<template>
  <div class="page" v-loading="loading">
    <div class="toolbar" style="margin-bottom:8px">
      <el-button @click="back"><el-icon><ArrowLeft /></el-icon> Server 列表</el-button>
      <span class="flex-1" v-if="server"><b>{{ server.name }}</b>
        <el-tag size="small" style="margin-left:8px">{{ server.status }}</el-tag>
      </span>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <p class="text-muted">
      工具状态：enabled（本侧启用/禁用）× removed_remote（远端已移除反向标记）；usable = enabled && !removed_remote && server.online。
      删除/禁用有 agent 引用且 confirm=false → 409 + 关联清单（MCP-03）。
    </p>

    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="name" label="工具名" min-width="200" />
      <el-table-column prop="source" label="来源" width="100" />
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="远端移除" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.removed_remote" type="danger" size="small">已移除</el-tag>
          <span v-else class="text-muted">否</span>
        </template>
      </el-table-column>
      <el-table-column label="可用" width="80">
        <template #default="{ row }">
          <el-tag :type="row.usable ? 'success' : 'info'" size="small">{{ row.usable ? '可用' : '否' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="所需 scope" min-width="180">
        <template #default="{ row }">
          <el-tag v-for="s in row.required_scopes || []" :key="s" size="small" type="info" style="margin:2px">{{ s }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="描述" min-width="200">
        <template #default="{ row }"><span class="text-muted" :title="row.description">{{ (row.description || '').slice(0, 60) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="onEnable(row)" :disabled="row.enabled || row.is_platform">启用</el-button>
          <el-button size="small" @click="onDisable(row)" :disabled="!row.enabled || row.is_platform">禁用</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)" :disabled="row.is_platform">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/mcp'

const route = useRoute()
const router = useRouter()
const serverId = route.params.serverId

const loading = ref(false)
const rows = ref([])
const server = ref(null)

function back() { router.push('/mcp/servers') }

async function load() {
  loading.value = true
  try {
    const [srv, tools] = await Promise.all([
      api.getServer(serverId),
      api.listTools(serverId, {}),
    ])
    server.value = srv.data
    const td = tools.data
    // 工具级 is_platform：source=platform（平台内置，不可改）
    rows.value = (td?.items || []).map((t) => ({ ...t, is_platform: t.source === 'platform' }))
  } finally { loading.value = false }
}

async function onEnable(row) {
  try { await api.enableTool(row.id); ElMessage.success('已启用') } catch (e) {}
  load()
}
async function onDisable(row) {
  try {
    await ElMessageBox.confirm(`禁用 ${row.name}？（有 agent 引用 → 409 + 清单）`, '确认', { type: 'warning' })
  } catch { return }
  try { await api.disableTool(row.id, true); ElMessage.success('已禁用') } catch (e) {}
  load()
}
async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`删除 ${row.name}？（平台侧移除，不删远端）`, '确认', { type: 'warning' })
  } catch { return }
  try { await api.deleteTool(row.id, true); ElMessage.success('已删除') } catch (e) {}
  load()
}
onMounted(load)
</script>
