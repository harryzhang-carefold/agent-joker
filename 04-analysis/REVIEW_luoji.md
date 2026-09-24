# REVIEW_luoji — agent-joker 设计文档独立审阅（产品视角）

> 审阅人：罗辑（产品经理，profile: luoji）｜日期：2026-09-22｜任务：t_1375043e
>
> **审阅对象**（5 份）：
> 1. `00-management/BRIEF.md`（原始需求基准，§2 用户原话逐条）
> 2. `01-product/FLOW_DIAGRAMS.md`（史强，21 张 mermaid 图）
> 3. `01-product/FEATURES.md`（罗辑，56 功能点）
> 4. `02-development/ARCHITECTURE.md`（章北海，9 章）
> 5. `02-development/DB_DESIGN.md`（章北海，15 章/33 表）
> 6. `00-management/DESIGN_REVIEW.md`（褚岩终审——本审阅独立验证其结论是否成立，可推翻）
>
> **方法**：独立逐条对照，不抽查、不引用终审结论作为证据。全部 5 份文档已完整通读；
> 上游自验脚本 `05-temp/validate_d03.py` 由本审阅**独立复跑**（结果：mermaid 9 块、组件 31 项、
> 功能点 56/56 覆盖、BRIEF 规范 ID 45、ARCH §7 对照表 39 行——与终审 §0 一致）；
> BRIEF §2 bullet 计数由本审阅独立脚本重新清点（38 顶级 / 41 含子项，见 P1-3）。
>
> **覆盖情况判定口径**：
> - **完整** = BRIEF 原话每个语义点在 5 份文档中均有落点且语义一致；
> - **部分** = 有落点，但存在与 BRIEF 原话的语义偏差、未标注"推测"的偏离、或表述未对齐；
> - **缺失** = BRIEF 原话要点在 5 份文档中均无落点。

---

## 1. 逐条对照表（BRIEF §2 全部 45 个标准 ID，无抽查）

> 证据列格式：`FLOW §x / ARCH §x / DB §x / FEATURES <ID>`。
> 统计：**完整 41 条、部分 4 条（S01、SA03、TA03、G03）、缺失 0 条**。

### 1.1 基础功能（B01–B05）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| B01 用户管理 | 完整 | FLOW §3.1、§4.1 S1 / ARCH §1.1（IAMService）、§2.1 / DB §1.2 users（15 字段逐行）/ FEATURES BASE-01 | 无。创建/禁用/重置密码均有落点 |
| B02 角色管理 | 完整 | FLOW §3.1 / ARCH §1.1、§4.6 / DB §1.3 roles + §1.6 user_roles / FEATURES BASE-02 | 无。角色→权限并集生效机制明确（JWT 签发时计算） |
| B03 权限管理 | 完整 | FLOW §3.1（权限校验流程图）/ ARCH §4.6（scope 三类命名）/ DB §1.4 scopes + §1.5 role_scopes / FEATURES BASE-03 | 无。"用户→角色→scope 三级"为 BRIEF §4-P3 推测范围，已标【推测】并落 DECISION-004 |
| B04 登入登出 | 完整 | FLOW §4.1 S1 / ARCH §2.1（双令牌+黑名单）/ DB §1.7 auth_refresh_tokens / FEATURES BASE-04、BASE-05 | JWT 双令牌属 P2 推测范围，已标注；登出即时失效策略（黑名单）已裁定 |
| B05 接口操作日志 | 完整 | FLOW §3.1、S1 / ARCH §4.1⑦（BFF 中间件统一异步写）/ DB §1.8 api_audit_logs（15 字段+5 组合索引）/ FEATURES BASE-06 | 无。脱敏、写失败不阻断、按时间/用户/接口筛选均有落点 |

### 1.2 存储模块（S01–S04）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| S01 保存文件：本地/GCS/OSS，配置文件可配置 | **部分** | FLOW §3.2（上传流程图 local/gcs/oss 三分支）/ ARCH §1.1（StorageBackend 策略层）、§5.3（STORAGE_BACKEND 等环境变量）/ DB §2.1 storage_files.backend 行级记录 / FEATURES STORE-01..03 | **既有文件后端切换策略未显式成文**：DB 按行内 backend 分派 = 隐含"保留原后端访问（不迁移）"，但三份文档均未用一句话裁定该策略，而 FEATURES STORE-03 验收 2 明确要求"既有文件在新后端下的处理策略在设计文档说明"。详见 P2-1 |
| S02 访问文件：本地目录需统一接口、按文件名访问 | 完整 | FLOW §3.2 / ARCH §3.1、§2.2 / DB §2.1（访问接口行为说明：GET /api/storage/files/{file_name}，404/403 语义）/ FEATURES STORE-04 | 无。统一接口覆盖全部后端（BRIEF 仅要求本地场景，设计为超集，合规） |
| S03 保存文件上传记录 | 完整 | FLOW §3.2（UploadRecord）/ ARCH §2.2 / DB §2.2 storage_upload_records（source 含 api/mcp/agent/kb/skill）/ FEATURES STORE-05 | 无。任意来源上传均留痕、可筛选 |
| S04 上传/访问接口可注册为 MCP 工具 | 完整 | FLOW §3.2（PlatformMCP-UploadDoc/QueryDoc）/ ARCH §3.1（平台内置 3 工具）/ DB §5.2 mcp_tools（source=platform）/ FEATURES STORE-06、STORE-07 | 无。BRIEF 说"可注册"，设计做成固定平台工具（能力超集），且被第三方 agent（TA02）消费闭环 |

### 1.3 LLM 节点（L01–L03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| L01 LLM endpoint 信息维护 | 完整 | FLOW §3.3 / ARCH §1.1 / DB §3.1 llm_endpoints（含 supports_vision、加密 api_key、连通性测试）/ FEATURES LLM-01 | 无。平台级共享为【推测】裁定（ARCH §9-13），已标注 |
| L02 embedding 模型信息维护 | 完整 | FLOW §3.3 / ARCH §1.1 / DB §3.2 llm_embedding_models（dimensions 建库锁定）/ FEATURES LLM-02 | 无 |
| L03 reranker 模型信息维护 | 完整 | FLOW §3.3 / ARCH §1.1 / DB §3.3 llm_reranker_models / FEATURES LLM-03 | 无。可选引用，未配置时跳过 rerank |

### 1.4 RAG（R01–R10）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| R01 创建知识库 | 完整 | FLOW §3.4 / ARCH §2.2 / DB §4.1 rag_knowledge_bases（tag/embedding/rerank/topK/阈值/切分默认）/ FEATURES RAG-01 | 库级 tag 设置本身完整；tag 粒度问题（文档级 vs 库级）计于 SA03/TA03 行，见 P1-1 |
| R02 上传文档类型 txt/word/excel/pdf/png/jpg | 完整 | FLOW §3.4（6 类上传节点）/ ARCH §2.2（DocParser 按扩展名分派）、§7 R02 / DB §4.2 rag_docs.doc_type 枚举 / FEATURES RAG-02 | 无遗漏。但 "word" 仅实现为 `.docx`（python-docx），旧格式 `.doc` 不支持且文档未说明取舍，见 P2-2 |
| R03 图片/扫描 PDF/文档内图片走 LLM 视觉 | 完整 | FLOW §3.4（视觉分支+解析流水线）、§4.2 S2 / ARCH §2.2（视觉解析）、§6#6 / DB §4.4 rag_doc_images（逐图记录 vision_endpoint_id/vision_text/status）/ FEATURES RAG-03 | 无。解析实现属 P5 推测范围，已标注；OCR 仅降级已记 RISK |
| R04 上传文档（调用存储模块 API） | 完整 | FLOW §4.2 S2（RAG→SS 时序）/ ARCH §2.2 / DB §4.2 rag_docs.file_id→storage_files / FEATURES RAG-02 | 无 |
| R05 切分策略：定长/父子/语义/结构化/表格 | 完整 | FLOW §3.4（5 分支）/ ARCH §2.2（5 策略工厂）、DECISION-020 / DB §4.3 rag_chunks（split_strategy/parent_id/is_table/split_params）/ FEATURES RAG-04 | 无。参数默认值属【推测】，已标注 |
| R06 原文档查看 + 手动修改 chunk | 完整 | FLOW §3.4 / ARCH §2.2、§2.3 / DB §4.3 rag_chunks.content（可编辑）+ edited_at + 修改后重算向量 / FEATURES RAG-05 | 无。编辑留痕（操作人/时间）有字段 |
| R07 选择 embedding 模型、rerank 模型（可选） | 完整 | FLOW §3.4 / ARCH §2.2 检索分支 / DB §4.1（embedding_model_id 必选、reranker_model_id 可空）/ FEATURES RAG-06、RAG-07 | 无。换模型=全库重嵌入（DECISION-006，【推测】已标注） |
| R08 设置 topK、阈值 | 完整 | FLOW §3.4（检索流程 topK/阈值分支）/ ARCH §2.2、DECISION-006 / DB §4.1 top_k_default/score_threshold/recall_top_n / FEATURES RAG-08 | 阈值作用面（rerank 分 vs 余弦）为裁定+【推测】，已标注；"单次检索覆盖库默认"为推测（P2-4） |
| R09 检索返回 chunk 索引 + 原文档位置（反向定位） | 完整 | FLOW §3.4、S2 / ARCH §2.2（反向定位 URL）、§4.5 / DB §4.3 rag_chunks.pos(JSONB)+chunk_index+UNIQUE(doc_id,chunk_index) / FEATURES RAG-09 | 无。位置结构 `{page, section_path, char_start, char_end, table_row}` 已裁定（【推测】标注） |
| R10 知识库查询接口做成 MCP 工具 | 完整 | FLOW §3.4（PlatformMCP-RAGSearch）/ ARCH §3.1 / DB §5.2 mcp_tools（rag_search, source=platform）/ FEATURES RAG-10 | 无。返回体含 chunk+索引+位置+tag，支撑引用规则 |

### 1.5 MCP（M01–M03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| M01 URL 注册 MCP server，支持多个 | 完整 | FLOW §3.5 / ARCH §3.2（注册+连通性探测+多 server）/ DB §5.1 mcp_servers（url/transport/status/last_sync_at）/ FEATURES MCP-01 | 无 |
| M02 工具列表 + 禁用/启用/删除 | 完整 | FLOW §3.5 / ARCH §3.2（工具状态机）/ DB §5.2 mcp_tools（input_schema 快照/enabled/removed_remote）/ FEATURES MCP-02 | 无。平台内置工具同列（source 标记） |
| M03 删除/禁用提示关联调用方 | 完整 | FLOW §3.5（关联提示分支）/ ARCH §3.2（409+agent 清单+confirm）/ DB §7.2.3 agent_mcp_tools（deleted_at IS NULL 查询主索引）/ FEATURES MCP-03 | 无。BRIEF 说"可能存在"，设计做实际引用查询（更强，合规） |

### 1.6 Skills（K01–K02）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| K01 手动添加/上传 skill，维护名称内容 | 完整 | FLOW §3.6 / ARCH §1.1 / DB §6.1 skills（name/content/source/version）/ FEATURES SKILL-01 | 无。两种形态（manual/upload）均有落点 |
| K02 元数据存 DB、文件走存储模块 | 完整 | FLOW §3.6 / ARCH §1.1 / DB §6.1 skills + §6.2 skill_files（file_id→storage_files）/ FEATURES SKILL-02 | 无。分离+一致性（上传记录 source=skill）可验证 |

### 1.7 Agent（A01–A04）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| A01 创建、维护 agent 信息 | 完整 | FLOW §3.7 / ARCH §1.1 / DB §7.1 agents（name/type/system_prompt/status）/ FEATURES AGENT-01 | 无。删除策略（会话保留/引用清理/记忆清理）已裁定并标注 |
| A02 类型：简易（本地 langchain）/第三方（URL） | 完整 | FLOW §3.7 / ARCH §2.3、§2.4、§6#2 / DB §7.1 agents.type + third_party_url / FEATURES AGENT-02 | 无。langchain 编排方式（tool-calling loop）属 P7 推测，DECISION-007 已标注 |
| A03 配置 LLM/RAG 库/MCP 工具/skills，从已存在列表勾选 | 完整 | FLOW §3.7（勾选关系图）/ ARCH §1.2 / DB §7.2 四张勾选表（agent_llm_endpoints/agent_knowledge_bases/agent_mcp_tools/agent_skills）/ FEATURES AGENT-03 | 无。回显、未选不启用、引用禁用/删除行为均有落点 |
| A04 对话交互、会话列表、对话详情 | 完整 | FLOW §3.7、S3、S4 / ARCH §2.3、§2.4、§4.5 / DB §7.3 agent_sessions + §7.4 agent_messages（tool_calls/citations/file_ids/token_usage）/ FEATURES AGENT-04 | 无。会话新建/删除/重命名闭环 |

### 1.8 简易 agent（SA01–SA03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| SA01 记忆：redis 短期/pgsql 长期/obsidian 沉淀 | 完整 | FLOW §3.7（配置关系图）、S3 / ARCH §2.3、§6#12 / DB §7.5 agent_memories + §7.6 agent_obsidian_notes + §11 Redis `joker:mem:*` + §12 vault 目录 / FEATURES AGENT-07、AGENT-08 | 无。obsidian 实现属 P6 推测，已标注；redis 降级策略（退单轮）有落点 |
| SA02 交互涉及文件需上传到存储模块 | 完整 | FLOW S3（文件分支 SAR→SS）/ ARCH §2.3 / DB §2.2 storage_upload_records（source=agent）+ §7.4 agent_messages.file_ids / FEATURES AGENT-06 | 文件上传走内部 API 直调（不经 ToolInterceptor）——该路径归属"工具调用"边界问题统一计于 G03 行（P1-2），本条需求本身（文件入存储模块+留痕）完整 |
| SA03 official tag 或用户明确要求 → 回复末尾附 RAG 来源 + 链接原文位置 | **部分** | FLOW S3（alt 分支）、§3.4 / ARCH §2.3、§4.5（RAG 来源规则+定位 URL）/ DB §4.1 rag_knowledge_bases.tag + §7.4 agent_messages.citations / FEATURES AGENT-05 | **tag 粒度偏差（P1-1）**：BRIEF 原话是"知识**文档** tag 是 official"（文档级），但三份设计文档均实现为**知识库级** tag（DB rag_knowledge_bases.tag="库 tag"，rag_docs 表**无 tag 字段**）；且 FLOW S3 时序写"RAG 结果含 tag=official **文档**"、FEATURES AGENT-05 描述引 BRIEF 原文"知识文档 tag"，与自身数据/依赖提示"知识库 tag 字段"自相矛盾。后果：同一知识库内无法只把个别文档标为 official，引用判定粒度粗于用户原话；该偏离未标注【推测】、未向用户说明 |

### 1.9 第三方 agent（TA01–TA03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| TA01 记忆由 agent 提供方实现 | 完整 | FLOW S4（"记忆由提供方实现，平台不存"前置 Note）/ ARCH §2.4 / DB §7.1 agents.third_party_session_param + §7.3 external_session_id（仅透传句柄）/ FEATURES AGENT-09 | 无。平台侧不存记忆、不注入记忆，仅保留会话/trace |
| TA02 文件经存储 MCP 工具上传（提供方决定是否调用） | 完整 | FLOW S4（平台 MCP 工具分支）/ ARCH §2.4、§3.1 / DB §2.2（source=mcp:platform）/ FEATURES AGENT-10 | 无。"不强制"语义（不配置该工具对话仍正常）有落点 |
| TA03 RAG 引用同上（平台提供信息，提供方决定是否显示） | **部分** | FLOW S4（"agent 提供方决定是否显示"alt 分支）/ ARCH §2.4、§4.5 / DB §7.4 citations / FEATURES AGENT-11 | 同 SA03：**tag 粒度偏差（P1-1）**——判定条件中"知识文档 tag=official"被实现为库级 tag；"平台提供检索结果及引用原文档信息、提供方决定显示"这部分完整 |

### 1.10 BFF 网关（G01–G06）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| G01 统一鉴权/流量控制/API 路由/协议转换（OpenAI 兼容） | 完整 | FLOW §3.8 / ARCH §4.1（7 步管线）、§4.5（协议转换）/ DB §8.1 bff_rate_limit_configs / FEATURES BFF-01..04 | 无。限流维度/阈值、配置化路由为【推测】，已标注 DECISION-013/014 |
| G02 提取 tenant_id/user_id/scopes + agent 访问权限校验（员工/管理员例） | 完整 | FLOW §3.1（权限校验流程图）、S3/S4 / ARCH §4.1③⑤、§4.6（agent:use:<id> scope 方案）/ DB §1.4 scopes（agent:use 动态 upsert）/ FEATURES BFF-05 | 无。BRIEF 例子（客服 vs 数据分析 Agent）有明确落地形式 |
| G03 工具调用必须经 BFF 统一拦截（总则） | **部分** | FLOW §3.8（拦截统一动作图）、S3、S4 / ARCH §4.3（两种模式同一动作链）、§4.4（拦截 trace 留痕）/ DB §9.2 trace_events（tool_call 事件，scope_check/token_injected/machine_credential_ref/denied）/ FEATURES BFF-06 | **拦截边界未裁定（P1-2，终审已识别 R1，本审阅确保持立并给出产品建议）**：BRIEF 用词是"Agent 工具调用**必须**经过 BFF 统一拦截"（强要求）；ARCH 中简易 agent 的 **RAG 检索**（SAR→RAG 内部 API）与**文件上传**（SAR→SS 内部 API）走内部 API 直调、**不产生 tool_call 拦截 trace**。若测试把这两条路径判为"工具调用"，BFF-06 验收 1（"任一工具调用 trace 中均可看到 BFF 拦截记录，无绕过路径"）判 FAIL。且 ARCH §1.1 数据流要点（"不存在绕过拦截的路径"）与 §9-7（"直调存储内部 API"）两处表述未对齐。产品建议见 §3 P1-2 |
| G04 简易 agent：代码层拦截 LangChain Tool 回调 | 完整 | FLOW S3（Tool 执行回调分支）/ ARCH §2.3（模式①）、§4.3（InterceptorTool 工厂，无裸注册路径）/ DB §9.2（mode=simple）/ FEATURES BFF-07 | 无 |
| G05 第三方 agent：拦截 HTTP 响应中的 Tool Call | 完整 | FLOW S4（HTTP 响应拦截分支）/ ARCH §2.4（模式②）、§3.3（协议约定）/ DB §9.2（mode=third_party）/ FEATURES BFF-08 | 无。协议（OpenAI 兼容 tool_calls + /tool_results）为 DECISION-008【推测】，已标注，测试需备 mock（D5） |
| G06 拦截三动作：scope 校验/强制注入 token/机器凭证代理执行 | 完整 | FLOW §3.8（①②③ 全画出，含失败分支）/ ARCH §4.3（三动作实现细节）、§4.4 / DB §5.2 required_scopes + §9.2 payload / FEATURES BFF-09 | 无。"mcp 工具/接口统一校验 access token"（业务系统自身机制）在 ARCH §3.1 有落点 |

### 1.11 Trace（T01–T02）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| T01 记录每会话交互（含文件）/工具调用/RAG 调用/时间点/token | 完整 | FLOW §3.9（记录范围+写点）、S3/S4 / ARCH §4.4 / DB §9.1 trace_sessions + §9.2 trace_events（event_type 覆盖 message/file/tool_call/rag/system，token_usage/latency_ms/created_at）/ FEATURES TRACE-01 | 无。五要素+文件事件齐全，与会话/消息互查 |
| T02 trace 数据检索 | 完整 | FLOW §3.9（多维检索）/ ARCH §4.7（错误码）、DB 索引 / DB §9.2（组合索引 + payload tsvector 全文检索）/ FEATURES TRACE-02 | 无。关键词/时间/用户/agent/会话/事件类型/工具名多维+租户隔离 |

### 1.12 覆盖性核对（独立清点）

本审阅独立清点 BRIEF §2 原始 bullet 数：**顶级 bullet 38 条、含 BFF 拦截 3 条子项共 41 条、展开标准 ID 45 个**（脚本清点，非目测）。
45 个标准 ID 中每行至少映射一个功能点 + 一个图 + 一个架构章节 + 一个表/字段，**无"缺失"项**。
与终审"42 已覆盖 + 3 部分覆盖"的差异：本审阅将 SA03/TA03 从"已覆盖"降为"部分覆盖"（tag 粒度偏差，终审未识别），故为 **41 完整 + 4 部分 + 0 缺失**。

---

## 2. DESIGN_REVIEW.md（褚岩终审）结论验证

> 任务要求：验证终审结论是否成立，可推翻。以下逐条独立复核。

### 2.1 数字基线（终审 §0）

| 终审声明 | 本审阅独立验证 | 裁定 |
|---|---|---|
| 复跑 validate_d03.py 全过 | 本审阅独立复跑，输出一致（mermaid 9、组件 31、功能点 56/56、规范 ID 45、ARCH §7 39 行） | **成立** |
| 组件命名 31/31 一致 | 复跑确认清单 31 项；抽查 WebConsole/BFFGateway/ToolInterceptor/StorageService/RAGService/PlatformMCPServer/SimpleAgentRuntime 等在 FLOW/ARCH/DB 中同名；PlatformMCP-* 三"组件"→PlatformMCPServer 三工具的映射在 ARCH §3.1、DB §5.2 显式声明 | **成立** |
| FLOW 21 图 | 本审阅 grep 确认 21 个 mermaid 块 | **成立** |
| 【推测】标注密度（FLOW 66/ARCH 56+30/DB 119） | 复跑确认 ARCH 56、DB 119；密度充足，抽样未发现应标未标（唯一例外：tag 粒度偏离未标注，见 P1-1） | **基本成立**（密度结论成立；"无应标未标"不成立，见 P1-1） |

### 2.2 交叉一致性结论（终审 §1）

| 终审结论 | 本审阅复核 | 裁定 |
|---|---|---|
| 关键分支 14 项在"图→架构→表"三层闭合 | 逐项复核：登录/JWT 黑名单、本地 vs 云三分支、视觉分支、5 切分、topK/阈值、反向定位、scope 失败、强制覆写、机器凭证、MCP 关联提示、多租户隔离、第三方 HTTP 拦截、三层记忆——均三层闭合。**但"official tag 引用"分支**：图与架构按"文档/库 tag"措辞混用，表只有库级 tag，三层在**粒度**上未真正对齐（分支画了，语义粗于 BRIEF） | **基本成立，1 项修正**（official tag 分支粒度偏差，终审漏判 → 本审阅 P1-1） |
| 56/56 功能点可回溯，抽样无断链 | 复跑确认 56/56；独立抽查 RAG-03/RAG-09/AGENT-07/AGENT-10/BFF-09/TRACE-01/STORE-06 的 DB 落点，无断链 | **成立** |
| 不一致 #1（P1 拦截边界）：ARCH §1.1 vs §9-7 表述张力 | 原文核对：ARCH §1.1 数据流要点"不存在绕过拦截的路径" vs §9-7"简易 agent 直调存储内部 API……两条路径都经 ToolInterceptor，无绕过"——两处措辞矛盾（§9-7 称内部 API"也经 ToolInterceptor"，§1.1 与 FLOW S3 时序显示直调不经 ToolInterceptor）。RISK-006 已立 | **成立**（本审阅确认为 P1，且确认终审"需开发前裁定"的处置正确） |
| 不一致 #2（P1 计数口径）："39 条" vs 45 行 | 本审阅独立清点：**"39" 无法由任何清点方法导出**——顶级 bullet=38、含子项=41、标准 ID=45，三者均≠39。ARCH §7 表头（line 637）与 FEATURES §10.1（line 655）都写"39 条"，而实际对照表均为 45 行 | **成立，且比终审描述更严重**：终审认为 39 疑似"按原始 bullet 行计数"，但实际顶级 bullet 是 38 条——39 连 bullet 口径都对不上。覆盖性"无遗漏"结论不受影响（45 行逐条核过），但数字必须勘误（见 P1-3） |
| 不一致 #3（P2）：DB §14 "25 张表" vs "33 张" | 原文核对 DB line 1120："上图覆盖全部 25 张表（……共 33 张……）"——同句自相矛盾，25 为笔误（实际枚举 33） | **成立** |
| 不一致 #4（P2）：表头"§7 九张"口径 | 本审阅清点 §7 实际表数：7.1 agents + 7.2.1~7.2.4 四张勾选表 + 7.3~7.6 = **9 张，"九张"数字本身正确**；问题仅在"6 个 ### 小节 vs 9 张表"的口径易误读。终审将其列为"不一致"，但数字并非错误 | **部分推翻**：降级为纯表述澄清（P2-3），非数字错误 |
| 不一致 #5（P2）：S01 迁移策略未成文 | 复核 DB §2 章首说明与 storage_files.backend 字段：仅隐含"保留原后端访问"，未显式成文 | **成立** |
| 终审 §1.4 表格中"DB_DESIGN 表头 §18"的引用 | DB_DESIGN 全文只有 15 章（§1–§15），"§18"不存在，系终审引用笔误 | **小误**（P2 级引用勘误，不影响实质结论） |

### 2.3 终审总体结论（PASS_WITH_ISSUES，P1×2、P2×3、无 P0）

| 终审论断 | 本审阅裁定 |
|---|---|
| 无 P0（无 BRIEF 需求整体缺失、无三文档矛盾到无法实现） | **成立**（本审阅逐条核过 45 项，无缺失；唯一强张力 G03 属边界澄清，不阻断设计） |
| P1×2（拦截边界 R1 + 计数口径） | **不完整**：漏掉 1 个 P1（tag 粒度偏差 P1-1）。实际 P1 = 3 |
| P2×3（DB 25/33 笔误、§7 九张口径、S01 策略未成文） | **不完整**：另需补 .doc/.docx 范围、单次 topK 覆盖推测、终审自身"§18"引用笔误等。实际 P2 ≥ 6 |
| "7 个推测项全部闭环到 DECISION 且标注【推测】" | **成立**（P1–P7 → DECISION-003/002/004/006/005/019/007，逐条核对 DECISIONS 21 条索引，ARCH §8 与 DECISIONS.md 一致） |
| "为什么不是 FAIL / 不是无条件 PASS" 的论证 | **成立**（论证逻辑正确；本审阅维持 PASS_WITH_ISSUES 档，但问题清单需按本审阅 §3 扩充） |

> **对终审结论的总体裁定**：终审的**判定档位（PASS_WITH_ISSUES）成立**，其四维方法（交叉一致性/逐条对照/推测项/遗留问题）有效、数字基线可信；但**问题清单不完整**——终审漏掉 tag 粒度偏差（P1），计数口径问题被低估（39 无法由任何口径导出），且"§7 九张"一项实为表述澄清而非错误。本审阅不推翻其判定，但**推翻其问题清单的完备性**。

---

## 3. 问题清单（P0 / P1 / P2）

### P0（阻断开发）

**无。**

### P1（开发前必须裁定/修正，影响验收判据）

| # | 问题 | 位置 | 产品视角说明与建议 |
|---|---|---|---|
| **P1-1** | **tag 粒度偏差：BRIEF 要求"知识文档 tag"，设计实现为"知识库 tag"**。DB rag_docs 表无 tag 字段，rag_knowledge_bases.tag 为库级；FLOW S3 写"tag=official 文档"、FEATURES AGENT-05 描述引 BRIEF 原文"知识文档 tag"，与自身数据提示"知识库 tag 字段"矛盾；该偏离未标注【推测】（违反 BRIEF §6"推断内容必须标注推测"的质量要求） | DB §4.1/§4.2、FLOW §3.4+S3、ARCH §4.5、FEATURES RAG-01/AGENT-05 | 后果：一个知识库内无法只将个别文档标 official，引用判定粒度粗于用户原话（例：混合了 official 文档与普通文档的库，所有 chunk 都会被附引用）。**产品建议（二选一，需用户确认）**：① 推荐——rag_docs 增加 tag 字段（文档级，NULL 时继承库级或判为非 official），FEATURES/ARCH/DB 同步修订，语义完全对齐 BRIEF；② 简化裁定——明确"tag 仅在知识库级"，文档中显式写明该偏离并获得用户确认。**终审漏判此项，需补入遗留问题并升级 R1 级处理** |
| **P1-2** | **工具调用拦截边界未裁定**（终审 R1，本审阅确保持立）：BRIEF 强要求"Agent 工具调用**必须**经过 BFF 统一拦截"；简易 agent 的 RAG 检索与文件上传走内部 API 直调、不产生 tool_call 拦截 trace；ARCH §1.1 与 §9-7 两处表述矛盾 | ARCH §1.1/§2.3/§4.3/§9-7、FEATURES BFF-06 | **产品建议**：将"工具调用"明确界定为 **MCP 工具调用**（含平台内置 upload_doc/query_doc/rag_search——agent 勾选后调用时必经 ToolInterceptor）；RAG 检索/文件上传的内部 API 路径界定为"平台内部服务调用"，不属 agent 工具，但**必须**：a) 经用户身份校验（tenant/scope，防越权）；b) 落 trace（rag/file 事件类型，已有字段）；c) 在 BFF-06 验收要点 1 中写明排除项（"RAG/文件内部 API 调用以 rag/file 事件留痕，不产生 tool_call 事件"）；d) 统一 ARCH §1.1 与 §9-7 措辞为一处权威表述。因 BRIEF 用词为"必须"，**该界定需用户确认后方可作为验收基线** |
| **P1-3** | **计数口径错误**：ARCH §7（line 637）与 FEATURES §10.1（line 655）均声明"BRIEF §2 共 39 条原话需求"，但独立清点为 38 顶级 bullet / 41 含子项 / 45 标准 ID，**39 无法由任何口径导出**；两份文档实际对照表均为 45 行 | ARCH §7、FEATURES §0/§10.1 | 覆盖性结论（无遗漏）成立、不受影响，但"39 条"数字削弱可验证性并可能误导后续开发/测试引用。**建议统一改为**："BRIEF §2 共 38 条顶级需求项（BFF 拦截项含 3 条子项，展开为 45 个标准 ID），对照表按 45 个标准 ID 逐条覆盖"。终审 D2 已列此勘误，但低估了严重性（终审认为 39≈bullet 口径，实际不符） |

### P2（开发阶段顺手修正，不阻断）

| # | 问题 | 位置 | 处置建议 |
|---|---|---|---|
| **P2-1** | 存储后端切换后**既有文件处理策略未显式成文**（隐含"保留原后端访问、不迁移"） | DB §2（storage_files.backend）、FEATURES STORE-03 验收 2 | 开发前在 ARCH §2.2 或 DB §2 补一句裁定："采用保留原后端访问策略（按行内 backend 分派，不做迁移）"（终审 D3 已列，确认） |
| **P2-2** | BRIEF "word" 仅实现为 `.docx`（python-docx），旧格式 `.doc` 不支持且文档未说明取舍 | ARCH §2.2 DocParser、DB §4.2 doc_type 枚举 | 在 ARCH §2.2 或 DECISIONS 补一句：".doc 旧格式不在支持范围（422 拒绝并提示转 .docx）"或纳入支持 |
| **P2-3** | DB 表头"§7 九张"：数字正确（§7 实为 9 张表），但 6 个 ### 小节 vs 9 张表的口径易误读 | DB 文首 line 18 | 补注"§7 共 9 张表 = 1 定义 + 4 勾选 + 4 会话/消息/记忆/obsidian"（终审 #4 降为此级；本审阅部分推翻终审"不一致"定性——数字并非错） |
| **P2-4** | RAG-08 验收 3"单次检索覆盖库默认 topK/阈值"为推测，API 是否支持未定 | FEATURES RAG-08、DB §4.1 | 开发时明确 rag_search API 是否接受单次 topK/threshold 覆盖参数（终审 D4 已列，确认） |
| **P2-5** | DB §14 "25 张表"笔误（应为 33） | DB line 1120 | 文字勘误（终审 #3 已列，确认） |
| **P2-6** | 终审报告自身引用笔误："DB_DESIGN 表头 §18"——DB_DESIGN 仅 15 章，无 §18 | DESIGN_REVIEW §1.4 #4 | 终审文档引用勘误（本审阅新发现），不影响其实质结论 |

### 与终审遗留问题的对账

| 终审遗留项 | 本审阅裁定 |
|---|---|
| R1 拦截边界（P1，最高优先） | 维持 P1，确认为本审阅 P1-2，并给出产品侧界定建议 |
| R2 RISK-003 双通道裁定待确认 | 维持：第三方 RAG 检索"双通道并存"、简易 agent 文件"双路径"的裁定合理（与 FLOW S3/S4 一致），闭环可演示，**仍需用户确认**（与 P1-2 一并确认最优） |
| R3 向量 1536 维 + 补零 | 维持待用户确认（RISK-004）；补零对余弦相似度无影响的数学论证成立 |
| R4 阈值/topN/切分默认参数 | 维持待用户确认；均可配置，风险低 |
| D1–D6 | D1→P1-2；D2→P1-3（严重性上调）；D3→P2-1；D4→P2-4；D5（mock 测试资产）维持；D6（占位模板清理）维持——PRD/USER_STORIES/PRODUCT_DECISIONS 等模板待开发阶段由产品/开发/测试角色填充，与事实源（FLOW/FEATURES/ARCH/DB）并存期间以事实源为准 |

---

## 4. 总体结论

### 判定：**部分符合**（接近符合；无缺失项、无 P0；3 个 P1 需在开发前裁定/修正）

**符合的部分（5 份文档共同达成）**：
1. **BRIEF §2 全部 45 个标准 ID 逐条有落点，无缺失项**——9 大模块（基础 5 / 存储 4 / LLM 3 / RAG 10 / MCP 3 / Skills 2 / Agent 4 / 简易 3 / 第三方 3 / BFF 6 / Trace 2）在"流程图→功能点→架构→数据库"四层均闭合；
2. BRIEF §6 强制的 4 条核心流程时序图（登录鉴权、上传→解析→切分→检索、简易 agent 对话含拦截、第三方 agent 对话）与 3 类关键分支（official 引用、scope 校验失败、本地 vs 云存储）全部画出；
3. BRIEF §4 的 7 个推测项（P1–P7）全部闭环到 DECISIONS（21 条）并标注【推测】，高风险参数推测均有 RISK 跟踪；
4. 组件命名契约 31/31、功能点 56/56 可回溯（独立复跑验证）；
5. 数据库 33 张表字段逐行列出无概括省略，Redis key/Obsidian 目录/多租户隔离/索引策略齐备（符合 BRIEF §6 对 DB_DESIGN 的验收标准）。

**部分符合的原因（3 个 P1）**：
1. **P1-1 tag 粒度偏差**（本审阅新发现，终审漏判）：BRIEF"知识**文档** tag"被实现为"知识**库** tag"，rag_docs 缺 tag 字段，且偏离未标注【推测】；
2. **P1-2 工具调用拦截边界**（终审已识别，确认）：BRIEF"必须"强要求下，简易 agent 的 RAG 检索/文件上传内部 API 路径是否属"工具调用"未裁定，两处架构表述矛盾，直接影响 BFF-06 验收判据；
3. **P1-3 计数口径错误**（终审已识别，低估严重性）："39 条"无法由任何清点口径导出（实际 38 顶级 bullet / 41 含子项 / 45 标准 ID）。

**为什么不是"符合"**：P1-1 是用户原话语义的真实偏离（tag 粒度），P1-2 是 BRIEF 强要求（"必须"）与当前设计表述的真实张力，两者都必须在开发前裁定并获得用户确认。

**为什么不是"不符合"**：无任何 BRIEF 需求整体缺失，无三文档相互矛盾到无法实现的冲突，5 份文档质量总体高（证据链完整、推测标注密度充足、可回溯性强）；3 个 P1 均为"边界澄清/粒度对齐/数字勘误"级别，有明确处置路径，不推翻任何核心设计。

---

## 5. 给项目经理（褚岩）的交接要点

1. **P1-1（tag 粒度）是终审漏判的新问题**，建议升级为与 R1 同级的开发前裁定项（需用户二选一：文档级 tag 改表，或确认库级 tag 简化）；
2. P1-2（拦截边界）+ R2（双通道）建议**合并为一次用户确认**（产品建议已给出，见 §3）；
3. P1-3 为文档勘误，开发前随手修（ARCH §7 表头 + FEATURES §0/§10.1 的"39 条"）；
4. P2 六项均为顺手修正，无风险；
5. 本审阅与终审（DESIGN_REVIEW.md）结论档位一致（PASS_WITH_ISSUES / 部分符合），问题清单以本审阅 §3 为准（P1×3、P2×6，含终审已列项的对账）。

*（完）REVIEW_luoji.md — 罗辑（产品），2026-09-22。独立审阅：45 标准 ID 逐条对照（无抽查）+ 终审结论逐条验证（含 1 项推翻、1 项修正）+ 独立脚本复验。总体结论：部分符合（无 P0、3 P1、6 P2、0 缺失）。*
