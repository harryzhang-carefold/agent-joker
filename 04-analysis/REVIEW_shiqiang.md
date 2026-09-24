# REVIEW_shiqiang — agent-joker 设计文档独立审阅（系统分析师视角）

> 审阅人：史强（shiqiang，系统分析师）｜ 日期：2026-09-22 ｜ 任务：t_a78127d7
>
> **审阅对象**（5 份）：
> 1. `00-management/BRIEF.md`（原始需求基准，§2 逐条原话）
> 2. `01-product/FLOW_DIAGRAMS.md`（史强，TASK-D01）
> 3. `01-product/FEATURES.md`（罗辑，TASK-D02）
> 4. `02-development/ARCHITECTURE.md`（章北海，TASK-D03）
> 5. `02-development/DB_DESIGN.md`（章北海，TASK-D03）
> 6. `00-management/DESIGN_REVIEW.md`（褚岩终审，**验证其结论是否成立，可推翻**）
>
> **方法**：独立逐条对照 BRIEF §2 全部 45 个标准 ID（不抽查、不依赖上游自验脚本）；
> 交叉证据 = FLOW（图/组件契约）↔ ARCH（机制/时序）↔ DB（表/字段）↔ FEATURES（功能点）↔ DECISIONS（21 条）；
> 对 DESIGN_REVIEW 的每条结论做独立复核（§4），并给出本审阅**独立新发现**（§3，终审未覆盖项）。
>
> **来源声明**：设计阶段无运行系统/代码可逆向，本审阅的证据基准为 5 份文档文本本身 + BRIEF 原话。
> 审阅过程未修改任何被审文档。

---

## 1. 逐条对照表（BRIEF §2 全部 45 个标准 ID，逐条不抽查）

> 覆盖情况：完整 = 5 份文档中 FLOW/ARCH/DB 三层均有落点且无未决歧义；
> 部分 = 有落点但存在未裁定歧义或未成文项（问题描述列注明）；缺失 = 无落点。
> 证据列格式：`FLOW §x / ARCH §y / DB §z / FEATURES xx-NN`。

### 1.1 基础功能（B01–B05）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| B01 用户管理 | 完整 | FLOW §3.1 / ARCH §1.1(IAM)、§2.1 / DB §1.2 users / FEATURES BASE-01 | 无。CRUD/禁用/重置密码/租户绑定齐全 |
| B02 角色管理 | 完整 | FLOW §3.1 / ARCH §1.1、§4.6 / DB §1.3 roles、§1.5 / FEATURES BASE-02 | 无 |
| B03 权限管理 | 完整 | FLOW §3.1(权限校验图) / ARCH §4.6(scope 三类) / DB §1.4 scopes、§1.5 / FEATURES BASE-03 | 无。agent 授权表达已裁定为 `agent:use:<id>` scope（DECISION-004） |
| B04 登入登出 | 完整 | FLOW §4.1 S1 / ARCH §2.1、§4.1② / DB §1.7 auth_refresh_tokens / FEATURES BASE-04/05 | 无。JWT 双令牌+登出黑名单为【推测】P2 项，已闭环 DECISION-002 |
| B05 接口操作日志 | 完整 | FLOW §3.1(AM) / ARCH §4.1⑦ / DB §1.8 api_audit_logs / FEATURES BASE-06 | 无。脱敏、异步不阻断、筛选索引均有落点 |

### 1.2 存储模块（S01–S04）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| S01 保存文件（本地/GCS/OSS，配置文件可配） | **部分** | FLOW §3.2(三分支图) / ARCH §2.2、§5.3(STORAGE_BACKEND) / DB §2.1 storage_files.backend / FEATURES STORE-01..03 | **既有文件迁移策略未显式成文**：DB `backend` 行级分派隐含「保留原后端访问」，但 FEATURES STORE-03 验收 2 要求该策略「在设计文档说明」，ARCH/DB 均未成文（终审 #5 已识别，复核成立） |
| S02 访问文件（统一接口/按文件名） | 完整 | FLOW §3.2 / ARCH §2.2(访问接口行为)、§3.1 / DB §2.1(UNIQUE(tenant_id,file_name)) / FEATURES STORE-04 | 无。404/403/同名 409 行为均已定义 |
| S03 保存文件上传记录 | 完整 | FLOW §3.2(UploadRecord) / ARCH §2.2 / DB §2.2 storage_upload_records / FEATURES STORE-05 | 无。来源枚举 api/mcp:platform/agent/kb/skill 覆盖全部来源 |
| S04 上传/访问接口注册为 MCP 工具 | 完整 | FLOW §3.2(MCP化) / ARCH §3.1(PlatformMCPServer) / DB §5.2 mcp_tools(source=platform) / FEATURES STORE-06/07 | 无。组件名→工具名的有意映射已双向声明（FLOW §1 与 ARCH §3.1） |

### 1.3 LLM 节点（L01–L03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| L01 LLM endpoint 信息维护 | 完整 | FLOW §3.3 / ARCH §1.1、§2.3 / DB §3.1 llm_endpoints / FEATURES LLM-01 | 无。含 supports_vision（供 RAG-03）、连通性测试、引用保护 |
| L02 embedding 模型信息维护 | 完整 | FLOW §3.3 / ARCH §2.2 / DB §3.2 llm_embedding_models / FEATURES LLM-02 | 无。dimensions 建库锁定机制已定义 |
| L03 reranker 模型信息维护 | 完整 | FLOW §3.3 / ARCH §2.2 / DB §3.3 llm_reranker_models / FEATURES LLM-03 | 无。可选引用（NULL=跳过 rerank） |

### 1.4 RAG（R01–R10）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| R01 创建知识库 | 完整 | FLOW §3.4 / ARCH §2.2 / DB §4.1 rag_knowledge_bases / FEATURES RAG-01 | 无。tag/embedding/rerank/topK/阈值/切分默认全在库表 |
| R02 上传 6 类文档 | 完整 | FLOW §3.4(解析流水线) / ARCH §2.2(DocParser 分派) / DB §4.2 rag_docs.doc_type / FEATURES RAG-02 | 无。非支持类型 422 已定义 |
| R03 图片/扫描PDF/文档内图片走 LLM 视觉 | 完整 | FLOW §3.4(视觉分支)+§4.2 S2 / ARCH §2.2、§6#6 / DB §4.4 rag_doc_images / FEATURES RAG-03 | 无。三类 source_type 逐图记录；OCR 仅降级（DECISION-005） |
| R04 上传文档（调存储模块 API） | 完整 | FLOW §4.2 S2 / ARCH §2.2 / DB §4.2 rag_docs.file_id→storage_files / FEATURES RAG-02 | 无。source=`kb` 上传记录联动 |
| R05 5 种切分策略 | 完整 | FLOW §3.4(5 策略分支) / ARCH §2.2(ChunkSplitter)、§6#11 / DB §4.2 split_strategy、§4.3 / FEATURES RAG-04 | 无。库级默认+文档级覆盖+可重切分；默认参数已裁定（DECISION-020） |
| R06 原文档查看 + 手动改 chunk | 完整 | FLOW §3.4(RV/CH) / ARCH §2.2(反向定位 URL) / DB §4.3 content(可编辑)/edited_at / FEATURES RAG-05 | 无。改后重算 embedding 已定义；留痕（edited_at+updated_by） |
| R07 选 embedding/rerank 模型 | 完整 | FLOW §3.4(检索流程) / ARCH §2.2(检索分支) / DB §4.1 embedding/reranker_model_id / FEATURES RAG-06/07 | 无 |
| R08 topK、阈值 | 完整 | FLOW §3.4(topK/阈值分支) / ARCH §2.2、DECISION-006 / DB §4.1 top_k_default/score_threshold / FEATURES RAG-08 | 阈值语义（作用面）已裁定【推测】；「单次检索覆盖库默认」仍为【推测】待开发明确（D4，终审已列）——不降级覆盖，因设计文档已给出默认行为且标注 |
| R09 chunk 索引 + 原文档位置（反向定位） | 完整 | FLOW §4.2(反向定位回查) / ARCH §2.2、§4.5(定位 URL) / DB §4.3 pos(JSONB)/chunk_index、UNIQUE(doc_id,chunk_index) / FEATURES RAG-09 | 无。位置结构 `{page,section_path,char_start,char_end,table_row}` 已裁定（ARCH §9-11） |
| R10 知识库查询做成 MCP 工具 | 完整 | FLOW §3.4(MC) / ARCH §3.1(rag_search) / DB §5.2 mcp_tools / FEATURES RAG-10 | 无。返回体含 chunk+索引+位置+tag（供引用） |

### 1.5 MCP（M01–M03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| M01 URL 注册 MCP server（多个） | 完整 | FLOW §3.5(注册流程) / ARCH §3.2(探测/状态机) / DB §5.1 mcp_servers / FEATURES MCP-01 | 无 |
| M02 工具列表 + 禁用/启用/删除 | 完整 | FLOW §3.5 / ARCH §3.2(同步策略/状态机) / DB §5.2 mcp_tools(enabled/removed_remote) / FEATURES MCP-02 | 无。平台内置工具同列（source=platform）满足验收 4 |
| M03 删除/禁用提示关联调用方 | 完整 | FLOW §3.5(关联提示分支) / ARCH §3.2(409+清单) / DB §7.2.3 agent_mcp_tools / FEATURES MCP-03 | 无。检测查询与主索引均已定义 |

### 1.6 Skills（K01–K02）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| K01 手动添加/上传 skill | 完整 | FLOW §3.6 / ARCH §1.1(SkillsService) / DB §6.1 skills(source=manual/upload) / FEATURES SKILL-01 | 无 |
| K02 元数据存 DB、文件走存储模块 | 完整 | FLOW §3.6 / ARCH §1.1 / DB §6.1+§6.2 skill_files→storage_files / FEATURES SKILL-02 | 无。分离+一致+上传记录 source=skill 均有落点 |

### 1.7 Agent（A01–A04）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| A01 创建/维护 agent 信息 | 完整 | FLOW §3.7 / ARCH §1.1 / DB §7.1 agents / FEATURES AGENT-01 | 无。删除策略已裁定（会话保留/配置级联清/记忆清/笔记保留） |
| A02 类型：简易(langchain)/第三方(URL) | 完整 | FLOW §3.7(类型二选一) / ARCH §2.3、§2.4、§6#2 / DB §7.1 type / FEATURES AGENT-02 | 无。编排方式 tool-calling loop 已裁定【推测】P7（DECISION-007） |
| A03 配置四要素（从已存在列表勾选） | 完整 | FLOW §3.7(配置关系图) / ARCH §1.2、§7 / DB §7.2 四张勾选表 / FEATURES AGENT-03 | 无。回显/未选不启用/引用删除联动均有定义 |
| A04 对话交互 + 会话列表 + 对话详情 | 完整 | FLOW §3.7(SE/DT) / ARCH §2.3/§2.4、§4.5 / DB §7.3 agent_sessions、§7.4 agent_messages / FEATURES AGENT-04 | 无。新建/删除/重命名闭环 |

### 1.8 简易 agent（SA01–SA03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| SA01 记忆 redis 短期/pgsql 长期/obsidian 沉淀 | 完整 | FLOW §3.7(MEM)+§4.3 S3 / ARCH §2.3、§6#12 / DB §7.5 agent_memories、§7.6 agent_obsidian_notes、§11 Redis keys、§12 vault 目录 / FEATURES AGENT-07/08 | 无。三层各有实体落点；redis 降级策略、obsidian 目录/frontmatter 格式均已定义【推测】 |
| SA02 交互文件上传到存储模块 | **部分** | FLOW §4.3 S3(文件分支) / ARCH §1.1 数据流要点、§2.3(内部 API)、§9-7 / DB §2.2 source=agent / FEATURES AGENT-06 | **拦截边界张力**（与 G03 同根）：简易 agent 的文件上传走「存储内部 API 直调」，不产生 `tool_call` 拦截 trace 事件（仅 file 事件）；ARCH §1.1「不存在绕过拦截的路径」与 §9-7「直调内部 API」措辞未对齐。若验收把「agent 发起的文件上传」判为「工具调用」，BFF-06 验收 1 可能误判 FAIL。需开发前裁定（终审 #1/R1 已识别，复核成立） |
| SA03 official tag/用户要求 → 附 RAG 来源 + 链接 | 完整 | FLOW §4.3 S3(alt 分支)+§4.4 S4 / ARCH §4.5(RAG 来源规则)、DECISION-017 / DB §4.1 kb.tag、§7.4 citations(JSONB) / FEATURES AGENT-05 | 无。「或」关系、show_citations 参数+LLM 意图兜底、定位链接 URL 均已定义 |

### 1.9 第三方 agent（TA01–TA03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| TA01 记忆由提供方实现 | 完整 | FLOW §3.7(M2x)+§4.4 S4 / ARCH §2.4 / DB §7.1 external_session_id 透传、§11 joker:session:ext / FEATURES AGENT-09 | 无。平台不存、仅透传会话句柄，边界清晰 |
| TA02 文件经存储 MCP 工具上传（提供方决定是否调用） | 完整 | FLOW §4.4 S4(平台 MCP 分支) / ARCH §2.4、§3.1 / DB §5.2 platform 工具 / FEATURES AGENT-10 | 无。「不强制」（不配置该工具对话仍正常）已明确 |
| TA03 RAG 引用同上（提供方决定是否显示） | 完整 | FLOW §4.4 S4(RAG alt) / ARCH §2.4、§4.5 / DB §7.4 citations / FEATURES AGENT-11 | 无。平台提供完整引用信息的完整性可验证 |

### 1.10 BFF 网关（G01–G06）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| G01 BFF：统一鉴权/流量控制/API 路由/协议转换 | 完整 | FLOW §3.8 / ARCH §4.1(管线①-⑦)、§4.5 / DB §8.1 bff_rate_limit_configs / FEATURES BFF-01..04 | 无。限流维度/默认值、配置化路由、OpenAI 兼容双模式均已裁定 |
| G02 chat 提取 tenant/user/scopes + agent 访问校验 | 完整 | FLOW §3.1(权限校验图)+§4.1 S1 / ARCH §4.1③⑤、§4.6 / DB §1.4 scopes(agent:use) / FEATURES BFF-05 | 无。员工/管理员示例落地为 scope 方案，跨租户 403 双道防线（BFF+DB 过滤） |
| G03 工具调用必须经 BFF 统一拦截（总则） | **部分** | FLOW §3.8(拦截图) / ARCH §4.3、§4.4 / DB §9.2 trace_events(tool_call 事件) / FEATURES BFF-06 | 同 SA02：简易 agent 的 RAG 检索与文件上传两条内部 API 路径不产生 tool_call 拦截记录；BRIEF「必须」字面强要求与该设计存在张力，属「工具调用」定义边界未裁定（终审 #1/R1 已识别，复核成立，P1 最高优先） |
| G04 简易 agent：代码层拦截 LangChain Tool 回调 | 完整 | FLOW §4.3 S3(TI 拦截) / ARCH §2.3(模式①)、§4.3、DECISION-015 / DB §9.2(mode=simple) / FEATURES BFF-07 | 无。InterceptorTool 工厂、无裸注册路径的不变量已声明 |
| G05 第三方 agent：拦截 HTTP 响应中的 Tool Call | 完整 | FLOW §4.4 S4 / ARCH §2.4(模式②)、DECISION-008 / DB §9.2(mode=third_party) / FEATURES BFF-08 | 无。tool_calls 协议 + /tool_results 回传 + 最大轮次已定义 |
| G06 拦截三动作（scope 校验/注入 token/机器凭证代理执行） | 完整 | FLOW §3.8(统一动作图) / ARCH §4.3(动作链①②③)、§4.4 / DB §5.2 required_scopes、§9.2 payload(token_injected/machine_credential_ref/scope_check) / FEATURES BFF-09 | 无。三动作均可独立验证（篡改无效/代理凭证/越权防护），留痕字段齐全 |

### 1.11 Trace + 检索（T01–T02）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| T01 记录每会话交互（含文件）/工具调用/RAG 调用/时间点/token | 完整 | FLOW §3.9(写点) / ARCH §4.4(事件字段)、§2 各时序 / DB §9.1 trace_sessions、§9.2 trace_events(五事件类型) / FEATURES TRACE-01 | 无。五要素（含 file 事件、token 会话合计、时间戳）+ 简易/第三方双覆盖 + 会话互查均落点 |
| T02 trace 数据检索 | 完整 | FLOW §3.9(QR) / ARCH §4.7 / DB §9.2(组合索引+payload tsvector 全文) / FEATURES TRACE-02 | 无。多维筛选+关键词全文+下钻+租户隔离均已定义 |

### 1.12 对照小结

- **45 个标准 ID：完整 42、部分 3（S01、SA02、G03）、缺失 0**。
- 3 个「部分覆盖」归因于 2 个独立未决项：**① 工具拦截边界（SA02/G03 同根，P1）**；**② S01 既有数据迁移策略未成文（P2）**。
- BRIEF §4 的 7 个推测项（P1–P7）全部闭环到 DECISION-002/003/004/005/006/007/019 且标注【推测】，无未决推测（与 FEATURES §10.2 映射一致，本审阅逐条核对成立）。
- 质量要求「推断标注推测」：三文档【推测】标注实测 FLOW 54 / ARCH 24 / DB 88（按 `【推测】` 直接计数，另含图内 `[推测]`），密度充足，未发现「超出 BRIEF 却未标注」的实质性推断（个别字段级小推断如 `last_score`、`prompt_version` 均已标注）。

---

## 2. 对 DESIGN_REVIEW.md 终审结论的独立验证（可推翻项逐一复核）

> 终审结论：**PASS_WITH_ISSUES**（P1×2、P2×3、无 P0，45 ID 中 42 完整 + 3 部分）。

| 终审结论项 | 独立复核 | 复核结果 |
|---|---|---|
| ① 组件命名契约 31/31 一致 | 我逐一核对 FLOW §1 清单 31 项在 ARCH/DB 的落名：WebConsole→BFFGateway→ToolInterceptor→…→PlatformMCP-RAGSearch，三文档同一组件同一名称；PlatformMCP-UploadDoc/QueryDoc/RAGSearch 三个「组件」落地为 PlatformMCPServer 的 3 个**工具**（upload_doc/query_doc/rag_search），ARCH §3.1 与 DB §5.2 均显式说明该「组件名→工具名」映射 | **成立**。命名契约 100% 达成 |
| ② 14 项强制关键分支「图→架构→表」三层闭合 | 我独立复核其中高风险 6 项：登录鉴权+双令牌（FLOW S1 / ARCH §2.1 / DB §1.7+Redis 黑名单）、本地 vs 云存储三分支（FLOW §3.2 BE 分支 / ARCH §2.2 / DB §2.1 backend 行级分派）、视觉解析（FLOW §3.4 分支 / ARCH §2.2 / DB §4.4）、5 切分（FLOW §3.4 / ARCH §2.2 / DB §4.2-4.3 split_strategy/parent_id/is_table）、scope 校验失败分支（FLOW §3.8 SC 失败 / ARCH §4.3 RJ / DB §9.2 status=denied）、第三方 HTTP 拦截（FLOW S4 / ARCH §2.4 / DB §9.2 mode=third_party）——均三层闭合 | **成立** |
| ③ 45 标准 ID 42 完整 + 3 部分，无缺失无 P0 | 我按 §1 独立逐条重做（不依赖其 §2 表），结论**逐项一致**：42 完整 / 3 部分（S01、SA02、G03）/ 0 缺失；部分覆盖归因相同（#1 拦截边界、#5 迁移策略） | **成立**（我独立得出同样数字与归因） |
| ④ P1 #1 拦截边界（简易 agent RAG 检索/文件上传走内部 API 直调） | 我核 ARCH 原文：§1.1 数据流要点「不存在绕过拦截的路径（F: BFF-07 验收要点 3）」与 §9-7「简易 agent 直调存储内部 API（S3 流程图一致）」并存；§2.3 S3 时序中 `SAR->>RAG`、`SAR->>SS` 为内部 API 路径，trace 只落 rag/file 事件、**无 tool_call 事件**。BRIEF G03 原话「Agent 工具调用**必须**经过 BFF 统一拦截」——若 RAG 检索/文件上传被判定为「工具调用」，则 BFF-06 验收 1（「任一工具调用 trace 中均可看到 BFF 拦截记录，无绕过路径」）存在误判 FAIL 风险 | **成立，且我认为是本设计最实质的一点**。裁定方向我支持终审给的两案（定义「工具调用」边界并统一表述；或两条内部路径也落 tool_call 等价事件），建议开发前必裁 |
| ⑤ P1 #2 计数口径（「39 条」vs 45 标准 ID） | 我核 FEATURES §10.1 表：实际枚举 45 行（B5+S4+L3+R10+M3+K2+A4+SA3+TA3+G6+T2=45），而 FEATURES line 13/655 与 ARCH line 637 均写「39 条」。BRIEF §2 实际顶层 bullet 约 41 行（含 G 小节子项），「39」口径不可复现 | **成立**（口径确实不符，终审描述准确；本审阅另发现「39」连 BRIEF 顶层 bullet 数都对不上，更需在文档中写死计数方法） |
| ⑥ P2 #3 DB「25 张 vs 33 张」笔误 | 我核 DB line 1120：「上图覆盖全部 **25 张表**（…——共 **33 张**…）」，同句自相矛盾；§15 总表实为 33 张 | **成立**（纯笔误） |
| ⑦ P2 #4 「§7 九张」口径 | 我核 DB §7：7.1(1 张) + 7.2(4 张勾选表) + 7.3/7.4/7.5/7.6(4 张) = 9 张表 / 6 个 `###` 小节，表头 line 18「§7 九张」按表计正确但易误读 | **成立**（表述澄清即可） |
| ⑧ P2 #5 S01 迁移策略未成文 | 我核 FEATURES STORE-03 验收 2「既有文件在新后端下的处理策略（保留原后端访问/迁移）在设计文档说明」；ARCH/DB 均只有 `backend` 行级分派（隐含保留原后端），未见成文 | **成立** |
| ⑨ 遗留问题清单（R1-R7 / D1-D6） | 逐条核对：R1（拦截边界）成立；R2（双通道并存待确认）合理（FLOW S4 与 ARCH §9-6 表述一致）；R3（1536 维补零）成立且属高风险推测（RISK-004 跟踪中）；R4（默认参数）成立；D1-D6 处置合理。D6（占位模板 PRD/USER_STORIES/DESIGN 等未填充）经我核实属实——这些文件仍为 `{{PROJECT_NAME}}` 模板，不影响设计事实源，但开发/测试前需填充或删除 | **全部成立，无推翻项** |

**对终审的验证结论**：DESIGN_REVIEW 的 PASS_WITH_ISSUES 判定**成立，不推翻**。其 2 个 P1、3 个 P2、42+3 对照结论经我独立复核均属实；其未发现项中未发现重大遗漏（本审阅新增发现见 §3，均为 P2 级）。

---

## 3. 本审阅独立新发现问题（终审未覆盖）

| # | 级别 | 位置 | 问题描述 | 建议 |
|---|---|---|---|---|
| N1 | **P2** | ARCH §4.5（line 517）/ ARCH §8 DECISION-016 行（line 711）/ DECISIONS.md DECISION-016 / DB §7.1 agents.name | **OpenAI 兼容 `model` 参数语义三处不一致**：ARCH §4.5 写「model 字段即 **agent_id 或 agent 别名**」；DECISION-016 写「model 字段 = **agent 名称**（tenant 内唯一）」；DB §7.1 写「name … **= OpenAI model 标识域**」。另：**跨租户 model 解析路径未说明**——BFF 在鉴权提取 tenant 之前无法按 (tenant, name) 唯一定位 agent，需先跨租户查 name 再校验 `agent:use:<id>`，该解析与鉴权顺序在架构中未定义 | 统一为「model = agent 名称（租户内唯一）」或「model = agent_id」其一；补充 BFF 解析流程（查候选→租户/scope 校验→404/403 语义），写入 ARCH §4.5 |
| N2 | **P2** | DB §4.4 rag_doc_images.image_file_id（line 409）↔ DB §13.3 外键汇总（line 1024「级联」）↔ DB §2.1 storage_files.deleted_at（line 216「被 RAG 文档引用的文件禁删（409）」） | **外键行为自相矛盾**：业务逻辑规定被 RAG 文档引用的文件禁删（409），但 §13.3 将 `rag_doc_images.image_file_id → storage_files` 定为**级联删除**——若允许物理删除，会连带删除视觉解析记录；同表 `image_file_id` 的引用保护应与其他「被引用禁删」字段一致 | 改为 RESTRICT（与 §1033 的 `rag_docs.file_id`「限制（文件被引用禁删）」同口径），或在 §2.1 删除流程中显式说明该场景 |
| N3 | **P2** | DB §7.4 agent_messages（索引 line 647）/ DB §13.2「租户主查询索引」清单（line 964-981）↔ BASE-07 验收 3 / DB §10.2 | **索引策略与自声明不一致**：DB §10.2 声明「主查询索引一律以 tenant_id 打头」，DESIGN_REVIEW §1.2 亦按此裁定「✓ 完整」；但 `agent_messages` 的主查询索引为 `idx_messages_session(session_id, created_at)`，**tenant_id 未打头**（agent_sessions 有 tenant 打头索引，agent_messages 没有）。功能上无漏洞（session 已隐含租户），但按 BASE-07 验收 3「所有业务表含 tenant_id 且有相应索引」与自声明口径，存在可被测试抓到的偏差 | 补 `idx_messages_tenant(tenant_id, ...)` 或在 §10.2 注明「session 从属表按 session 打头（session 已隐含租户）」的例外口径 |

> 说明：N1–N3 均为 P2（不阻断开发、不改变设计正确性、可在开发前随手修正），与终审的 P1×2 性质不同；未发现任何 P0/P1 级终审遗漏。

---

## 4. 问题清单（按 P0/P1/P2 汇总）

### P0（阻断）
- **无**。

### P1（开发前必须裁定，不阻断设计终审）

| # | 问题 | 责任 | 来源 |
|---|---|---|---|
| P1-1 | **工具拦截边界**：简易 agent 的 RAG 检索 + 文件上传走内部 API 直调、不产生 tool_call 拦截 trace；与 BRIEF「工具调用必须经 BFF 统一拦截」字面强要求存在张力；ARCH §1.1 与 §9-7 表述未对齐。影响 SA02/G03 与 BFF-06 验收判据。裁定选项：① 明确「工具调用」= MCP 工具调用（内部 RAG/文件 API 属平台内部服务调用，落 rag/file 事件即可），并统一表述 + 写入 BFF-06 验收排除项；② 两条内部路径也落 tool_call 等价事件。 | 罗辑 + 章北海 + 用户 | 终审 #1/R1（本审阅复核成立） |
| P1-2 | **计数口径**：FEATURES/ARCH 声明「39 条」，对照表实为 45 个标准 ID；「39」口径不可复现（BRIEF 顶层 bullet 约 41 行）。需在文档写死计数方法（如「39 条原话 → 展开 45 个标准 ID」）。 | 章北海 / 罗辑 | 终审 #2（本审阅复核成立并加强：39 连 bullet 数都对不上） |

### P2（记录，开发前/开发中随手修正）

| # | 问题 | 来源 |
|---|---|---|
| P2-1 | S01 既有数据迁移策略未成文：明确「保留原后端访问（不迁移）」写入 ARCH/DB | 终审 #5（复核成立） |
| P2-2 | DB §14「25 张表」笔误 →「33 张」 | 终审 #3（复核成立） |
| P2-3 | DB 表头「§7 九张」注明构成（1 定义 + 4 勾选 + 4 会话/消息/记忆/obsidian） | 终审 #4（复核成立） |
| P2-4 | OpenAI `model` 参数语义三处不一致（agent_id/别名/名称）+ 跨租户解析路径未定义 | 本审阅 N1（新发现） |
| P2-5 | `rag_doc_images.image_file_id` FK 行为（级联）与「被 RAG 文档引用的文件禁删（409）」矛盾，应 RESTRICT | 本审阅 N2（新发现） |
| P2-6 | `agent_messages` 主查询索引未 tenant 打头，与 §10.2 自声明口径/BASE-07 验收 3 存在偏差 | 本审阅 N3（新发现） |
| P2-7 | 高风险推测待用户确认：向量 1536 维 + 低维补零（RISK-004）、阈值/topN/切分默认值、第三方 agent 协议（DECISION-008，需 mock server）、trace/审计 90 天保留（RISK-005）、权限三级模型（DECISION-004） | 终审 R3-R7（复核成立） |
| P2-8 | 占位模板未清理：PRD/USER_STORIES/PRODUCT_DECISIONS/DESIGN/DEV_REPORT/03-testing 仍为 `{{PROJECT_NAME}}` 模板，与事实源并存易混淆 | 终审 D6（本审阅核实属实） |

---

## 5. 总体结论

**判定：部分符合（PASS_WITH_ISSUES）——与褚岩终审结论一致，不推翻。**

依据：

1. **覆盖完整性**：BRIEF §2 全部 45 个标准 ID 中 **42 个完整覆盖、3 个部分覆盖（S01、SA02、G03）、0 缺失**；BRIEF §4 七个推测项（P1–P7）全部闭环到 DECISION 并标注【推测】。五份文档（FLOW/FEATURES/ARCH/DB/REVIEW）在 31 项组件命名契约、14 项强制关键分支、56 个功能点回溯上相互一致（本审阅独立复核成立）。
2. **为什么不是「符合」**：存在 2 个 P1——① 工具拦截边界（BRIEF「必须」硬要求 vs 内部 API 直调设计的真实张力，直接威胁 BFF-06 验收判据，开发前必须裁定）；② 计数口径（削弱「逐条无遗漏」的可验证性）。另有 8 个 P2（含本审阅新发现 3 项：model 参数语义不一致、FK 行为矛盾、索引口径偏差）。
3. **为什么不是「不符合」**：无任何 BRIEF 需求整体缺失；无三文档相互矛盾到无法实现的冲突；P1 均属「边界澄清/表述勘误」而非设计错误，且已给出明确处置方向与责任方；全部推测项已闭环并标注。

**交付质量评价**（系统分析视角）：四份设计文档的证据链（图→机制→表→功能点→决策）完整可复核，「推测」标注纪律执行到位，交叉契约（命名/功能点 ID/决策编号）全部落地——设计文档质量达到「可直接进入开发」的水位，遗留的 2 个 P1 属**实现边界澄清**，按终审规则记录于遗留问题、不 block 设计终审；但**开发启动前必须完成 P1-1 的裁定**（D1/R1），否则测试阶段 BFF-06 验收存在误判风险。

---

*（完）REVIEW_shiqiang.md — 史强（系统分析师），2026-09-22。独立逐条对照 45 标准 ID + 终审 9 项结论复核 + 3 项新发现（P2）。只读审阅，未修改任何被审文档。*
