<template>
  <div class="page" v-loading="loading">
    <div class="toolbar" style="margin-bottom:8px">
      <el-button @click="back"><el-icon><ArrowLeft /></el-icon> Trace 会话列表</el-button>
      <span class="flex-1"><b>会话 <span class="mono">{{ (session && session.session_id) || sid }}</span></b></span>
      <el-button @click="load"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <el-card class="sum-card" v-if="session">
      <el-descriptions :column="4" border>
        <el-descriptions-item label="Agent"><span class="mono">{{ session.agent_id }}</span></el-descriptions-item>
        <el-descriptions-item label="用户"><span class="mono">{{ session.user_id }}</span></el-descriptions-item>
        <el-descriptions-item label="状态">{{ session.status }}</el-descriptions-item>
        <el-descriptions-item label="事件数">{{ session.event_count }}</el-descriptions-item>
        <el-descriptions-item label="工具调用">{{ session.tool_call_count }}</el-descriptions-item>
        <el-descriptions-item label="RAG 调用">{{ session.rag_call_count }}</el-descriptions-item>
        <el-descriptions-item label="文件事件">{{ session.file_event_count }}</el-descriptions-item>
        <el-descriptions-item label="Token 总计">{{ session.total_tokens }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card>
      <template #header>
        <b>事件时间线（全链路）</b>
        <div class="toolbar" style="margin:0; float:right">
          <el-select v-model="evType" clearable placeholder="事件类型" size="small" style="width:140px" @change="loadEvents">
            <el-option v-for="t in ['message','tool_call','rag','file','system']" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
      </template>

      <el-timeline>
        <el-timeline-item
          v-for="ev in events" :key="ev.id"
          :type="evTypeColor(ev.event_type)"
          :timestamp="fmt(ev.created_at)"
          placement="top"
        >
          <div class="ev">
            <el-tag size="small" :type="evTypeColor(ev.event_type)">{{ ev.event_type }}</el-tag>
            <span class="text-muted" v-if="ev.tool_name" style="margin-left:8px">工具: {{ ev.tool_name }}</span>
            <span class="text-muted" v-if="ev.rag_kb_id" style="margin-left:8px">RAG: {{ ev.rag_kb_id?.slice(0, 8) }}…</span>
            <el-tag size="small" type="info" v-if="ev.token_usage" style="margin-left:8px">
              token {{ ev.token_usage.total_tokens || (ev.token_usage.prompt_tokens || 0) + (ev.token_usage.completion_tokens || 0) }}
            </el-tag>
            <el-tag size="small" v-if="ev.status && ev.status !== 'ok'" type="danger" style="margin-left:8px">{{ ev.status }}</el-tag>
            <span class="text-muted mono" v-if="ev.latency_ms" style="margin-left:8px">{{ ev.latency_ms }}ms</span>
            <el-collapse v-if="ev.payload" class="ev-payload">
              <el-collapse-item title="payload">
                <pre class="codeblock">{{ JSON.stringify(ev.payload, null, 2) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-timeline-item>
        <el-timeline-item v-if="!events.length" type="info">暂无事件</el-timeline-item>
      </el-timeline>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as api from '@/api/trace'

const route = useRoute()
const router = useRouter()
const sid = route.params.sid

const loading = ref(false)
const session = ref(null)
const events = ref([])
const evType = ref('')

function evTypeColor(t) {
  return t === 'tool_call' ? 'warning' : t === 'rag' ? 'primary' : t === 'file' ? 'info' : t === 'system' ? 'danger' : 'success'
}
function fmt(s) {
  if (!s) return ''
  try { return new Date(s).toLocaleString() } catch { return s }
}
async function load() {
  loading.value = true
  try {
    const s = await api.getTraceSession(sid)
    session.value = s.data
    await loadEvents()
  } finally { loading.value = false }
}
async function loadEvents() {
  const params = { page: 1, page_size: 500 }
  if (evType.value) params.event_type = evType.value
  const res = await api.listTraceEvents(sid, params)
  events.value = res.data?.items || []
}
function back() { router.push('/trace/sessions') }
onMounted(load)
</script>

<style scoped>
.sum-card { margin-bottom: 12px; }
.ev { font-size: 13px; }
.ev-payload { margin-top: 6px; }
pre.codeblock { max-height: 300px; }
</style>
