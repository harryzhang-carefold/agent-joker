# REVISION_VERIFY — agent-joker 文档修订复核（TASK-D08）

> 复核人：云天明（测试/可验证性视角）｜日期：2026-09-22
> 任务：复核 TASK-D05/D06/D07 三份文档修订是否逐条修复 5 份独立审阅（REVIEW_*.md）提出的 P0/P1/P2 问题，并重点验证两条用户级裁定（D-A / D-B）是否全链路落地且口径一致。
> 方法：**只读复核**——不修改任何被审文档。逐条核对证据（文档 + 章节 + 行号）；发现未修复项在本文件精确标注（文件+章节+期望改法），不自行改。
>
> 被复核对象（D05/D06/D07 修订后 4 份设计文档）：
> - `01-product/FLOW_DIAGRAMS.md`（D05，史强）
> - `01-product/FEATURES.md`（D06，罗辑）
> - `02-development/ARCHITECTURE.md`（D07，章北海）
> - `02-development/DB_DESIGN.md`（D07，章北海）
>
> 问题来源（5 份审阅）：`REVIEW_chuyan.md` / `REVIEW_luoji.md` / `REVIEW_shiqiang.md` / `REVIEW_yuntianming.md` / `REVIEW_zhangbeihai.md`
>
> 用户裁定基准（2026-09-22 正式确认，见任务书与 `05-temp/d_b_ruling.md`）：
> - **D-A**：official tag = **文档级两级判定**（文档级 `tag=official`，或文档级为空且所属知识库 `tag=official`）。
> - **D-B**：工具调用拦截边界 = ①agent 对接业务系统统一经 BFF 网关；②**MCP 工具调用** 100% 经 BFF ToolInterceptor。非拦截范围 = 简易 agent 对平台内部服务的直接 API 调用（RAG 检索/文件上传下载）——不产生 `tool_call` 事件，但保留 a) 用户身份校验(tenant/scope) b) `(agent_id, kb_id)` 勾选校验(未勾选 403) c) 落 trace 为 rag/file 事件。文档中引用时写「**用户裁定 2026-09-22**」，不再写张力/待裁定/推测。

---

## 0. 复核口径说明

- 5 份审阅各自有独立的 P1-N / P2-N 编号，编号互相冲突（如 5 份均有「P1-1」但指向不同问题）。本文件**按问题主题去重合并**（非按字面编号），每项列出全部提出方，便于溯源。
- 「已修复」= 在 4 份被审设计文档中找到修复证据且口径一致；「部分修复」= 部分落地或有残留；「未修复」= 在 4 文档内无修复证据；「非本范围」= 修复位置在 4 份设计文档之外（属 D09 收口 / 管理文件），不计入本次「已修复」统计但单列。
- 行号基于修订后文件当前快照。

## 1. 总体结论（TL;DR）

**结论：在 4 份被审设计文档范围内——全部通过（PASS）。**

- P0：0（5 份审阅均无 P0，本次复核未发现新增 P0）。
- P1：3 项唯一主题（D-B 拦截边界 / D-A tag 粒度 /「39 条」计数口径）**全部已修复**。
- P2：16 项唯一主题在 4 文档内**全部已修复**；另 1 项「部分修复」（高风险推测项在 4 文档内已裁定/标注，但 `00-management/RISKS.md` 未同步），3 项属「非本范围」（修复位置在 D09/管理文件，见 §5）。
- 两条裁定 **D-A / D-B 全链路落地、4 处口径一致**（§2 / §3）。
- 交叉一致性抽查：修订**未引入新的不一致**（§4）——组件命名 31 项不变、表数 33 一致、引用章节号有效、4 文档内无「张力/待裁定/未裁定」残留字样、无「39 条」口径残留。
- **非阻塞**。残留项（RISKS.md 同步 / D09 收口项）不阻断本次「4 份设计文档修订」的验收，已在 §5 精确标注供 D09 / 后续任务处理。

汇总计数（按问题主题去重）：**唯一问题 23 项**（P1×3 + P2×20）；4 文档内**已修复 19 项**（P1×3 + P2×16）；**部分 1 项**（P2）；**非本范围 3 项**（P2，D09/管理文件）。

---

## 2. 裁定 D-A 全链路一致性验证（official tag 文档级两级判定）

裁定基准：文档级 `tag=official`，**或**文档级为空且所属知识库 `tag=official` → 判定 official。

| # | 口径落点（任务书指定 4 处） | 证据（文档:章节:行号） | 一致 |
|---|---|---|---|
| 1 | **FLOW 判定逻辑** | FLOW §4.3 S3 时序 L665「chunk+…+tag（两级判定）」/L667 alt 分支「文档级 tag=official，或文档级为空且所属知识库 tag=official」/L683 关键分支说明；§4.4 S4 L743/L746/L763；§3.4 检索图 Q9 节点 L308「tag 信息（文档级 tag，供两级判定）」；KB 创建节点 L255 | ✅ |
| 2 | **FEATURES RAG-01 + AGENT-05** | RAG-01 L215「文档级 tag 在上传/管理文档时设置（见 D-A）」/L221 验收4「文档 tag 可空，NULL 继承库级 tag 参与判定——裁定 D-A」/L223 数据提示；AGENT-05 L419「official 判定规则（裁定 D-A）：tag 为文档级两级判定」/L422 验收1/L425 验收4「同一知识库内混合…仅 official 判定命中的文档附来源（两级判定生效）」/L427 数据提示 | ✅ |
| 3 | **ARCH §4.5** | L551「RAG 引用规则…D-A 文档级两级判定，用户裁定 2026-09-22」/L552「official 判定（两级）：命中 chunk 所属**文档**的 `rag_docs.tag=official` **或**（文档级 `tag` 为空 **且** 其所属**知识库** `rag_knowledge_bases.tag=official`）→ 判定为 official。文档级 tag 优先，NULL 继承库级」 | ✅ |
| 4 | **DB `rag_docs.tag` 字段** | L372「tag\|TEXT\|文档级 tag…文档级官方标记（D-A 两级判定，用户裁定 2026-09-22）：可空。判定 official 规则 = 本字段 tag=official **或**（本字段为 NULL 且所属 rag_knowledge_bases.tag=official）」+ 索引 idx_docs_tag；L344 rag_knowledge_bases.tag「库级默认…文档级以 rag_docs.tag 为准（NULL 继承本表 tag）」；L1019/L1025 索引清单入列 | ✅ |

**判定**：D-A 四处口径完全一致（文档级优先、NULL 继承库级），且 DB 已实际新增 `rag_docs.tag text` 可空字段 + idx_docs_tag 索引（字段级落地，非仅措辞）。**D-A 全链路落地，一致。**

---

## 3. 裁定 D-B 全链路一致性验证（工具调用 = MCP 工具调用 + 内部 API 校验+trace+排除项）

裁定基准：拦截范围 = ①agent 对接业务系统（经 BFF 网关）+ ②MCP 工具调用 100% 经 ToolInterceptor；非拦截范围 = 内部 API 直调（不产生 tool_call 事件，保留身份校验 + KB 勾选校验(未勾选403) + rag/file 事件）。

| # | 口径落点（任务书指定 4 处） | 证据（文档:章节:行号） | 一致 |
|---|---|---|---|
| 1 | **FLOW S3** | §2 拦截边界说明 L62「拦截范围=①…②MCP 工具调用…非拦截范围：…内部 API 直调…不产生 tool_call 拦截事件，但保留 a)身份校验 b)(agent_id,kb_id) 勾选校验(未勾选403) c)落 rag/file 事件」；S3 时序 L645「SAR->>SAR: Tool 执行回调：进程内调用 ToolInterceptor（共享库…DECISION-015）」（MCP 工具路径）+ L654-655「RAG 检索（内部 API 直调，不产生 tool_call 事件）…校验用户身份+(agent_id,kb_id) 已勾选(未勾选403)」+ L657 文件直调 + L675「内部直调路径落 rag/file 事件，不产生 tool_call 事件，用户裁定 2026-09-22」；S4 L743-755（第三方：MCP 100% tool_call + 平台侧 RAG 落 rag 事件）；L684 留痕边界说明 | ✅ |
| 2 | **FEATURES BFF-06 验收** | BFF-06 L544「工具调用定义为 **MCP 工具调用**…必须经 BFF 统一拦截」/L545 拦截边界「非拦截范围…不产生 tool_call 拦截事件，但保留 a)b)c)」/L548 验收1「任一 **MCP 工具调用**…100% 覆盖（无绕过路径）；**排除项**：RAG/文件内部 API 直调以 rag/file 事件留痕，不产生 tool_call 事件（仍须身份校验+勾选校验，未勾选 403——裁定 D-B，用户裁定 2026-09-22）」 | ✅ |
| 3 | **ARCH §1.1 + §9-7 + §2.3** | §1.1 L145-149「工具调用拦截范围（权威表述，用户裁定 2026-09-22，D-B；§1.1/§2.3/§4.3/§9 全文统一于此）…BFF-06 验收判据 = 任一 MCP 工具调用…内部 API 直调以 rag/file 事件留痕」；§2.3 S3 时序 L309-334（TI 共享库 SAR 进程内 + 内部直调校验+rag/file 事件）；§4.3 L498-503 拦截范围/非拦截范围；§4.4 L532-540「内部 API 直调只落 rag/file 事件，不产生 tool_call 事件（D-B 非拦截范围，用户裁定 2026-09-22）」；§9-7 L766「已裁定（D-B，用户裁定 2026-09-22）：两条路径…①MCP 100% 经 ToolInterceptor；②内部 API 直调…校验身份+勾选(未勾选403)+rag/file 事件」 | ✅ |
| 4 | **DB trace 事件类型** | §9.2 L792「事件类型：…/ tool_call（工具调用，含 BFF 拦截记录字段——BFF-06 验收 1）/ rag / file …」+ L799 event_type 枚举 + L802 payload_tsv + L819 tool_call payload 字段（mode/scope_check/token_injected/machine_credential_ref）；§7.2.2 L606「D-B 内部直调勾选校验（用户裁定 2026-09-22）：…(agent_id,kb_id) 在 agent_knowledge_bases 存在 deleted_at IS NULL 有效勾选行——未勾选→403；并校验用户身份；该调用落 trace 为 rag 事件（非 tool_call，属非拦截范围）」；§8 L733-735 持久化裁定「工具调用拦截审计走 trace 表 tool_call 事件」 | ✅ |

**判定**：D-B 四处口径完全一致，且关键细节全部落地：MCP 工具 100% tool_call、内部 API 直调不产生 tool_call 但保留身份校验 + `(agent_id,kb_id)` 勾选校验(未勾选403) + rag/file 事件。BFF-06 验收 1 已写明**排除项**（测试判据来源明确，消除原「必判 FAIL」风险）。原文三处矛盾（§1.1「不存在绕过」 vs §9-7「两条路径都经 TI」 vs S3 图直连）已收敛为单一权威表述（§1.1），§9-7 改标「已裁定（D-B）」。**D-B 全链路落地，一致。**

> 措辞合规检查：4 文档内「张力 / 待裁定 / 未裁定」= **0 处**（grep 全量核对）；引用一律为「用户裁定 2026-09-22」。

---

## 4. 交叉一致性抽查（修订是否引入新的不一致）

| 抽查项 | 结果 | 证据 |
|---|---|---|
| 组件命名契约（31 项，FLOW §1 为契约源） | ✅ 不变 | FLOW §1 组件清单计数 = 31（awk 复核）；ARCH/FLOW 沿用同一命名，无漂移 |
| DB 表数（33 张）一致性 | ✅ 一致 | DB L30 文首/L1066 ER 引言/L1140 §14 核对/L1182 §15 核对 均 33 张；§7 九张构成已补注（1+4+4=9） |
| 「39 条」口径残留 | ✅ 无残留 | 4 文档内仅修订记录行提及「39 条」（描述改动本身）；正文口径统一为「41 条 bullet / 45 个标准 ID」（FEATURES L14/L16/L668、ARCH L669/L679）；DB 无 39/41/45 口径句（不涉计数） |
| 引用章节号有效性 | ✅ 有效 | ARCH §4.3/§4.4/§4.5/§9-7/§9-13/§10.x 等被引章节均存在（heading 核对）；DB §4.2=rag_docs（tag 字段落点）、§7.2.x 勾选表、§8 BFF 持久化、§9.2 trace_events 被引均对位 |
| 原三处矛盾点收敛 | ✅ 收敛 | ARCH 内「两条路径都经 ToolInterceptor」矛盾句已改「已裁定（D-B）」（L766）；「不存在绕过拦截的路径」仅在 §1.1 权威表述中以「MCP 工具调用…无绕过路径」的**精确限定**出现，不再与内部直调路径冲突 |
| 「张力/待裁定/未裁定」残留字样 | ✅ 0 处 | 4 文档 grep 全量 = 0（FEATURES §11「待确认点」为原始产品侧开放问题，已分别由 ARCH/DB 裁定，非 D-B 张力措辞） |
| D-A/D-B 修订连带一致性 | ✅ 一致 | S3 读侧双路径（MCP 工具路径经 TI + 内部直调不经 TI）在 FLOW/ARCH/DB 三层口径一致；TI 统一为「进程内共享库、SAR/BFF 进程内执行、trace 进程内写点」（DECISION-015）全文对齐 |

**判定**：本次修订**未引入新的不一致**。所有交叉引用有效，命名/表数/口径收敛，无新矛盾。

---

## 5. 逐条验证表（5 份审阅 P0/P1/P2 去重合并，按主题）

### 5.1 P0（阻断）
| 主题 | 提出方 | 状态 | 说明 |
|---|---|---|---|
| （无） | 5 份审阅均报 0 P0 | — | 本次复核亦未发现 P0（无 BRIEF 需求整体缺失、无三文档矛盾到不可实现） |

### 5.2 P1（开发前必须裁定/修正）
| 主题 | 提出方 | 状态 | 修复证据 |
|---|---|---|---|
| **P1-A 工具调用拦截边界（= D-B）**：BRIEF「必须经 BFF 统一拦截」vs 内部 API 直调；ARCH §1.1 vs §9-7 矛盾；BFF-06 验收判据悬空 | chuyan P1-1、luoji P1-2、shiqiang P1-1、yuntianming P1-1、zhangbeihai P1-1 | ✅ 已修复 | 见 §3 全链路 4 处一致 + BFF-06 验收 1 排除项成文（FEATURES L548）+ ARCH §1.1 权威表述（L145-149）+ §9-7 改「已裁定 D-B」（L766）+ FLOW S3 勾选校验/rag·file 事件 + DB §7.2.2/§9.2/§8 |
| **P1-B official tag 粒度（= D-A）**：BRIEF「知识文档 tag」被实现为知识库级；rag_docs 无 tag 字段；偏离未标注 | luoji P1-1（终审漏判新发现；yuntianming P2-5、chuyan/zhangbeihai/shiqiang 于对照表 SA03/TA03 行同提） | ✅ 已修复 | 见 §2 全链路 4 处一致 + DB 实际新增 `rag_docs.tag text` 可空字段（L372）+ idx_docs_tag（L1019）+ FEATURES RAG-01/AGENT-05 两级判定验收 |
| **P1-C 「39 条」计数口径失效**：声明 39 条 vs 对照表 45 行，39 不可导出 | chuyan P1-2、luoji P1-3、shiqiang P1-2、yuntianming P1-2、zhangbeihai P1-2 | ✅ 已修复 | FEATURES L14/L16/L668、ARCH L669/L679 统一为「41 条 bullet（4 条含子项）→ 45 个标准 ID」；4 文档正文无「39 条」口径残留 |

### 5.3 P2（文字勘误 / 表述澄清）
| 主题 | 提出方 | 状态 | 修复证据 |
|---|---|---|---|
| S01 后端切换既有文件处理策略未成文 | chuyan P2-3、luoji P2-1、shiqiang P2-1、yuntianming P2-3、zhangbeihai P2-3 | ✅ 已修复 | FEATURES STORE-03 L131「保留原后端访问策略…不做自动迁移」+L135 验收3；ARCH §1.1 L150/§2.2 L219「保留原后端访问（不迁移）…新上传走新后端」；DB §2 L206 同句（引用 ARCH §1.1 权威裁定） |
| DB §14「25 张表」笔误 → 33 | chuyan P2-1、luoji P2-5、shiqiang P2-2、yuntianming P2-4、zhangbeihai P2-1 | ✅ 已修复 | DB L1140 改「33 张」（§14 核对句）；L1182 §15 核对 33 |
| DB 文首「§7 九张」口径易误读 | chuyan P2-2、luoji P2-3、shiqiang P2-3、yuntianming P2-4、zhangbeihai P2-2 | ✅ 已修复 | DB L30 补注「§7 九张【= 1 agent 定义 + 4 配置勾选 + 4 会话/消息/记忆/obsidian，共 6 个 ### 小节】」 |
| `.doc` 旧格式 422 拒绝 | luoji P2-2 | ✅ 已修复 | ARCH §2.2 L218「.doc 旧格式不支持——上传时 422 拒绝并提示转 .docx」；DB §4.2 L373 doc_type 枚举同 |
| RAG-08 单次 topK/阈值覆盖（原为推测） | luoji P2-4 | ✅ 已修复 | FEATURES RAG-08 L286「设计决策（2026-09-22，非推测）：支持单次检索级 topK/threshold 覆盖，未传回落库默认」+L290 验收3 |
| FEATURES 功能点统计小错（48→47 / 混合 4→5） | zhangbeihai P2-6 | ✅ 已修复 | FEATURES L16/L698「4 纯推测 + 5 混合 + 47 明确要求（4+5+47=56）」，5 个混合点（BASE-04/05、RAG-03、AGENT-02、BFF-05）均标注 |
| 内部 RAG 检索 API 未说明 `(agent_id,kb_id)` 勾选校验 | zhangbeihai P2-4 | ✅ 已修复 | FLOW S3 L655 + ARCH §4.2 L495「内部 RAG 检索 API…校验 (agent_id,kb_id) 在 agent_knowledge_bases 已勾选，未勾选→403」+ DB §7.2.2 L606 |
| S3 图与「进程内共享库调用」措辞不一致（DECISION-015） | zhangbeihai P2-5 | ✅ 已修复 | FLOW S3 L645 改「SAR->>SAR: 进程内调用 ToolInterceptor（共享库，SAR 进程内执行，非独立进程）」；ARCH §1.1/§2.3/§4.3/§1.2 统一「共享代码库、拦截在 SAR/BFF 进程内执行、trace 进程内写点」 |
| OpenAI `model` 参数语义三处不一致 + 跨租户解析路径未定义 | shiqiang N1/P2-4 | ✅ 已修复 | ARCH §4.5 L545-547「model = agent 名称（agents.name，租户内唯一，单一语义）+ BFF 解析路径（提取 tenant → (tenant,name) 查 agent → 不存在404 / 无权限403）」；DB §7.1 L555 agents.name「OpenAI 兼容端点 model 字段取值（DECISION-016）」；DECISION-016 同步 |
| `rag_doc_images.image_file_id` FK 级联 → RESTRICT | shiqiang N2/P2-5 | ✅ 已修复 | DB L423「FK→storage_files.id（RESTRICT：被 RAG 文档图片引用的文件禁止删除）」+ L1044 §13.3 外键汇总改 RESTRICT |
| `agent_messages` 主查询索引未 tenant 打头 | shiqiang N3/P2-6 | ✅ 已修复 | DB L665/L997 `idx_messages_session(tenant_id, session_id, created_at)`（tenant 打头，对齐 §10.2 自声明） |
| 三张 agent 勾选表字段表漏列 `deleted_at` | yuntianming P2-1 | ✅ 已修复 | DB §7.2.1 L589 / §7.2.2 L603 / §7.2.4 L632 均补 `deleted_at` 行（解勾软删） |
| `trace_events.payload_tsv` 生成列未进字段表 | yuntianming P2-2 | ✅ 已修复 | DB §9.2 L802「payload_tsv\|TSVECTOR\|…GENERATED ALWAYS AS (to_tsvector…) STORED…索引 idx_trc_events_payload_tsv GIN」+ L1029 索引清单入列 |
| MCP 关联调用方范围未限定 | yuntianming P2-6 | ✅ 已修复 | FLOW §3.5 L354「关联调用方检测范围限定为平台内 agent 勾选（agent_mcp_tools 表）；第三方 agent 提供方的调用不在检测范围（用户裁定 2026-09-22 口径）」 |
| 黑盒验收 mock 资产前置（G05/TA/AGENT-09-11） | yuntianming P2-7 | ✅ 已修复 | FEATURES BFF-08 L569 / AGENT-09 L464 / AGENT-10 L474 / AGENT-11 L484 各补「黑盒验收依赖 mock 第三方 MCP server + mock 第三方 agent（DECISION-008）；mock 资产在开发阶段完成，列为开发→测试交接检查项（测试侧 P2-7，2026-09-22 确认）」 |
| S01「配置文件可配置」落地为 env 注入，等价性未明说 | chuyan P2-4（新发现） | ✅ 已修复 | DB §2 L205「存储后端配置（backend/路径/bucket/凭证）在**配置文件/环境变量**（S01「配置文件可配置」），不落 DB」；ARCH §5.3 L624「STORAGE_BACKEND…存储后端切换（S01，配置文件化）」——已把 S01 原话与 env/.env 实现显式关联，等价性成文 |
| **高风险推测项待用户确认（R3-R7：1536 维+补零、90 天保留、权限三级、第三方协议、默认参数）** | shiqiang P2-7 | ⚠️ 部分修复 | **4 文档内已裁定/标注**：权限三级（ARCH §9-2 L761 已裁定 DECISION-004）、默认参数（ARCH §9-4/5 已裁定 DECISION-006）、第三方协议（DECISION-008）、补零/90 天保留标注【推测】+RISK 跟踪。**残留**：`00-management/RISKS.md` 的 **RISK-006 仍标 OPEN 且保留旧「张力/未对齐/开发前最高优先裁定」措辞**，RISK-004/005 仍标 OPEN/待用户确认——4 文档已按「用户裁定 2026-09-22」定稿，风险登记表未同步（见 §6） |
| DESIGN_REVIEW 自身引用笔误「DB_DESIGN 表头 §18」（DB 仅 15 章） | luoji P2-6 | ➖ 非本范围 | 修复位置在 `00-management/DESIGN_REVIEW.md` 自身（非 4 份被审设计文档）；属 D09 收口（DESIGN_REVIEW 追加修订记录时一并勘误） |
| 占位模板未清理（PRD/USER_STORIES/PRODUCT_DECISIONS/DESIGN.md/DEV_REPORT.md/03-testing 仍为 `{{PROJECT_NAME}}`） | shiqiang P2-8 | ➖ 非本范围 | 修复位置在 6 份占位文件 + 03-testing，非 4 份被审设计文档；**已明确属 D09 任务 c 项**（chuyan 收口：替换为「本文档由 <真实文档> 承接，本文件作废」） |
| DESIGN_REVIEW #5 将引用句误标「BRIEF S03 原话」（实为 FEATURES STORE-03 验收 2） | chuyan P2-3（附带） | ➖ 非本范围 | 引用出处勘误在 `00-management/DESIGN_REVIEW.md` 自身；属 D09 收口范围，不影响 4 文档实质（S01 策略已在 4 文档成文） |

> 备注：`FEATURES §11「待确认点」`、`ARCH §9「仍未裁定的留给 DESIGN_REVIEW/用户确认」` 中的开放项（同名文件/chunk 位置/引用识别/多租户范围/机器凭证/tool call 协议/换 embedding/obsidian 边界）为**原始产品/设计侧开放问题**，已在 ARCH §9（#10-17）逐项裁定或标注【推测】，非 D-A/D-B 张力措辞，不属本次待修项。

---

## 6. 残留问题清单（精确标注，供 D09 / 后续任务处理）

> 以下项**不阻断**本次「4 份设计文档修订」验收（4 文档本身已全部通过），但需收口/跟进。按责任域标注：

1. **`00-management/RISKS.md` 风险登记表未同步 D-A/D-B 裁定**（P2，交叉一致性问题，建议 D09 或新增小任务处理，责任人 chuyan/章北海）：
   - **RISK-006**：仍标 `OPEN`，且描述保留旧措辞「边界未定」「与 BRIEF 字面『必须』存在张力」「ARCH §1.1 与 §9-7 两处表述未对齐」「开发前最高优先裁定」——与 4 文档已按「用户裁定 2026-09-22（D-B）」定稿的口径**冲突**。期望改法：状态改 `已裁定（用户裁定 2026-09-22，D-B）`，描述改写为已收敛口径（MCP 工具 100% 经 TI；内部直调不产生 tool_call 但保留身份校验+勾选403+rag/file 事件；ARCH §1.1 已为单一权威表述），并关闭。
   - **RISK-004 / RISK-005**：1536 维补零、90 天保留策略仍标「待用户确认」/OPEN——4 文档内已标【推测】并设计定稿，若用户未正式确认，保留 OPEN 合理；建议 D09 在 DESIGN_REVIEW 修订记录中明确「RISK-004/005 维持 OPEN 待用户确认」的处置口径，避免与 4 文档「已裁定」表述歧义。

2. **`00-management/DESIGN_REVIEW.md` §18 引用笔误**（luoji P2-6，属 D09 范围）：§1.4 表 #3/#4 中「DB_DESIGN 表头 §18」应为「§14」（DB 仅 §1–§15）。D09 追加「§6 审阅后修订记录」时一并勘误。

3. **占位模板清理**（shiqiang P2-8，**已明确属 D09 任务 c 项**）：01-product 下 PRD/USER_STORIES/PRODUCT_DECISIONS、02-development 下 DESIGN/DEV_REPORT、03-testing 空模板——替换 `{{PROJECT_NAME}}` 为「本文档由 <真实文档> 承接，本文件作废」。本卡不改（只读复核 + 只写 REVISION_VERIFY.md 约束）。

---

## 7. 最终结论

- **复核对象**：4 份被审设计文档（FLOW_DIAGRAMS / FEATURES / ARCHITECTURE / DB_DESIGN）。
- **判定**：✅ **全部通过（PASS）**——5 份审阅在 4 文档范围内的全部 P1（3 项）与 P2（16 项）问题**逐条已修复**，证据见 §2/§3/§5；两条用户级裁定 **D-A / D-B 全链路落地、4 处口径一致**；交叉一致性抽查**未引入新不一致**。
- **P0**：0（无新增，无阻断）。
- **汇总计数**（按问题主题去重）：唯一问题 **23** 项（P1×3 + P2×20）；4 文档内**已修复 19** 项（P1×3 + P2×16）；**部分 1** 项（shiqiang P2-7，4 文档已裁定但 RISKS.md 未同步）；**非本范围 3** 项（luoji P2-6 / shiqiang P2-8 / chuyan P2-3 附带，均属 D09/管理文件）。
- **是否满足验收标准**：**是**（4 份设计文档口径一致、BRIEF 45 标准 ID 覆盖不缺失、两条裁定落地可作测试判据来源）。
- **是否可进入下一阶段**：**可以**。4 份设计文档修订验收通过；D09 收口（DESIGN_REVIEW 修订记录 + DECISIONS 增 D-A/D-B + 占位模板清理 + STATUS 更新 + RISKS.md 同步 + §18 勘误）为独立后续任务，不阻塞本卡交付。
- **测试视角提示**：BFF-06 验收 1 判据已明确（「任一 MCP 工具调用 100% tool_call；内部 API 直调以 rag/file 事件留痕」），测试阶段可直接据此出题；第三方 agent/MCP 黑盒验收的 mock 资产（DECISION-008 协议）列为开发→测试交接检查项，测试前须确认 mock 资产就绪。

*（完）REVISION_VERIFY.md — 云天明（测试工程师），2026-09-22。只读复核，未修改任何被审文档。*
