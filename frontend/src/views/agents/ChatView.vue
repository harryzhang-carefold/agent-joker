<template>
  <div class="chat-page" v-loading="loading">
    <div class="chat-header" v-if="agent">
      <el-button @click="back"><el-icon><ArrowLeft /></el-icon> Agent 列表</el-button>
      <span class="flex-1"><b>{{ agent.name }}</b>
        <el-tag size="small" style="margin-left:8px">{{ agent.type }}</el-tag>
      </span>
      <el-button v-if="session" size="small" @click="onNewSession">新会话</el-button>
      <el-button size="small" @click="onCloseSession" :disabled="!session">关闭会话</el-button>
      <span class="flex-1"></span>
      <el-checkbox v-model="showCitations">显示引用</el-checkbox>
      <el-checkbox v-model="useStream" style="margin-left:12px">SSE 流式</el-checkbox>
    </div>

    <div class="chat-main">
      <!-- 消息区 -->
      <div class="msg-area" ref="msgArea">
        <div v-if="!messages.length" class="empty">
          <p>与 <b>{{ agent?.name }}</b> 对话（经 BFF /v1/chat/completions，model=agent 名称）。</p>
          <p class="text-muted">开启「SSE 流式」可增量显示回复；命中引用来源时附来源卡片（show_citations / official 命中）。</p>
        </div>
        <template v-for="(m, i) in messages" :key="i">
          <div class="chat-bubble" :class="m.role">
            <span v-if="m.streaming && !m.content" class="text-muted">生成中…</span>
            <span>{{ m.content }}</span>
          </div>
          <!-- 工具调用 -->
          <div v-if="m.tool_calls?.length" class="tool-calls">
            <div v-for="tc in m.tool_calls" :key="tc.id" class="tool-call">
              <el-tag size="small" type="warning">tool: {{ tc.function.name }}</el-tag>
              <pre class="codeblock">{{ tc.function.arguments }}</pre>
            </div>
          </div>
          <!-- 引用来源卡片 -->
          <div v-if="m.citations?.length" class="citations">
            <div class="cite-title">引用来源（{{ m.citations.length }}）</div>
            <div v-for="(c, ci) in m.citations" :key="ci" class="cite-card" :class="{ official: c.is_official }">
              <div class="src-title">
                {{ c.doc_file_name || c.title || ('来源 ' + (ci + 1)) }}
                <el-tag v-if="c.is_official" size="small" type="warning" style="margin-left:6px">官方</el-tag>
                <span class="text-muted" v-if="c.score != null"> · score {{ (c.score * 100).toFixed(0) }}%</span>
              </div>
              <div class="src-content">{{ (c.content || '').slice(0, 160) }}…</div>
              <div class="text-muted" v-if="c.pos">{{ describePos(c.pos) }}</div>
            </div>
          </div>
        </template>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <el-input v-model="input" type="textarea" :rows="3" placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
          @keydown.enter.exact.prevent="onSend" :disabled="sending" />
        <div class="input-bar">
          <span class="text-muted" v-if="session">会话 {{ session.slice(0, 8) }}…</span>
          <span class="flex-1"></span>
          <el-button type="primary" :loading="sending" @click="onSend">
            <el-icon><Promotion /></el-icon> 发送
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as api from '@/api/agents'
import { streamChat } from '@/api/chat'
import { useAuthStore } from '@/stores/auth'
import { describePos } from '@/utils/rag'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const agentId = route.params.agentId

const loading = ref(false)
const sending = ref(false)
const agent = ref(null)
const messages = ref([])
const input = ref('')
const session = ref('')
const showCitations = ref(true)
const useStream = ref(false)
const msgArea = ref(null)

function back() { router.push('/agents') }
function scrollBottom() {
  nextTick(() => {
    if (msgArea.value) msgArea.value.scrollTop = msgArea.value.scrollHeight
  })
}

async function loadAgent() {
  loading.value = true
  try {
    const res = await api.getAgent(agentId)
    agent.value = res.data
    showCitations.value = !!agent.value.show_citations_default
  } finally { loading.value = false }
}

async function onSend() {
  const msg = input.value.trim()
  if (!msg || sending.value) return
  input.value = ''
  // 用户消息
  messages.value.push({ role: 'user', content: msg })
  // 助手占位（流式时增量填充）
  const ai = { role: 'assistant', content: '', streaming: true }
  messages.value.push(ai)
  sending.value = true
  scrollBottom()

  const acc = { content: '', tool_calls: [], citations: null, sessionId: null }

  try {
    if (useStream.value) {
      // SSE 流式
      await streamChat({
        accessToken: auth.accessToken,
        model: agent.value.name,
        message: msg,
        sessionId: session.value || null,
        showCitations: showCitations.value,
        stream: true,
        onDelta: (d) => { acc.content += d; ai.content = acc.content; scrollBottom() },
        onToolCalls: (tcs) => {
          for (const tc of tcs) if (!acc.tool_calls.find((x) => x.id === tc.id)) acc.tool_calls.push(tc)
          ai.tool_calls = acc.tool_calls
        },
        onSession: (sid) => { acc.sessionId = sid },
        onCitations: (c) => { acc.citations = c },
        onDone: () => { finalize(ai, acc) },
        onError: (e) => { ai.content = '⚠️ ' + (e.content || e) || e; finalize(ai, acc) },
      })
    } else {
      // 块式（带完整 citations）：经 /api/agents/{id}/chat
      const res = await api.agentChat(agentId, {
        message: msg,
        session_id: session.value || undefined,
        show_citations: showCitations.value,
      })
      const d = res.data
      acc.content = d.reply || ''
      acc.tool_calls = (d.tool_calls || []).map((tc) => ({
        id: tc.id, type: 'function',
        function: { name: tc.name, arguments: JSON.stringify(tc.args || {}) },
      }))
      acc.citations = d.citations
      acc.sessionId = d.session_id
      finalize(ai, acc)
    }
  } catch (e) {
    ai.content = '⚠️ 请求失败: ' + (e?.response?.data?.detail || e?.message || e)
    finalize(ai, acc)
  } finally {
    sending.value = false
  }
}

function finalize(ai, acc) {
  ai.streaming = false
  if (!ai.content) ai.content = ''
  ai.tool_calls = acc.tool_calls
  ai.citations = acc.citations
  if (acc.sessionId) session.value = acc.sessionId
  scrollBottom()
}

function onNewSession() {
  session.value = ''
  messages.value = []
}
async function onCloseSession() {
  if (!session.value) return
  try {
    await api.closeSession(agentId, session.value)
    ElMessage.success('会话已关闭（触发沉淀：长期记忆 + obsidian 笔记）')
    session.value = ''
    messages.value = []
  } catch (e) {}
}

onMounted(loadAgent)
</script>

<style scoped>
.chat-page { display: flex; flex-direction: column; height: 100%; }
.chat-header {
  display: flex; align-items: center; gap: 10px; padding: 10px 16px;
  background: #fff; border-bottom: 1px solid #e4e7ed;
}
.chat-main { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.msg-area { flex: 1; overflow: auto; padding: 16px; }
.empty { text-align: center; color: #909399; padding: 40px 0; }
.input-area { border-top: 1px solid #e4e7ed; background: #fff; padding: 12px 16px; }
.input-bar { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.tool-calls { margin: 6px 0; }
.tool-call { margin: 4px 0; }
.citations { margin: 8px 0; }
.cite-title { font-size: 12px; font-weight: 600; color: #606266; margin-bottom: 4px; }
</style>
