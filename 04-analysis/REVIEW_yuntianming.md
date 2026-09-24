# REVIEW_yuntianming — agent-joker 设计文档独立审阅（测试/可验证性视角）

> 审阅人：云天明（测试工程师）｜任务：t_44419f1f｜日期：2026-09-22
> 审阅对象：`00-management/BRIEF.md`（§2 逐条原话为基准）、`01-product/FLOW_DIAGRAMS.md`、`01-product/FEATURES.md`、`02-development/ARCHITECTURE.md`、`02-development/DB_DESIGN.md`、`00-management/DESIGN_REVIEW.md`（验证其结论是否成立，可推翻）
> 方法：独立复核，不采信上游自测数字。本人复跑了 `05-temp/validate_d03.py`，并用独立脚本/正则对关键声明逐条重算（复算脚本：`05-temp/review_t44419f1f_check.py`）。对照口径：BRIEF §2 展开为 45 个标准 ID（B01–B05、S01–S04、L01–L03、R01–R10、M01–M03、K01–K02、A01–A04、SA01–SA03、TA01–TA03、G01–G06、T01–T02），逐条覆盖 4 份设计文档（图/功能点/架构/表）。
> 视角声明：作为测试工程师，除「是否覆盖」外，每条我还关注**可验收性**——验收标准是否可被黑盒验证（可构造输入/可观测输出/有失败判据）。

---

## 0. 对 DESIGN_REVIEW.md 既有终审结论的独立验证（任务要求第 2 条：可推翻）

复跑 `python3 05-temp/validate_d03.py` 输出与 DESIGN_REVIEW §0 声称一致：mermaid 9 块（ARCH 8 + DB 1）、组件清单 31 项、功能点 56 个、覆盖 56/56、ARCH §7 对照表行 39（脚本按宽松正则计，本人严格重算为 45 行，见下）、推测标注 ARCH 56/DB 119。

对 DESIGN_REVIEW 的 5 项不一致发现逐条验证：

| DESIGN_REVIEW 发现 | 本人独立验证 | 结论是否成立 |
|---|---|---|
| #1 P1 拦截边界（ARCH §1.1「不存在绕过拦截的路径」↔ §9-7「简易 agent 直调存储/RAG 内部 API 不经 ToolInterceptor」） | 核实：ARCH §1.1 数据流要点第 5 条原文即「不存在绕过拦截的路径（F: BFF-07 验收要点 3）」，而同文档 §9 表第 7 行裁定「简易 agent 直调存储内部 API（S3 流程图一致）」；S3 时序图中 `SAR->>RAG`、`SAR->>SS` 均为内部 API 直调，未画 ToolInterceptor 介入。两处措辞确实未对齐，且这两条路径只产生 `rag`/`file` trace 事件、不产生 `tool_call` 拦截事件，与 BRIEF G03「Agent 工具调用**必须**经过 BFF 统一拦截」及 FEATURES BFF-06 验收 1（「任一工具调用 trace 中均可看到 BFF 拦截记录（无绕过路径）」）存在字面冲突 | **成立**，且从测试视角比原文更严重：BFF-06 验收 1 是**可黑盒验证**的判据（抓 trace 事件），按当前文档实现，测试把「agent 发起的 RAG 检索/文件上传」判为工具调用时该验收必然 FAIL。若团队裁定这两条不算「工具调用」，必须把排除项写进 BFF-06 验收标准，否则测试无依据 |
| #2 P1 计数口径（「39 条」vs 45 个标准 ID） | 本人严格重算 ARCH §7 表格：`\| [A-Z]+0[0-9]` 行 = **45 行**（B01–B05/S01–S04/L01–L03/R01–R10/M01–M03/K01–K02/A01–A04/SA01–SA03/TA01–TA03/G01–G06/T01–T02，无重复、无缺漏）。FEATURES §10.1 与 ARCH §7 均写「39 条原话需求」，但 BRIEF §2 实际 bullet 行数（数一遍）= 41 行（基础 1 条长 bullet 含 5 个功能词；G 小节 6 行），39 既非 45 也非 41，口径无从对上 | **成立**（「39」这个数字本身三处都找不到出处，比「口径未说明」更差）。已覆盖性本身不受影响（45/45 逐行核对见 §2），但「逐条无遗漏」的自证口径失效，终审时无法复核 |
| #3 P2 DB §14「25 张表」vs「33 张」自相矛盾 | 核实 DB_DESIGN line 1120：「上图覆盖全部 25 张表（……共 33 张……）」，同句自相矛盾；实际枚举 33 张（§15 总表逐张列出，本人数过 = 33） | **成立** |
| #4 P2 表头「§7 九张」口径 | 核实 DB 文首：「§7 九张」；§7 实际 `###` 小节 6 个，`####` 勾选表 4 张，1+4+4=9。数字本身正确（§15 总表 §7 占 9 张），仅表述易误读 | **成立**（轻微） |
| #5 P2 S01 后端切换「既有文件处理策略」未成文 | 核实：DB §2 说明「访问时按行内 backend 分派」（= 保留原后端访问的隐含策略），但「是否迁移/选哪种策略」未显式成文；FEATURES STORE-03 验收 2 要求「既有文件在新后端下的处理策略（保留原后端访问/迁移）在设计文档说明」。当前文档只能推导出「保留原后端」，没有一句明确裁定 | **成立**（部分覆盖） |

**对 DESIGN_REVIEW 总体判定（PASS_WITH_ISSUES）的验证**：42 已覆盖 + 3 部分覆盖（S01/SA02/G03）的结论本人逐行复核无误；「无 P0、无整体缺失」成立；7 个推测项（P1–P7）全部闭环到 DECISION-002/003/004/005/006/007/019 并标注【推测】，本人逐一核对成立。**DESIGN_REVIEW 结论成立，不推翻**；但本人新增 3 项 DESIGN_REVIEW 未发现的 P2 问题（见 §3）。

---

## 1. 逐条对照表（BRIEF §2 第 2 节每一条原话 → 4 份设计文档覆盖情况）

> 覆盖情况判据：**完整** = 图/功能点/架构/表三层都有落点且验收可判；**部分** = 有落点但存在表述冲突、隐含未成文或验收判据有歧义；**缺失** = 任一层面无落点。证据列给出 文档+章节/表。

### 1.1 基础功能（B01–B05）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| B01 用户管理 | 完整 | FLOW §3.1；FEAT BASE-01；ARCH §1.1 IAMService；DB `users`（租户内唯一 username、status、重置密码、软删保留引用） | 无 |
| B02 角色管理 | 完整 | FLOW §3.1；FEAT BASE-02；ARCH §4.6；DB `roles`/`role_scopes`（内置角色、删除前校验引用 409） | 无 |
| B03 权限管理 | 完整 | FLOW §3.1；FEAT BASE-03；ARCH §4.6（scope 三类 + 并集计算 + `agent:use:<id>` 方案）；DB `scopes`/`role_scopes`/`user_roles` | 权限模型层级（用户→角色→scope）为【推测】，DESIGN_REVIEW R5 已列待用户确认，测试阶段按该模型构造用例即可 |
| B04 登入登出 | 完整 | FLOW §3.1+§4.1 S1；FEAT BASE-04/05/09；ARCH §2.1（bcrypt + JWT 双令牌 + 登出黑名单）；DB `auth_refresh_tokens` + Redis `joker:jwt:deny:<jti>` | 无（JWT 细节为【推测】P2，已闭环 DECISION-002） |
| B05 接口操作日志 | 完整 | FLOW §3.1；FEAT BASE-06（脱敏/筛选/写失败不阻断 3 个可验收点）；ARCH §4.1⑦；DB `api_audit_logs`（method/path/status/latency/ip + 组合索引支撑筛选） | 无 |

### 1.2 存储模块（S01–S04）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| S01 保存文件：本地路径 / GCS / OSS，配置文件可配置 | **部分** | FLOW §3.2（三分支图）；FEAT STORE-01/02/03；ARCH §2.2+§5.3（`STORAGE_BACKEND` 环境变量）；DB `storage_files.backend`/`storage_key` 行级记录落点 | 「后端切换后既有文件的处理策略（保留原后端 vs 迁移）」未显式成文（DESIGN_REVIEW #5/D3）。FEATURES STORE-03 验收 2 明确要求该策略在设计文档说明——测试无法对「未说明的行为」出判据。DB 行级 backend 分派只隐含「保留原后端」，需一句话裁定 |
| S02 访问文件：本地目录需统一接口，按文件名访问 | 完整 | FLOW §3.2；FEAT STORE-04；ARCH §3.1/§2.2（`GET /api/storage/files/{file_name}`，后端透明）；DB `storage_files` UNIQUE(tenant_id,file_name)，不存在 404/跨租户 403 行为已写明 | 同名文件策略（409 不版本化）为【推测】裁定（ARCH §9-10），已闭环，可验收 |
| S03 保存文件上传记录 | 完整 | FLOW §3.2；FEAT STORE-05；ARCH §2.2（UploadRecord）；DB `storage_upload_records`（source 枚举 api/mcp/agent/kb/skill + 失败也留痕 + 筛选索引） | 无 |
| S04 上传和访问文件接口都可注册为 MCP 工具 | 完整 | FLOW §3.2/§1（PlatformMCP-UploadDoc/QueryDoc）；FEAT STORE-06/07；ARCH §3.1（PlatformMCPServer 3 工具薄封装 + 内部 API 校验注入 token）；DB `mcp_tools`(source=platform) | 无 |

### 1.3 LLM 节点（L01–L03）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| L01 LLM endpoint 信息维护 | 完整 | FLOW §3.3；FEAT LLM-01；ARCH §1.1 LLMNodeService；DB `llm_endpoints`（base_url/model/api_key_enc/supports_vision/连通性测试/被引用禁删） | 平台级共享（租户可见彼此 endpoint）为【推测】裁定（ARCH §9-13），DESIGN_REVIEW R5 待确认；测试阶段按「平台级共享」出用例 |
| L02 embedding 模型信息维护 | 完整 | FLOW §3.3；FEAT LLM-02；ARCH §1.1；DB `llm_embedding_models`（dimensions 建库锁定，支撑换模型重嵌入行为） | 无 |
| L03 reranker 模型信息维护 | 完整 | FLOW §3.3；FEAT LLM-03；ARCH §1.1；DB `llm_reranker_models`（可选引用，NULL=跳过 rerank） | 无 |

### 1.4 RAG（R01–R10，核心模块）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| R01 创建知识库 | 完整 | FLOW §3.4；FEAT RAG-01；ARCH §2.2；DB `rag_knowledge_bases`（tag/embedding 必选锁定/rerank 可选/topK/阈值/切分默认/删除级联已声明） | 无 |
| R02 上传文档类型：txt、word、excel、pdf、png、jpg | 完整 | FLOW §3.4（6 类分支图）；FEAT RAG-02（非支持类型 422 可验收）；ARCH §2.2（DocParser 按扩展名分派 + 状态机）；DB `rag_docs.doc_type` + `status` 状态机 | 无 |
| R03 图片/扫描版 PDF/普通文档内图片 → LLM 视觉提供内容（论文公式、图表） | 完整 | FLOW §3.4 视觉分支 + §4.2 S2；FEAT RAG-03（4 个可验收点：公式截图/扫描 PDF/插图）；ARCH §2.2+§6#6（多模态 endpoint 过滤 supports_vision）；DB `rag_doc_images`（逐图记录 source_type 三态/vision_endpoint_id/vision_text/token） | 视觉不可用时的 OCR 降级路径标注为【推测】+ RISK 跟踪（ARCH §6#6），闭环可演示即可；降级行为若发生需在 trace 可见（`rag_doc_images.status=skipped` 已支撑） |
| R04 上传文档（调用存储模块 API） | 完整 | FLOW §4.2 S2（`RAG->>SS 保存原文件`）；FEAT RAG-02 验收 3（上传记录 source=kb 可查）；DB `rag_docs.file_id` FK storage_files | 无 |
| R05 切分策略：定长、父子、语义、结构化/文档树、表格 | 完整 | FLOW §3.4（5 策略分支）+ §4.2 S2；FEAT RAG-04（同文档 5 策略各切一次 + 父子两级互引 + 参数可配可重切）；ARCH §2.2+DECISION-020（5 策略工厂）；DB `rag_chunks.parent_id`/`split_strategy`/`is_table`/`split_params` + 库/文档两级覆盖 | 默认参数（500/50、1:4、0.25）为【推测】，DESIGN_REVIEW R4 待确认；均可配，不阻断 |
| R06 原文档查看 + 手动修改 chunk 内容 | 完整 | FLOW §3.4；FEAT RAG-05（改后检索返回新内容 = 向量联动可验收）；ARCH §2.2；DB `rag_chunks.content`（可编辑）/`edited_at`/`updated_by` 审计 + 「修改后必须重算 embedding」已写明 | 无 |
| R07 支持选择 embedding 模型、rerank 模型（可选） | 完整 | FLOW §3.4 检索分支；FEAT RAG-06/07；ARCH §2.2；DB `rag_knowledge_bases.embedding_model_id`/`reranker_model_id`（可空） | 换 embedding 模型 = 全库重嵌入任务（DECISION-006），`rag_knowledge_bases.status=reindexing` 支撑，期间检索用旧向量【推测】——测试可验证「切换期间不报错」 |
| R08 支持设置 topK、阈值 | 完整 | FLOW §3.4（阈值过滤分支）；FEAT RAG-08（阈值调至 1.0 返回 0 条 = 可验收）；ARCH §2.2+DECISION-006（阈值作用面裁定）；DB `top_k_default`/`score_threshold`/`recall_top_n` | 「单次检索参数覆盖库默认」仍为【推测】（DESIGN_REVIEW D4），开发时需明确 API 是否支持——测试用例依赖该判据 |
| R09 检索返回 chunk 索引及所在原文档位置，反向定位 | 完整 | FLOW §3.4 反向定位 + §4.2 S2；FEAT RAG-09（定位跳转可验收）；ARCH §2.2+§4.5（定位 URL `?file=&page=&section=&chunk=`）；DB `rag_chunks.chunk_index`（UNIQUE(doc_id,chunk_index)）+ `pos` JSONB（{page,section_path,char_start,char_end,table_row} 统一结构已裁定） | 位置表达形式为【推测】裁定（ARCH §9-11），已闭环，可验收 |
| R10 支持 MCP server，知识库查询接口做成 MCP 工具 | 完整 | FLOW §3.4+§1（PlatformMCP-RAGSearch）；FEAT RAG-10（工具返回 chunk+位置+tag 引用信息）；ARCH §3.1（`rag_search` 薄封装 `/internal/rag/search`）；DB `mcp_tools`(source=platform, rag_search, required_scopes=["rag:search"]) | 无 |

### 1.5 MCP（M01–M03）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| M01 通过 URL 注册 MCP server，支持多个 | 完整 | FLOW §3.5；FEAT MCP-01；ARCH §3.2（注册→连通性探测→tools/list 快照）；DB `mcp_servers`（url/transport/status online-unreachable/last_sync_at/多行即多个） | 无 |
| M02 显示每个 server 工具列表，禁用/启用/删除 | 完整 | FLOW §3.5；FEAT MCP-02（含平台内置工具同列）；ARCH §3.2（状态机：enabled × removed_remote × server.status）；DB `mcp_tools`（input_schema 快照/enabled/removed_remote/删除=平台侧移除远端不动） | 无 |
| M03 删除、禁用需提示可能存在关联的调用方 | 完整 | FLOW §3.5（关联检测 409 确认分支图）；FEAT MCP-03；ARCH §3.2（409 + agent 清单 + confirm=true 重试）；DB `agent_mcp_tools`（deleted_at IS NULL 查询主索引，SQL 已给出） | 关联范围限定为「agent 勾选」（FLOW §3.5 说明），是否含第三方 agent 提供方为【推测】——BRIEF 原话「可能存在关联的调用方」未限定范围，按最小实现（agent 勾选）可验收，建议开发阶段确认 |

### 1.6 Skills（K01–K02）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| K01 手动添加、上传 skill，维护名称、内容 | 完整 | FLOW §3.6；FEAT SKILL-01（手动/上传两形态 + 列表/删除/查询）；ARCH §1.1 SkillsService；DB `skills`（content/source manual-upload/version/status） | skill 运行时注入方式（提示词注入）为【推测】（DB §6.1），测试阶段可验证「勾选后 system prompt 含 skill 内容」 |
| K02 元数据存数据库，文件调用存储模块 API | 完整 | FLOW §3.6；FEAT SKILL-02（SQL 可验证 + 上传记录 source=skill）；DB `skills` + `skill_files`（file_id FK storage_files，元数据/文件分离） | 无 |

### 1.7 Agent（A01–A04）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| A01 创建、维护 agent 信息 | 完整 | FLOW §3.7；FEAT AGENT-01；ARCH §1.1 AgentService；DB `agents`（type/system_prompt/删除策略已写明：会话保留+引用级联+Redis 清除+obsidian 保留） | 无 |
| A02 类型：简易（本地 langchain）/ 第三方（URL 创建、维护、交互） | 完整 | FLOW §3.7；FEAT AGENT-02；ARCH §2.3/§2.4 双运行时 + DECISION-007（tool-calling loop）；DB `agents.type`/`third_party_url` | langchain 编排方式为【推测】P7 已闭环 DECISION-007；第三方「维护」= 编辑 URL/凭证配置（`agents` 表字段支撑），可验收 |
| A03 配置 LLM endpoint、RAG 库、MCP 工具、skills，从已存在列表勾选 | 完整 | FLOW §3.7（勾选关系图）；FEAT AGENT-03（4 候选来源 + 回显 + 未选不启用）；ARCH §1.2；DB 四张勾选表 `agent_llm_endpoints`/`agent_knowledge_bases`/`agent_mcp_tools`/`agent_skills` | 见 §3 新增问题 P2-1：四张勾选表中 3 张（7.2.1/7.2.2/7.2.4）字段表未列 `deleted_at`，但 7.2.1 的约束与 §13.1 均引用该列 |
| A04 对话交互、会话列表、对话详情 | 完整 | FLOW §3.7+§4.3/§4.4；FEAT AGENT-04（会话管理闭环）；ARCH §2.3/§2.4+§4.5（OpenAI 兼容）；DB `agent_sessions`（title/重命名/删除/message_count/total_tokens）+ `agent_messages`（role/tool_calls/citations/file_ids/token_usage 过程信息齐全） | 无 |

### 1.8 简易 agent（SA01–SA03）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| SA01 记忆：redis 短期 / pgsql 长期 / obsidian 知识沉淀 | 完整 | FLOW §3.7+§4.3 S3（三层读写已画）；FEAT AGENT-07/08（含 redis 不可用降级可验收点）；ARCH §2.3+DECISION-019；DB `agent_memories` + `agent_obsidian_notes` + §12 vault 目录结构 + Redis `joker:mem:*`（N=20/TTL 30min/互斥锁） | 长期记忆提炼时机（会话关闭或每 N 轮）与注入 top10 为【推测】（DB §7.5），验收 2「新会话引用旧事实」可验证，提炼时机只影响稳定性不影响可验收性 |
| SA02 交互涉及文件 → 上传到存储模块 | **部分** | FLOW §4.3 S3（文件分支 `SAR->>SS`）；FEAT AGENT-06（上传记录 source=agent 可查）；DB `storage_upload_records.source=agent` + `agent_messages.file_ids` + trace file 事件 | 该路径为**内部 API 直调、不经 ToolInterceptor**（ARCH §9-7 裁定），与 G03「必须经 BFF 统一拦截」字面冲突——即 DESIGN_REVIEW #1 拦截边界问题。文件上传本身有落点（表/事件/记录齐全），判「部分」只因拦截边界未裁定导致 BFF-06 验收判据悬空 |
| SA03 official tag 或用户明确要求 → 回复末尾附 RAG 来源，可链接原文对应位置 | 完整 | FLOW §4.3 S3（两条件「或」分支已画）；FEAT AGENT-05（三态可验收：official 附/非 official+要求附/其他不附）；ARCH §4.5（DECISION-017：show_citations 参数 + LLM 意图兜底）；DB `rag_knowledge_bases.tag` + `agent_messages.citations`（{doc_id,chunk_id,chunk_index,pos,url}） | tag 在**知识库级**（DB `rag_knowledge_bases.tag`），而 BRIEF 原话是「知识文档 tag 是 official」——按库级 tag 实现时，同库文档不可区分 official 与否，粒度粗于原话字面。DB `citations.kb_tag` 说明按库判定。此为可接受的设计简化（BRIEF 未定义文档级 tag 机制），但测试阶段需按「库级 tag」出用例并在验收前与用户确认粒度 |

### 1.9 第三方 agent（TA01–TA03）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| TA01 记忆由 agent 提供方实现 | 完整 | FLOW §4.4 S4；FEAT AGENT-09（平台不存/不注入可验收）；ARCH §2.4；DB `agent_sessions.external_session_id` + Redis `joker:session:ext:*`（仅透传句柄，无平台记忆表） | 无 |
| TA02 文件经存储模块 MCP 工具上传（平台提供工具，提供方决定是否调用） | 完整 | FLOW §4.4 S4（平台 MCP 工具分支）；FEAT AGENT-10（「不配置该工具对话仍正常」= 不强制的可验收表述）；ARCH §2.4/§3.1；DB `mcp_tools`(upload_doc/query_doc, platform) + `storage_upload_records.source=mcp:platform` | 无 |
| TA03 RAG 引用同上（平台提供检索结果及引用原文档信息，提供方决定是否显示） | 完整 | FLOW §4.4 S4（「是否显示由提供方决定」分支已画）；FEAT AGENT-11（平台侧引用信息完整性可验收）；ARCH §2.4/§4.5；DB `agent_messages.citations` | BRIEF 两处表述（MCP 工具形式 vs 平台直接提供信息）的歧义已由 ARCH §9-6 裁定为「双通道并存」并标注待复核（DESIGN_REVIEW R2）——测试阶段两条通道都要测，风险已记录 |

### 1.10 BFF 网关（G01–G06）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| G01 统一鉴权（Access Token）、流量控制、API 路由、协议转换（OpenAI 兼容） | 完整 | FLOW §3.8；FEAT BFF-01..04（401/429/404/标准 SDK 直连均可验收）；ARCH §4.1 管线①②④⑥；DB `bff_rate_limit_configs`（限流可配置持久化） | 无（限流默认值 50/10/5 为【推测】，可配置，DESIGN_REVIEW R6 待确认） |
| G02 chat 接口提取 tenant_id/user_id/scopes；校验用户是否有权访问目标 Agent（员工/管理员例） | 完整 | FLOW §3.1+§3.8；FEAT BFF-05（员工 403/管理员通过/跨租户 403 三用例）；ARCH §4.1③⑤+§4.6（`agent:use:<id>`/`agent:use:*` scope 落地）；DB `scopes`（agent 创建时自动 upsert 动态 scope）+ `agents` | 无（权限模型为【推测】P3，已闭环 DECISION-004，DESIGN_REVIEW R5 待用户确认） |
| G03 工具调用必须经 BFF 统一拦截（总则） | **部分** | FLOW §3.8（统一动作链 + scope 失败分支图）；FEAT BFF-06；ARCH §4.3/§4.4（两模式同一动作链 + trace 留痕）；DB `trace_events`(tool_call, status=denied, payload.scope_check/token_injected) | **DESIGN_REVIEW #1（P1）**：简易 agent 的 RAG 检索/文件上传走内部 API 直调不经拦截，ARCH §1.1「不存在绕过拦截的路径」与 §9-7 表述未对齐；BFF-06 验收 1 的字面判据（「任一工具调用 trace 中均可看到 BFF 拦截记录」）在裁定前无测试依据。这是全部 45 条中**唯一影响验收判定**的悬空点 |
| G04 简易 Agent：代码层拦截 LangChain Tool 执行回调 | 完整 | FLOW §4.3 S3；FEAT BFF-07（「直连底层工具库绕过回调的路径不存在」可验收）；ARCH §2.3/§4.3 模式①（InterceptorTool 工厂，无裸注册入口） | 实现为进程内共享库调用（DECISION-015），测试验证点 = trace 中 tool_call 事件必现 |
| G05 第三方 Agent：拦截 HTTP 响应中的 Tool Call 意图 | 完整 | FLOW §4.4 S4；FEAT BFF-08（trace 完整链路可验收）；ARCH §2.4/§4.3 模式②（DECISION-008：OpenAI tool_calls + /tool_results 回传 + 最大 8 轮） | 第三方协议为【推测】（DECISION-008），测试阶段需 mock 第三方 agent server（DESIGN_REVIEW D5/R7 已列），否则 G05/TA02/TA03 无法黑盒验收——测试准备项已明确 |
| G06 拦截三动作：校验 Scope；强制覆写参数（注入 Access Token 防越权）；BFF 机器凭证代理执行 | 完整 | FLOW §3.8（三动作 + 失败分支）；FEAT BFF-09（5 个可验收点：低权限拒绝/篡改 token 无效/跨租户被防/机器凭证抓包可验/业务侧二次校验）；ARCH §4.3（覆写规则到字段级：access_token/token/Authorization 一律覆写，tenant 锁定）；DB `mcp_tools.required_scopes` + `trace_events.payload`(machine_credential_ref) | 无；BFF-09 的 5 个验收点全部可黑盒构造（含「篡改 agent 传入 token 工具收到的仍是用户真实 token」这类强判据），设计质量高 |

### 1.11 Trace（T01–T02）

| BRIEF 条目（原话） | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| T01 记录每会话交互内容（含上传/生成文件）、工具调用、RAG 调用、时间点、token 耗费 | 完整 | FLOW §3.9（写点）+ S3/S4 时序；FEAT TRACE-01（五要素 + 文件事件 + 双 agent 均记录）；ARCH §4.4（tool_call 事件全字段）；DB `trace_sessions`（1:1 汇总 + 冗余计数）+ `trace_events`（message/file/tool_call/rag/system 五型 + payload 结构约定 + latency/created_at） | 文件事件记录的是文件名引用（与 UploadRecord 双向可追溯，FLOW §3.9），可验收；token 第三方 agent 由提供方报告否则 NULL（DB §7.4 已写明降级） |
| T02 对 trace 数据的检索功能 | 完整 | FLOW §3.9（多维检索）；FEAT TRACE-02（时间/用户/agent/会话/事件类型/关键词 + 下钻 + 租户隔离）；ARCH §4.7；DB `trace_events` 组合索引 + payload tsvector 全文索引（GIN） | 见 §3 新增问题 P2-2：`payload_tsv` 生成列在 §9.2 字段表中**未逐行列出**，仅出现在 §9.2 说明文字与 §13.2 索引清单，与「每张表全部字段逐行列出」要求不完全一致 |

### 1.12 BRIEF §6 交付物验收标准本身的符合性（附加核对）

| 交付物要求（BRIEF §6） | 判定 |
|---|---|
| FLOW_DIAGRAMS：覆盖全部 9 大模块；核心流程（登录鉴权、上传→解析→切分→检索、agent 对话含工具拦截、第三方 agent 对话）为时序图；关键分支（official tag 引用、工具 scope 校验失败、本地 vs 云存储）必须画出 | **符合**：§3.1–3.9 九模块齐全；S1–S4 四张时序图齐全；三个强制分支逐一核对均在图中（§3.2 上传三分支、§3.8/S3/S4 scope 失败 alt、§4.3/S4 official 分支） |
| ARCHITECTURE：服务划分、组件交互、关键时序、MCP server 设计、BFF 设计、部署拓扑、选型理由、与 BRIEF 逐条对照无遗漏 | **符合**：§1–§6 齐全（含 18 项选型理由表 + compose 拓扑）；§7 对照表 45 行全 ID 无遗漏（本人重算） |
| DB_DESIGN：按业务功能分章；每张表全部字段逐行列出（禁止概括省略）；覆盖全部 9 模块的表 + Redis key + obsidian 目录；ER 图；多租户隔离与索引策略说明 | **基本符合，有 2 处瑕疵**：分章 9 模块齐全（33 表）、Redis §11（15 key）、obsidian §12、ER §14、多租户 §10+索引 §13 均在；但①7.2.1/7.2.2/7.2.4 三张勾选表字段表漏列 `deleted_at`（而约束/级联引用了它）②`trace_events.payload_tsv` 生成列未进字段表——均违反「全部字段逐行列出」的字面标准（详见 §3 P2-1/P2-2） |
| DESIGN_REVIEW：三文档交叉检查 + BRIEF 逐条对照 + 遗留问题清单 | **符合**：本人独立验证其 5 项发现全部成立，未推翻任何结论 |

---

## 2. 总体结论

**部分符合（整体覆盖完整准确，无缺失项、无 P0；3 条部分覆盖 + 本人新增 3 项 P2，均可在开发前小成本收敛）。**

量化：45 个标准 ID 中 **42 完整 / 3 部分（S01、SA02、G03）/ 0 缺失**——与 DESIGN_REVIEW 终审判定一致，本人独立复核**不推翻**其 PASS_WITH_ISSUES 结论。

从测试视角的补充判断：

1. **可验收性整体优秀**。FEATURES 的 56 个功能点几乎每条都带了可黑盒构造的验收判据（状态码、可查询的表/记录、可抓包验证的凭证行为、可 SQL 验证的持久化），BFF-09 的 5 条、RAG-03 的 4 条尤其具体。设计阶段就给出失败判据，测试阶段可直接转用例。
2. **唯一的验收风险点是 G03/SA02 拦截边界（P1，R1）**：这不是「没设计」，而是「两条路径都设计了但边界未裁定」，且当前文档措辞自相矛盾（§1.1 vs §9-7）。**在裁定并统一表述之前，BFF-06 验收 1 无法出题**——测试会把它列为开发准入条件。
3. **第三方 agent 相关（G05/TA01–03/AGENT-09–11）的验收全部依赖 mock 第三方 agent server**（DECISION-008 协议尚未有实现）。DESIGN_REVIEW D5 已列测试准备项，测试侧确认：mock 必须在开发阶段完成并冻结协议，否则该模块验收阻塞。
4. **推测标注纪律好**：7 个 P 级推测项全部闭环到 DECISION 且标注，高风险推测（1536 维补零、阈值作用面、限流值）均进了 RISK/遗留清单，无「未决推测」。测试阶段对标注【推测】的行为一律按「行为与文档一致」出判据，不按猜测出判据。

---

## 3. 问题清单（按 P0/P1/P2）

### P0（阻塞）

无。未发现 BRIEF 需求整体缺失或三文档矛盾到无法实现的问题。

### P1（开发前必须裁定，不裁定则验收无依据）

| # | 问题 | 位置 | 要求 |
|---|---|---|---|
| P1-1 | **工具拦截边界未裁定**（继承 DESIGN_REVIEW R1，测试侧定性为开发准入条件）：简易 agent 的 RAG 检索与文件上传走内部 API 直调、不经 ToolInterceptor、不产生 tool_call 拦截事件；与 BRIEF G03「必须经过 BFF 统一拦截」及 BFF-06 验收 1「任一工具调用 trace 中均可看到 BFF 拦截记录（无绕过路径）」字面冲突；ARCH §1.1 与 §9-7 表述未对齐 | ARCH §1.1 数据流要点 5、§9 表第 7 行、FEATURES BFF-06 验收 1、DB §8 持久化裁定 | 罗辑+章北海裁定「工具调用」边界并统一表述：若 RAG 检索/文件上传不算工具调用 → 把排除项**写进 BFF-06 验收标准原文**（测试判据来源）；若算 → 这两条内部 API 路径须落 tool_call（或等价）trace 事件。裁定前本项不解除 |
| P1-2 | **「39 条」计数口径失效**（继承 DESIGN_REVIEW #2，测试侧升级表述）：FEATURES §10.1 与 ARCH §7 均声明「39 条原话需求」，但 ARCH §7 对照表实为 45 行标准 ID，BRIEF §2 原始 bullet 实为 41 行——「39」在两边都对不上，「逐条无遗漏」的自证口径无法复核 | FEATURES §10.1 核对句（line 655）、ARCH §7（line 637）、BRIEF §2 | 统一为「45 个标准 ID（源自 BRIEF §2 的 41 条 bullet，其中 5 条 bullet 各含多项）」或明确计数方法；否则终审对照表的行数基准不可信 |

### P2（开发阶段随手收敛，不影响验收框架）

| # | 问题 | 位置 | 要求 |
|---|---|---|---|
| P2-1 | **三张 agent 勾选表字段表漏列 `deleted_at`**：7.2.1 `agent_llm_endpoints` 的约束「uk_agent_llm_single(agent_id) WHERE deleted_at IS NULL」、7.2.2 的级联语义、7.2.4 的「agent_skills 级联清理」都引用 `deleted_at`，但三张表的字段表均未逐行列出该字段（7.2.3 `agent_mcp_tools` 有列）。违反 DB_DESIGN 文首「每张表全部字段逐行列出，禁止概括省略」的自设标准 | DB_DESIGN §7.2.1/7.2.2/7.2.4 | 三张表字段表补 `deleted_at` 行（或明确「本表无软删」并修正引用它的约束/级联描述） |
| P2-2 | **`trace_events.payload_tsv` 生成列未进字段表**：tsvector 生成列 + GIN 索引在 §9.2 说明文字与 §13.2 中出现，但 §9.2 字段表未逐行列出 `payload_tsv` | DB_DESIGN §9.2、§13.2 | 字段表补一行（类型 tsvector GENERATED ALWAYS AS (...) / 生成规则 / GIN 索引） |
| P2-3 | **S01 后端切换后既有文件处理策略未成文**（继承 DESIGN_REVIEW #5/D3）：DB 行级 `backend` 分派只隐含「保留原后端访问」，「不迁移」未显式裁定 | DB_DESIGN §2、ARCH §2.2、FEATURES STORE-03 验收 2 | 一句话裁定「保留原后端访问、不自动迁移」写入 ARCH/DB |
| P2-4 | 文字勘误（继承 DESIGN_REVIEW #3/#4）：DB §14「25 张表」→「33 张」；DB 表头「§7 九张」注明构成（1 定义 + 4 勾选 + 4 会话/消息/记忆/obsidian） | DB_DESIGN §14（line 1120）、文首（line 18） | 勘误 |
| P2-5 | **official tag 粒度**：BRIEF 原话为「知识**文档** tag 是 official」，设计落为**知识库级** tag（`rag_knowledge_bases.tag`），同库文档不可区分；属可接受的设计简化但粒度粗于原话字面 | DB_DESIGN §4.1（tag 字段）、§4.2（rag_docs 无 tag 字段）、FEATURES AGENT-05 | 开发前与用户确认按库级 tag 验收；若需文档级 tag，`rag_docs` 补 tag 字段（成本小，宜早定） |
| P2-6 | **MCP 关联调用方范围**：BRIEF「可能存在关联的调用方」未限定范围，设计只查 agent 勾选（`agent_mcp_tools`），第三方 agent 提供方的调用不在检测范围 | FLOW §3.5 关键分支说明、DB §7.2.3 | 按最小实现（agent 勾选）验收即可，建议开发阶段与用户确认是否够用 |
| P2-7 | **测试资产前置**：G05/TA01–03/AGENT-09–11 的黑盒验收全部依赖 mock 第三方 MCP server + mock 第三方 agent（实现 DECISION-008 协议）；当前 03-testing 仍为空模板 | ARCH §5.2（mock-mcp/mock-agent 行）、DESIGN_REVIEW D5/R7 | 测试侧确认：mock 资产在开发阶段完成、协议随 DECISION-008 冻结，列为开发→测试交接的检查项 |

### 对 DESIGN_REVIEW 的独立评价

DESIGN_REVIEW 的 5 项发现（P1×2 + P2×3）本人**全部验证成立**，其 PASS_WITH_ISSUES 判定、42+3 覆盖分布、7 推测项闭环结论均经独立复核无误，**不推翻**。本人新增 P2-1/P2-2（字段表完整性瑕疵）与 P2-5/P2-6/P2-7（验收粒度与测试前置项）为其未覆盖的补充；P1-1/P1-2 与其 R1/#2 同源，测试侧将 P1-1 定性为**开发准入条件**（裁定前 BFF-06 验收无法出题）。

---

*（完）REVIEW_yuntianming.md — 云天明（测试工程师），2026-09-22。独立逐条对照 45 标准 ID × 4 份设计文档，复跑上游自验 + 独立重算关键数字；结论：部分符合（42 完整 / 3 部分 / 0 缺失，无 P0；P1×2 开发前裁定，P2×7 记录）。只读审阅，未修改任何其他文档。*
