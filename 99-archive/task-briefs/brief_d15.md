项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: D12/D13/D14 完成后复核（你云天明，测试视角）。对象: 02-development/ARCHITECTURE.md、01-product/FEATURES.md、01-product/FLOW_DIAGRAMS.md。

验证项:
1. F1: 全文（4 份设计文档）无 "re-embedding" 残留，ARCH §9-16 与 DB §4.1 状态名统一为 reindexing
2. F2: ARCH §5.3 env 变量表含 TRACE_RETENTION_DAYS=90 / AUDIT_RETENTION_DAYS=90 两行
3. 切分对比查看三文档一致:
   a. FEATURES 有新功能点（双向联动描述、4 条验收标准、标"用户新增需求 2026-09-22"非推测、统计数+1、单列用户后续新增需求区）
   b. FLOW 有新流程图（双向联动 + 文档类型定位粒度分支 + 组件名沿用 31 项契约无新组件 + 图数统计更新）
   c. ARCH 有接口说明（原文档查看/chunk 列表/双向定位: 复用或新增 API 明确，pos 坐标结构含页码/段落/行偏移/图片区域按文档类型）
   d. 三文档功能名一致: 「切分对比查看（原文档-chunk 双向联动）」
4. 交叉: 若 D12 动了 DB 字段，DB 计数/索引/ER 同步; 是否引入新不一致
5. 输出 04-analysis/REVISION_VERIFY_D12.md: 逐条验证表 + 结论(PASS/残留清单)。只读，不改被审文档
6. 完成后 kanban 标记完成，summary: 验证项数/通过数/残留数 + 结论
