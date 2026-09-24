import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// S10 路由：9 模块 + 对话 + 切分对比。懒加载分包。
const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/components/Layout.vue'),
    redirect: '/users',
    children: [
      // 基础
      { path: 'users', name: 'users', component: () => import('@/views/base/UsersView.vue'), meta: { title: '用户管理', group: '基础', scope: 'iam:manage' } },
      { path: 'roles', name: 'roles', component: () => import('@/views/base/RolesView.vue'), meta: { title: '角色管理', group: '基础', scope: 'iam:manage' } },
      { path: 'scopes', name: 'scopes', component: () => import('@/views/base/ScopesView.vue'), meta: { title: '权限(scope)', group: '基础', scope: 'iam:manage' } },
      { path: 'tenants', name: 'tenants', component: () => import('@/views/base/TenantsView.vue'), meta: { title: '租户管理', group: '基础', scope: 'iam:manage' } },
      { path: 'audit', name: 'audit', component: () => import('@/views/base/AuditView.vue'), meta: { title: '接口操作日志', group: '基础', scope: 'trace:read' } },
      // 存储
      { path: 'storage/files', name: 'files', component: () => import('@/views/storage/FilesView.vue'), meta: { title: '文件上传记录', group: '存储', scope: 'storage:read' } },
      { path: 'storage/backends', name: 'backends', component: () => import('@/views/storage/BackendsView.vue'), meta: { title: '存储后端配置', group: '存储', scope: 'storage:read' } },
      // LLM 节点
      { path: 'llm/endpoints', name: 'endpoints', component: () => import('@/views/llm/EndpointsView.vue'), meta: { title: 'Chat 端点', group: 'LLM 节点', scope: 'llm:manage' } },
      { path: 'llm/embeddings', name: 'embeddings', component: () => import('@/views/llm/EmbeddingsView.vue'), meta: { title: 'Embedding 模型', group: 'LLM 节点', scope: 'llm:manage' } },
      { path: 'llm/rerankers', name: 'rerankers', component: () => import('@/views/llm/RerankersView.vue'), meta: { title: 'Reranker 模型', group: 'LLM 节点', scope: 'llm:manage' } },
      // RAG
      { path: 'rag/kbs', name: 'kbs', component: () => import('@/views/rag/KbListView.vue'), meta: { title: '知识库', group: 'RAG', scope: 'kb:manage' } },
      { path: 'rag/kbs/:kbId', name: 'kb-docs', component: () => import('@/views/rag/KbDetailView.vue'), meta: { title: '知识库文档', group: 'RAG', scope: 'kb:manage' } },
      { path: 'rag/kbs/:kbId/docs/:docId/compare', name: 'kb-compare', component: () => import('@/views/rag/CompareView.vue'), meta: { title: '切分对比查看', group: 'RAG', scope: 'kb:manage' } },
      { path: 'rag/search', name: 'rag-search', component: () => import('@/views/rag/SearchView.vue'), meta: { title: '检索测试', group: 'RAG', scope: 'rag:search' } },
      // MCP
      { path: 'mcp/servers', name: 'mcp-servers', component: () => import('@/views/mcp/ServersView.vue'), meta: { title: 'MCP Server', group: 'MCP', scope: 'mcp:manage' } },
      { path: 'mcp/servers/:serverId/tools', name: 'mcp-tools', component: () => import('@/views/mcp/ToolsView.vue'), meta: { title: 'MCP 工具', group: 'MCP', scope: 'mcp:manage' } },
      // Skills
      { path: 'skills', name: 'skills', component: () => import('@/views/skills/SkillsView.vue'), meta: { title: 'Skill 管理', group: 'Skills', scope: 'skills:manage' } },
      // Agent
      { path: 'agents', name: 'agents', component: () => import('@/views/agents/AgentsView.vue'), meta: { title: 'Agent 维护', group: 'Agent', scope: 'agents:manage' } },
      { path: 'agents/:agentId/config', name: 'agent-config', component: () => import('@/views/agents/AgentConfigView.vue'), meta: { title: 'Agent 配置', group: 'Agent', scope: 'agents:manage' } },
      { path: 'agents/:agentId/chat', name: 'agent-chat', component: () => import('@/views/agents/ChatView.vue'), meta: { title: 'Agent 对话', group: 'Agent', scope: 'agent:use:*' } },
      // Trace
      { path: 'trace/sessions', name: 'trace-sessions', component: () => import('@/views/trace/SessionsView.vue'), meta: { title: 'Trace 会话', group: 'Trace', scope: 'trace:read' } },
      { path: 'trace/sessions/:sid', name: 'trace-detail', component: () => import('@/views/trace/TraceDetailView.vue'), meta: { title: 'Trace 会话详情', group: 'Trace', scope: 'trace:read' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 登录守卫
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isLoggedIn) {
    return { path: '/' }
  }
  return true
})

export default router
