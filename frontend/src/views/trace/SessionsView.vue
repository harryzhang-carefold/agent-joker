<template>
  <div class="page">
    <h2>Trace 会话 <span class="text-muted">（TRACE-02，scope trace:read）</span></h2>
    <div class="toolbar">
      <el-input v-model="q.agent_id" placeholder="agent_id" clearable style="width:200px" @change="load" />
      <el-select v-model="q.status" clearable placeholder="状态" style="width:130px" @change="load">
        <el-option v-for="s in ['active','ended','failed']" :key="s" :label="s" :value="s" />
      </el-select>
      <el-input v-model="q.keyword" placeholder="事件关键词（全文）" clearable style="width:200px" @change="load" />
      <el-button @click="load"><el-icon><Search /></el-icon> 查询</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border @row-click="goDetail">
      <el-table-column prop="session_id" label="会话 ID" width="280">
        <template #default="{ row }"><span class="mono">{{ row.session_id }}</span></template>
      </el-table-column>
      <el-table-column prop="agent_id" label="Agent" width="280">
        <template #default="{ row }"><span class="mono">{{ row.agent_id }}</span></template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'ended' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="event_count" label="事件" width="70" />
      <el-table-column prop="tool_call_count" label="工具" width="70" />
      <el-table-column prop="rag_call_count" label="RAG" width="70" />
      <el-table-column prop="total_tokens" label="Token" width="90" />
      <el-table-column label="开始时间" width="200">
        <template #default="{ row }">{{ fmt(row.started_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click.stop="goDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import * as api from '@/api/trace'

const router = useRouter()
const loading = ref(false)
const rows = ref([])
const q = reactive({ agent_id: '', status: '', keyword: '' })

function fmt(s) {
  if (!s) return '-'
  try { return new Date(s).toLocaleString() } catch { return s }
}
async function load() {
  loading.value = true
  try {
    const params = { page: 1, page_size: 50 }
    if (q.agent_id) params.agent_id = q.agent_id
    if (q.status) params.status = q.status
    if (q.keyword) params.keyword = q.keyword
    const res = await api.listTraceSessions(params)
    rows.value = res.data?.items || []
  } finally { loading.value = false }
}
function goDetail(rowOrEv) {
  const row = rowOrEv?.row || rowOrEv
  // 后端 detail/events 的 {sid} = trace_sessions.id（PK，S09 契约），非逻辑 session_id。
  // 列表项同时返回 id 与 session_id，二者不同 —— 必须用 id 定位，否则跨租户 403。
  if (row?.id) router.push(`/trace/sessions/${row.id}`)
}
onMounted(load)
</script>
