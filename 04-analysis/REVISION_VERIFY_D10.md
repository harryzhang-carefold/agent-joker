# REVISION_VERIFY_D10 — D10 裁定落地复核（TASK-D11）

> 复核人：云天明（测试工程师，测试/可验证性视角）
> 日期：2026-09-22
> 类型：**只读复核**（未修改任何被审文档）
> 复核对象：TASK-D10 修订后的 4 份文档
> - `02-development/ARCHITECTURE.md`
> - `02-development/DB_DESIGN.md`
> - `00-management/DECISIONS.md`
> - `00-management/RISKS.md`
>
> 上游交接（t_7c3af14b）：D10 按用户 2026-09-22 两条正式裁定（D-C/D-D）修订 4 份文档，共 12 处修订，自报「4 文档无 1536 统一/补零/90天【推测】活跃设计残留；rag_chunks_vec 进 §15 表清单；§14/§15 计数、索引清单、字段表、ER 图与新增表一致；表数 34 三处一致」。本报告独立复核，不采信上游自测。

---

## 0. 验证项总览

| # | 验证项 | 结论 |
|---|---|---|
| V1 | D-C：无「1536 统一存储/补零/超维 422 拒绝」活跃设计残留 | ✅ PASS（残留均在「废原…」历史说明内，符合任务口径） |
| V2 | D-C：每库独立向量表方案在 DB 落地（§4.4 表结构 + HNSW 索引 + §13 索引清单 + §15 表清单计数） | ✅ PASS |
| V3 | D-C：每库独立向量表方案在 ARCH 落地（建库/换模型重算向量流程），embedding_dim 为建库快照 | ✅ PASS |
| V4 | D-D：无「90天【推测】」残留 | ✅ PASS |
| V5 | D-D：TRACE_RETENTION_DAYS/AUDIT_RETENTION_DAYS 可配置 + 默认 90 天，在 DB（api_audit_logs / trace_events 两处）与 ARCH 一致 | ⚠️ PASS_WITH_ISSUE（§5.3 env 变量表未收录两个变量，见 F2） |
| V6 | RISKS RISK-004 / RISK-005 = CLOSED | ✅ PASS |
| V7 | 交叉一致性：表数计数、索引清单、ER 图与新增 rag_chunks_vec 表一致；未引入新不一致 | ⚠️ PASS_WITH_ISSUE（引入 1 处跨文档状态名不一致，见 F1；计数/ER/索引均一致） |

**结论：D10 两项裁定（D-C/D-D）全部落地，7 项验证项 5 项 PASS、2 项 PASS_WITH_ISSUE（均为低严重度文档一致性问题，无阻塞、不推翻 D10 结论）。残留清单 2 项（F1/F2）。**

---

## 1. D-C（DECISION-024：向量维度按 embedding 模型、每库独立向量表）

### V1 全文残留清查（PASS）

方法：对 4 份被审文档全文检索 `1536 / 补零 / 零填充 / 高维 / 超维 / 超维422 / re-embedding / 全库重嵌入 / 统一维`，逐条人工核对每条命中是否属「活跃设计表述」还是「历史『废原…』说明」。

全部命中（按文件）：

| 文件 | 行 | 内容 | 判定 |
|---|---|---|---|
| ARCHITECTURE.md | 15 | 文首修订记录：「废原『全平台统一 1536 维 + 低维补零 + 高维 422 拒绝』」 | 历史说明（修订记录），合规 |
| ARCHITECTURE.md | 225 | §2.2 向量化：「废原『统一 1536 维 + 低维补零 + 高维 422 拒绝』」 | 历史说明（同段新设计为「维度 = 该库所选 embedding 模型维度」），合规 |
| ARCHITECTURE.md | 736 | §8 DECISION-006 摘要：「换模型 = 全库重嵌入任务」 | 活跃表述，但属换模型重嵌入策略（DECISION-006/024 一致），非 1536 残留；状态名见 F1 |
| ARCHITECTURE.md | 754 | §8 DECISION-024 摘要：「（废『统一 1536 + 补零 + 422 拒绝』）」 | 历史说明（决策摘要内），合规 |
| DECISIONS.md | 46 | DECISION-006 决策：「（原『统一 1536 维存储』已被 D-C / DECISION-024 取代）」 | 历史说明（显式标注已被取代），合规 |
| DECISIONS.md | 49 | DECISION-006 理由：「【维度存储方式已由 D-C / DECISION-024 取代】：原『1536 维统一存储（低维模型右补零…>1536 维模型建库时 422 拒绝）』方案于 2026-09-22 被用户裁定…取代（废补零假设与 422 拒绝）」 | 历史说明（显式标注被取代），合规 |
| DECISIONS.md | 175-177 | DECISION-024 决策/背景/备选：多次出现「统一 1536 + 补零 + 422 拒绝」 | 均为「废原…方案」背景叙述与备选对比，合规 |
| RISKS.md | 8 | RISK-004 行：原风险描述含「DB_DESIGN 统一按 1536 维存储（<1536 补零、>1536 建库拒绝 422）」 | 风险原始描述（CLOSED 行的问题陈述），处置列已写明「废原『统一 1536 + 补零 + 422 拒绝』」，合规 |
| DB_DESIGN.md | 16 | 文首修订记录 ⑪-1：「废原『统一 1536 维 + 低维补零 + 高维 422 拒绝』」 | 历史说明（修订记录），合规 |
| DB_DESIGN.md | 406 | §4.3 rag_chunks.embedding：「**废原『全平台统一 1536 维 + 低维补零 + 高维 422 拒绝』方案**」 | 历史说明（同字段活跃表述为「向量按库独立表存储」），合规 |
| DB_DESIGN.md | 418 | §4.4 设计说明：「（D-C / DECISION-024，废原『全平台统一 1536 维 + 低维补零 + 高维 422 拒绝』）」 | 历史说明（同段新设计为「维度 = 该库所选 embedding 模型的真实维度」），合规 |

**判定：0 处活跃设计残留。** 所有 1536/补零/422 命中均处于「废原…/已被取代/CLOSED 行原始问题描述」语境，与任务「除历史说明外不得残留」口径一致。补充核查：全文 `422` 唯一活跃用途为 §2.2/§7 R02「`.doc` 旧格式上传 422 拒绝」，与向量维度无关，属 luoji 审阅 P2-2 独立裁定，未受 D-C 影响。

### V2 DB 侧落地（PASS）

| 落点 | 位置 | 核查结果 |
|---|---|---|
| 新增 §4.4 `rag_chunks_vec` 每库独立向量表 | DB_DESIGN §4.4（line 418 起） | ✅ 表结构：`chunk_id` PK / `knowledge_base_id` / `embedding VECTOR(N)`（N = 该库 embedding 模型真实维度）；命名规范 `rag_chunks_vec_<kb_id>`（kb_id = 32 位无连字符 UUID，合法标识符后缀）；建库时动态建表 |
| HNSW 索引按实际维度 N | DB_DESIGN §4.4 + §13 | ✅ 索引清单含 `idx_chunks_vec_embedding`（HNSW，维度 N）；§13.3 FK 汇总含 `rag_chunks_vec.chunk_id / knowledge_base_id → 级联/级联（D-C / DECISION-024 每库独立向量表）` |
| §4.3 rag_chunks.embedding 说明 | DB_DESIGN §4.3（line 406） | ✅ 改「向量不入本表，按库独立表存储」，指向 §4.4；修改 content 必须重算（写对应库向量表） |
| §4.1 embedding_dim 建库快照 | DB_DESIGN §4.1 | ✅ `embedding_dim` = 建库时所选 embedding 模型 `dimensions` 快照；`embedding_model_id` 建库后锁定；status 补 `reindexing`（重嵌入任务进行中，期间检索用旧向量【推测】）+ 换模型全量重算流程（新建按新维度表 → 全量重嵌入 → 切换引用 → 删旧表） |
| §15 表清单计数 | DB_DESIGN §14/§15 | ✅ 表数 33→34：文首（line 31）「34 张业务表（…§4 五张…）」、§14 标题「34 张表全量关系」+ line 1166 核对行逐表枚举 34 张含 `rag_chunks_vec`、§15 核对结论「RAG 5…共 34 张」三处一致 |
| DECISION-024 约束 a-e 落地 | DB_DESIGN §4.1/§4.4 | ✅ a) 不同库不同维度互不约束（§4.4）；b) 检索只走本库向量表（§4.4/§4.3 检索按库过滤）；c) 换模型全量重算（§4.1 status 说明）；d) embedding_dim 建库快照（§4.1）；e) 模型维度变更/删除只影响「不可新选」、存量库向量表仍可检索（DECISION-024 决策 d/e，DB 侧经 §4.1 锁定语义支撑） |

### V3 ARCH 侧落地（PASS）

| 落点 | 位置 | 核查结果 |
|---|---|---|
| 建库流程 | ARCH §2.2（line 220） | ✅ 「选 embedding 模型 → 按该模型维度动态建该库独立向量表 `rag_chunks_vec_<kb_id>` + 固化 `rag_knowledge_bases.embedding_dim`（建库快照）→ 写入库配置。不同库可用不同维度，互不约束」 |
| 向量化 | ARCH §2.2（line 225） | ✅ 写入该库独立向量表，维度 = 该库所选 embedding 模型维度；换模型 → 全量重算向量（重建该库向量表，DECISION-006/024） |
| 检索路由 | ARCH §2.2（line 226） | ✅ 查询向量化用该库 embedding 模型 → 路由到该库自己的独立向量表，余弦召回；D-C：检索只走该 KB 向量表、不跨库 |
| §7 R01 | ARCH §7（line 689） | ✅ 建库时按所选 embedding 模型维度动态建独立向量表 + 固化 embedding_dim 快照（D-C/DECISION-024） |
| §8 决策摘要 | ARCH §8（line 754） | ✅ DECISION-024 行（含「废原」标注 + 章节映射 §2.2、§6#4、§7 R01、DB §4.4）；决策计数 21→25 与 DECISIONS.md 25 条一致 |
| DECISION-006 同步 | DECISIONS.md line 46/49 | ✅ 原 1536 表述改「已被 D-C/DECISION-024 取代」+ 历史保留，与 DECISION-024 无矛盾 |

**注（非残留、非问题）**：ARCH §2.2 mermaid 时序图与 §1.2 组件图以 `PG[PostgreSQL（pgvector）]` 抽象表示落库（「写 rag_chunks（embedding+位置）」），未显式命名 `rag_chunks_vec_<kb_id>` 表。表级命名与结构权威归属 DB_DESIGN §4.4，ARCH 正文（建库/向量化/检索三处 bullet）均已落地，不构成不一致。

---

## 2. D-D（DECISION-025：trace/审计日志保留天数可配置）

### V4 全文残留清查（PASS）

方法：4 份被审文档全文检索 `90天【推测】/90 天【推测】/90天 推测/推测.*90/90.*推测`。

**判定：0 处「90 天【推测】」残留。** 现存「90 天」表述全部为「默认 90 天，默认值为设计决定（非推测）」或「废『90 天【推测】』」修订记录，合规。

### V5 可配置 + 默认 90 天（PASS_WITH_ISSUE，见 F2）

| 落点 | 位置 | 核查结果 |
|---|---|---|
| DB api_audit_logs | DB_DESIGN §1.8（line 199） | ✅ 「保留天数可配置（环境变量 `AUDIT_RETENTION_DAYS`，默认 90 天，默认值为设计决定）；月分区 + 过期分区 DROP PARTITION（定期任务按配置天数清理，参数化非硬编码）」 |
| DB trace_events | DB_DESIGN §9.2（line 850） | ✅ 「保留天数可配置（环境变量 `TRACE_RETENTION_DAYS`，默认 90 天，默认值为设计决定）；分区表按月 + 过期 DROP PARTITION，与审计日志一致（RISK-005 已 CLOSED）」 |
| ARCH 一致性 | ARCH line 15（修订记录）、§8 DECISION-025（line 755） | ✅ 「天数可配置（`TRACE_RETENTION_DAYS`/`AUDIT_RETENTION_DAYS`，默认 90 天）+ 月分区 + 过期 DROP PARTITION（D-D/DECISION-025，废『90 天【推测』』）」；与 DB 两处表述一致 |
| DECISIONS | DECISIONS.md DECISION-025（line 181 起） | ✅ 决策/背景/备选/理由/影响完整；影响列明确「`.env.example` 增 `TRACE_RETENTION_DAYS`/`AUDIT_RETENTION_DAYS`（默认 90）」 |
| **ARCH §5.3 env 变量表** | ARCH §5.3（line 622-634） | ❌ **该表未收录 `TRACE_RETENTION_DAYS`/`AUDIT_RETENTION_DAYS`**（现有项：JWT_SECRET、STORAGE_*、GCS_*/OSS_*、DB_DSN/REDIS_URL、BFF_RATE_LIMIT_*、BFF_ROUTES_FILE、OBSIDIAN_VAULT_PATH、LLM_FALLBACK_ENDPOINT）。详见 F2 |

### V6 风险关闭（PASS）

| 风险 | 位置 | 核查结果 |
|---|---|---|
| RISK-004（向量维度） | RISKS.md line 8 | ✅ 状态 = **CLOSED**；处置 = D-C/DECISION-024 裁定全文 + 落点章节（DB §4.4/§4.1/§4.3/§13/§14/§15；ARCH §2.2/§7 R01/§6#4/§8）——与本次核查实际落点一致 |
| RISK-005（trace/审计存储增长） | RISKS.md line 9 | ✅ 状态 = **CLOSED**；处置 = D-D/DECISION-025 裁定全文 + 落点章节（DB §1.8/§9.2；ARCH §2.2/保留策略处；.env.example 增两变量）——与本次核查实际落点一致 |

---

## 3. 交叉一致性（V7，PASS_WITH_ISSUE）

| 检查项 | 结果 |
|---|---|
| 表数 34 三处一致（文首 line 31 / §14 标题 + line 1166 枚举 / §15 核对结论 line 1209） | ✅ 一致（§4 四张→五张，RAG 5 张） |
| §15 逐表枚举含 rag_chunks_vec | ✅ line 1166 枚举 34 张含 `rag_chunks_vec`（34 张逐一可数） |
| §13 索引清单 + §13.3 FK 汇总含 rag_chunks_vec | ✅ `idx_chunks_vec_embedding`（HNSW 按 N）+ `rag_chunks_vec.chunk_id / knowledge_base_id` 级联/级联 |
| ER 图（§14 mermaid）与新增表一致 | ✅ 含 `rag_chunks ||--o{ rag_chunks_vec : "向量(D-C每库独立表)"` 与 `rag_knowledge_bases ||--o{ rag_chunks_vec : "每库一表"` 两条连线，与 §13.3 FK 一致 |
| 决策计数 ARCH §8（25 条，DECISION-001..025）与 DECISIONS.md（25 条） | ✅ 一致（D10 补 DECISION-022..025，21→25） |
| **是否引入新不一致** | ⚠️ 引入 1 处低严重度跨文档状态名不一致（F1）；另 1 处 env 变量表遗漏（F2，已计入 V5）。其余交叉核对无新增矛盾 |

---

## 4. 残留清单（2 项，均低严重度）

### F1 — P2（低）：跨文档「重嵌入状态机」状态名不一致
- **位置**：ARCHITECTURE.md §9-16（line 782）「状态机 **`re-embedding`** 期间检索用旧向量【推测】」（DECISION-006）vs DB_DESIGN.md §4.1 `rag_knowledge_bases.status`（line 354）= `active` / **`reindexing`** / `disabled`（「`reindexing` = 重嵌入任务进行中」）；DB_DESIGN §4.3 rag_docs.status 亦含 `reindexing`（line 375）。
- **性质**：同一概念（换 embedding 模型全量重算期间）在两文档中状态名不同（`re-embedding` vs `reindexing`）；ARCH 侧仅 1 处（§9-16），ARCH 未给出 kb 级 status 枚举值，故为「引用名与 DB 权威枚举不一致」，非设计矛盾。
- **影响**：开发/测试阶段按状态机名写断言、查库状态时可能取不到值（按 `re-embedding` 查库将查无此值）；属文档一致性问题，不影响 D-C 裁定本身。
- **建议**：ARCH §9-16 状态名对齐 DB_DESIGN §4.1 的 `reindexing`（或两文档统一）。可随后续文档小修处理，不阻塞。
- **与 D10 关系**：D10 上游自报「无新不一致」，此项为其遗漏——本复核独立发现。

### F2 — P2（低）：ARCH §5.3 `.env.example` 变量表未收录 D-D 两个新变量
- **位置**：ARCHITECTURE.md §5.3「配置与环境（.env.example 项）」表（line 622-634）。
- **性质**：DECISION-025 影响列（DECISIONS.md line 185）与 RISKS.md RISK-005 处置列均明确「`.env.example` 增 `TRACE_RETENTION_DAYS`/`AUDIT_RETENTION_DAYS`（默认 90）」；但 ARCH §5.3 作为「.env.example 项」清单未增列这两项。§5.3 是 ARCH 内唯一集中列 env 变量的位置，缺列造成「DECISIONS/RISKS 声明的落点」在 ARCH 内不可见（ARCH 修订记录 line 15 与 §8 仅声明策略，未落 env 表）。
- **影响**：部署配置清单不完整（实现 `.env.example` 时若仅对照 ARCH §5.3 会漏配两变量，退回默认 90 天——行为不破坏，仅可配置性入口缺失且文档链断裂）；属文档一致性问题，不影响 D-D 裁定本身。
- **建议**：ARCH §5.3 增行：`TRACE_RETENTION_DAYS=90` / `AUDIT_RETENTION_DAYS=90`（默认值，D-D / DECISION-025）。可随后续文档小修处理，不阻塞。
- **与 D10 关系**：D10 上游自报落点「ARCH §2.2/§8 同步」未覆盖 §5.3 env 表，本复核独立发现。

---

## 5. 结论

**D10 两项用户裁定（D-C / DECISION-024、D-D / DECISION-025）在 4 份文档中全部落地，裁定语义、落点章节、风险关闭（RISK-004/005 CLOSED）、计数同步（表数 34、决策 25 条）均复核通过。**

- 验证项：7 项；通过（PASS）：5 项；PASS_WITH_ISSUE：2 项（V5、V7）。
- 残留：2 项，均为 **P2 低严重度文档一致性**问题（F1 状态名 `re-embedding` vs `reindexing`；F2 ARCH §5.3 env 表缺两变量），**无 P0/P1、无阻塞、不推翻 D10 结论**。
- 复核边界：只读复核，未修改任何被审文档；复核范围以 4 份被审文档全文 + 上游交接自报对照为准，未运行代码（本项目尚处设计阶段，无实现代码可执行）。

**建议下一步**：F1/F2 两处小修（各 1 行级）可由文档负责人随下一轮文档维护一并处理，或在 DESIGN_REVIEW 终审时口头确认「DB_DESIGN 为状态名/env 清单的权威源」后关闭。

---

*（完）REVISION_VERIFY_D10.md — 云天明，2026-09-22（TASK-D11 只读复核）。*
