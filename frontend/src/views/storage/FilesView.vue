<template>
  <div class="page">
    <h2>文件上传记录 <span class="text-muted">（STORE-05，scope storage:read/write）</span></h2>
    <div class="toolbar">
      <el-upload :show-file-list="false" :before-upload="onUpload" accept=".txt,.md,.docx,.xlsx,.pdf,.csv">
        <el-button type="primary"><el-icon><Upload /></el-icon> 上传文件</el-button>
      </el-upload>
      <el-select v-model="q.source" clearable placeholder="来源" style="width:150px" @change="load">
        <el-option v-for="s in ['api','mcp:platform','agent','kb','skill']" :key="s" :label="s" :value="s" />
      </el-select>
      <el-input v-model="q.file_name" placeholder="文件名模糊" clearable style="width:200px" @change="load" />
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" stripe border>
      <el-table-column prop="file_name" label="文件名" min-width="220" />
      <el-table-column prop="source" label="来源" width="130" />
      <el-table-column prop="size_bytes" label="大小" width="110">
        <template #default="{ row }">{{ fmtSize(row.size_bytes) }}</template>
      </el-table-column>
      <el-table-column prop="content_type" label="类型" width="160" />
      <el-table-column prop="backend" label="后端" width="100" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column label="时间" width="200">
        <template #default="{ row }">{{ fmtTime(row.created_at || row.uploaded_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="onDownload(row)">下载</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
        </template>
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
import { ElMessage } from 'element-plus'
import * as api from '@/api/storage'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const q = reactive({ source: '', file_name: '', page: 1, page_size: 50 })

function fmtSize(b) {
  if (b == null) return '-'
  if (b < 1024) return b + ' B'
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1048576).toFixed(1) + ' MB'
}
function fmtTime(s) {
  if (!s) return '-'
  try { return new Date(s).toLocaleString() } catch { return s }
}

async function load() {
  loading.value = true
  try {
    const params = { page: q.page, page_size: q.page_size }
    if (q.source) params.source = q.source
    if (q.file_name) params.file_name = q.file_name
    const res = await api.listFiles(params)
    rows.value = res.data?.items || []
    total.value = res.data?.total ?? rows.value.length
  } finally { loading.value = false }
}

async function onUpload(file) {
  try {
    await api.uploadFile(file, 'api')
    ElMessage.success(`已上传 ${file.name}`)
    load()
  } catch (e) {}
  return false
}

async function onDownload(row) {
  const res = await httpGet(row.file_name)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = row.file_name
  a.click()
  URL.revokeObjectURL(url)
}
async function httpGet(fileName) {
  // 下载走原始 fetch（axios 流式）
  const res = await fetch(`/api/storage/files/${encodeURIComponent(fileName)}`, {
    headers: { Authorization: `Bearer ${auth.accessToken}` },
  })
  if (!res.ok) throw new Error('download failed ' + res.status)
  return res
}
async function onDelete(row) {
  try {
    await api.deleteFile(row.file_name)
    ElMessage.success('已删除')
    load()
  } catch (e) {}
}
onMounted(load)
</script>
