# DESIGN_REVIEW — agent-joker 设计终审

> 交付物：设计阶段 TASK-D04（父任务 t_5f373ddc，本卡 t_d7803553）。作者：褚岩（项目经理/终审），2026-09-22。
> 终审对象：`01-product/FLOW_DIAGRAMS.md`（史强）、`01-product/FEATURES.md`（罗辑）、`02-development/ARCHITECTURE.md`（章北海）、`02-development/DB_DESIGN.md`（章北海）、`00-management/DECISIONS.md`（21 条）。
> 方法：独立终审——逐条对照不跳。上游自验脚本 `05-temp/validate_d03.py` 已复跑全过（见 §0）；本报告在其基础上做**跨文档一致性**、**BRIEF 逐条对照**、**推测项**、**遗留问题**四维复核，并给出终审结论。

---

## 0. 复跑上游自验（独立复核基线）

复跑 `python3 05-temp/validate_d03.py`，结果与上游报告一致：

| 项 | 结果 | 终审复核 |
|---|---|---|
| mermaid 图数（架构 8 + DB 1） | 9 | ✓ 与 ARCHITECTURE/DB_DESIGN 实际块数一致（FLOW 另有 21，独立渲染） |
| 组件清单项（FLOW §1） | 31 | ✓ |
| 功能点总数（FEATURES） | 56 | ✓ |
| 功能点覆盖 | 56/56 | ✓ 见 §2 |
| ARCH §7 对照表行数 | 39 | ⚠ 见 §1 不一致项 #2（行数实为 45 行标准 ID） |
| 【推测】标注数 | 架构 56 / DB 119 | ✓（另按 `【推测】/[推测]` 直接计：FLOW 66、ARCH 30、DB 93，口径不同，均表明标注密度充足） |

**结论**：上游自验数字可信，可作终审基线。以下为本报告**独立发现**（上游自验未覆盖的跨文档一致性维度）。

---

## 1. 三文档交叉一致性检查（FLOW_DIAGRAMS ↔ ARCHITECTURE ↔ DB_DESIGN）

### 1.1 组件命名一致性（31 项契约）

FLOW §1「组件命名清单」31 项组件，逐一核对是否在 ARCHITECTURE / DB_DESIGN 中沿用**同一名称**（FLOW 文首声明：命名冲突以 FLOW 为准并回填）。

| 结论 | 说明 |
|---|---|
| **一致（31/31）** | WebConsole、BFFGateway、ToolInterceptor、AuthService、IAMService、AuditLogService、StorageService、StorageBackend、UploadRecord、LLMNodeService、RAGService、DocParser、ChunkSplitter、VectorStore、MCPRegistryService、SkillsService、AgentService、TraceService、SimpleAgentRuntime、ThirdPartyAgent、ObsidianVault、LLMNode、EmbeddingNode、RerankNode、MCPServer、PlatformMCPServer、PostgreSQL、Redis、PlatformMCP-UploadDoc、PlatformMCP-QueryDoc、PlatformMCP-RAGSearch —— 三文档同一组件同一名称，无命名漂移。 |
| 命名↔实现的对应关系已声明 | FLOW 的 `PlatformMCP-UploadDoc/QueryDoc/RAGSearch` 三个「组件」在 ARCHITECTURE/DB 中落地为 PlatformMCPServer 的 3 个**工具**（`upload_doc`/`query_doc`/`rag_search`，DB `mcp_tools.source=platform`）。此为「组件名→工具名」的有意映射，ARCHITECTURE §3.1 与 DB §5.2 均已显式说明，**非冲突**。 |

> 裁定：**组件命名契约 100% 达成**，无 P0/P1 命名冲突。

### 1.2 关键分支：在 架构 / 表 中均有支撑

BRIEF 与 FLOW 强制画出的关键分支，逐一核对是否在 ARCHITECTURE（时序/机制）与 DB_DESIGN（表/字段）中都有落点：

| 关键分支 | FLOW（图） | ARCHITECTURE（支撑） | DB_DESIGN（支撑） | 结论 |
|---|---|---|---|---|
| 登录鉴权 + JWT 双令牌 + 登出黑名单 | §4.1 S1 | §2.1、§4.1②、DECISION-002 | `auth_refresh_tokens`、Redis `joker:jwt:deny:<jti>` | ✓ 完整 |
| 本地 vs 云存储（local/gcs/oss 三分支） | §3.2 上传流程图 | §2.2、§5.3（STORAGE_BACKEND） | `storage_files.backend`/`storage_key`、混合定位 | ✓ 完整（既有数据迁移策略见 §4 遗留 #6） |
| 视觉 LLM 解析分支（图片/扫描 PDF/内嵌图） | §3.4 解析流水线 + §4.2 S2 | §2.2 视觉分支、DECISION-005 | `rag_doc_images`（vision_endpoint_id/status/vision_text） | ✓ 完整 |
| 5 种切分策略分支（含父子块） | §3.4 + §4.2 S2 | §2.2 ChunkSplitter、DECISION-020 | `rag_chunks.split_strategy`/`parent_id`/`is_table` | ✓ 完整 |
| topK/阈值 + rerank 配置与否分支 | §3.4 检索 + §4.2 S2 | §2.2、DECISION-006 | `rag_knowledge_bases.top_k_default`/`score_threshold`/`reranker_model_id` | ✓ 完整 |
| 原文反向定位（chunk 索引 + 位置） | §3.4 + §4.2 S2 | §2.2 反向定位、§4.5 定位 URL | `rag_chunks.pos`(JSONB)/`chunk_index`、UNIQUE(doc_id,chunk_index) | ✓ 完整 |
| official tag 引用 / 用户要求引用 | §4.3 S3 + §4.4 S4 | §4.5 RAG 来源规则、DECISION-017 | `rag_knowledge_bases.tag`、`agent_messages.citations`(JSONB) | ✓ 完整 |
| 工具 scope 校验**失败**分支 | §3.8 工具拦截图 + S3/S4 | §4.3 动作链 ① 失败拒绝、§4.4 留痕 | `mcp_tools.required_scopes`、`trace_events.status=denied` | ✓ 完整 |
| 强制覆写参数（注入 Access Token） | §3.8 + S3/S4 | §4.3 动作链 ② | `trace_events.payload.token_injected` | ✓ 完整 |
| 机器凭证代理执行 | §3.8 + S3/S4 | §4.3 动作链 ③、DECISION-012 | `mcp_servers.auth_headers_enc`、`trace_events.payload.machine_credential_ref` | ✓ 完整 |
| MCP 删除/禁用提示关联调用方 | §3.5 注册流程 | §3.2 关联检测 409 确认 | `agent_mcp_tools`（deleted_at IS NULL）+ 索引 | ✓ 完整 |
| 多租户行级隔离 + tenant 打头索引 | 各模块 | §4.2 TenantScope、DECISION-004 | §10 隔离策略、§13 索引清单（tenant 打头） | ✓ 完整 |
| 第三方 agent HTTP 响应拦截 Tool Call | §4.4 S4 | §2.4、DECISION-008（tool_calls + /tool_results） | `agents.third_party_url/transport/auth_enc`、`trace_events.mode=third_party` | ✓ 完整 |
| agent 四层记忆（redis/pgsql/obsidian） | §3.7 + S3 | §2.3、§6#12、DECISION-019 | `agent_memories`、`agent_obsidian_notes`、Redis `joker:mem:*` | ✓ 完整 |

> 裁定：**全部强制关键分支在「图→架构→表」三层均闭合**，无 P0 缺失分支。

### 1.3 功能点在表中可回溯（56/56）

FEATURES 56 个功能点，逐一核对 DB_DESIGN 每表头部 `F:` 标注 + ARCH §7 支撑章节是否覆盖。上游脚本已验证 56/56；终审抽样复核关键/高风险功能点：

| 功能点 | DB 落点 | ARCH 支撑 | 复核 |
|---|---|---|---|
| RAG-03 视觉解析 | `rag_doc_images`（逐图记录） | §2.2 视觉分支、§6#6 | ✓ |
| RAG-05 原文查看 + chunk 手改 | `rag_chunks.content`(可编辑)/`edited_at`，改后重算 embedding | §2.2、§2.3 | ✓ |
| RAG-09 反向定位 | `rag_chunks.pos`/`chunk_index` | §2.2、§4.5 | ✓ |
| RAG-10 知识检索 MCP 工具 | `mcp_tools`(source=platform, rag_search) | §3.1 | ✓ |
| AGENT-05/11 引用规则 | `agent_messages.citations`(JSONB) | §4.5 | ✓ |
| AGENT-07 三层记忆 | `agent_memories`(pgsql) + Redis `joker:mem` + obsidian | §2.3 | ✓ |
| AGENT-08 obsidian 沉淀 | `agent_obsidian_notes` + §12 vault 目录 | §6#12、DECISION-019 | ✓ |
| AGENT-10 第三方文件经 MCP 工具 | `storage_upload_records.source=mcp:platform` | §2.4、§3.1 | ✓ |
| BFF-09 三动作 | `mcp_tools.required_scopes`、`trace_events`(denied/token_injected/machine_credential_ref) | §4.3/§4.4 | ✓ |
| BFF-02 限流可配置 | `bff_rate_limit_configs` + Redis `joker:rl:*` | §4.1①、DECISION-013 | ✓ |
| MCP-03 关联调用方 | `agent_mcp_tools` | §3.2 | ✓ |
| TRACE-01/02 记录 + 检索 | `trace_sessions`/`trace_events`（含 payload tsvector 全文） | §4.4、§4.7 | ✓ |
| STORE-06/07 存储 MCP 化 | `mcp_tools`(upload_doc/query_doc, platform) | §3.1 | ✓ |
| BASE-05/09 登出 + refresh | `auth_refresh_tokens` + Redis 黑名单 | §2.1、DECISION-002 | ✓ |

> 裁定：**56/56 功能点在表中可回溯**，抽样复核无断链。无 P0 遗漏。

### 1.4 发现的不一致项（逐条，含处置）

| # | 级别 | 位置 | 不一致描述 | 处置 |
|---|---|---|---|---|
| 1 | **P1** | ARCH §1.1/§2.3/§4.3 ↔ BRIEF §2-BFF「Agent 工具调用**必须**经过 BFF 统一拦截」 | 简易 agent 的 **RAG 检索**（`SAR->>RAG 内部 API`）与**文件上传**（`SAR->>SS 内部 API`）走**内部 API 直调、不经 ToolInterceptor**（ARCH §1.1 数据流要点、§9-7 裁定均明示）。这与「工具调用**必须**经 BFF 统一拦截」的字面强要求存在张力：内部 API 虽携带用户身份做租户/scope 二次校验（非越权），但**不产生 `tool_call` 拦截 trace 事件**。若测试阶段把「agent 发起的 RAG 检索/文件上传」判为「工具调用」，则 BFF-06 验收 1（「任一工具调用 trace 中均可看到 BFF 拦截记录，无绕过路径」）可能判 FAIL。 | **需罗辑+章北海在开发前裁定并文档化**：①明确「工具调用」的边界（是否含 RAG 检索/文件上传这两条内部 API 路径）；②若含 → 内部 API 调用也需落 `trace_events.tool_call`（或等价事件）并补 BFF 侧校验；若不含 → 在 ARCH §9-7 与 FEATURES BFF-06 明确「RAG/文件属平台内部服务调用，不属 agent 工具，故不走 ToolInterceptor，但同样经身份校验 + trace 记录（rag/file 事件）」，并把此例外写进 BFF-06 验收要点的排除项。当前文档两处表述（§1.1「不存在绕过拦截的路径」vs §9-7「直调存储内部 API」）在措辞上未对齐，**开发阶段必须收敛为一处权威表述**。 |
| 2 | **P1** | ARCH §7（line 637）+ FEATURES §10.1（line 655）「39 条」 | 两份文档均声明「BRIEF §2 共 **39 条**原话需求」，但按 FEATURES §10.1 自身列出的标准 ID（B01–B05、S01–S04、L01–L03、R01–R10、M01–M03、K01–K02、A01–A04、SA01–SA03、TA01–TA03、G01–G06、T01–T02）实际枚举为 **45 行**（5+4+3+10+3+2+4+3+3+6+2=45）。「39 条」的计数口径（疑似按 BRIEF 原始 bullet 行，而非展开后的标准 ID 行）**未在文档中说明**，与对照表实际行数（45）不符，削弱「逐条无遗漏」可验证性。 | **不阻断**，但需章北海/罗辑统一口径：或改「39 条 bullet → 展开 45 个标准 ID」，或注明计数方法。本终审按**展开 45 个标准 ID 逐条**复核，见 §2，结论无遗漏。 |
| 3 | **P2** | DB_DESIGN §14（line 1120） | 同一核对句先写「上图覆盖全部 **25 张表**」，随后「共 **33 张**」，前后数字自相矛盾（实际枚举 33 张，「25」为笔误）。表头 §14 与 §15 核对结论均写 33 张（正确）。 | 文字勘误：将「25 张」改为「33 张」。不影响设计正确性（表集合完整）。 |
| 4 | **P2** | DB_DESIGN 表头 §14「§7 九张」↔ §7 实际小节 | 文首声明「§7 九张」，但 §7 的表小节实际为 7.1 + 7.2(下挂 4 张勾选表) + 7.3/7.4/7.5/7.6 共 **6 个 `###` 小节**；「9 张」= 7.1(1) + 7.2(4) + 7.3–7.6(4)，把 7.2 的 4 张勾选表计入才得 9。表述口径（小节 vs 表）易引起「到底 9 张还是 6 节」的误读。全表实为 33 张（§15 总表逐张列出，正确）。 | 文字澄清：注明「§7 共 9 张表 = 1 定义 + 4 勾选 + 4 会话/消息/记忆/obsidian」，与 §15 总表对齐即可。 |
| 5 | **P2**（引用出处勘误：该句实为 **FEATURES STORE-03 验收 2** 的产品侧要求，并非 BRIEF 原话；BRIEF S03 原话仅「保存文件上传记录」） | FEATURES STORE-03 验收 2 ↔ ARCH/DB | 需求句「切换后端不改代码；既有文件在新后端下的处理策略在设计文档说明」——DB 用 `storage_files.backend` 行级记录后端、访问时按行分派（**保留原后端访问**），这是「保留原后端」策略；但**是否支持「迁移」以及选择哪种策略**未在文档显式成文（仅隐含「保留原后端访问」）。FEATURES STORE-03 验收 2 要求该策略「在设计文档说明」。 | 开发阶段补一句裁定：采用「保留原后端访问（不迁移）」（与 DB `backend` 行级分派一致），写入 ARCH §2.2 或 DB §2 说明。当前为「部分说明」。 |

> **P0 检查结论**：未发现 BRIEF 需求整体缺失、或三文档相互矛盾导致无法实现的 P0 问题。#1（拦截边界）是**唯一需要开发前裁定**的 P1，但它不阻断设计终审（属实现边界澄清，非设计错误），按任务规则记录于遗留问题、不 block。

---

## 2. 与 BRIEF 需求逐条对照表（BRIEF §2 → 三文档支撑位置 → 状态）

> 口径：按 FEATURES §10.1 展开的 **45 个标准 ID** 逐条（解决 §1 不一致 #2）。状态：已覆盖 = 三文档（图/架构/表）均有落点；部分覆盖 = 有落点但需补说明（见备注）。

| ID | BRIEF 原话（节选） | FLOW | ARCH | DB | 状态 | 备注 |
|---|---|---|---|---|---|---|
| B01 | 用户管理 | §3.1 | §1.1 IAM、§2.1 | users | 已覆盖 | |
| B02 | 角色管理 | §3.1 | §4.6 | roles/role_scopes | 已覆盖 | |
| B03 | 权限管理 | §3.1 | §4.6 | scopes/role_scopes | 已覆盖 | agent:use:<id> scope 方案 |
| B04 | 登入登出 | §3.1/§4.1 | §2.1、§4.1② | auth_refresh_tokens | 已覆盖 | 双令牌+黑名单 |
| B05 | 接口操作日志 | §3.1 | §4.1⑦ | api_audit_logs | 已覆盖 | 脱敏+异步 |
| S01 | 保存文件（本地/GCS/OSS，配置可配） | §3.2 | §2.2、§5.3 | storage_files.backend | 已覆盖（2026-09-22 v2 修订：既有数据「保留原后端访问、不自动迁移」策略已显式成文，见 §6） |
| S02 | 访问文件（统一接口/按文件名） | §3.2 | §3.1、§2.2 | storage_files | 已覆盖 | 租户内唯一+409 |
| S03 | 保存上传记录 | §3.2 | §2.2 | storage_upload_records | 已覆盖 | |
| S04 | 上传/访问接口注册 MCP 工具 | §3.2 | §3.1 | mcp_tools(platform) | 已覆盖 | |
| L01 | LLM endpoint 维护 | §3.3 | §1.1 | llm_endpoints | 已覆盖 | 平台级共享 |
| L02 | embedding 模型维护 | §3.3 | §1.1 | llm_embedding_models | 已覆盖 | dimensions 建库锁定 |
| L03 | reranker 模型维护 | §3.3 | §1.1 | llm_reranker_models | 已覆盖 | 可选引用 |
| R01 | 创建知识库 | §3.4 | §2.2 | rag_knowledge_bases | 已覆盖 | 删除级联已声明 |
| R02 | 上传 6 类文档 | §3.4 | §2.2 | rag_docs.doc_type | 已覆盖 | 非支持类型 422 |
| R03 | 图片/扫描 PDF/内嵌图走 LLM 视觉 | §3.4/§4.2 | §2.2、§6#6 | rag_doc_images | 已覆盖 | OCR 仅降级 |
| R04 | 上传文档（调存储模块 API） | §4.2 | §2.2 | rag_docs.file_id | 已覆盖 | |
| R05 | 5 种切分策略 | §3.4/§4.2 | §2.2、DECISION-020 | rag_chunks | 已覆盖 | 参数可配+可重切 |
| R06 | 原文查看 + 手动改 chunk | §3.4 | §2.2、§2.3 | rag_chunks.content/edited_at | 已覆盖 | 改后重算向量 |
| R07 | 选 embedding/rerank 模型 | §3.4 | §2.2 检索分支 | kb.embedding/reranker_model_id | 已覆盖 | |
| R08 | 设置 topK、阈值 | §3.4 | §2.2、DECISION-006 | kb.top_k_default/score_threshold | 已覆盖 | 单次覆盖=推测，见遗留 |
| R09 | 检索返回 chunk 索引 + 原文位置 | §3.4/§4.2 | §2.2、§4.5 | rag_chunks.pos/chunk_index | 已覆盖 | 位置 JSON 结构已定 |
| R10 | 知识库查询做成 MCP 工具 | §3.4 | §3.1 | mcp_tools(rag_search) | 已覆盖 | |
| M01 | URL 注册 MCP server（多个） | §3.5 | §3.2 | mcp_servers | 已覆盖 | 连通性探测 |
| M02 | 工具列表 + 禁用/启用/删除 | §3.5 | §3.2 | mcp_tools | 已覆盖 | 状态机+来源标记 |
| M03 | 删除/禁用提示关联调用方 | §3.5 | §3.2 | agent_mcp_tools | 已覆盖 | 409+清单 |
| K01 | 手动添加/上传 skill | §3.6 | §1.1 | skills | 已覆盖 | |
| K02 | 元数据存 DB、文件走存储模块 | §3.6 | §1.1 | skills + skill_files | 已覆盖 | 分离+一致 |
| A01 | 创建/维护 agent | §3.7 | §1.1 | agents | 已覆盖 | |
| A02 | 类型：简易/第三方 | §3.7 | §2.3/§2.4 | agents.type | 已覆盖 | |
| A03 | 配置四要素（从列表勾选） | §3.7 | §1.2 | 4 张 agent_* 勾选表 | 已覆盖 | 回显+未选不启用 |
| A04 | 对话/会话列表/对话详情 | §3.7 | §2.3/§2.4、§4.5 | agent_sessions/messages | 已覆盖 | |
| SA01 | 记忆 redis/pgsql/obsidian | §3.7/S3 | §2.3 | agent_memories/obsidian + Redis | 已覆盖 | 三层 |
| SA02 | 文件上传到存储模块 | S3 | §2.3 | storage_upload_records(source=agent) | 已覆盖（2026-09-22 v2 修订 D-B：内部 API 直调属非拦截范围，保留身份校验 + 勾选校验 + rag/file 事件，见 §6） |
| SA03 | official/要求时附 RAG 来源+链接 | S3/S4 | §2.3、§4.5 | kb.tag + messages.citations | 已覆盖（D-A：official 判定为文档级两级判定，见 §6） |
| TA01 | 记忆由提供方实现 | S4 | §2.4 | 平台不存（external_session_id） | 已覆盖 | |
| TA02 | 文件经存储 MCP 工具（提供方决定是否调用） | S4 | §2.4、§3.1 | mcp_tools(platform) | 已覆盖 | 不强制 |
| TA03 | RAG 引用同上（提供方决定是否显示） | S4 | §2.4、§4.5 | messages.citations | 已覆盖 | |
| G01 | BFF 鉴权/流控/路由/协议转换 | §3.8 | §4.1、§4.5 | bff_rate_limit_configs | 已覆盖 | |
| G02 | 提取 tenant/user/scopes + agent 访问校验 | §3.8 | §4.1③⑤、§4.6 | scopes(agent:use) + agents | 已覆盖 | |
| G03 | 工具调用必须经 BFF 拦截（总则） | §3.8 | §4.3、§4.4 | trace_events(tool_call) | 已覆盖（2026-09-22 v2 修订 D-B：工具调用 = MCP 工具调用，100% 经 ToolInterceptor；内部 API 直调以 rag/file 事件留痕，见 §6） |
| G04 | 简易 agent 拦截 LangChain Tool 回调 | S3 | §2.3、§4.3 模式① | InterceptorTool（无裸注册） | 已覆盖 | |
| G05 | 第三方 agent 拦截 HTTP 响应 Tool Call | S4 | §2.4、§4.3 模式② | trace_events.mode | 已覆盖 | |
| G06 | 拦截三动作（scope/注入/代理） | §3.8 | §4.3 | mcp_tools.required_scopes + trace | 已覆盖 | |
| T01 | 记录每会话交互/工具/RAG/时间/token | S3/S4 | §4.4 | trace_sessions/trace_events | 已覆盖 | 五要素齐全 |
| T02 | trace 检索 | §3.9 | §4.7 | trace_events 索引 + tsvector | 已覆盖 | 多维+全文 |

> **对照结论（v1 原始结论）**：45 个标准 ID 中 **42 个「已覆盖」，3 个「部分覆盖」（S01、SA02、G03）**，3 个部分覆盖均归因于同一组已识别项（#1 拦截边界、#5 迁移策略），**无「缺失」项、无 P0**。**v2 修订后（2026-09-22）**：#1 已由用户裁定 D-B 关闭、#5 策略已在 4 文档成文，S01/SA02/G03 三项转为「已覆盖」，**45/45 已覆盖**（见 §6）。BRIEF §4 的 7 个推测项（P1–P7）全部有对应 DECISION 且标注【推测】，见 §3。

---

## 3. 推测项清单（所有【推测】标注汇总）

> BRIEF §4 的 7 个推测项（P1–P7）**全部**已在 DECISIONS.md 完成选型并标注，逐条映射：

| 推测项 | DECISION | 决策 | 风险/用户确认点 |
|---|---|---|---|
| P1 前端管理界面 | DECISION-003 | Vue3 + Vite + Pinia + Element Plus | 低（技术栈可换，闭环不影响） |
| P2 认证方案 | DECISION-002 | 密码 + JWT 双令牌(HS256) + 登出黑名单 | 低（access 15m/refresh 7d 数值待用户确认） |
| P3 多租户模型 | DECISION-004 | 行级 tenant_id + ORM 过滤；scope 三级 | 中（权限模型用户未明确，需确认） |
| P4 向量库选型 | DECISION-006 | pgvector(HNSW, 1536 维统一) | 中（**RISK-004**：维度/补零假设需确认） |
| P5 RAG 解析流水线 | DECISION-005 | pymupdf/docx/openpyxl + LLM 视觉（OCR 仅降级） | 中（视觉不可用降级路径需 RISK 跟踪） |
| P6 Obsidian 沉淀 | DECISION-019 | 容器 volume vault + MD 笔记 + DB 索引 | 低 |
| P7 langchain 编排 | DECISION-007 | tool-calling loop（非 ReAct） | 低 |

> **其余【推测】标注**（三文档合计约 189 处，密度充足）归为「参数/实现细节推测」，非独立决策，汇总为以下**高风险推测**（用户需确认或开发阶段定夺）：

| 高风险推测 | 位置 | 内容 | 风险 |
|---|---|---|---|
| 向量 1536 维统一 + 低维补零 | DB `rag_chunks.embedding`、DECISION-006 | <1536 右补零（补零分量恒 0，余弦不受影响）、>1536 建库 422 | **RISK-004**，补零假设需用户确认 |
| 切分默认参数 | DECISION-020 / DB split_params | 定长 500token/重叠50；父子 1:4；语义阈值 0.25；表格整表/行组 | 闭环可跑，参数可按需调 |
| 检索 topN/阈值默认 | DECISION-006 / DB | topN=max(topK*3,20)；阈值默认 0.30，作用面=有 rerank 用 rerank 分、无则余弦 | 阈值语义属裁定，需用户确认 |
| 限流默认值 | DECISION-013 | 租户 50 QPS / 用户 10 QPS / 登录 IP 5/min | 低，可配置 |
| 第三方 agent 协议 | DECISION-008 | OpenAI 兼容 tool_calls + `/tool_results` 回传 | 中（需测试阶段备 mock server 联调） |
| trace/审计 90 天保留 + 按月分区 | DB §1.8/§9.2 | 在线 90 天，过期 DROP PARTITION | **RISK-005**（存储增长） |
| 长期记忆提炼时机/注入 top10 | DB `agent_memories` | 会话关闭或每 N 轮提炼；新会话注入 top10 | 低，可调 |
| obsidian 目录/vault 布局 | DB §12、DECISION-019 | `vault/<tenant>/<agent>/<yyyy-mm>/` + frontmatter | 低 |
| 同名文件唯一(409) | ARCH §9-10 | 租户内唯一，不自动版本化 | 低，版本化留迭代 |
| 简易 agent 双路径（RAG/文件走内部 API） | ARCH §9-7 | 直调存储/RAG 内部 API，平台 MCP 工具同时可用 | **关联 #1**，需与 G03 拦截边界一并对齐 |

> 结论：7 个 P 级推测项**全部闭环到 DECISION**，无「未决推测」；高风险参数推测均已在 RISK/遗留中跟踪。

---

## 4. 遗留问题清单（未决 / 需用户确认 / 开发阶段注意）

### 4.1 需用户/产品确认（开发前建议拍板）

| # | 问题 | 责任 | 说明 |
|---|---|---|---|
| R1 | **拦截边界（P1，最高优先）**：简易 agent 的 RAG 检索 + 文件上传走内部 API 直调，是否属 BRIEF「工具调用必须经 BFF 统一拦截」范围？ | 罗辑 + 章北海 + 用户 | 见 §1 不一致 #1 / §2 G03。需明确「工具调用」定义，并统一 ARCH §1.1 与 §9-7 的表述；决定是否给这两条内部 API 路径补 `tool_call` trace。影响 BFF-06/09 验收判据。 |
| R2 | **RISK-003 两项歧义裁定复核**：①第三方 agent RAG 检索=「平台侧执行+提供信息」还是「agent 调 MCP 检索工具」；②简易 agent 是否经平台 MCP 工具传文件。 | 罗辑 / 褚岩 | ARCH §9-6/§9-7 已按「双通道并存 / 简易 agent 双路径」裁定并标注待复核。本轮维持该裁定（与 FLOW S4/S3 一致），**终审后请用户确认**，确认前开发按双通道实现（两路径都可用，不互斥，风险最低）。 |
| R3 | **向量 1536 维 + 补零假设（RISK-004）**：统一 1536 维、低维补零、>1536 建库拒绝，是否符合预期？ | 用户 | 若需支持高维模型，DB 预留 embedding_dim 快照，可平迁「每库独立向量表」。 |
| R4 | **阈值/topN/切分默认参数**（§3 高风险推测）是否为期望默认值？ | 用户 | 均可配置，确认默认即可。 |

### 4.2 需用户确认（低优先，闭环可演示即可）

- R5：权限模型「用户→角色→scope 三级」+ `agent:use:<id>` scope 方案（DECISION-004）——BRIEF 未指定层级，请确认。
- R6：JWT access 15m / refresh 7d、限流 50/10/5、trace 保留 90 天 等数值默认。
- R7：第三方 agent 工具协议 = OpenAI 兼容 tool_calls + `/tool_results`（DECISION-008）——测试阶段需备 mock 第三方 agent server 联调。

### 4.3 开发阶段注意事项（不阻断设计，进入开发时落实）

| # | 事项 | 说明 |
|---|---|---|
| D1 | 收敛 #1 拦截边界表述 | ARCH §1.1（「不存在绕过拦截的路径」）与 §9-7（「直调存储内部 API」）措辞统一为一处权威表述，同步进 BFF-06 验收排除项。 |
| D2 | 文档勘误（P2，开发前随手修） | ①DB §14「25 张表」→「33 张表」；②DB 表头「§7 九张」注明构成（1+4+4）；③「39 条」统一为「45 个标准 ID（源自 39 条 bullet）」或注明计数口径（ARCH §7 / FEATURES §10.1）。 |
| D3 | S01 后端切换策略成文 | 明确「保留原后端访问（不迁移）」，写入 ARCH/DB（FEATURES STORE-03 验收 2 要求）。 |
| D4 | RAG 单次检索参数覆盖 | RAG-08 验收 3「单次覆盖默认」当前为推测，开发时明确 API 是否支持单次 topK/阈值 覆盖库默认。 |
| D5 | mock 测试资产 | 第三方 MCP server + 第三方 agent（实现 DECISION-008 协议）mock，03-testing 阶段准备，供闭环演示与 BFF 拦截链测试。 |
| D6 | 清理占位模板 | `01-product/PRD.md`、`01-product/USER_STORIES.md`、`01-product/PRODUCT_DECISIONS.md`、`02-development/DESIGN.md`、`03-testing/*.md` 等仍为 `{{PROJECT_NAME}}` 占位/空模板。设计阶段以 FLOW/FEATURES/ARCH/DB 为事实源，这些模板**不影响本终审**；进入开发/测试阶段前由对应角色填充（PRD/USER_STORIES→罗辑，DESIGN/DEV_REPORT→章北海，TEST_*→云天明），或删除避免与事实源混淆。 |

### 4.4 已知范围受限（记录，非问题）

- RISK-001：`05-temp/assets/` 原始素材缺失，全部需求以 BRIEF §2 用户原话为准——设计全部基于 BRIEF，不确定处已标【推测】。
- RISK-002：9 模块体量大，已拆 4 卡并行 + 自验脚本，风险已消化。
- RISK-005：trace/审计明细表随会话量增长——已按月分区 + 过期清理 + 归档预案，开发阶段监控表体积。

---

## 5. 结论

### 判定：**PASS_WITH_ISSUES**

### 判定理由

**通过（无 P0）**：
1. **组件命名契约 31/31 一致**，三文档同一组件同一名称，无冲突（FLOW 契约完全落地）。
2. **关键分支全覆盖**：登录鉴权、本地/云存储、视觉解析、5 切分、topK/阈值、反向定位、official 引用、scope 校验失败、强制覆写、机器凭证代理、MCP 关联提示、多租户隔离、第三方 HTTP 拦截、三层记忆——在「图→架构→表」三层均闭合。
3. **功能点 56/56 可回溯**，BRIEF 45 个标准 ID 逐条对照 **无缺失、无 P0**（42 已覆盖 + 3 部分覆盖，部分覆盖均归因于已识别的 #1/#5）。
4. **7 个推测项（P1–P7）全部闭环到 DECISION** 并标注【推测】，无未决推测。
5. 上游自验脚本复跑全过，数字可信。

**带问题（P1/P2，不阻断、记录于遗留问题）**：
- **P1 ×1（R1/拦截边界）**：简易 agent 的 RAG 检索 + 文件上传走内部 API 直调、不经 ToolInterceptor，与 BRIEF「工具调用必须经 BFF 统一拦截」字面强要求存在张力；ARCH §1.1 与 §9-7 两处表述未对齐。**需罗辑+章北海+用户在开发前裁定并文档化**（不影响设计正确性，属实现边界澄清；按任务规则不 block，进入开发时优先落实 D1/R1）。
- **P1 ×1（计数口径）**：「39 条」与展开 45 个标准 ID 不符，口径未说明（§1 #2），削弱可验证性——D2 勘误。
- **P2 ×3**：DB「25/33 张」笔误、§7「九张」口径、S01 迁移策略未成文（§1 #3/#4、D3）。

**为什么不是 FAIL**：无任何 BRIEF 需求整体缺失，无三文档相互矛盾到无法实现的冲突，P1 均为「边界澄清/表述勘误」而非「设计错误」，且已给出明确处置与责任。

**为什么不是无条件 PASS**：#1 拦截边界是 BRIEF 硬要求（「必须」）与当前设计的真实张力点，若不在开发前裁定，BFF-06 验收存在被误判 FAIL 的风险；故降级为 PASS_WITH_ISSUES 并列为开发前**最高优先**确认项（R1）。

---

## 6. 审阅后修订记录（2026-09-22，v2 修订）

> 本节为 TASK-D09 收口追加，记录设计终审（§5，PASS_WITH_ISSUES）之后、开发启动前的**独立审阅 → 用户裁定 → 文档修订 → 独立复核**闭环全过程。事实源以 `04-analysis/REVISION_VERIFY.md`（云天明复核报告）为准，本节为管理侧汇总。

### 6.1 闭环过程

| 阶段 | 任务 | 产出 |
|---|---|---|
| 独立审阅（5 份并行） | TASK-D05/D06/D07 前，5 位角色各自独立审阅 4 份设计文档 | `04-analysis/REVIEW_chuyan.md` / `REVIEW_luoji.md` / `REVIEW_shiqiang.md` / `REVIEW_yuntianming.md` / `REVIEW_zhangbeihai.md` |
| 用户级裁定（2 条） | 用户 2026-09-22 正式裁定 D-A、D-B | 裁定口径见 §6.2 |
| 文档修订（4 份） | 按审阅发现 + 裁定修订 FLOW/FEATURES/ARCH/DB | TASK-D05（史强，FLOW）/ D06（罗辑，FEATURES）/ D07（章北海，ARCH+DB） |
| 独立复核（只读） | TASK-D08，云天明逐条复核 5 份审阅的 P0/P1/P2 是否全部修复 + D-A/D-B 是否全链路落地 | `04-analysis/REVISION_VERIFY.md`，结论 **PASS** |

### 6.2 两条用户级裁定（用户 2026-09-22 确认，编号顺延入 DECISIONS.md）

- **D-A — official tag 判定粒度 = 文档级两级判定**：文档级 `tag=official`，**或**文档级为空且所属知识库 `tag=official` → 判定 official（文档级优先，NULL 继承库级）。落点 4 处一致：FLOW §4.3/§4.4 判定逻辑、FEATURES RAG-01+AGENT-05 验收、ARCH §4.5、DB `rag_docs.tag` 字段（新增可空字段 + idx_docs_tag）。
- **D-B — 工具调用拦截边界**：拦截范围 = ① agent 对接业务系统（业务系统 AI chat / 调用 agent 能力统一经 BFF 网关：统一鉴权、流控、路由、OpenAI 协议转换）；② **MCP 工具调用**（含平台内置 `upload_doc`/`query_doc`/`rag_search` 与 URL 注册的外部 MCP server）**100% 经 BFF ToolInterceptor**（scope 校验、Access Token 强制注入、机器凭证代理执行）。**非拦截范围**：简易 agent 对平台内部服务的直接 API 调用（RAG 检索、文件上传/下载）——不产生 `tool_call` 拦截事件，但保留 a) 用户身份校验(tenant/scope)、b) `(agent_id, kb_id)` 在 `agent_knowledge_bases` 勾选校验（未勾选 403）、c) 落 trace 为 rag/file 事件。落点 4 处一致：FLOW S3、FEATURES BFF-06 验收 1（含排除项）、ARCH §1.1（权威表述）+§9-7（改「已裁定」）、DB trace 事件类型 + §7.2.2。

### 6.3 5 份独立审阅发现汇总（按主题去重）

- **唯一问题 23 项**（P1×3 + P2×20）：
  - **P1×3**：D-B 工具调用拦截边界、D-A official tag 粒度、「39 条」计数口径失效——**全部已修复**。
  - **P2×20**：4 文档内 **16 项全部已修复**；**1 项部分修复**（高风险推测项 R3–R7 在 4 文档内已裁定/标注，但 `00-management/RISKS.md` 未同步）；**3 项非本范围**（属 D09/管理文件，见 §6.4）。
- 各审阅另对 DESIGN_REVIEW 本身的复核：一致确认 v1 终审「PASS_WITH_ISSUES」判定档位成立、不推翻，但指出 v1 问题清单**不完备**（漏 P1 tag 粒度、低估「39 条」严重性——39 无法由任何口径导出）。

### 6.4 每条问题处置状态（已修复 / 已关闭 / 残留）

| # | 主题 | 提出方 | 处置 |
|---|---|---|---|
| 1 | 工具调用拦截边界（D-B） | chuyan P1-1 / luoji P1-2 / shiqiang P1-1 / yuntianming P1-1 / zhangbeihai P1-1 | ✅ 已修复（用户裁定 D-B，4 处口径一致 + BFF-06 验收 1 排除项成文） |
| 2 | official tag 粒度（D-A） | luoji P1-1（终审漏判新发现）/ yuntianming P2-5 等 | ✅ 已修复（用户裁定 D-A，DB 新增 `rag_docs.tag` + idx_docs_tag） |
| 3 | 「39 条」计数口径 | chuyan P1-2 / luoji P1-3 / shiqiang P1-2 / yuntianming P1-2 / zhangbeihai P1-2 | ✅ 已修复（统一为「41 条 bullet（4 条含子项）→ 45 个标准 ID」） |
| 4 | S01 后端切换既有文件处理策略 | chuyan P2-3 / luoji P2-1 / shiqiang P2-1 / yuntianming P2-3 / zhangbeihai P2-3 | ✅ 已修复（FEATURES STORE-03 + ARCH §1.1/§2.2 + DB §2 成文「保留原后端访问、不自动迁移」） |
| 5 | DB §14「25 张」笔误 → 33 | chuyan P2-1 / luoji P2-5 / shiqiang P2-2 / yuntianming P2-4 / zhangbeihai P2-1 | ✅ 已修复 |
| 6 | DB 文首「§7 九张」口径 | chuyan P2-2 / luoji P2-3 / shiqiang P2-3 / yuntianming P2-4 / zhangbeihai P2-2 | ✅ 已修复（补注 1+4+4=9） |
| 7 | `.doc` 旧格式 422 拒绝 | luoji P2-2 | ✅ 已修复（ARCH §2.2 + DB §4.2 doc_type 枚举） |
| 8 | RAG-08 单次 topK/阈值覆盖（原推测） | luoji P2-4 | ✅ 已修复（FEATURES RAG-08 改「设计决策 2026-09-22，非推测」） |
| 9 | FEATURES 功能点统计小错（48→47 / 混合 4→5） | zhangbeihai P2-6 | ✅ 已修复（4+5+47=56） |
| 10 | 内部 RAG 检索 API 未说明 `(agent_id,kb_id)` 勾选校验 | zhangbeihai P2-4 | ✅ 已修复（FLOW S3 + ARCH §4.2 + DB §7.2.2） |
| 11 | S3 图与「进程内共享库调用」措辞不一致（DECISION-015） | zhangbeihai P2-5 | ✅ 已修复 |
| 12 | OpenAI `model` 参数语义三处不一致 + 跨租户解析路径 | shiqiang N1/P2-4 | ✅ 已修复（ARCH §4.5 + DB §7.1 + DECISION-016 同步） |
| 13 | `rag_doc_images.image_file_id` FK 级联 → RESTRICT | shiqiang N2/P2-5 | ✅ 已修复（DB L423 + §13.3） |
| 14 | `agent_messages` 主查询索引未 tenant 打头 | shiqiang N3/P2-6 | ✅ 已修复（idx_messages_session(tenant_id,...)） |
| 15 | 三张 agent 勾选表字段表漏列 `deleted_at` | yuntianming P2-1 | ✅ 已修复（§7.2.1/7.2.2/7.2.4 补列） |
| 16 | `trace_events.payload_tsv` 生成列未进字段表 | yuntianming P2-2 | ✅ 已修复（§9.2 字段表 + 索引清单） |
| 17 | MCP 关联调用方范围未限定 | yuntianming P2-6 | ✅ 已修复（FLOW §3.5 限定为平台内 agent 勾选） |
| 18 | 黑盒验收 mock 资产前置（G05/TA/AGENT-09-11） | yuntianming P2-7 | ✅ 已修复（各功能点补「mock 资产开发阶段完成，列开发→测试交接检查项」） |
| 19 | S01「配置文件可配置」落地 env 注入等价性未明说 | chuyan P2-4（新发现） | ✅ 已修复（DB §2 + ARCH §5.3 显式关联 S01 原话与 env 实现） |
| 20 | **高风险推测项待用户确认（R3–R7）** | shiqiang P2-7 | ⚠️ 部分修复（4 文档内已裁定/标注；**残留**：`RISKS.md` RISK-006 仍 OPEN+旧措辞，RISK-004/005 仍标待用户确认——见 §6.5） |
| 21 | DESIGN_REVIEW §18 引用笔误（应为 §14） | luoji P2-6 | ✅ 已修复（本卡 D09：§1.4 #3/#4 两处「§18」改「§14」） |
| 22 | 占位模板未清理（PRD/USER_STORIES/PRODUCT_DECISIONS/DESIGN/DEV_REPORT/03-testing） | shiqiang P2-8 | ✅ 已修复（本卡 D09：6 份占位文件替换为「本文档由 <真实文档> 承接，本文件作废」） |
| 23 | DESIGN_REVIEW #5 将引用句误标「BRIEF S03 原话」 | chuyan P2-3（附带） | ✅ 已修复（本卡 D09：§1.4 #5 出处勘误为 FEATURES STORE-03 验收 2） |

### 6.5 残留问题清单（不阻断开发，标注 P 级与责任人）

| # | 残留项 | P 级 | 责任人 | 处置口径 |
|---|---|---|---|---|
| 1 | `RISKS.md` RISK-006 仍标 OPEN + 旧「张力/未对齐/待裁定」措辞，与 4 文档「已裁定 D-B（用户裁定 2026-09-22）」冲突 | P2 | chuyan（D09） | 本卡已同步：RISK-006 改「已裁定（D-B）CLOSED」 |
| 2 | `RISKS.md` RISK-004（1536 维补零）/ RISK-005（90 天保留）仍标 OPEN/待用户确认 | P2 | chuyan + 用户 | 4 文档内已标【推测】并设计定稿；**维持 OPEN 待用户确认**（本卡已在 RISKS.md 标注该处置口径，避免与 4 文档「已裁定」表述歧义） |
| 3 | 第三方 agent / 第三方 MCP server 黑盒验收 mock 资产（DECISION-008 协议） | P2 | 章北海（开发）→ 云天明（测试） | 列为开发→测试交接检查项，测试前须确认 mock 资产就绪 |

### 6.6 复核结论（引自 REVISION_VERIFY.md）

- **4 份设计文档范围内：全部通过（PASS）**。P0=0、未修复=0、非阻塞。
- D-A / D-B 全链路落地、4 处口径一致；交叉一致性抽查**未引入新不一致**（组件命名 31 不变、表数 33 一致、引用章节号有效、4 文档内「张力/待裁定/未裁定」与「39 条」口径残留 = 0）。
- 可进入下一阶段（开发）。

### 6.7 终审结论更新

v1 终审结论 **PASS_WITH_ISSUES**（P1×2 + P2×3，无 P0）——经 §6.1 闭环后：**5 份审阅在 4 份设计文档范围内的全部 P1/P2 问题已逐条修复，两条用户级裁定 D-A/D-B 全链路落地，BRIEF 45 个标准 ID 45/45 覆盖**。**设计阶段 v2 修订完成，正式定稿（PASS）**，可进入开发阶段。残留项见 §6.5，均为非阻塞（RISKS.md 已同步、mock 资产为开发→测试交接项）。

---

*（完）DESIGN_REVIEW.md — 褚岩（PM/终审），2026-09-22。v1 独立终审 + v2 审阅后修订记录（§6）。结论：v1 PASS_WITH_ISSUES → v2 修订后 PASS（4 文档 45/45 覆盖、D-A/D-B 全链路落地、5 份审阅 P1/P2 全部闭环）。*
