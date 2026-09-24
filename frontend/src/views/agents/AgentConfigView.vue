<template>
  <div class="page" v-loading="loading">
    <div class="toolbar" style="margin-bottom:8px">
      <el-button @click="back"><el-icon><ArrowLeft /></el-icon> Agent 列表</el-button>
      <span class="flex-1" v-if="agent"><b>{{ agent.name }}</b>
        <el-tag size="small" style="margin-left:8px">{{ agent.type }}</el-tag>
        <el-tag :type="agent.status === 'active' ? 'success' : 'info'" size="small" style="margin-left:8px">{{ agent.status }}</el-tag>
      </span>
      <el-button @click="reload"><el-icon><Refresh /></el-icon> 刷新</el-button>
    </div>

    <el-card class="cfg-card" v-if="agent">
      <template #header><b>基础信息</b></template>
      <el-form label-width="140px">
        <el-form-item label="系统提示词">
          <el-input v-model="edit.system_prompt" type="textarea" :rows="5" />
        </el-form-item>
        <el-form-item label="max_tool_rounds">
          <el-input-number v-model="edit.max_tool_rounds" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="默认显示引用">
          <el-switch v-model="edit.show_citations_default" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="edit.status">
            <el-option label="active" value="active" />
            <el-option label="disabled" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="agent.type === 'third_party'" label="第三方 URL">
          <el-input v-model="edit.third_party_url" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="onSaveBase">保存基础信息</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 四要素勾选（A03） -->
    <el-card class="cfg-card" v-if="agent">
      <template #header><b>四要素配置（从列表勾选）</b>
        <el-button size="small" type="primary" :loading="saving" style="float:right" @click="onSaveFour">保存四要素</el-button>
      </template>
      <el-row :gutter="16">
        <el-col :span="12">
          <div class="factor-title">LLM Endpoint（恰好 1 条）</div>
          <el-checkbox-group v-model="four.llm_endpoint_ids">
            <el-checkbox v-for="e in endpoints" :key="e.id" :value="e.id" :disabled="e.status !== 'active'">
              {{ e.name }} <span class="text-muted">({{ e.status }})</span>
            </el-checkbox>
          </el-checkbox-group>
        </el-col>
        <el-col :span="12">
          <div class="factor-title">知识库 (KB)</div>
          <el-checkbox-group v-model="four.knowledge_base_ids">
            <el-checkbox v-for="k in kbs" :key="k.id" :value="k.id">
              {{ k.name }}
            </el-checkbox>
          </el-checkbox-group>
        </el-col>
        <el-col :span="12">
          <div class="factor-title">MCP 工具</div>
          <el-checkbox-group v-model="four.mcp_tool_ids">
            <el-checkbox v-for="t in tools" :key="t.id" :value="t.id">
              {{ t.server_name }}/{{ t.name }}
            </el-checkbox>
          </el-checkbox-group>
        </el-col>
        <el-col :span="12">
          <div class="factor-title">Skills</div>
          <el-checkbox-group v-model="four.skill_ids">
            <el-checkbox v-for="s in skills" :key="s.id" :value="s.id">{{ s.name }}</el-checkbox>
          </el-checkbox-group>
        </el-col>
      </el-row>
      <p class="text-muted">四要素：LLM endpoint 必须恰好勾选 1 条；KB/MCP 工具/skill 可多勾（未勾选 → 该 agent 不可用对应资源，403 语义）。候选不存在或 disabled → 422。</p>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as agentsApi from '@/api/agents'
import * as llm from '@/api/llm'
import * as rag from '@/api/rag'
import * as mcpApi from '@/api/mcp'
import * as skillsApi from '@/api/skills'

const route = useRoute()
const router = useRouter()
const agentId = route.params.agentId

const loading = ref(false)
const saving = ref(false)
const agent = ref(null)
const edit = reactive({ system_prompt: '', max_tool_rounds: 8, show_citations_default: false, status: 'active', third_party_url: '' })
const four = reactive({ llm_endpoint_ids: [], knowledge_base_ids: [], mcp_tool_ids: [], skill_ids: [] })

// 候选列表
const endpoints = ref([])
const kbs = ref([])
const tools = ref([])
const skills = ref([])

function back() { router.push('/agents') }

async function reload() {
  loading.value = true
  try {
    const res = await agentsApi.getAgent(agentId)
    agent.value = res.data
    edit.system_prompt = agent.value.system_prompt || ''
    edit.max_tool_rounds = agent.value.max_tool_rounds || 8
    edit.show_citations_default = !!agent.value.show_citations_default
    edit.status = agent.value.status || 'active'
    edit.third_party_url = agent.value.third_party_url || ''
    four.llm_endpoint_ids = agent.value.llm_endpoint_ids || []
    four.knowledge_base_ids = agent.value.knowledge_base_ids || []
    four.mcp_tool_ids = agent.value.mcp_tool_ids || []
    four.skill_ids = agent.value.skill_ids || []
    await loadCandidates()
  } finally { loading.value = false }
}

async function loadCandidates() {
  const [e, k, servers, sk] = await Promise.all([
    llm.listEndpoints({ status: 'active' }),
    rag.listKbs({ page: 1, page_size: 200, status: 'active' }),
    mcpApi.listServers({}),
    skillsApi.listSkills({ page: 1, page_size: 200, status: 'active' }),
  ])
  endpoints.value = e.data?.items || []
  kbs.value = k.data?.items || []
  skills.value = sk.data?.items || []
  // 聚合所有 server 的工具
  const srvs = servers.data?.items || []
  const all = []
  for (const s of srvs) {
    try {
      const t = await mcpApi.listTools(s.id, {})
      for (const tool of (t.data?.items || [])) {
        all.push({ id: tool.id, name: tool.name, server_name: s.name })
      }
    } catch {}
  }
  tools.value = all
}

async function onSaveBase() {
  saving.value = true
  try {
    const body = {
      system_prompt: edit.system_prompt,
      max_tool_rounds: edit.max_tool_rounds,
      show_citations_default: edit.show_citations_default,
      status: edit.status,
    }
    if (agent.value.type === 'third_party') body.third_party_url = edit.third_party_url
    await agentsApi.updateAgent(agentId, body)
    ElMessage.success('基础信息已保存')
  } catch (e) {} finally { saving.value = false }
}

async function onSaveFour() {
  saving.value = true
  try {
    if (four.llm_endpoint_ids.length !== 1) {
      return ElMessage.warning('LLM endpoint 必须恰好勾选 1 条')
    }
    await agentsApi.updateAgent(agentId, {
      llm_endpoint_ids: four.llm_endpoint_ids,
      knowledge_base_ids: four.knowledge_base_ids,
      mcp_tool_ids: four.mcp_tool_ids,
      skill_ids: four.skill_ids,
    })
    ElMessage.success('四要素已保存')
    reload()
  } catch (e) {} finally { saving.value = false }
}

onMounted(reload)
</script>

<style scoped>
.cfg-card { margin-bottom: 12px; }
.factor-title { font-weight: 600; margin-bottom: 8px; font-size: 13px; }
.el-checkbox { margin-right: 12px; margin-bottom: 6px; display: inline-flex; }
</style>
