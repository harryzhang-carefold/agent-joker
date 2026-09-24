项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: 两处 P2 残留修复（04-analysis/REVISION_VERIFY_D10.md §4 F1/F2）+ 新 RAG 需求「切分对比查看」的架构支撑。改 ARCHITECTURE.md（必要时 DB_DESIGN.md）。

【F1 修复】ARCHITECTURE.md §9-16（line ~782）状态机名 `re-embedding` 改为 `reindexing`，与 DB_DESIGN §4.1 rag_knowledge_bases.status 枚举（active/reindexing/disabled）对齐。全文检索 "re-embedding" 一并统一。

【F2 修复】ARCHITECTURE.md §5.3 env 变量表（line ~622-634）增两行: TRACE_RETENTION_DAYS=90 / AUDIT_RETENTION_DAYS=90（默认值，D-D / DECISION-025）。

【新 RAG 需求（用户 2026-09-22）: 切分对比查看】
上传文档切分后，支持左右分栏对比查看: 左栏=原文档（渲染展示 txt/word/excel/pdf/图片），右栏=chunk 切片列表。
- 交互: 点击右栏某 chunk → 左栏滚动定位并高亮该 chunk 对应的原文位置（用 rag_chunks.pos/chunk_index 反向定位，已有设计）；点击左栏原文区域 → 右栏定位到包含该位置的 chunk（双向联动）
- 在 ARCHITECTURE 中说明: 该功能所需接口组合（原文档查看接口 + chunk 列表接口 + 位置定位）——若现有 RAG 接口已覆盖则明确说明复用；若有缺口（如 chunk→原文位置映射接口、原文高亮坐标接口），补 API 定义（路径/参数/返回，含 pos JSONB 的坐标结构: 页码/段落/行偏移/图片区域，按文档类型）
- 若涉及 DB 字段补充（如 pos 结构细化），同步 DB_DESIGN 并在文档头部修订记录注明
- 该功能点由 luoji 在 FEATURES 新增（RAG-12 或顺延），你与 luoji 的表述需一致: 功能名「切分对比查看（原文档-chunk 双向联动）」。如需协调接口细节，以你（开发）定义为准，luoji 侧功能描述引用

完成后 kanban 标记完成，summary 列出: F1/F2 修复位置 + 对比查看所需接口（复用/新增清单）+ 是否动了 DB。只改 ARCHITECTURE.md / DB_DESIGN.md。
