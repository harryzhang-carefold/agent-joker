项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: 修订复核——等 D05/D06/D07 三份文档修订完成后，你（云天明，测试视角）逐条复核所有问题是否已修复。

输入: 04-analysis/ 下 5 份 REVIEW_*.md（问题来源）+ 修订后的 01-product/FLOW_DIAGRAMS.md、01-product/FEATURES.md、02-development/ARCHITECTURE.md、02-development/DB_DESIGN.md。

复核口径:
1. 汇总 5 份 REVIEW 的全部 P0/P1/P2 条目（去重，按问题 ID 合并），逐条验证修订后文档中是否已修复: 已修复/未修复/部分修复 + 证据（文档+章节+行号）
2. 重点验证两条裁定是否全链路落地且口径一致:
   D-A（official tag 文档级两级判定）: FLOW 判定逻辑 / FEATURES RAG-01+AGENT-05 / ARCH §4.5 / DB rag_docs.tag 字段 四处一致
   D-B（工具调用=MCP 工具调用 + 内部 API 校验+trace+排除项）: FLOW S3 / FEATURES BFF-06 验收 / ARCH §1.1+§9-7+§2.3 / DB trace 事件类型 四处一致
3. 交叉一致性抽查: 修订是否引入新的不一致（如组件命名漂移、表数变化、引用章节号失效）
4. 输出 04-analysis/REVISION_VERIFY.md: 逐条验证表 + 结论（全部通过 / 列出残留问题）
5. 只读复核 + 只写 REVISION_VERIFY.md，不修改任何被审文档。发现未修复项，在你的文件里精确标注（文件+章节+期望改法），不要自己改

完成后 kanban 标记完成，summary 给出: 总条数 / 已修复 / 未修复数 + 结论。
