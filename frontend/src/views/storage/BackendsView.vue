<template>
  <div class="page">
    <h2>存储后端配置 <span class="text-muted">（STORE-03，DECISION-027，scope storage:read）</span></h2>
    <div class="toolbar">
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>
    <el-alert type="info" :closable="false" style="margin-bottom:12px"
      title="后端切换由 env STORAGE_BACKEND=local|gcs|oss 配置（重启生效）；切换后新上传走新后端，既有文件按 backend 行内分派从原后端读。" />
    <el-table :data="backends" v-loading="loading" stripe border>
      <el-table-column prop="name" label="后端" width="140" />
      <el-table-column label="当前" width="100">
        <template #default="{ row }">
          <el-tag :type="row.active ? 'success' : 'info'" size="small">{{ row.active ? '当前' : '备用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="已配置" width="100">
        <template #default="{ row }">
          <el-tag :type="row.configured ? 'success' : 'warning'" size="small">{{ row.configured ? '是' : '否' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="根 / 桶 / 错误" min-width="260">
        <template #default="{ row }">
          <span class="mono">{{ row.root || row.bucket || row.error || '-' }}</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import * as api from '@/api/storage'

const loading = ref(false)
const backends = ref([])

async function load() {
  loading.value = true
  try {
    const res = await api.listBackends()
    backends.value = res.data?.items || []
  } finally { loading.value = false }
}
onMounted(load)
</script>
