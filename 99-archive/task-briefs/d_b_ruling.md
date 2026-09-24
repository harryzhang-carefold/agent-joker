【D-B 裁定已由用户 2026-09-22 正式确认，覆盖此前任务书中"存在张力待裁定"的表述，按本口径写文档】

D-B 最终口径（用户裁定，文档中引用时写"用户裁定 2026-09-22"，不要再写成张力/待裁定/推测）:
- 拦截范围 = 两个边界:
  1. agent 对接业务系统: 业务系统 AI chat / 业务系统调用 agent 能力, 统一经 BFF 网关(统一鉴权 Access Token、流量控制、API 路由、OpenAI 兼容协议转换)
  2. MCP 工具调用(含平台内置 MCP 工具 upload_doc/query_doc/rag_search 和通过 URL 注册的外部 MCP server): 必须经 BFF ToolInterceptor 统一拦截(scope 校验、Access Token 强制注入、机器凭证代理执行)
- 非拦截范围(用户明确): 简易 agent 在 agent 管理平台内部对平台内部服务的直接 API 调用——RAG 检索、文件上传/下载等, 属于平台内部服务调用, 不产生 tool_call 拦截事件。但必须保留: a) 用户身份校验(tenant/scope); b) (agent_id, kb_id) 在 agent_knowledge_bases 勾选校验(未勾选 403); c) 落 trace 为 rag/file 事件。

文档措辞要求: 把"简易 agent 内部直调与 BRIEF 必须拦截存在张力/未裁定"类表述全部替换为上述边界定义; BFF-06 验收标准按此口径写(拦截 100% 覆盖 MCP 工具调用; 内部 API 直调以 rag/file 事件留痕); ARCH §1.1 与 §9-7 统一为此权威表述。
