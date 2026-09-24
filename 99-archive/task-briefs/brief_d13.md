项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: 在 01-product/FEATURES.md 新增 RAG 功能点「切分对比查看」（用户 2026-09-22 新增需求），编号顺延（RAG-12 或按现有编号规则）。

功能点内容（用户原话: "上传文档切分之后，可对比查看原文档（左边元文档，右边chunk切片）"）:
- 功能描述: 文档切分完成后，左右分栏对比查看: 左栏原文档（txt/word/excel/pdf/图片 渲染展示），右栏 chunk 切片列表
- 交互: 点击右栏 chunk → 左栏定位并高亮对应原文位置; 点击左栏原文 → 右栏定位包含该位置的 chunk（双向联动）
- 验收标准: 1) 六类文档均可打开对比视图; 2) chunk→原文定位准确（与 rag_chunks.pos/chunk_index 一致）; 3) 原文→chunk 反向定位正确; 4) 手动修改 chunk 后对比视图实时更新
- 标注: 用户新增需求（2026-09-22），非推测
- 同步: §0/§10 功能点统计数 +1; 与 BRIEF 对照表若按 45 标准 ID 口径，此条在对照表下方单列「用户后续新增需求」区（不破坏 45 ID 口径）
- 接口细节以 zhangbeihai 在 ARCHITECTURE 的定义为准（并行任务），你只写功能与验收，不定义接口

完成后 kanban 标记完成，summary 给功能点编号与位置。只改 FEATURES.md。
