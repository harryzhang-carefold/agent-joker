项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: 等 D08 修订复核（yuntianming 的 REVISION_VERIFY.md）完成后收尾:

1. 阅读 04-analysis/REVISION_VERIFY.md。若全部通过:
   a. 更新 00-management/DESIGN_REVIEW.md: 追加「§6 审阅后修订记录」——两条用户级裁定（D-A tag 文档级 / D-B 工具调用边界）、5 份独立审阅的发现汇总、每条问题的处置状态（已修复/残留）、残留问题清单（如有，标注 P 级与责任人）
   b. 更新 00-management/DECISIONS.md: 新增 D-A、D-B 两条决策（编号顺延），注明用户 2026-09-22 确认
   c. 清理占位模板残留（shiqiang P2-8）: 01-product 下 PRD.md/USER_STORIES.md/PRODUCT_DECISIONS.md、02-development 下 DESIGN.md/DEV_REPORT.md、03-testing 空模板——把 {{PROJECT_NAME}} 占位模板替换为「本文档由 <真实文档> 承接，本文件作废」一行说明，避免与事实源混淆
   d. 更新 00-management/STATUS.md: 设计阶段 v2 修订完成
2. 若 REVISION_VERIFY.md 有未修复项: 逐条建子任务派回对应文档作者（shiqiang=FLOW, luoji=FEATURES, zhangbeihai=ARCH+DB）修复并让 yuntianming 再验，全部收敛后再执行上面 a-d
3. 全部收敛后 kanban 标记完成，summary 给出: 修订条目总数、裁定 2 条、残留问题数、交付物清单（供我汇报用户）
