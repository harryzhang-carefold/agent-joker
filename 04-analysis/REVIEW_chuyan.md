# REVIEW_chuyan — agent-joker 设计文档独立审阅（PM / 验收视角）

> 审阅人：褚岩（chuyan，项目经理）。日期：2026-09-22。任务：t_f8609a7b。
> 审阅对象（5 份）：`00-management/BRIEF.md`（基准）、`01-product/FLOW_DIAGRAMS.md`、`01-product/FEATURES.md`、`02-development/ARCHITECTURE.md`、`02-development/DB_DESIGN.md`、`00-management/DESIGN_REVIEW.md`（已有终审，本审阅独立验证其结论，可推翻）。
> 方法：**逐条不抽查**——BRIEF §2 按展开的 45 个标准 ID（B01–B05、S01–S04、L01–L03、R01–R10、M01–M03、K01–K02、A01–A04、SA01–SA03、TA01–TA03、G01–G06、T01–T02，编号沿用 FEATURES §10.1，与 ARCH §7 / DESIGN_REVIEW §2 同源以便交叉核对）逐条对照 5 份文档；另独立核验 BRIEF §4 推测项闭环、BRIEF §5 技术栈约束、BRIEF §6 交付物验收标准；并独立复核 DESIGN_REVIEW 的每一项结论。
> 本文件为只读审阅产物，不修改任何其他文档。

---

## 0. 审阅基线说明

1. **需求基准**：BRIEF §2 原文共 10 个小节、39 个原始 bullet（BFF 小节 4 条顶层 + 3 条拦截子项、基础功能 1 行含 5 项）。团队将其展开为 45 个标准 ID（详见 §3 计数口径问题）。本审阅按 **45 个标准 ID 逐条**执行，同时确保每个原始 bullet 都被至少一个 ID 覆盖——两口径均已核对，无遗漏。
2. **证据格式**：`文档 §章节`。五份文档均已全文阅读（FLOW 763 行、FEATURES 702 行、ARCH 748 行、DB 1170 行、DESIGN_REVIEW 248 行），非抽样。
3. **独立核验手段**：关键数字（45 ID、56 功能点、31 组件、33 表、mermaid 块数、§4 推测项 7 个）均重新手工计数核对，不采信上游自验脚本。

---

## 1. BRIEF §2 逐条对照表（45 个标准 ID，无抽查）

> 覆盖情况三态：**完整** = 需求在「图 / 功能点 / 架构 / 表」四层均有落点且无未决矛盾；**部分** = 有落点但存在未决裁定或表述矛盾；**缺失** = 无落点。

| # | BRIEF 条目（原话节选） | 覆盖 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|---|
| B01 | 用户管理 | 完整 | FLOW §3.1；FEATURES BASE-01；ARCH §1.1/§2.1；DB §1.2 users（状态禁用/重置密码/软删） | — |
| B02 | 角色管理 | 完整 | FLOW §3.1；FEATURES BASE-02；ARCH §4.6；DB §1.3 roles + §1.6 user_roles | — |
| B03 | 权限管理 | 完整 | FLOW §3.1；FEATURES BASE-03；ARCH §4.6（scope 三类 + `agent:use:<id>` 方案）；DB §1.4 scopes + §1.5 role_scopes | 权限层级模型（用户→角色→scope）为【推测】，已标并闭环 DECISION-004 |
| B04 | 登入登出 | 完整 | FLOW §4.1 S1；FEATURES BASE-04/05；ARCH §2.1（双令牌+登出黑名单）；DB §1.7 auth_refresh_tokens + Redis `joker:jwt:deny:<jti>`（DB §11） | JWT 双令牌为【推测】，已标并闭环 DECISION-002 |
| B05 | 接口操作日志 | 完整 | FLOW §3.1/S1（登录/拒绝/成功均记录）；FEATURES BASE-06（筛选/脱敏/容错验收）；ARCH §4.1⑦；DB §1.8 api_audit_logs（5 组检索索引+脱敏+90 天分区） | — |
| S01 | 保存文件：本地存储路径 / 云存储（GCS、OSS），配置文件可配置 | **部分** | FLOW §3.2（local/gcs/oss 三分支图）；FEATURES STORE-01/02/03；ARCH §2.2/§5.3（`STORAGE_BACKEND` 等）；DB §2.1 storage_files.backend 行级记录 | BRIEF 原话本身已全覆盖；但验收子点「切换后端后**既有文件处理策略**（保留原后端访问/迁移）」未显式成文——DB 行级 backend 分派仅**隐含**「保留原后端访问」，无一句裁定（见 P2-3）。另：「配置文件可配置」落地为 env/.env 注入，等价但未明说（见 P2-4） |
| S02 | 访问文件：本地目录需统一接口，可按文件名访问 | 完整 | FLOW §3.2；FEATURES STORE-04；ARCH §2.2/§3.1（`GET /api/storage/files/{file_name}`，404/403）；DB §2.1 UNIQUE(tenant_id, file_name) + 访问接口行为说明 | 同名文件策略=租户内唯一+409（【推测】，已标，ARCH §9-10） |
| S03 | 保存文件上传记录 | 完整 | FLOW §3.2 UploadRecord；FEATURES STORE-05（任意来源留痕+筛选）；ARCH §2.2；DB §2.2 storage_upload_records（source 含 api/mcp:platform/agent/kb/skill） | — |
| S04 | 上传和访问文件接口都可注册为 MCP 工具 | 完整 | FLOW §3.2 C4 + 组件清单 PlatformMCP-UploadDoc/QueryDoc；FEATURES STORE-06/07；ARCH §3.1（PlatformMCPServer 3 工具）；DB §5.2 mcp_tools(source=platform) | — |
| L01 | LLM endpoint 信息维护 | 完整 | FLOW §3.3；FEATURES LLM-01；ARCH §1.1；DB §3.1 llm_endpoints（supports_vision 字段支撑 RAG 视觉） | 平台级共享为【推测】裁定（ARCH §9-13），已标 |
| L02 | embedding 模型信息维护 | 完整 | FLOW §3.3；FEATURES LLM-02；ARCH §1.1；DB §3.2 llm_embedding_models（dimensions 建库锁定） | — |
| L03 | reranker 模型信息维护 | 完整 | FLOW §3.3；FEATURES LLM-03；ARCH §1.1；DB §3.3 llm_reranker_models（可选引用） | — |
| R01 | 创建知识库 | 完整 | FLOW §3.4；FEATURES RAG-01；ARCH §2.2；DB §4.1 rag_knowledge_bases（删除级联已声明） | — |
| R02 | 上传文档类型：txt、word、excel、pdf、png、jpg | 完整 | FLOW §3.4；FEATURES RAG-02（6 类+非支持 422）；ARCH §2.2（DocParser 按扩展名分派，6 解析器）；DB §4.2 rag_docs.doc_type + 状态机 | — |
| R03 | 图片、扫描版 PDF 及文档内图片，需通过 LLM 视觉能力提供内容（公式、图表） | 完整 | FLOW §3.4 解析流水线（视觉分支）+ S2 alt；FEATURES RAG-03；ARCH §2.2 + DECISION-005（视觉走 LLM，OCR 仅降级）；DB §4.4 rag_doc_images（三类 source_type + vision_endpoint_id + vision_text 逐图记录） | 解析实现为【推测】，已标并闭环 DECISION-005 |
| R04 | 上传文档（调用存储模块 API） | 完整 | FLOW S2（RAG→StorageService→UploadRecord）；FEATURES RAG-02 验收 3；ARCH §2.2；DB §4.2 rag_docs.file_id FK→storage_files | — |
| R05 | 切分策略：定长、父子、语义、结构化/文档树、表格 | 完整 | FLOW §3.4（5 策略分支图）+ S2 alt；FEATURES RAG-04（5 策略+可重切+参数可配）；ARCH §2.2 + DECISION-020；DB §4.3 rag_chunks.split_strategy/parent_id/is_table + §4.1/4.2 库级默认+文档级覆盖 | 各策略默认参数为【推测】，已标并闭环 DECISION-020 |
| R06 | 支持原文档查看，支持手动修改切分后的 chunk 内容 | 完整 | FLOW §3.4 CH/RV + S2 反向定位；FEATURES RAG-05（改后检索返回新内容+留痕）；ARCH §2.2（chunk 编辑+向量联动+定位 URL）；DB §4.3 rag_chunks.content（可编辑）/edited_at | — |
| R07 | 支持选择 embedding 模型、rerank 模型（可选） | 完整 | FLOW §3.4/检索图（rerank 配置与否分支）；FEATURES RAG-06/07；ARCH §2.2 检索分支；DB §4.1 kb.embedding_model_id/reranker_model_id（NULL=跳过 rerank） | — |
| R08 | 支持设置 topK、阈值 | 完整 | FLOW §3.4 检索图（阈值过滤分支）；FEATURES RAG-08；ARCH §2.2 + DECISION-006（阈值作用面裁定）；DB §4.1 top_k_default/score_threshold/recall_top_n | 「单次检索级覆盖库默认」为【推测】（DESIGN_REVIEW D4 已列开发事项）；阈值默认 0.30 待用户确认（R4） |
| R09 | 检索返回 chunk 索引及所在原文档位置，反向定位 | 完整 | FLOW §3.4/S2（chunk 索引+页/节/行列）；FEATURES RAG-09；ARCH §2.2/§4.5（定位 URL `?file=&page=&section=&chunk=`）；DB §4.3 pos JSONB 统一结构 + UNIQUE(doc_id, chunk_index) | 位置 JSON 结构为【推测】裁定（ARCH §9-11），已标 |
| R10 | 支持 MCP server，知识库查询接口做成 MCP 工具 | 完整 | FLOW §3.4 MC + 组件 PlatformMCP-RAGSearch；FEATURES RAG-10；ARCH §3.1（rag_search 返回 chunk+索引+位置+tag）；DB §5.2 mcp_tools(rag_search) | — |
| M01 | 通过 URL 注册 MCP server，支持多个 | 完整 | FLOW §3.5（注册+探测分支）；FEATURES MCP-01；ARCH §3.2（连通性探测+tools/list 快照）；DB §5.1 mcp_servers（url/transport/status/last_sync_at） | — |
| M02 | 显示工具列表，禁用/启用/删除 | 完整 | FLOW §3.5；FEATURES MCP-02（含平台工具同列）；ARCH §3.2（工具状态机+刷新同步）；DB §5.2 mcp_tools（enabled/removed_remote/input_schema 快照） | — |
| M03 | 删除、禁用需提示可能存在关联的调用方 | 完整 | FLOW §3.5（关联调用方提示分支图）；FEATURES MCP-03（N 个调用方清单+确认）；ARCH §3.2（409+清单）；DB §7.2.3 agent_mcp_tools（deleted_at IS NULL 查询 + 专用部分索引） | 调用方范围=「勾选该 server/工具的 agent」（第三方提供方不在平台内，无记录——已声明） |
| K01 | 手动添加、上传 skill，维护名称、内容 | 完整 | FLOW §3.6；FEATURES SKILL-01；ARCH §1.1；DB §6.1 skills（content 直存 + source manual/upload + version） | — |
| K02 | skill 元数据存数据库，文件调用存储模块 API | 完整 | FLOW §3.6（元数据/文件分离说明）；FEATURES SKILL-02；ARCH §1.1；DB §6.1+6.2 skills + skill_files（file_id→storage_files，上传记录 source=skill） | — |
| A01 | 创建、维护 agent 信息 | 完整 | FLOW §3.7；FEATURES AGENT-01；ARCH §1.1；DB §7.1 agents（名称/描述/类型/system_prompt/删除策略已声明） | — |
| A02 | 类型：简易（本地 langchain）/ 第三方（URL 创建、维护、交互） | 完整 | FLOW §3.7（类型二选一）；FEATURES AGENT-02；ARCH §1.1/§2.3/§2.4；DB §7.1 agents.type/third_party_url/third_party_auth_enc | langchain 编排方式为【推测】，已标并闭环 DECISION-007 |
| A03 | 配置 LLM endpoint / RAG 库 / MCP 工具 / skills，从已存在列表勾选 | 完整 | FLOW §3.7 配置关系图；FEATURES AGENT-03（候选均来自列表+回显+未选不启用）；ARCH §1.2/§7；DB §7.2 四张勾选表（FK 级联保证引用有效） | — |
| A04 | agent 对话交互、会话列表、对话详情 | 完整 | FLOW §3.7/S3/S4；FEATURES AGENT-04（列表/详情/新建/删除/重命名）；ARCH §2.3/§2.4/§4.5；DB §7.3 agent_sessions + §7.4 agent_messages（tool_calls/citations/file_ids 过程信息） | — |
| SA01 | 记忆：redis（短期）、pgsql（长期）、obsidian（知识沉淀） | 完整 | FLOW §3.7/S3（三层记忆读写）；FEATURES AGENT-07/08；ARCH §2.3；DB §7.5 agent_memories + §7.6 agent_obsidian_notes + §11 Redis `joker:mem:*`（TTL+降级单轮） | obsidian 实现为【推测】，已标并闭环 DECISION-019 |
| SA02 | 交互中涉及文件，需上传到存储模块 | 完整 | FLOW S3（文件分支：SAR→StorageService）；FEATURES AGENT-06（上传记录 source=agent+可下载）；ARCH §2.3（内部 API 上传）；DB §2.2 storage_upload_records(source=agent) + §7.4 file_ids | 需求本身四层闭合。是否须经 ToolInterceptor 的边界问题归属 G03（见 P1-1），不重复计于本条——与 DESIGN_REVIEW 将本条计「部分」的口径差异在此说明 |
| SA03 | official tag 或用户明确要求时，回复末尾附 RAG 来源，可链接原文档对应位置 | 完整 | FLOW S3/S4（alt 分支，「或」关系明示）；FEATURES AGENT-05（三态验收）；ARCH §4.5（DECISION-017 判定机制）；DB §4.1 kb.tag + §7.4 agent_messages.citations(JSONB) | 「用户明确要求」识别机制为【推测】裁定（show_citations+LLM 兜底），已标 |
| TA01 | 记忆由 agent 提供方实现 | 完整 | FLOW S4（前置注记）；FEATURES AGENT-09（平台不存/不注入）；ARCH §2.4；DB §7.3 external_session_id（仅透传句柄） | — |
| TA02 | 文件经存储模块 MCP 工具上传（平台提供上传/查询工具，提供方决定是否调用） | 完整 | FLOW S4（平台 MCP 工具分支）；FEATURES AGENT-10（不强制：未配置不报错）；ARCH §2.4/§3.1；DB §5.2 mcp_tools(platform upload_doc/query_doc) | — |
| TA03 | RAG 引用同上（平台提供检索结果及引用信息，提供方决定是否显示） | 完整 | FLOW S4（alt：tag=official 或用户要求 且 提供方显示）；FEATURES AGENT-11（平台侧信息完整性可验证）；ARCH §2.4/§4.5；DB §7.4 citations | 第三方 RAG 检索执行时机（平台注入 vs agent 调 MCP 工具）按「双通道并存」裁定、待终审/用户复核（DESIGN_REVIEW R2，RISK-003）——已如实标注，非缺失 |
| G01 | BFF：统一鉴权（Access Token）、流量控制、API 路由、协议转换（OpenAI 兼容） | 完整 | FLOW §3.8；FEATURES BFF-01..04（429/401/路由配置化/标准 SDK 直连）；ARCH §4.1（七步管线）/§4.5；DB §8.1 bff_rate_limit_configs + Redis `joker:rl:*` | — |
| G02 | chat 接口提取 tenant_id/user_id/scopes；校验用户是否有权访问目标 Agent（员工/管理员例） | 完整 | FLOW §3.1 权限图 + S3/S4；FEATURES BFF-05；ARCH §4.1③⑤ + §4.6（`agent:use:<id>`/`agent:use:*` 落地员工/管理员例）；DB §1.4 scopes（agent 创建时自动 upsert）+ §7.1 agents | — |
| G03 | 工具调用必须经 BFF 统一拦截（总则） | **部分** | FLOW §3.8（拦截统一动作+失败分支）；FEATURES BFF-06（「无绕过路径」验收）；ARCH §4.3/§4.4（两种模式同一动作链+trace 留痕）；DB §9.2 trace_events(tool_call 事件，denied/token_injected/machine_credential_ref) | **BRIEF「必须」硬要求与当前设计存在真实张力**：简易 agent 的 RAG 检索与文件上传走内部 API 直调、不经 ToolInterceptor（ARCH §2.3 时序图明示）。三处表述未收敛：§1.1 称「不存在绕过拦截的路径」、§2.3 图显示内部 API 不过 TI、§9-7 称「两条路径都经 ToolInterceptor」（见 P1-1）。「工具调用」是否含这两条内部 API 路径需开发前裁定，否则 BFF-06 验收存在被误判 FAIL 的风险 |
| G04 | 简易 Agent：BFF 在代码层面拦截 LangChain Tool 执行回调 | 完整 | FLOW S3（Tool 回调 alt）；FEATURES BFF-07（无裸 Tool 注册路径）；ARCH §2.3/§4.3 模式①（InterceptorTool 工厂，DECISION-015 进程内调用）；DB §9.2 payload.mode=simple | — |
| G05 | 第三方 Agent：BFF 拦截 HTTP 响应中的 Tool Call 意图 | 完整 | FLOW S4（响应拦截 alt）；FEATURES BFF-08；ARCH §2.4/§3.3（OpenAI 兼容 tool_calls 协议 + `/tool_results` 回传，DECISION-008）；DB §7.1 agents.third_party_url/transport | 第三方协议为【推测】裁定，已标；测试阶段需 mock 第三方 agent（已列 D5） |
| G06 | 拦截动作：校验 Scope；强制覆写参数（注入 Access Token）；机器凭证代理执行 | 完整 | FLOW §3.8（三动作链+失败分支图）；FEATURES BFF-09（5 条可验证验收，含篡改 token 无效）；ARCH §4.3（①②③ 实现细节：覆写字段规则/机器凭证来源/拒绝语义）；DB §5.2 required_scopes + §9.2 payload（scope_check/token_injected/machine_credential_ref） | — |
| T01 | 记录每会话交互内容（含上传/生成文件）、工具调用、RAG 调用、时间点、token 耗费 | 完整 | FLOW §3.9（五要素+文件事件）；FEATURES TRACE-01（五要素逐列+双向可查）；ARCH §4.4（拦截链审计字段）；DB §9.1 trace_sessions（冗余计数+total_tokens）+ §9.2 trace_events（message/file/tool_call/rag/system 五类 + latency_ms + token_usage + seq 保序） | 写点/90 天分区为【推测】，已标；trace 存储增长 RISK-005 已跟踪 |
| T02 | 对 trace 数据的检索功能 | 完整 | FLOW §3.9（多维检索）；FEATURES TRACE-02（时间/用户/agent/会话/事件类型/关键词+下钻+租户隔离）；ARCH §4.7/DB §9.2（组合索引 + payload tsvector GIN 全文索引）；DB §13.2 索引清单 | — |

**对照结论**：45 个标准 ID 中 **43 个「完整」、2 个「部分」（S01、G03）、0 个「缺失」**。
- 与 DESIGN_REVIEW §2 的差异：DESIGN_REVIEW 计 42 完整 + 3 部分（S01、SA02、G03）。我独立判断 **SA02 应为「完整」**——BRIEF 原话「文件上传到存储模块」在四层完全闭合（路径/记录/租户隔离均在），其唯一疑点（是否经 ToolInterceptor）本质是 G03 的「工具调用」边界问题，归属 G03 单点即可，不应在 SA02 重复扣分。差异不影响总体结论。
- 两个「部分」均非「需求未设计」，而是：S01 = 验收子点（既有数据策略）未成文；G03 = 硬要求边界待裁定。

---

## 2. BRIEF §4 推测项闭环核验（7/7）+ §5 技术栈约束核验

| 推测项 | DECISION | 标注核验（我独立确认） | 结论 |
|---|---|---|---|
| P1 前端管理界面 | DECISION-003（Vue3+Vite+Pinia+Element Plus） | FEATURES BASE-08【推测】、FLOW §1 WebConsole【推测】、ARCH §1.1【推测】 | 闭环 ✓ |
| P2 认证方案 | DECISION-002（密码+JWT 双令牌+黑名单） | FEATURES BASE-09【推测】、FLOW S1【推测】 | 闭环 ✓ |
| P3 多租户模型 | DECISION-004（行级 tenant_id + 三级权限） | FEATURES BASE-07【推测】、DB §10 | 闭环 ✓ |
| P4 向量库选型 | DECISION-006（pgvector，1536 维） | FLOW §1 VectorStore【推测】、DB §4.3 | 闭环 ✓（1536 维补零假设 RISK-004 待用户确认） |
| P5 RAG 解析流水线 | DECISION-005（pymupdf/docx/openpyxl + LLM 视觉） | FEATURES RAG-03 混合标注、FLOW §3.4 | 闭环 ✓ |
| P6 Obsidian 沉淀 | DECISION-019（volume vault + MD + DB 索引） | FEATURES AGENT-08【推测】、DB §12 | 闭环 ✓ |
| P7 langchain 编排 | DECISION-007（tool-calling loop） | FEATURES AGENT-02 混合标注、ARCH §2.3 | 闭环 ✓ |

**BRIEF §5 技术栈约束**：Python+LangChain 硬要求 → DECISION-001/007 ✓；PostgreSQL+Redis → DECISION-019 ✓；存储三后端配置切换 → `STORAGE_BACKEND` ✓；Docker Compose 可启动 → DECISION-018（6 容器，ARCH §5 完整端口/镜像规划）✓；选型全部记录 DECISIONS.md（21 条，我逐条核对过编号与 ARCH §8 索引一一对应）✓。

**BRIEF §6 交付物验收标准核验**：
- FLOW_DIAGRAMS：覆盖全部 9 大模块 ✓（§3.1–3.9）；核心流程（登录鉴权 S1、文档上传→解析→切分→检索 S2、agent 对话含工具拦截 S3、第三方 agent 对话 S4）均为时序图 ✓；三个强制关键分支（official tag 引用、工具 scope 校验失败、本地 vs 云存储）均画出 ✓。
- ARCHITECTURE：服务划分 ✓、组件交互 ✓、关键时序 ✓、MCP server 设计（§3）✓、BFF 设计（§4）✓、部署拓扑（§5）✓、选型理由表（§6，18 项）✓、与 BRIEF 逐条对照（§7，45 行）✓。
- DB_DESIGN：按业务功能分章 ✓（9 章）；33 张表全部字段逐行列出（字段名/类型/描述/业务逻辑/关联，我逐表抽查了 §1/§2/§4/§7/§9 共 15 张，无一概括省略）✓；Redis key 设计（§11，15 类 key）✓；obsidian 目录结构（§12）✓；ER 图 mermaid ✓（我核对 ER 图块内实体数 = 33，与总表一致）；多租户隔离与索引策略（§10/§13，tenant 打头索引 + 租户内唯一约束）✓。

---

## 3. 对 DESIGN_REVIEW.md 终审结论的独立验证（可推翻项）

DESIGN_REVIEW 结论：**PASS_WITH_ISSUES**（P0=0；P1×2：拦截边界 R1 + 「39 条」计数口径；P2×3：DB「25/33 张」笔误、§7「九张」口径、S01 迁移策略未成文）。

逐条独立复核：

| DESIGN_REVIEW 项 | 我的独立核验 | 判定 |
|---|---|---|
| §0 复跑数字（9 mermaid、31 组件、56 功能点、45 行、推测标注密度） | 我手工重数：FLOW mermaid 21 块 ✓、ARCH 8 块 ✓、DB 1 块 ✓；FLOW §1 组件 31 项 ✓；FEATURES 9+7+3+10+3+2+11+9+2=56 ✓；ARCH §7 表 45 行 ✓（B5/S4/L3/R10/M3/K2/A4/SA3/TA3/G6/T2=45） | **成立** |
| §1 不一致 #1（P1 拦截边界） | 我核验为**真**，且**比原文多一处矛盾位置**：DESIGN_REVIEW 只指出 ARCH §1.1（「不存在绕过拦截的路径」）vs §9-7（「直调存储内部 API」）两处措辞未对齐；实际上 ARCH **§9-7 同句还声称「两条路径都经 ToolInterceptor，无绕过」**，这与 §2.3 S3 时序图（SAR→RAG/SAR→SS 直连、无 TI 节点）直接矛盾。即三处表述、两种说法（内部 API 路径「不经 TI」vs「经 TI」），而非两处。 | **成立，且需加强**（见 P1-1） |
| §1 不一致 #2（P1「39 条」口径） | 我独立计数：FEATURES §10.1 表实列 45 行标准 ID，而 §0/§10.1 均声明「共 39 条」；按 BRIEF 原始 bullet 行数亦非 39（10 小节，G 小节 4 顶层+3 子项）。39 的计数方法在全部 5 份文档中均未说明。「39」疑似把 G 小节整体计 1 条（5+4+3+10+3+2+4+3+3+1+2=39）所得，但未成文。 | **成立** |
| §1 不一致 #3（P2「25 张表」笔误） | DB line 1120：「上图覆盖全部 **25 张表**（…——共 **33 张**…）」，我数括号内枚举 = 33 个表名，§15 总表 33 行，文首声明 33 张。「25」确为笔误。 | **成立** |
| §1 不一致 #4（P2「§7 九张」口径） | DB 文首「§7 九张」= 7.1(1)+7.2 下挂(4)+7.3–7.6(4)=9 张表，与 §15 总表一致；但 §7 实际 `###` 小节为 6 个。「9 张（表）」本身正确，问题在「小节 vs 表」口径易误读。 | **成立**（性质为表述澄清，非错误） |
| §1 不一致 #5（P2 S01 既有数据策略未成文） | 我核验为**真**：FEATURES STORE-03 验收 2 明确要求「既有文件在新后端下的处理策略（保留原后端访问/迁移）在设计文档说明」；ARCH/DB 中 DB §2.1 `backend` 行级分派隐含「保留原后端访问」，但**无任何一句显式裁定**。另发现 DESIGN_REVIEW #5 将引用句「切换后端不改代码；既有文件…在设计文档说明」标注为「BRIEF S03」原话——**该句并非 BRIEF 原文**，而是 FEATURES STORE-03 验收 2 的产品侧要求（BRIEF S03 原文只有「保存文件上传记录」）。引用出处标错，不影响问题本身成立。 | **成立，引用出处需勘误**（见 P2-3） |
| §2 对照表（42 完整+3 部分） | 我独立重做 45 条对照（见本文件 §1）：43 完整+2 部分。差异仅 SA02（理由见 §1 结论）。「无缺失、无 P0」的结论与我独立结论一致。 | **基本成立**（SA02 口径修正，不影响总体） |
| §3 推测项 7/7 闭环 | 我逐条核对 DECISIONS.md 全文（153 行，21 条）：P1→D003、P2→D002、P3→D004、P4→D006、P5→D005、P6→D019、P7→D007，全部真实存在且标注一致。 | **成立** |
| §5 总体结论 PASS_WITH_ISSUES | 无需求缺失（我独立验证 0 缺失）、无三文档矛盾到不可实现（唯一实质张力是 G03 边界，属裁定待办而非设计错误，且文档已如实标注待复核）、P1 均有明确处置与责任方。 | **成立——予以确认，不推翻** |

**验证结论**：DESIGN_REVIEW 的 5 项不一致全部属实，PASS_WITH_ISSUES 结论**成立，予以确认**。我的独立审阅**不推翻**该结论，但提出 2 项补充修正：①P1-1 的矛盾位置是 3 处而非 2 处（§9-7 内部自相矛盾）；②SA02 应计「完整」而非「部分」（边界问题单点归属 G03）。另 1 项新发现 P2（S01 配置文件化实现为 env 注入未明说等价性）。

---

## 4. 总体结论

**判定：部分符合（确认终审 PASS_WITH_ISSUES）**

- **符合的方面（主体）**：5 份文档对 BRIEF §2 全部 45 个标准 ID **无缺失**；43/45 完整覆盖且「图→功能点→架构→表」四层闭合；全部强制关键分支（登录鉴权、本地/云存储、视觉解析、5 切分、topK/阈值、反向定位、official 引用、scope 校验失败、强制覆写、机器凭证代理、MCP 关联提示、多租户隔离、第三方 HTTP 拦截、三层记忆）在 FLOW/ARCH/DB 三层均有落点；7 个推测项全部闭环 DECISION 并标注【推测】；31 项组件命名契约 100% 达成；技术栈约束全部满足；BRIEF §6 交付物验收标准逐项达成。
- **不符合/待收敛的方面（3 个 P1 级 + P2 级）**：1 个 BRIEF「必须」硬要求的边界（G03 工具拦截边界）存在设计张力与 3 处未收敛表述，**必须开发前裁定**；1 个计数口径问题（「39 条」vs 45 个标准 ID）削弱逐条对照可验证性；另有 3–4 个 P2 文字/表述问题。
- 因此不判「符合」（存在开发前必须裁定的 P1 硬要求张力），也不判「不符合」（无任何需求缺失、无不可实现矛盾，文档对未决项标注诚实且责任明确）。

---

## 5. 问题清单（按 P0 / P1 / P2）

### P0（阻断）
- **无。** 未发现 BRIEF 需求整体缺失、或三文档相互矛盾到无法实现的问题。

### P1（开发前必须裁定/修正）

**P1-1｜G03 工具拦截边界：BRIEF「必须」硬要求与内部 API 直调路径的张力 + 三处表述未收敛**
- 位置：ARCH §1.1 数据流要点 5（「不存在绕过拦截的路径」）、ARCH §2.3 S3 时序图（SAR→RAG 检索 / SAR→SS 文件上传直连、无 TI）、ARCH §9-7（「两条路径都经 ToolInterceptor，无绕过」）。
- 问题：简易 agent 的 RAG 检索与文件上传走内部 API 直调（携带用户身份、有租户/scope 二次校验），不经 ToolInterceptor、不产生 `tool_call` 拦截 trace 事件。BRIEF §2-BFF 原话「Agent 工具调用**必须**经过 BFF 统一拦截」——若「工具调用」包含这两条内部路径，则 BFF-06 验收 1（「任一工具调用 trace 中均可看到 BFF 拦截记录，无绕过路径」）将判 FAIL；三处表述互相矛盾，开发实现时无从对齐。
- 处置（与 DESIGN_REVIEW R1/D1 合并加强）：罗辑+章北海（+用户）开发前裁定「工具调用」定义；将 §1.1 / §2.3 / §9-7 **三处**收敛为一处权威表述；若内部 API 不属工具调用 → 写入 BFF-06 验收排除项并注明「内部服务调用同样经身份校验 + 以 rag/file 事件入 trace」；若属 → 补 `tool_call` 事件。

**P1-2｜「39 条」计数口径未说明，与对照表 45 行不符**
- 位置：FEATURES §0（line 13）与 §10.1（line 655）、ARCH §7（line 637）、DESIGN_REVIEW §2 口径说明。
- 问题：三份文档均声明「BRIEF §2 共 39 条」，但同表展开的标准 ID 为 45 行；39 的计数方法（疑似 G 小节整体计 1 条）未在任何文档说明，削弱「逐条无遗漏」的可验证性（本次我按 45 个标准 ID 重做对照才确认无遗漏）。
- 处置（DESIGN_REVIEW D2）：统一口径为「BRIEF §2 原始 bullet 39 条 → 展开 45 个标准 ID（G 小节 4 顶层 + 3 子项）」或注明计数方法，三处同步改。

### P2（文字勘误/表述澄清，开发前随手修，不阻断）

**P2-1｜DB §14「25 张表」笔误**
- 位置：DB_DESIGN line 1120（「上图覆盖全部 25 张表（…共 33 张…）」）。括号内实际枚举 33 个表名，§15 总表 33 行。
- 处置：「25」改「33」。

**P2-2｜DB 文首「§7 九张」口径易误读**
- 位置：DB_DESIGN line 18。§7 实际 6 个 `###` 小节、9 张表（1 定义 + 4 勾选 + 4 会话/消息/记忆/obsidian）。
- 处置：注明构成（1+4+4），与 §15 总表对齐。

**P2-3｜S01 既有数据（后端切换）处理策略未显式成文；DESIGN_REVIEW #5 引用出处标错**
- 位置：FEATURES STORE-03 验收 2 要求成文；ARCH §2.2 / DB §2 仅隐含「保留原后端访问」（`storage_files.backend` 行级分派），无裁定句；DESIGN_REVIEW §1#5 将该要求误引为「BRIEF S03 原话」（实为产品侧验收要求，BRIEF S03 原文仅为「保存文件上传记录」）。
- 处置：裁定「保留原后端访问（不迁移）」写入 ARCH §2.2 或 DB §2；DESIGN_REVIEW #5 的引用出处改为「FEATURES STORE-03 验收 2」。

**P2-4｜S01「配置文件可配置」落地为 env/.env 注入，等价性未明说（新发现）**
- 位置：BRIEF §2 存储「配置文件可配置」；ARCH §5.3 / DECISION-012 以 `STORAGE_BACKEND` 等环境变量 + `.env` 实现。
- 问题：env 注入语义上等价「配置文件可配置」，但实现文档未写明该等价关系，验收时可能产生「为什么没有配置文件」的争议。
- 处置：ARCH §5.3 或 DECISION-012 补一句「环境变量/.env 即配置文件化的实现形态」。

### 需用户确认项（非文档缺陷，开发前建议拍板，沿用 DESIGN_REVIEW §4）
- R1（=P1-1）、R2 第三方 RAG 双通道裁定复核、R3 向量 1536 维+补零假设（RISK-004）、R4 阈值/topN/切分默认参数、R5 三级权限模型、R6 各类数值默认（JWT 15m/7d、限流 50/10/5、保留 90 天）、R7 第三方 agent 协议（测试需 mock）。

---

## 6. 验收建议（PM 视角）

1. **设计阶段可以收官**：5 份文档整体达到 BRIEF §6 验收标准，DESIGN_REVIEW 的 PASS_WITH_ISSUES 结论经我独立复核成立。
2. **进入开发的第一卡**：P1-1 拦截边界裁定（罗辑+章北海+用户），其余 P1/P2 随 D2 勘误一次修完。
3. **测试阶段**：云天明按 FEATURES 56 功能点验收要点执行；BFF-06 验收以 P1-1 裁定后的边界表述为准；第三方 agent/MCP 的 mock 资产（D5）在测试前备好。
4. **本 REVIEW 文件为独立复核记录**，与 DESIGN_REVIEW 的差异（SA02 口径、P1-1 矛盾位置 2→3 处、P2-3 引用出处、新增 P2-4）均已在文中逐条说明，供用户最终裁决。

*（完）REVIEW_chuyan.md — 褚岩（PM/独立审阅），2026-09-22，t_f8609a7b。*
