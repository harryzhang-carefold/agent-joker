// S10 菜单配置（与 router meta 对齐）。scope=null 表示所有登录用户可见。
// 多租户 UI：数据天然按当前用户 JWT 租户行级过滤（BFF 强制）；
// 平台管理员（iam:manage）可在「租户管理」跨租户管理。
// S17/BUG-07：platform_only 标记的条目仅平台管理员（system 租户）可见。
export const menu = [
  {
    group: '基础',
    icon: 'User',
    items: [
      { path: '/users', title: '用户管理', scope: 'iam:manage' },
      { path: '/roles', title: '角色管理', scope: 'iam:manage' },
      { path: '/scopes', title: '权限 (scope)', scope: 'iam:manage' },
      { path: '/tenants', title: '租户管理', scope: 'iam:manage', platform_only: true },
      { path: '/audit', title: '接口操作日志', scope: 'trace:read' },
    ],
  },
  {
    group: '存储',
    icon: 'Folder',
    items: [
      { path: '/storage/files', title: '文件上传记录', scope: 'storage:read' },
      { path: '/storage/backends', title: '存储后端配置', scope: 'storage:read' },
    ],
  },
  {
    group: 'LLM 节点',
    icon: 'Cpu',
    items: [
      { path: '/llm/endpoints', title: 'Chat 端点', scope: 'llm:manage' },
      { path: '/llm/embeddings', title: 'Embedding 模型', scope: 'llm:manage' },
      { path: '/llm/rerankers', title: 'Reranker 模型', scope: 'llm:manage' },
    ],
  },
  {
    group: 'RAG',
    icon: 'Collection',
    items: [
      { path: '/rag/kbs', title: '知识库', scope: 'kb:manage' },
      { path: '/rag/search', title: '检索测试', scope: 'rag:search' },
    ],
  },
  {
    group: 'MCP',
    icon: 'Connection',
    items: [{ path: '/mcp/servers', title: 'MCP Server', scope: 'mcp:manage' }],
  },
  {
    group: 'Skills',
    icon: 'MagicStick',
    items: [{ path: '/skills', title: 'Skill 管理', scope: 'skills:manage' }],
  },
  {
    group: 'Agent',
    icon: 'ChatDotRound',
    items: [
      { path: '/agents', title: 'Agent 维护', scope: 'agents:manage' },
    ],
  },
  {
    group: 'Trace',
    icon: 'DataLine',
    items: [{ path: '/trace/sessions', title: 'Trace 会话', scope: 'trace:read' }],
  },
]
