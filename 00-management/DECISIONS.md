# DECISIONS — agent-joker

> 重要决策记录。技术选型、范围变更、流程调整都记录于此。
> 2026-09-22 起由章北海（TASK-D03）新增 21 条架构选型决策（DECISION-001..021），与 02-development/ARCHITECTURE.md §8 索引一一对应。
> 2026-09-22 追加 2 条用户级裁定（DECISION-022/023，对应审阅记录中的 D-A/D-B），用户 2026-09-22 正式确认（DESIGN_REVIEW §6）。
> 2026-09-22（TASK-D10）再追加 2 条用户级裁定（DECISION-024/025，对应 D-C/D-D）：向量维度按 embedding 模型维度（每库独立向量表）、trace/审计日志保留天数可配置（默认 90 天），用户 2026-09-22 正式裁定，RISK-004/005 关闭。

---

## DECISION-001
- **决策**：后端框架采用 **FastAPI（Python 3.12）**。
- **背景**：BRIEF §5 硬性要求 Python + LangChain；框架由团队选型。
- **备选**：Django（重、异步弱）；Flask（同步为主，SSE/长耗时 LLM 调用体验差）。
- **理由**：LangChain 硬要求 → 必须 Python；FastAPI 异步原生（SSE 流式、长耗时 LLM 调用不阻塞）、Pydantic 校验、OpenAPI 文档免费、Python 官方 MCP SDK 支持。
- **影响**：全部后端服务（BFFGateway / PlatformAPI / AgentRuntime）统一技术栈；团队需 Python 3.12 + async 开发能力。

## DECISION-002
- **决策**：认证方案 = **密码登录（bcrypt）+ JWT 双令牌**（access 15min 无状态 / refresh 7d 有状态存表）+ **登出黑名单（Redis）**。JWT 用 HS256（BFF 与 AuthService 共享密钥）。
- **背景**：BRIEF §4-P2「JWT 倾向，登入登出方式由团队确定」；BASE-05 要求登出后令牌不可用。
- **备选**：RS256 非对称（多服务公钥分发复杂，闭环无必要）；纯无状态 JWT（登出无法即时失效）。
- **理由**：refresh 有状态 → 登出/重置密码即时吊销；access 无状态 → BFF 本地校验零跨服务开销；黑名单兜底 access 未到期失效（TTL=剩余有效期）。
- **影响**：auth_refresh_tokens 表 + Redis `joker:jwt:deny:<jti>`；角色变更的权限生效窗口 ≤ access 有效期 15min（可接受）。

## DECISION-003
- **决策**：前端管理控制台采用 **Vue 3 + Vite + Pinia + Element Plus**。
- **背景**：BRIEF §4-P1 明确「Vue3 或 React（团队选型并记录 DECISIONS）」。
- **备选**：React + Ant Design（同样可行）。
- **理由**：团队 Vue 熟练度（【推测】）；Element Plus 管理台组件（表格/表单/树）齐全，覆盖用户/知识库/MCP/Agent 管理 + 会话详情页面。
- **影响**：WebConsole 为 SPA，Nginx 托管静态资源 + 反代（ARCHITECTURE §5）。

## DECISION-004
- **决策**：多租户 = **行级 tenant_id + ORM 强制过滤（shared-schema / row-level）**；权限模型 = **用户 → 角色 → scope 三级**；agent 访问控制落地为 **scope 项 `agent:use:<agent_id>`（含 `agent:use:*` 通配）**，不另建 agent-角色关系表。
- **背景**：BRIEF §4-P3 团队方案；FLOW_DIAGRAMS §5-2（权限层级未定）；BASE-03 要求「设计文档明确」agent 授权表达。
- **备选**：每租户独立 schema/独立库（隔离更强、运维成本高，闭环阶段过度）。
- **理由**：行级隔离实现成本最低、可验证（BASE-07 三条件）；scope 方案比关系表少一处映射，且与 JWT claims 的 scopes 数组天然对齐（BFF 校验无需二次查询）。
- **影响**：DB_DESIGN §10（隔离策略/索引策略）；所有业务表含 tenant_id 且主索引 tenant 打头。

## DECISION-005
- **决策**：文档解析库 = **pymupdf（pdf）+ python-docx（word）+ openpyxl（excel）+ 直读（txt）**；图片/扫描 PDF 走 **LLM 视觉解析**，**不前置 OCR 引擎**（OCR 仅作视觉 LLM 不可用时的降级路径）。
- **背景**：BRIEF §4-P5 解析流水线由团队设计；R03 原话要求视觉内容走 LLM 视觉能力。
- **备选**：tesseract/paddleocr 前置 OCR（与 BRIEF「LLM 视觉能力」原话冲突，且增加系统依赖，compose 可复现性下降）。
- **理由**：纯 Python、无系统依赖（docker 可复现）；pymupdf 同时提供 pdf 文本层提取 + 内嵌图片抽取 + 扫描版检测（无文本层 → 视觉分支）；openpyxl 将 Excel 转 Markdown 表格供表格切分策略。
- **影响**：RAG-03 视觉依赖 LLM 节点中 supports_vision=true 的 endpoint；视觉不可用降级路径记 RISK 跟踪。

## DECISION-006
- **决策**：向量库 = **pgvector（PostgreSQL 内，HNSW 索引，向量按库独立表存储——维度 = 该库所选 embedding 模型维度）**（原「统一 1536 维存储」已被 **D-C / DECISION-024，用户裁定 2026-09-22** 取代，见下）；检索阈值语义 = **有 rerank 时作用于 rerank 分数，无 rerank 时作用于余弦相似度**（两情况阈值均生效）；换 embedding 模型 = **全库重算向量（重建该库独立向量表）**（不做多模型并存）。
- **背景**：BRIEF §4-P4 向量库选型留给团队；FLOW_DIAGRAMS §5-5 阈值语义未定；FEATURES §11-7 换模型策略未定。
- **备选**：Qdrant/Weaviate 独立向量库（多一个服务 + 数据同步链路，闭环规模收益不足；检索接口已抽象为 VectorStore，规模上去可平迁）。
- **理由**：闭环规模（每库数千~数万 chunk）下 pgvector 性能足够；与元数据同库 → chunk 元数据与向量同库、检索 = 向量表召回 + 元数据 join（一致性）、部署简单（compose 一容器）。**【维度存储方式已由 D-C / DECISION-024 取代】**：原「1536 维统一存储（低维模型右补零，补零分量恒 0 不影响余弦相似度；>1536 维模型建库时 422 拒绝）」方案于 2026-09-22 被用户裁定「维度按库、每库独立向量表 `rag_chunks_vec_<kb_id>`」取代（废补零假设与 422 拒绝）。
- **影响**：DB_DESIGN §4.4 `rag_chunks_vec`（每库独立向量表，HNSW 按实际维度 N）+ §4.3 `rag_chunks.embedding`（向量不入本表，按库独立表存储）；`rag_knowledge_bases.embedding_dim` 记录该库实际维度（建库快照）；RISK-004 已 CLOSED（D-C）。

## DECISION-007
- **决策**：简易 agent 的 LangChain 编排方式 = **tool-calling loop（function-calling 循环）**，不用 ReAct。
- **背景**：BRIEF §4-P7 编排方式由团队设计。
- **备选**：ReAct（文本解析易碎、token 开销大、工具调用可靠性差）。
- **理由**：BRIEF 硬要求 LangChain（✓）；tool-calling loop 基于 LLM 原生 function-calling，工具调用结构化可靠，且 Tool 执行回调点清晰（BFF-07 拦截点 = InterceptorTool 工厂，无裸注册路径）。
- **影响**：SimpleAgentRuntime 实现；最大工具轮次可配（agents.max_tool_rounds，默认 8）。

## DECISION-008
- **决策**：第三方 agent 的 **Tool Call 意图协议 = OpenAI 兼容 `tool_calls` + 平台回传端点 `POST {agent_url}/tool_results`**；工具标识 = `mcp:<server_id>:<tool_name>`（第三方工具）/ `platform:<name>`（平台工具）。
- **背景**：BRIEF 未指定第三方 agent 的 tool call 意图表达（FEATURES §11-6 遗留）；BFF-08 要求「拦截 HTTP 响应中的 Tool Call 意图」。
- **备选**：自定义封闭协议（与外部生态不兼容）；stdio 本地进程（与 URL 注册矛盾）。
- **理由**：OpenAI 兼容格式是 LLM agent 生态通用表达，BFF 的 OpenAI 适配层可复用；/tool_results 回传形成闭环（BFF 拦截 → 代理执行 → 回传 → agent 继续推理，最多 max_tool_rounds 轮）。
- **影响**：测试阶段需准备 mock 第三方 agent server（实现该协议的样例，供闭环演示与测试）。

## DECISION-009
- **决策**：BFF → PlatformAPI 内部鉴权 = **`X-Auth-Tenant/X-Auth-User/X-Auth-Scopes` 头 + `X-Auth-Sig`（HMAC-SHA256 共享密钥签名）**；PlatformAPI 只信任签名头中的 tenant，不信任请求体 tenant 字段。
- **背景**：BFF-01 要求业务服务不重复实现 token 校验；BFF-09 验收 3 要求防租户越权（agent 参数篡改无效）。
- **备选**：mTLS（compose 内证书管理复杂）；完全信任内部网络（不满足越权防护验收）。
- **理由**：HMAC 签名防内部头伪造，实现简单无额外服务；「只信头不信体」是租户越权防护的关键不变量。
- **影响**：INTERNAL_HMAC_SECRET 环境变量；PlatformAPI 中间件校验签名。

## DECISION-010
- **决策**：MCP 工具列表同步 = **注册时 + 手动刷新时全量同步**（upsert 按 server_id+tool_name），**运行时不轮询**；调用失败（如远端工具已删）返回明确错误并触发一次后台重新同步。
- **背景**：MCP-01/02 要求连通性探测与工具列表管理；同步频率 BRIEF 未指定。
- **备选**：定时轮询（资源浪费，远端无变更时无意义）。
- **理由**：闭环规模下手动刷新足够；upsert 幂等；失败触发单次同步保证状态最终一致。
- **影响**：mcp_tools.last_sync_at / removed_remote 字段；Redis 工具快照缓存（10min）。

## DECISION-011
- **决策**：MCP 传输 = **Streamable HTTP（默认）+ SSE（兼容旧 server）**；不部署本地 stdio 进程。
- **背景**：BRIEF「通过 URL 注册 MCP server」→ 必须 HTTP 系传输。
- **备选**：stdio（与 URL 注册矛盾，排除）。
- **理由**：Streamable HTTP 是 MCP 规范现行标准传输；SSE 兼容存量 server。
- **影响**：mcp_servers.transport 字段；BFF 的 MCP 客户端需支持两种传输。

## DECISION-012
- **决策**：机器凭证（GCS/OSS 凭证、第三方 MCP server API key、LLM endpoint API key、BFF↔API 密钥）= **环境变量 / .env 文件（docker compose 注入）；DB 中的凭证字段（api_key_enc / auth_headers_enc / third_party_auth_enc）用 Fernet 对称加密存储；一律不落日志/trace 明文**。
- **背景**：BFF-09「BFF 使用自己的机器凭证」；FEATURES §11-5 机器凭证管理方式未定；STORE-02「凭证存配置文件（不进 DB）」。
- **备选**：专用密钥管理服务（Vault 等，自测阶段过度）。
- **理由**：compose 本地可启动约束下 .env 最直接；DB 中必须存的凭证（LLM endpoint key 等管理面数据）加密兜底；脱敏规则覆盖 api_audit_logs / trace_events payload。
- **影响**：.env.example 只含变量名不含真实值；日志中间件脱敏器。

## DECISION-013
- **决策**：流量控制 = **Redis 固定窗口计数**，三维度：**租户 QPS 默认 50 / 用户 QPS 默认 10 / 登录接口 IP 5 次每分钟**；阈值可配置（bff_rate_limit_configs 表 + Redis 镜像，运行时调整即时生效）；超限返回 429。
- **背景**：BFF-02 要求限流/配额、维度与配置可验证可调整。
- **备选**：令牌桶（精度更高、复杂度不值）；nginx limit_req（维度受限，无法按租户/用户）。
- **理由**：固定窗口实现简单、单机足够、验收可测（压测单用户超阈值被限，其他用户不受影响）。
- **影响**：Redis `joker:rl:*` keys；bff_rate_limit_configs 表。

## DECISION-014
- **决策**：API 路由 = **配置化 YAML 路由表（路径前缀 → 目标服务 + 路径模板），启动加载 + 热加载 API**；新增模块端点不改 BFF 代码。
- **背景**：BFF-03 验收 3 明确「路由变更无需改 BFF 代码（配置化路由——设计文档明确该机制）」。
- **备选**：硬编码路由（不满足验收）。
- **理由**：BFF 作为网关的路由与鉴权/限流解耦，配置化是验收硬性要求。
- **影响**：BFF_ROUTES_FILE 环境变量；路由热加载端点（需平台级权限）。

## DECISION-015
- **决策**：BFF 模式①拦截（LangChain Tool 回调）= **进程内共享库调用**（SimpleAgentRuntime 与 ToolInterceptor 同容器组，InterceptorTool 工厂直接调用拦截器函数），不走 HTTP 自调用。
- **背景**：BFF-07「代码层面拦截 LangChain 的 Tool 执行回调」；调用方式 BRIEF 未指定。
- **备选**：HTTP 自调用（127.0.0.1 回调，多一次网络往返、序列化开销、超时复杂度）。
- **理由**：同容器组内进程内调用最简单可靠，且「工具注册只走 InterceptorTool 工厂」的不变量更容易强制（无裸 Tool 注册入口，BFF-07 验收 3）。
- **影响**：bffgateway 容器双进程（API + SimpleAgentRuntime worker，共享拦截器库，DECISION-018）。

## DECISION-016
- **决策**：OpenAI 兼容协议转换 = **BFF 内置 adapter（块式 + SSE 流式双模式）**；`/v1/chat/completions` 的 `model` 字段 = agent 名称（tenant 内唯一）。
- **背景**：BFF-04 要求统一 OpenAI 兼容格式、标准 SDK 可直接对接。
- **备选**：各引擎各自转换（重复实现、格式漂移，排除）。
- **理由**：适配点集中于 BFF，业务服务无感；model=agent 名称映射使 OpenAI SDK 的 `client.chat.completions.create(model="客服Agent", ...)` 直接可用。
- **影响**：BFF 的 openai_adapter 模块；agent 名称唯一性约束（DB UNIQUE(tenant_id, name)）。

## DECISION-017
- **决策**：「用户明确要求显示引用来源」的识别机制 = **请求参数 `show_citations` 显式开关（true/false，默认取 agents.show_citations_default）+ LLM 意图判定兜底**（未显式指定时，由 LLM 判断用户消息是否要求引用，如「给我出处」）。
- **背景**：AGENT-05/11 的引用规则条件之一是「用户明确要求」（识别机制 BRIEF 未指定，FEATURES §11-3 遗留）。
- **备选**：纯 LLM 判定（不稳定）；纯界面开关（无法覆盖自然语言要求）。
- **理由**：显式参数保证确定性（验收可测：官方 tag → 强制附；show_citations=true → 附；两者都无 → 不附）；LLM 兜底覆盖自然语言场景（闭环可演示）。
- **影响**：chat 请求 schema 增加 show_citations 可选字段；引用判定逻辑在运行时/BFF。

## DECISION-018
- **决策**：部署 = **Docker Compose 单机 6 容器**（nginx / bffgateway（双进程：API+SimpleAgentRuntime worker）/ platformapi（双进程：API+解析 worker）/ pg（pgvector/pgvector:pg16）/ redis（redis:7-alpine）/ volume×2）；宿主机端口 8080。
- **背景**：BRIEF §5「Docker Compose 本地可启动（团队自测用）」。
- **备选**：K8s（自测阶段过度）。
- **理由**：compose 满足「本地可启动 + 环境可复现」；双进程容器避免为 worker 单起容器（闭环规模下资源更省）；端口 8080 避免与宿主机 80/443 冲突。
- **影响**：deploy/ 目录（Dockerfile.bff / Dockerfile.api / docker-compose.yml / .env.example）；镜像/端口明细见 ARCHITECTURE §5。

## DECISION-019
- **决策**：主数据库 = **PostgreSQL 16 + pgvector（单库承载全部元数据/长期记忆/trace/向量）**；Redis 7（短期记忆/缓存/限流/黑名单，自测环境关闭 AOF 持久化）；Obsidian 沉淀 = **容器 volume 目录 `vault/<tenant_code>/<agent_name>/<yyyy-mm>/` + Markdown 笔记（frontmatter 元数据）+ PG 索引表 agent_obsidian_notes**。
- **背景**：BRIEF §5 PG/Redis 硬约束；BRIEF §4-P6 Obsidian 实现由团队设计。
- **备选**：Obsidian Sync API（依赖外部账号，闭环不可控，排除）。
- **理由**：单库减少组件与同步链路；目录即 vault（可用 Obsidian 直接打开验证，AGENT-08 验收 2）；DB 索引表支撑「沉淀内容可被 agent 后续对话引用」（验收 3）。
- **影响**：DB_DESIGN §12；长期记忆（agent_memories，结构化）与 obsidian 笔记（长篇）双写不同源（同一会话沉淀事件一次生成两者）。

## DECISION-020
- **决策**：切分引擎 = **基于 LangChain text-splitters 基础组件扩展的 5 策略工厂**：定长（fixed，默认 500 token / 重叠 50）/ 父子（parent_child，父:子 ≈ 1:4【推测】）/ 语义（semantic，相似度断点阈值 0.25【推测】）/ 结构化-文档树（structured_tree，按标题层级自研）/ 表格（table，整表或按行组转 Markdown【推测】）；策略与参数库级默认 + 文档级覆盖，支持重切分。
- **背景**：RAG-04 要求 5 种策略、参数可配、可重新切分；FLOW_DIAGRAMS §5-4 参数未指定。
- **备选**：全部自研（重复造轮子）；仅 LangChain 默认 splitter（缺文档树/表格策略，不满足 R05）。
- **理由**：定长/父子/语义用现成组件降低风险，文档树/表格自研补缺；参数全可配满足验收 4。
- **影响**：rag_chunks.split_strategy/split_params；重切分 = 删旧 chunk + 重建向量。

## DECISION-021
- **决策**：文档解析任务队列 = **FastAPI 进程内任务队列（BackgroundTasks + rag_docs.status 状态机驱动）**，worker 单并发串行处理；预留 Redis 任务队列 key（`joker:task:queue`）供 worker 重启不丢任务的兜底。
- **背景**：RAG-02 要求文档状态可查（解析中/成功/失败）；任务队列实现方式 BRIEF 未指定。
- **备选**：Celery + broker（多一个组件，自测规模收益低）。
- **理由**：闭环规模（文档数级）下进程内队列零额外组件；状态机可查满足验收；规模上去可平迁 Celery（接口已抽象）。
- **影响**：platformapi 双进程（API + 解析 worker）；状态机 `uploaded→parsing→splitting→embedded→ready/failed`。

## DECISION-022（D-A：official tag 判定粒度 = 文档级两级判定）
- **决策**：「知识文档 official 标记」= **文档级两级判定**——文档级 `tag=official`，**或**文档级为空且所属知识库 `tag=official` → 判定为 official（文档级优先，NULL 继承库级）。DB 落地：`rag_docs` 新增可空字段 `tag text` + 索引 `idx_docs_tag`；`rag_knowledge_bases.tag` 为库级默认。
- **背景**：BRIEF R01/SA03 原话为「知识**文档** tag 是 official」，v1 设计落为**知识库级** tag（`rag_knowledge_bases.tag`，`rag_docs` 无 tag 字段），粒度粗于原话字面（罗辑独立审阅 P1-1 发现，云天明 P2-5 等亦提；DESIGN_REVIEW §1 终审漏判）。
- **备选**：维持库级 tag（同库文档不可区分 official 状态，粗于 BRIEF 字面）；库级+文档级并存（冗余，无收益）。
- **理由**：文档级两级判定精确对齐 BRIEF 原话；NULL 继承库级保证存量/未设文档级标记的文档仍可按库级官方标记参与引用判定，验收可测（同一知识库内混合官方/非官方文档，仅命中 official 判定者附来源）。
- **影响**：DB_DESIGN §4.2 `rag_docs.tag` 字段 + §13 索引；FEATURES RAG-01/AGENT-05 验收；ARCH §4.5 RAG 引用规则；FLOW §4.3/§4.4 判定逻辑。文档引用时写「用户裁定 2026-09-22（D-A）」。

## DECISION-023（D-B：工具调用拦截边界）
- **决策**：拦截范围 = 两个边界：
  1. **agent 对接业务系统**：业务系统 AI chat / 业务系统调用 agent 能力，统一经 BFF 网关（统一鉴权 Access Token、流量控制、API 路由、OpenAI 兼容协议转换）；
  2. **MCP 工具调用**（含平台内置 MCP 工具 `upload_doc`/`query_doc`/`rag_search` 与通过 URL 注册的外部 MCP server）：**100% 经 BFF ToolInterceptor 统一拦截**（scope 校验、Access Token 强制注入、机器凭证代理执行）。
  **非拦截范围**（用户明确）：简易 agent 在 agent 管理平台内部对平台内部服务的直接 API 调用——RAG 检索、文件上传/下载等，属平台内部服务调用，**不产生 `tool_call` 拦截事件**；但必须保留 a) 用户身份校验（tenant/scope）；b) `(agent_id, kb_id)` 在 `agent_knowledge_bases` 勾选校验（未勾选 403）；c) 落 trace 为 rag/file 事件。
- **背景**：BRIEF G03「Agent 工具调用**必须**经过 BFF 统一拦截」与 v1 设计中简易 agent 的 RAG 检索/文件上传走内部 API 直调（不经 ToolInterceptor）存在字面张力；ARCH §1.1 与 §9-7 表述未对齐，BFF-06 验收 1 判据悬空（5 份独立审阅 P1 级一致提出；DESIGN_REVIEW §1 #1 / R1）。
- **备选**：①内部 API 直调也落 `tool_call` 事件（口径过宽，平台内部服务调用被误计为 agent 工具调用，trace 语义失真）；②维持 v1 双表述（矛盾不可验收）。
- **理由**：用户 2026-09-22 裁定「工具调用 = MCP 工具调用」，内部 API 直调属平台内部服务调用不产生 tool_call，但保留身份校验 + 勾选校验 + rag/file 事件留痕——BRIEF「必须拦截」在 MCP 工具边界上 100% 满足，内部直调用等价留痕（rag/file 事件）+ 双重校验兜底，验收判据明确（FEATURES BFF-06 验收 1 已写明排除项）。
- **影响**：ARCH §1.1（单一权威表述）/ §9-7（改「已裁定」）/ §2.3 / §4.3-4.4；FEATURES BFF-06 验收 1 排除项；FLOW S3/S4 时序；DB trace 事件类型（tool_call/rag/file）+ §7.2.2 勾选校验。RISK-006 同步关闭。文档引用时写「用户裁定 2026-09-22（D-B）」。

## DECISION-024（D-C：向量维度按 embedding 模型维度，每库独立向量表）
- **决策**（**用户裁定 2026-09-22**）：**向量维度不固定、不按全平台统一，而是按各知识库所选 embedding 模型的真实维度存储**，落地为**每知识库一张独立向量表 `rag_chunks_vec_<kb_id>`**（命名规范 `rag_chunks_vec_<kb_id>`，kb_id = `rag_knowledge_bases.id`，建库时动态建表）。**废原「全平台统一 1536 维存储 + 低于补零 + 高于拒绝 422」方案**。必须满足 a) 不同 KB 可用不同维度；b) 检索只走该 KB 自己的向量表（不跨库 join）；c) KB 更换 embedding 模型后需**全量重算向量**（新建按新维度的向量表 → 全量重嵌入 → 切换引用 → DROP 旧表）；d) `rag_knowledge_bases.embedding_dim` 记录该库实际维度（建库快照 = 建库时所选 embedding 模型 `dimensions`）；e) 模型维度变更/删除的影响：已建库维度固化于 `embedding_dim` + 独立向量表不受影响，禁用/删除模型只影响「不可新选」，存量库向量表仍可检索；需迁移则走 c) 全量重算。
- **背景**：RISK-004——不同 embedding 模型维度不同，pgvector 向量列维度是表级固定的；原设计「全平台统一 1536 维 + 低维补零 + 高维 422 拒绝」中「补零对余弦相似度无影响」属【推测】，且 422 拒绝高维模型限制能力、统一 1536 维对低维模型是浪费、对高维模型是硬上限（DESIGN_REVIEW §4.1 R3 / §6.5 待用户确认）。用户 2026-09-22 正式裁定：维度不固定，按 embedding 模型维度。
- **备选**：①维持「全平台统一 1536 + 补零 + 422 拒绝」（高维模型被拒、低维浪费、补零假设【推测】，RISK-004 不闭环）；②单表 + 维度分列（列维度固定，仍需多列/分表，复杂）；③**每库独立向量表（本方案）**——天然按库维度、检索隔离、换模型即重建该库表。
- **理由**：每库独立表彻底解决「维度按库不同 + 表级固定」矛盾，满足 a–e 全部约束；与元数据（`rag_chunks`）同库 → 检索 = 向量表召回 + 元数据 join（同库）；换模型流程清晰可验证（重建该库向量表）；`embedding_dim` 建库快照防漂移。
- **影响**：DB_DESIGN §4.4 新增 `rag_chunks_vec` 每库独立向量表（含 kb 关联 + HNSW 按实际维度）；§4.1 `embedding_dim` 改「建库快照」、`status` 补换模型重算流程；§4.3 `rag_chunks.embedding` 说明改「向量按库独立表存储」；§13 索引清单同步（`idx_chunks_vec_embedding` 按维度 N）+ §13.3 FK；§14/§15 表数 33→34（rag_chunks_vec 进表清单）。ARCH §2.2 向量化/检索/建库流程、§7 R01、§6#4、§8 同步。RISK-004 关闭。文档引用时写「用户裁定 2026-09-22（D-C）」。

## DECISION-025（D-D：trace/审计日志保留策略天数可配置）
- **决策**（**用户裁定 2026-09-22**）：**trace_events + api_audit_logs 的保留天数可配置**，默认 90 天（默认值标注为设计决定，非推测）；保留天数由配置文件/环境变量（`TRACE_RETENTION_DAYS` / `AUDIT_RETENTION_DAYS`）控制；实现沿用既有设计——**按月分区 + 定期任务按配置天数 DROP PARTITION / 清理**（参数化，非硬编码 90）。
- **背景**：RISK-005——trace_events + api_audit_logs 事件级明细表随会话量增长，存储/查询压力上升；原设计「在线 90 天保留」属【推测】（DESIGN_REVIEW §6.5 待用户确认）。用户 2026-09-22 正式裁定：保留天数不写死，做成可配置，默认 90 天作为设计决定。
- **备选**：①硬编码 90 天（不可调，环境/规模变化时无弹性）；②不保留（无限增长）；③**可配置天数 + 月分区 + 过期 DROP PARTITION（本方案）**。
- **理由**：可配置覆盖不同环境/合规/成本诉求；默认 90 天为设计决定（不再标【推测】）；月分区 + DROP PARTITION 已有设计基础，仅参数化，改动小、可复现。
- **影响**：DB_DESIGN §1.8（api_audit_logs 保留策略）/ §9.2（trace_events 保留策略）：去【推测】，改「保留天数可配置（`AUDIT_RETENTION_DAYS`/`TRACE_RETENTION_DAYS`，默认 90 天，默认值为设计决定）；月分区 + 过期 DROP PARTITION」。`.env.example` 增 `TRACE_RETENTION_DAYS`/`AUDIT_RETENTION_DAYS`（默认 90）。ARCH §2.2 / 相关保留策略处同步。RISK-005 关闭。文档引用时写「用户裁定 2026-09-22（D-D）」。

## DECISION-026（S01 开发决策：DB 会话 = SQLAlchemy 2.0 async + asyncpg）
- **决策**（S01 后端骨架，章北海 2026-09-23）：DB 访问统一 **SQLAlchemy 2.0 async engine（asyncpg 驱动）+ 原生 SQL `text()`**；不引入完整 ORM 映射层（34 表结构已定稿于 DB_DESIGN，ORM 映射价值低、维护面大；后续切片如需 ORM 再评估）。写操作一律显式 `commit()`（session 不自动提交）；多语句 SQL 由 shared 层拆分为单语句逐条执行（asyncpg 不支持多语句一次执行）。
- **背景**：S01 卡范围 3 要求「DB session（SQLAlchemy + asyncpg 或同步 psql——自行选定并记录 DECISION）」。
- **备选**：同步 psql/psycopg（与 FastAPI async 事件循环冲突，需线程池）；同步 SQLAlchemy（同上，SSE/LLM 长耗时路径阻塞）。
- **理由**：FastAPI 全异步栈（DECISION-001）；asyncpg 为 PG 最快 async 驱动；原生 SQL 与 DB_DESIGN 定稿 DDL 一一对应，避免 ORM/DDL 双源漂移。
- **影响**：`services/shared/joker_shared/db.py`（engine/session/租户 auth context）；全部写端点显式 commit；`init_schema.sql` 由 shared 层拆分执行（幂等可重跑）。

## DECISION-027（S02 开发决策：存储后端切换 = env + 重启生效 + 行级 backend 分派）
- **决策**（S02 存储模块，章北海 2026-09-23）：存储后端（local / gcs / oss）切换采用 **`.env` `STORAGE_BACKEND` + 重启生效**（卡 body 明示「配置文件化不重启改不了的部分可接受」）；切换后**新上传走新后端**，**既有文件按 `storage_files.backend` 行内记录的实际落点分派访问（保留原后端访问、不自动迁移）**——与 DB_DESIGN §2 平台级说明、STORE-03 验收要点 3 的既有裁定一致，本决策将其落地为运行期行为。云 SDK（google-cloud-storage / oss2）为**可选依赖**（`services/requirements-cloud.txt`），未安装或凭证/bucket 缺失时后端构造/使用在**运行期返回明确配置错误（HTTP 503 `storage backend not configured: ...`，并落一条 `failed` 上传记录）而非进程崩溃**。
- **背景**：STORE-02/03 要求 GCS/OSS 可切换且不落代码；卡验收 2「无云账号时返回明确配置错误而非崩溃」。自测环境无 GCS/OSS 账号（闭环本地验证，不验远端），需保证配置存在性可验证、不破坏本地闭环。
- **备选**：①切换时自动迁移既有文件到统一后端（数据搬迁复杂、失败回滚难、超出闭环范围）；②后端配置落 DB 管理面（与 DECISION-012「凭证/存储配置不进 DB、走配置文件」冲突）；③**env + 重启 + 行级 backend 分派 + 运行期配置错误（本方案）**。
- **理由**：与既有设计裁定（DB_DESIGN §2、STORE-03 验收 3）零冲突；env 注入契合 DECISION-012 与 compose 一键启动约束；行级分派让「保留原后端访问」成为自然行为（`backend` 列本就是每文件落点记录）；运行期配置错误保证无云账号时闭环不崩、配置缺失可诊断。
- **影响**：`joker_shared/storage/{base,local,gcs,oss,service}.py`（新增）；`services/requirements-cloud.txt`（新增可选云 SDK）；`deploy/docker-compose.yml` / `.env.example`（GCS/OSS env 透传 + STORAGE_BACKEND）；`GET /api/storage/backends` 暴露各后端 configured/error 状态（不含凭证）。本地后端 `/data/storage` 由 api 容器 entrypoint 保证属主（named volume 首启 root 属主问题）。
