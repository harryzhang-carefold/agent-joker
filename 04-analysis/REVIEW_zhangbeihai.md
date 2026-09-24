# REVIEW — agent-joker 设计文档独立审阅（开发视角）

> 任务：t_4f13ace1（agent-joker 设计文档独立审阅-章北海）。作者：章北海（开发工程师），2026-09-22。
> 审阅对象：`00-management/BRIEF.md`（基准）+ `01-product/FLOW_DIAGRAMS.md`、`01-product/FEATURES.md`、`02-development/ARCHITECTURE.md`、`02-development/DB_DESIGN.md`，并验证 `00-management/DESIGN_REVIEW.md` 的终审结论是否成立。
> 方法：独立逐条审阅（不照抄终审）——先按 BRIEF §2 全部原始 bullet 自行编号展开为 45 个标准 ID（B/S/L/R/M/K/A/SA/TA/G/T），再逐条到 5 份文档找落点（图/架构/表三级），并复核 DESIGN_REVIEW 的每个论断（数字、引用、裁定）。
> 独立核对基线（本次实际执行）：
> - mermaid 块数：FLOW 21 / ARCH 8 / DB 1（与 DESIGN_REVIEW §0 一致）；
> - FEATURES §10.1 标准 ID 枚举实为 **45 行**（5+4+3+10+3+2+4+3+3+6+2=45）；BRIEF §2 原始 bullet 实为 **42 行**（B1+S4+L3+R10+M3+K2+A4+SA3+TA3+G7+T2）——**「39 条」与两个口径都不符**，且 39 恰等于「去掉 G 小节（6 条）后的展开 ID 之和」（5+4+3+10+3+2+4+3+3+2=39），即该数字疑似漏掉了整个 BFF 小节，未做任何口径说明；
> - DECISIONS.md 21 条决策（DECISION-001..021）全部存在，与 ARCH §8 索引一一对应；
> - 【推测】标注密度：FLOW 58 / ARCH 56 / DB 119（与终审口径一致，密度充足）；
> - DB 表数：按 §15 总表逐张数 = 33 张（8+2+3+4+2+2+9+1+2），与文首声明一致。

---

## 1. 逐条对照表（BRIEF §2 每条原话 → 5 份文档覆盖情况）

> 覆盖情况：完整 = 图/架构/表三层（适用层）均有落点且无歧义；部分 = 有落点但存在未裁定/未成文/表述冲突；缺失 = 无落点。
> 证据格式：`文档 §章节`。5 份文档中 BRIEF 为基准，DESIGN_REVIEW 为被验证对象，故证据列主要给出 FLOW/FEATURES/ARCH/DB 的落点。

### 1.1 基础功能（B01–B05）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| B01 用户管理 | 完整 | FLOW §3.1；FEATURES BASE-01；ARCH §1.1(IAM)；DB §1.2 users（状态禁用/重置密码/软删） | 无 |
| B02 角色管理 | 完整 | FLOW §3.1；FEATURES BASE-02；ARCH §4.6；DB §1.3 roles + §1.5 role_scopes | 无 |
| B03 权限管理 | 完整 | FLOW §3.1（scope 即权限项）；FEATURES BASE-03；ARCH §4.6（scope 三类 + agent:use 方案）；DB §1.4 scopes | 无 |
| B04 登入登出 | 完整 | FLOW §3.1/§4.1(S1)；FEATURES BASE-04/05/09；ARCH §2.1（双令牌+黑名单）；DB §1.7 auth_refresh_tokens | JWT 双令牌为【推测】（P2），已标注并闭环 DECISION-002，不构成缺口 |
| B05 接口操作日志 | 完整 | FLOW §3.1；FEATURES BASE-06；ARCH §4.1⑦；DB §1.8 api_audit_logs（脱敏/异步/组合索引/90 天分区） | 无 |
| （BFF 原话「提取 tenant_id」→ 多租户模型，BRIEF §4-P3） | 完整 | FLOW §1(TEN)/§4.1；FEATURES BASE-07【推测】；ARCH §4.2 TenantScope；DB §10 隔离策略 + §1.1 tenants | P3 推测已闭环 DECISION-004；「平台级共享表」范围裁定在 ARCH §9-13【推测】，待用户确认（R5），不阻断 |

### 1.2 存储模块（S01–S04）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| S01 保存文件：本地/GCS/OSS，配置文件可配置 | **部分** | FLOW §3.2（BE 三分支）；FEATURES STORE-01/02/03；ARCH §1.1(StorageBackend)/§2.2/§5.3(STORAGE_BACKEND)；DB §2.1 storage_files.backend 行级记录 | **后端切换后既有文件策略未显式成文**：DB §2 只写「记录每文件实际落点，支持混合定位」（隐含=保留原后端访问、不迁移），FEATURES STORE-03 验收 2 明确要求「（保留原后端访问/迁移）在设计文档说明」。需一句话裁定成文（见 P2-5）。 |
| S02 访问文件：统一接口、按文件名访问 | 完整 | FLOW §3.2；FEATURES STORE-04；ARCH §3.1/§2.2；DB §2.1 访问接口行为说明（404/403/租户内唯一 409） | 无 |
| S03 保存文件上传记录 | 完整 | FLOW §3.2(UploadRecord)；FEATURES STORE-05；ARCH §2.2；DB §2.2 storage_upload_records（source 六类/筛选索引） | 无 |
| S04 上传/访问接口可注册为 MCP 工具 | 完整 | FLOW §3.2(PlatformMCP-UploadDoc/QueryDoc)；FEATURES STORE-06/07；ARCH §3.1（upload_doc/query_doc，source=platform）；DB §5.2 mcp_tools(source=platform) | 无 |

### 1.3 LLM 节点（L01–L03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| L01 LLM endpoint 信息维护 | 完整 | FLOW §3.3；FEATURES LLM-01；ARCH §1.1；DB §3.1 llm_endpoints（supports_vision/加密 key/连通性测试/引用保护） | 无 |
| L02 embedding 模型信息维护 | 完整 | FLOW §3.3；FEATURES LLM-02；DB §3.2（dimensions 建库锁定） | 无 |
| L03 reranker 模型信息维护 | 完整 | FLOW §3.3；FEATURES LLM-03；DB §3.3（可选引用） | 无 |

### 1.4 RAG（R01–R10，核心模块）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| R01 创建知识库 | 完整 | FLOW §3.4；FEATURES RAG-01；ARCH §2.2；DB §4.1（tag/embedding 锁定/级联删除已声明） | 无 |
| R02 上传 6 类文档 | 完整 | FLOW §3.4/§4.2(S2)；FEATURES RAG-02；ARCH §2.2(DocParser 分派)；DB §4.2 rag_docs.doc_type（非支持类型 422） | 无 |
| R03 图片/扫描 PDF/内嵌图走 LLM 视觉 | 完整 | FLOW §3.4 解析流水线（三类分支）+§4.2(S2 alt)；FEATURES RAG-03；ARCH §2.2 视觉分支；DB §4.4 rag_doc_images（逐图记录 vision_endpoint_id/vision_text/status） | 解析实现为 P5 推测，已闭环 DECISION-005；视觉不可用降级路径标【推测】并 RISK 跟踪 |
| R04 上传文档（调用存储模块 API） | 完整 | FLOW §4.2(S2)；FEATURES RAG-02；DB §4.2 rag_docs.file_id FK→storage_files（source=kb） | 无 |
| R05 切分策略 5 种 | 完整 | FLOW §3.4（S1–S5 五分支）+§4.2(S2)；FEATURES RAG-04；ARCH §2.2(ChunkSplitter 5 策略工厂)/DECISION-020；DB §4.3 split_strategy/parent_id/is_table + 重切分 | 各策略默认参数为【推测】，已列默认值（500/50、1:4、0.25 等），待用户确认（R4），不阻断 |
| R06 原文查看 + 手改 chunk | 完整 | FLOW §3.4(CH/RV)；FEATURES RAG-05；ARCH §2.2（改后重算 embedding）；DB §4.3 content/edited_at/updated_by + content_sha256 | 无 |
| R07 选择 embedding、rerank 模型 | 完整 | FLOW §3.4(RT)；FEATURES RAG-06/07；ARCH §2.2 检索分支；DB §4.1 embedding_model_id/reranker_model_id | 无 |
| R08 设置 topK、阈值 | 完整 | FLOW §3.4（Q4/Q7 分支）；FEATURES RAG-08；ARCH §2.2/DECISION-006（阈值语义裁定）；DB §4.1 top_k_default/score_threshold/recall_top_n | 验收 3「单次检索覆盖库默认」当前为【推测】（D4 待开发明确 API 是否支持），库级配置已完整 |
| R09 检索返回 chunk 索引 + 原文位置（反向定位） | 完整 | FLOW §3.4(Q9/Q10)+§4.2(S2)；FEATURES RAG-09；ARCH §2.2 反向定位/§4.5 定位 URL；DB §4.3 pos(JSONB)/chunk_index + UNIQUE(doc_id, chunk_index) | 位置 JSON 结构 `{page, section_path, char_start, char_end, table_row}` 已裁定（ARCH §9-11【推测】），闭环 |
| R10 知识库查询做成 MCP 工具 | 完整 | FLOW §3.4(MC)；FEATURES RAG-10；ARCH §3.1(rag_search)；DB §5.2 mcp_tools(source=platform, rag_search) | 无 |

### 1.5 MCP（M01–M03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| M01 通过 URL 注册 MCP server（多个） | 完整 | FLOW §3.5；FEATURES MCP-01；ARCH §3.2（注册→探测→tools/list 快照）；DB §5.1 mcp_servers（transport/status/last_sync_at） | 无 |
| M02 工具列表 + 禁用/启用/删除 | 完整 | FLOW §3.5；FEATURES MCP-02；ARCH §3.2（状态机 + 平台内置同列）；DB §5.2（enabled/removed_remote/input_schema 快照/UNIQUE(server_id,name)） | 无 |
| M03 删除/禁用提示关联调用方 | 完整 | FLOW §3.5（CHK/WARN/CONF 分支）；FEATURES MCP-03；ARCH §3.2（409+清单+confirm）；DB §7.2.3 agent_mcp_tools + idx_agent_tools_tool(WHERE deleted_at IS NULL) | 无 |

### 1.6 Skills（K01–K02）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| K01 手动添加/上传 skill，维护名称内容 | 完整 | FLOW §3.6；FEATURES SKILL-01；ARCH §1.1(SkillsService)；DB §6.1 skills（content/source/version） | 无 |
| K02 元数据存 DB、文件走存储模块 | 完整 | FLOW §3.6；FEATURES SKILL-02；ARCH §1.1；DB §6.1+§6.2（skill_files 引用 storage_files，source=skill） | 无 |

### 1.7 Agent（A01–A04）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| A01 创建/维护 agent 信息 | 完整 | FLOW §3.7；FEATURES AGENT-01；ARCH §1.1；DB §7.1 agents（system_prompt/删除策略已声明） | 无 |
| A02 类型：简易（langchain）/第三方（URL） | 完整 | FLOW §3.7；FEATURES AGENT-02；ARCH §1.1/§2.3/§2.4；DB §7.1 type/third_party_url | 编排方式 P7 已闭环 DECISION-007（tool-calling loop） |
| A03 配置四要素（从列表勾选） | 完整 | FLOW §3.7 配置关系图；FEATURES AGENT-03；ARCH §1.2；DB §7.2 四张勾选表（回显/未选不启用/引用保护） | 无 |
| A04 对话交互、会话列表、对话详情 | 完整 | FLOW §3.7/§4.3/§4.4；FEATURES AGENT-04；ARCH §2.3/§2.4/§4.5；DB §7.3 agent_sessions + §7.4 agent_messages | 无 |

### 1.8 简易 agent（SA01–SA03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| SA01 记忆：redis 短期 / pgsql 长期 / obsidian 沉淀 | 完整 | FLOW §3.7/§4.3(S3)；FEATURES AGENT-07/08；ARCH §2.3/§6#12；DB §7.5 agent_memories + §11 Redis joker:mem:* + §7.6/§12 obsidian | P6 已闭环 DECISION-019；长期记忆提炼时机为【推测】（R4 级，可调） |
| SA02 交互文件上传到存储模块 | **部分** | FLOW §4.3(S3 文件分支)；FEATURES AGENT-06；ARCH §2.3（内部 API 上传）；DB §2.2 storage_upload_records(source=agent) | **与 G03 拦截总则的边界冲突**（P1-1）：S3 图中文件上传走 `SAR->>SS 内部 API` 直调、不经 ToolInterceptor，与 BRIEF「工具调用必须经 BFF 统一拦截」字面要求存在张力。详见 P1-1。 |
| SA03 official tag / 用户要求时附 RAG 来源 + 链接 | 完整 | FLOW §4.3(S3 alt 两条件或)+§4.4(S4)；FEATURES AGENT-05；ARCH §4.5（DECISION-017 show_citations+LLM 兜底）；DB §4.1 kb.tag + §7.4 citations(JSONB) | 无 |

### 1.9 第三方 agent（TA01–TA03）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| TA01 记忆由提供方实现 | 完整 | FLOW §4.4(S4 前置注)；FEATURES AGENT-09；ARCH §2.4；DB §7.1 external_session_id（平台不存记忆，仅透传句柄） | 无 |
| TA02 文件经存储 MCP 工具（提供方决定是否调用） | 完整 | FLOW §4.4(S4 平台 MCP 分支)；FEATURES AGENT-10；ARCH §2.4/§3.1（可用不强制）；DB §5.2 平台工具行 | 「不配置该工具时对话仍正常」由工具可选性天然满足，闭环 |
| TA03 RAG 引用同上（提供方决定是否显示） | 完整 | FLOW §4.4(S4 RAG alt)；FEATURES AGENT-11；ARCH §2.4/§4.5；DB §7.4 citations | 无 |

### 1.10 BFF 网关（G01–G06）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| G01 统一鉴权/流量控制/API 路由/协议转换（OpenAI 兼容） | 完整 | FLOW §3.8；FEATURES BFF-01..04；ARCH §4.1 管线①②④⑥/§4.5；DB §8.1 bff_rate_limit_configs | 限流默认值/路由 YAML 为【推测】，已闭环 DECISION-013/014 |
| G02 chat 提取 tenant/user/scopes + 目标 Agent 访问校验 | 完整 | FLOW §3.8/§4.1(S1)；FEATURES BFF-05；ARCH §4.1③⑤/§4.6（agent:use:<id> scope）；DB §1.4 scopes（agent 创建自动 upsert） | 无 |
| G03 工具调用必须经 BFF 统一拦截（总则） | **部分** | FLOW §3.8；FEATURES BFF-06；ARCH §4.3/§4.4（两模式同一动作链 + tool_call 事件）；DB §9.2 trace_events（denied/token_injected/machine_credential_ref） | **拦截边界 P1-1**：简易 agent 的 RAG 检索 + 文件上传两条内部 API 路径不经 ToolInterceptor，BFF-06 验收 1「任一工具调用 trace 中均可看到 BFF 拦截记录（无绕过路径）」在测试判定时可能歧义。缓解：两条路径有 `rag`/`file` 类型 trace 事件（DB §9.2），留痕存在但非 tool_call 拦截事件。 |
| G04 简易 agent：代码层拦截 LangChain Tool 回调 | 完整 | FLOW §4.3(S3 回调分支)；FEATURES BFF-07；ARCH §2.3/§4.3 模式①（InterceptorTool 工厂，无裸注册） | 注：「进程内共享库调用」（DECISION-015）与 S3 图中 TI 独立参与者的画法有措辞不一致（见 P2-7），拦截机制本身完整 |
| G05 第三方 agent：拦截 HTTP 响应 Tool Call | 完整 | FLOW §4.4(S4 拦截分支)；FEATURES BFF-08；ARCH §2.4/§4.3 模式②（tool_calls 解析 + /tool_results 回传）；DB §9.2 payload.mode=third_party | 协议为【推测】DECISION-008，需测试 mock 联调（D5），不阻断设计 |
| G06 拦截三动作：scope 校验 / 强制覆写 token / 机器凭证代理 | 完整 | FLOW §3.8（SC/OW/EX 三分支）；FEATURES BFF-09；ARCH §4.3（①②③ 全链路 + 覆写字段规则 + 拒绝语义）；DB §5.2 required_scopes + §9.2 payload 三字段 | 机器凭证管理已裁定（DECISION-012，env/.env 不落表） |

### 1.11 Trace（T01–T02）

| BRIEF 条目 | 覆盖情况 | 证据（文档+章节） | 问题描述 |
|---|---|---|---|
| T01 记录每会话交互（含文件）/工具/RAG/时间点/token | 完整 | FLOW §3.9/§4.3/§4.4；FEATURES TRACE-01；ARCH §4.4；DB §9.1 trace_sessions + §9.2 trace_events（五要素 + file 事件 + payload 结构约定） | 无 |
| T02 trace 检索 | 完整 | FLOW §3.9(QR)；FEATURES TRACE-02；ARCH §4.7；DB §9.2 组合索引 + payload_tsv GIN 全文 + 租户隔离 | 中文分词用 simple 配置为【推测】（闭环够用） |

> **逐条核对结论**：BRIEF §2 展开 45 个标准 ID，**42 完整 + 3 部分（S01、SA02、G03）+ 0 缺失**。3 个部分项全部归因于两个已识别问题：P1-1 拦截边界（SA02、G03）与 P2-5 后端切换策略未成文（S01）。BRIEF §4 的 7 个推测项（P1–P7）逐条核对全部闭环到 DECISION（003/002/004/006/005/019/007）并带【推测】标注。

---

## 2. 对 DESIGN_REVIEW.md 终审结论的验证

> 任务要求「验证其结论是否成立，可推翻」。我对终审的每个关键论断做了独立复核（不依赖其数字，全部重算/重读）。

| 终审论断 | 我的独立复核 | 结论 |
|---|---|---|
| §0 上游自验数字（图数 9、组件 31、功能点 56、覆盖 56/56） | 实数 mermaid：FLOW 21/ARCH 8/DB 1 ✓；FEATURES 功能点按 §10.3 逐模块数 = 9+7+3+10+3+2+11+9+2 = 56 ✓；DB 每表头 F: 标注逐表核对 33 张表全有功能点回溯 ✓ | 成立 |
| §1-#1（P1）拦截边界：SAR→RAG/SS 内部 API 直调不经 ToolInterceptor，与 BRIEF「必须」张力；ARCH §1.1 与 §9-7 措辞未对齐 | 我重读确认：ARCH §1.1（line 135）「或平台内部 API（RAG 检索/文件上传，携带用户身份内部调用）——不存在绕过拦截的路径」；§2.3 S3 图 `SAR->>RAG`、`SAR->>SS` 直连无 TI；§9-7「两条路径都经 ToolInterceptor，无绕过」。**比终审指出的更严重：是 ARCH 内部三处（§1.1/§2.3 图/§9-7）互相矛盾**——§9-7 称两条路径都经拦截器，但其自己的 S3 时序图画的恰恰是不经。BRIEF 字面「必须」与设计的张力成立，且文档自身表述未收敛 | **成立，且需加强**（见 P1-1 扩展） |
| §1-#2（P1）「39 条」vs 45 个标准 ID，口径未说明 | 我重数：标准 ID = 45 行 ✓；BRIEF 原始 bullet = 42 行 ✓；「39」两者都不符，且 39 恰等于**去掉 G 小节后的 ID 之和**（即该计数疑似漏数了整个 BFF 小节）。FEATURES §0/§10.1 与 ARCH §7 均写「39 条」 | **成立**（比终审所述更明确：39 的来历就是漏了 G 小节，必须改口径） |
| §1-#3（P2）DB §14「25 张」vs「33 张」自相矛盾 | 重读 DB line 1120：「上图覆盖全部 25 张表（……共 33 张）」✓ 同一句内矛盾 | 成立 |
| §1-#4（P2）DB 表头「§7 九张」vs §7 实际 6 个 `###` 小节 | 重数 §7 小节：7.1/7.2/7.3/7.4/7.5/7.6 = 6 节；表数 = 1+4+4 = 9 张 ✓ 口径混淆成立 | 成立 |
| §1-#5（P2）S03 后端切换策略未显式成文 | 重读 DB §2 说明与 ARCH §9（17 项遗留无此项）：仅隐含「保留原后端访问」，未见「不迁移」的显式裁定句 | 成立 |
| §2 逐条对照：45 条 = 42 已覆盖 + 3 部分（S01/SA02/G03），无缺失无 P0 | 我独立逐条复核（本报告 §1，45 行全部重查证据），结果一致：42 完整 + 3 部分（S01/SA02/G03），0 缺失 | **成立**（逐条证据我已独立验证，非引用终审） |
| §3 推测项：P1–P7 全部闭环 DECISION | 逐条核对 7 项映射（003/002/004/006/005/019/007）✓，DECISIONS.md 21 条实际存在 ✓ | 成立 |
| §4 遗留 R1–R7 / D1–D6 | R1（拦截边界）我独立确认且建议升格处置（P1-1 扩展）；R2（双通道）与 FLOW S3/S4 一致 ✓；R3（1536 维补零）DB §4.3 有 RISK-004 跟踪 ✓；D2/D3 与我发现一致；D6 占位模板属实（PRD/USER_STORIES/PRODUCT_DECISIONS/DESIGN/DEV_REPORT 均为占位）✓ | 成立 |
| §5 判定 PASS_WITH_ISSUES | 无 P0 缺失、无三文档矛盾到不可实现、P1 均为边界澄清/口径勘误——我的独立复核未发现反例 | **成立，不推翻** |

> **验证结论**：DESIGN_REVIEW 的 5 项不一致（1 P1 拦截边界 + 1 P1 计数 + 3 P2）我全部独立复现，其 §2 逐条对照 42/3/0 的结论与我的独立复核完全一致，§5「PASS_WITH_ISSUES」判定**成立，不予推翻**。我另发现终审未覆盖的 3 个新问题（P2-6/7/8，见 §3）。

---

## 3. 总体结论

**符合（PASS_WITH_ISSUES）**——5 份文档完整准确覆盖了 BRIEF §2 全部 45 个标准 ID 原始需求（42 完整 + 3 部分 + 0 缺失），BRIEF §4 的 7 个推测项全部闭环 DECISION 并标注【推测】，BRIEF §6 各交付物验收标准（FLOW 4 核心时序 + 3 强制分支、ARCH 九章齐备、DB 33 表全字段逐行列出 + Redis key + obsidian 目录 + ER + 隔离/索引策略）逐条满足；未发现 P0 级缺失或三文档矛盾到无法实现的问题。

不满足「无条件符合」的原因：存在 2 个 P1（拦截边界需开发前裁定、「39 条」计数口径错误）与 6 个 P2（文字勘误/表述澄清/一处内部 API 校验缺省说明）。所有 P1/P2 均有明确处置路径，不阻断设计阶段验收。

## 4. 问题清单（按 P0/P1/P2）

### P0（阻断级）
**无。**

### P1（开发前必须裁定/修正）

**P1-1 拦截边界未裁定 + ARCH 内部三处表述互相矛盾（终审 #1，我复核后加强）**
- 位置：BRIEF §2-BFF「Agent 工具调用**必须**经过 BFF 统一拦截」 vs ARCH §1.1（line 135，「内部 API 直调……不存在绕过拦截的路径」）vs ARCH §2.3 S3 时序图（`SAR->>RAG`、`SAR->>SS` 直连、无 TI 参与者）vs ARCH §9-7（「两条路径都经 ToolInterceptor，无绕过」）。
- 问题：①简易 agent 的 RAG 检索、文件上传走内部 API 不经 ToolInterceptor，与「必须」字面强要求冲突；②ARCH 自身三处表述不可同时为真——§9-7 声称两条路径都经拦截器，S3 图画的却是不经；§1.1 的「不存在绕过拦截的路径」在内部 API 路径上只有「租户+身份校验、无 tool_call 拦截事件」这一弱化含义。
- 影响：BFF-06 验收 1（「任一工具调用 trace 中均可看到 BFF 拦截记录，无绕过路径」）在测试阶段可能被判 FAIL；FEATURES BFF-07 验收 3 的「绕过」边界同样受影响。
- 处置（建议裁定）：明确「工具调用」= 经 ToolInterceptor 的 MCP/工具执行；RAG 检索与文件上传属「平台内部服务调用」，不入拦截器，但①在 ARCH 统一一处权威表述（§1.1、§2.3、§9-7、§4.4 四处对齐），②给这两条内部 API 路径补 scope/勾选关系校验说明（见 P2-6），③trace 保留 rag/file 事件（现状已有）并在 FEATURES BFF-06 验收 1 的「无绕过路径」中显式排除这两类内部调用或改判据为「工具调用均有 tool_call 事件，内部调用有 rag/file 事件」。责任：罗辑 + 章北海 + 用户拍板。

**P1-2 「39 条」计数口径错误（终审 #2，我复核后定位到根因）**
- 位置：FEATURES §0（line 13）/§10.1（line 655）、ARCH §7（line 637）均写「BRIEF §2 共 39 条」。
- 问题：独立重数 = 45 个标准 ID / 42 条原始 bullet；「39」恰等于**去掉 BFF（G）小节后的 ID 之和**（5+4+3+10+3+2+4+3+3+2=39），即该计数把 BFF 6 条整个漏掉了。这不是「口径不同」，是**漏数**，且漏的恰好是 BRIEF 的硬要求小节（拦截总则等），会系统性削弱「逐条无遗漏」的可验证性。
- 处置：三处统一改为「45 个标准 ID（源自 42 条原始 bullet，B01–B05…G01–G06…T01–T02）」，并删除/修正「39 条」表述。责任：罗辑/章北海（开发前随手改）。

### P2（开发阶段修正，不阻断）

**P2-1 DB §14 表数自相矛盾（终审 #3，已复核）**：line 1120「上图覆盖全部 25 张表（……共 33 张）」——将「25 张」改「33 张」（§14 节标题 line 1046「25+ 张表」同步改）。

**P2-2 DB 表头「§7 九张」口径混淆（终审 #4，已复核）**：§7 实际 6 个 `###` 小节、9 张表。注明「§7 共 9 张表 = 1 定义 + 4 勾选 + 4 会话/消息/记忆/obsidian」，与 §15 总表对齐。

**P2-3 S01/S03 后端切换策略未成文（终审 #5，已复核）**：需在 ARCH §2.2 或 DB §2 显式写一句裁定：「切换后端采用**保留原后端访问（不迁移）**：`storage_files.backend` 行级记录实际落点，访问按行分派；新上传走新后端」。FEATURES STORE-03 验收 2 要求该策略「在设计文档说明」。

**P2-4（新发现）简易 agent 内部 RAG 检索 API 未说明「agent 只能检索其勾选的 KB」的校验**：S3 中 `SAR->>RAG 内部 API` 只说明「携带用户身份」（= 租户隔离），但未说明是否校验 `(agent_id, kb_id) ∈ agent_knowledge_bases`。若不校验，agent 可检索同租户内未勾选的其他 KB（数据面越权，虽不跨租户）。平台 MCP 工具路径有 `required_scopes` 校验，内部 API 路径的等价校验应成文。处置：ARCH §2.3/§4.2 补一句「内部 RAG 检索 API 校验 agent 对目标 KB 的勾选关系（agent_knowledge_bases），未勾选 403」。

**P2-5（新发现）S3 图与「进程内共享库调用」措辞不一致（DECISION-015）**：ARCH §4.3/§2.3 称 ToolInterceptor 为「进程内共享库调用」（即拦截逻辑在 SAR 进程内以共享库方式执行，TI 不是独立进程），但 S3 时序图把 TI 画成独立参与者、`SAR->>TI` 为跨进程箭头，且 §1.3 给了 SAR 独立端口 8002。三者混用了「进程内库调用」与「进程间调用」两种语义。处置：统一表述——明确 ToolInterceptor 是共享代码库、拦截在 SAR 进程内执行（或改 S3 图把 TI 并入 SAR 泳道），并明确 trace 写点（SAR 进程内上报）。不影响功能，但开发实现前必须收敛，否则「拦截发生在哪个进程」会直接影响 token 上下文传递的实现。

**P2-6（新发现）FEATURES 功能点统计小错**：FEATURES §0/§10.3 写「纯推测 4 + 混合 4 + 用户明确要求 48 = 56」，但 BASE-04/05 计为 2 个功能点时混合标注实为 5 个点（BASE-04、BASE-05、RAG-03、AGENT-02、BFF-05），4+5+47=56。将「48」改「47」或注明「BASE-04/05 合并计 1 项」。纯文字勘误。

### 遗留跟踪（非本审阅新增，确认在案）
- RISK-004（1536 维统一 + 补零假设）、RISK-005（trace 存储增长）、R1–R7/D1–D6（DESIGN_REVIEW §4）均确认已记录在案，进入开发阶段按清单落实。
- 占位模板（PRD/USER_STORIES/PRODUCT_DECISIONS/DESIGN.md/DEV_REPORT.md）按 D6 在开发/测试阶段前由对应角色填充或删除。

---

*（完）REVIEW_zhangbeihai.md — 章北海（开发视角独立审阅），2026-09-22。方法：45 标准 ID 逐条独立复核 + DESIGN_REVIEW 全部论断重算验证。结论：符合（PASS_WITH_ISSUES），P0×0 / P1×2 / P2×6，DESIGN_REVIEW 终审结论成立、不推翻。*
