<template>
  <div class="page">
    <h2>接口操作日志 <span class="text-muted">（BASE-06，scope trace:read）</span></h2>
    <div class="toolbar">
      <el-input v-model="q.path" placeholder="路径前缀，如 /api/rag" clearable style="width:240px" @change="load" />
      <el-date-picker v-model="q.range" type="daterange" range-separator="~"
        start-placeholder="开始" end-placeholder="结束" value-format="YYYY-MM-DDTHH:mm:ssZ"
        style="width:280px" />
      <el-button @click="load"><el-icon><Search /></el-icon> 查询</el-button>
      <el-button @click="reset"><el-icon><RefreshLeft /></el-icon> 重置</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="method" label="方法" width="80" />
      <el-table-column prop="path" label="路径" min-width="260" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status < 400 ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="latency_ms" label="耗时(ms)" width="100" />
      <el-table-column prop="client_ip" label="客户端IP" width="140" />
      <el-table-column label="时间" width="200">
        <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>

    <div class="toolbar" style="margin-top:12px">
      <el-pagination v-model:current-page="q.page" :total="total" :page-size="q.page_size"
        layout="total, prev, pager, next" @current-change="load" />
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import * as api from '@/api/iam'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const q = reactive({ path: '', range: null, page: 1, page_size: 50 })

function fmtTime(s) {
  if (!s) return '-'
  try { return new Date(s).toLocaleString() } catch { return s }
}
async function load() {
  loading.value = true
  try {
    const params = { page: q.page, page_size: q.page_size }
    if (q.path) params.path = q.path
    if (q.range && q.range.length === 2) {
      params.from = new Date(q.range[0]).toISOString()
      params.to = new Date(q.range[1]).toISOString()
    }
    const res = await api.listAuditLogs(params)
    rows.value = res.data?.items || []
    total.value = res.data?.total ?? rows.value.length
  } finally { loading.value = false }
}
function reset() {
  q.path = ''
  q.range = null
  q.page = 1
  load()
}
onMounted(load)
</script>
