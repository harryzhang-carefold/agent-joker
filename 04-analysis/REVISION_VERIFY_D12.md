# REVISION_VERIFY_D12 — TASK-D15 复核报告（D12/D13/D14 三任务落地）

> 复核人：云天明（测试视角）｜日期：2026-09-22｜任务：t_e891d226
> 上游：t_3dcfab5b（TASK-D12，ARCH+DB）、t_f6d8d621（TASK-D13，FEATURES）、t_8b7247d2（TASK-D14，FLOW）
> 复核对象：`02-development/ARCHITECTURE.md`、`01-product/FEATURES.md`、`01-product/FLOW_DIAGRAMS.md`、`02-development/DB_DESIGN.md`
> 方式：只读复核，全文检索 + 逐条人工核对，未修改任何被审文档。
> 方法：对 4 份设计文档全文检索关键词（`re-embedding` / `reindexing` / `RETENTION` / `切分对比查看` / `RAG-11` / 图数 / 表数），再逐条读取落地段落人工核对。

---

## 1. 逐条验证表

| # | 验证项 | 结果 | 证据（文件:行） |
|---|---|---|---|
| V1-F1a | 4 份设计文档全文无 `re-embedding` 活跃设计表述残留 | ✅ PASS | 全文 `grep 're-embedding'`（含大小写/下划线变体）4 份文档仅 1 处命中：ARCH line 17 修订记录中「`re-embedding` → `reindexing`」为**修复动作本身的引用**，非活跃设计表述。DB/FEATURES/FLOW 零命中。 |
| V1-F1b | ARCH §9-16 与 DB §4.1/§4.2 状态名统一为 `reindexing` | ✅ PASS | ARCH line 815（§9 表 #16）：「状态机 `reindexing` 期间检索用旧向量【推测】（DECISION-006；状态名与 DB_DESIGN §4.1 `rag_knowledge_bases.status` / §4.2 `rag_docs.status` 枚举对齐）」；DB line 355（§4.1 kb.status 枚举 `active`/`reindexing`/`disabled`）、line 376（§4.2 doc.status 含 `reindexing`）、line 432（§4.4 流程 ②「状态机 `reindexing`」）。三处枚举与 ARCH 完全一致。 |
| V2-F2 | ARCH §5.3 env 变量表含 `TRACE_RETENTION_DAYS=90` / `AUDIT_RETENTION_DAYS=90` | ✅ PASS（带备注） | ARCH line 665（§5.3 表内）：「`TRACE_RETENTION_DAYS=90` / `AUDIT_RETENTION_DAYS=90` | trace 事件 / 接口操作日志保留天数（默认 90 天…D-D / DECISION-025，DB_DESIGN §9.2 / §1.8）」。两变量均含值 90、含 D-D/DECISION-025 引用、指向 DB 章节。备注：两变量写在**同一行**（用 `/` 分隔），任务原文表述为「两行」——内容完备、意图满足，非问题（见 R3）。 |
| V3a-1 | FEATURES 有新功能点：双向联动描述 | ✅ PASS | FEATURES line 312-323：RAG-11「切分对比查看（原文档-chunk 双向联动）」，含交互 2 条（右→左 chunk 定位高亮、左→右 反查包含该位置的 chunk）。 |
| V3a-2 | FEATURES 新功能点：4 条验收标准 | ✅ PASS | FEATURES line 318-322 验收要点恰 4 条：① 六类文档均可打开对比视图；② chunk→原文定位与 `rag_chunks` 位置信息（pos/chunk_index）一致；③ 原文→chunk 反向定位正确（chunk 确实包含该位置）；④ 手改 chunk 保存后视图实时展示新内容（无需重新切分）。均可验证、含明确判定依据。 |
| V3a-3 | FEATURES 新功能点：标「用户 2026-09-22 新增」非推测 | ✅ PASS | line 314 来源：「【用户明确要求】（用户后续新增需求，2026-09-22；非推测，不计入 BRIEF §2 45 标准 ID 口径）」；line 313 描述附用户原话节选；line 689 单列 U-01 行（用户原话 + 2026-09-22 + 映射 RAG-11）。 |
| V3a-4 | FEATURES 新功能点：统计数 +1 | ✅ PASS | line 17 总量「9 个模块，共 **57** 个功能点（…48 个【用户明确要求】，含…RAG-11）」（56→57、用户明确 47→48，4+5+48=57 自洽）；line 330 §4.1 验收汇总第 5 条新增 RAG-11；line 707 §10.3 标题「57 个」，line 714 RAG 模块「RAG-01..11（11 个；RAG-11 为用户 2026-09-22 后续新增）」；line 721 统计说明同步。 |
| V3a-5 | FEATURES：单列「用户后续新增需求」区 | ✅ PASS | line 685-691：「#### 用户后续新增需求（BRIEF §2 之外，不计入 45 标准 ID 口径）」表 U-01 + 说明行，独立于 10.1 主表 45 标准 ID 口径。 |
| V3b-1 | FLOW 有新流程图：双向联动 | ✅ PASS | FLOW line 317-339（§3.4 M4 RAG 内第 4 张 mermaid 图）：左右分栏视图、双向联动分支（点右栏 chunk→F1/F2a/b/c 定位高亮；点左栏→G1 反查→G2）、chunk 修改后刷新（I→J）。 |
| V3b-2 | FLOW 新流程图：文档类型定位粒度分支 | ✅ PASS | line 326-329 决策节点 F2 三分支：文本类（txt/word/文本 pdf）= 页码/节/行级；表格（excel/文档内表格）= 单元格/行列范围级；图片/扫描 PDF = 图片区域（整图/页级）【推测】（与 ARCH §2.2.1 坐标结构表 6 行逐类型一致）。 |
| V3b-3 | FLOW 新流程图：组件名沿用 31 项契约、无新组件 | ✅ PASS | 新图组件仅 WebConsole / RAGService / StorageService / VectorStore，均出自 FLOW §1 契约表（实测 §1 表恰 31 行）；修订记录 line 24 ③ 自述「沿用第 1 章 31 项契约…未引入新组件」，与人工核对一致。 |
| V3b-4 | FLOW 新流程图：图数统计更新 | ✅ PASS | 实测 `grep -c '```mermaid'` = **22**（21→22）；修订记录 line 25 ④「图数 21 → 22（本文档无图数统计文字，全文图数已核对）」；§4.2 S2 时序图 line 604 写入侧末段新增「进入对比查看（…见 §3.4 切分对比查看流程）」，line 549 覆盖说明同步。 |
| V3c | ARCH 有接口说明（复用/新增明确 + pos 坐标按文档类型） | ✅ PASS | ARCH line 284-312 新增 §2.2.1：5 接口清单表——复用 3（原文档文件获取 `GET …/docs/{doc_id}/file`、chunk 列表 `GET …/chunks`、chunk 编辑 `PUT …/chunks/{chunk_id}`，均标注对应 RAG-05 验收）+ 新增 2（`GET …/chunks/{chunk_id}/location`、`GET …/chunks/by-location` 含重叠多命中 + `primary_chunk_id` 语义）；pos 坐标结构表 6 行覆盖 pdf（文本层/扫描）/docx/txt/xlsx/png·jpg，键含页码、章节路径、字符偏移、表格行列、整图，与 DB §4.3 现有 JSONB 键一致。 |
| V3d | 三文档功能名一致：「切分对比查看（原文档-chunk 双向联动）」 | ✅ PASS（带备注 R2） | 完整功能名命中：FEATURES line 312（标题）、ARCH line 17/284/286（修订记录+节标题+功能名声明）。FLOW 全文 0 处完整名——图题 line 317 用变体「切分对比查看（**左右分栏双向联动**）」，修订记录 line 22-23 用短名「切分对比查看」。三文档均指同一功能且 FLOW 显式声明「与 zhangbeihai 在 ARCH 的接口定义为同一功能」、ARCH 显式声明「与 luoji 在 FEATURES 表述一致」，交叉引用闭环成立；但 FLOW 图题未用标准全名（见 R2）。 |
| V4 | 交叉：D12 动 DB 字段 → DB 计数/索引/ER 同步；是否引入新不一致 | ✅ PASS | D12 实际 DB 变更 = 仅 `rag_chunks.pos` **字段语义说明补充**（table_row 键对象形状固定，DB line 404 + 头部 ⑫ line 17），无表/字段/索引/表结构变更。核对：DB line 32 表数「34 张」不变、line 1167 ER 核对清单 34 张全覆盖、line 1210 §15 总表核对结论 34 张、§13 索引清单未涉及 pos 变更（pos 无索引，不涉及）。ARCH §2.2.1 line 312 与 DB line 404/17 的 pos 结构表述逐字一致（`{page, section_path, char_start, char_end, table_row}` + table_row 对象约定），**未引入新不一致**。 |

**验证项 15 / 通过 15 / 其中 2 项带备注（R2、R3，均 P2 低严重度）/ 失败 0。**

---

## 2. 残留清单（P2，非阻塞）

| # | 残留 | 位置 | 性质 | 影响 | 建议 |
|---|---|---|---|---|---|
| R1 | 交叉引用错误：ARCH §2.2.1 line 286「流程见 FLOW_DIAGRAMS.md **§2**「切分对比查看」流程图」——该图实际位于 FLOW **§3.4**（M4 RAG 第 4 图）。FLOW 内部引用（line 604「见 §3.4」、line 549「§3.4」）均正确，错误仅出在 ARCH 这一处跨文档引用。 | ARCH line 286 | P2 文档交叉引用 | 读者按 §2 查找会找到「总览：模块关系图」而非目标流程图；测试/开发按图索骥多一步。 | 将 ARCH line 286 的「§2」改为「§3.4」。 |
| R2 | FLOW 新图题（line 317）用「切分对比查看（**左右分栏双向联动**）」，未用三文档标准全名「切分对比查看（原文档-chunk 双向联动）」；FEATURES/ARCH 均使用标准全名。 | FLOW line 317 | P2 命名一致性 | 按功能名精确检索（如按标准全名 grep）FLOW 会漏检；不影响理解（图内描述与 ARCH 定义一致且显式声明同一功能）。 | 图题括注改为「（原文档-chunk 双向联动）」或保留两者并列。 |
| R3 | F2 验证项要求「两行」，实际两变量写在 §5.3 表**同一行**（`TRACE_RETENTION_DAYS=90` / `AUDIT_RETENTION_DAYS=90` 同行）。 | ARCH line 665 | P2（偏格式） | 无实质影响：两变量名、默认值 90、D-D/DECISION-025 引用、DB 章节指向均完备；与同表其他「A / B」合并行风格（line 661-663 多处）一致。 | 可选拆两行；不拆亦视为满足。 |

无 P0 / P1 残留。R1-R3 均不推翻 D12/D13/D14 的落地结论。

---

## 3. 结论

**PASS（PASS_WITH_NOTES）**——D12/D13/D14 三个任务的全部落地要求均验证通过：

1. **F1 修复落地**：4 份设计文档无 `re-embedding` 活跃残留，ARCH §9-16 与 DB §4.1/§4.2 状态名统一为 `reindexing`。
2. **F2 修复落地**：ARCH §5.3 env 表已含 `TRACE_RETENTION_DAYS=90` / `AUDIT_RETENTION_DAYS=90`（同表同行，内容完备）。
3. **切分对比查看三文档一致**：FEATURES RAG-11（双向联动描述 + 4 条验收 + 用户 2026-09-22 非推测标注 + 统计 56→57/47→48 + 单列 U-01 区）、FLOW 新流程图（双向联动 + 6 类文档定位粒度分支 + 31 项契约组件无新增 + 图数 21→22 实测核对）、ARCH §2.2.1 接口清单（3 复用 + 2 新增 + 6 类 pos 坐标结构表）全部到位，三文档功能名一致（交叉引用闭环成立）。
4. **交叉一致性**：D12 未动 DB 表结构（仅 pos 语义说明补充），34 张表/索引/ER 计数全部核对一致，未引入新不一致。

验证项 15 / 通过 15 / 残留 3（均 P2 低严重度，见 §2）/ 无 P0/P1 / 无阻塞。
