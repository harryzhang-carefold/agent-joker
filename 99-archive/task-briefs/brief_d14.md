项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: 在 01-product/FLOW_DIAGRAMS.md 新增「切分对比查看」流程（用户 2026-09-22 新增需求，与 zhangbeihai 在 ARCH 的接口定义为同一功能）。

需求: 文档切分完成后，左右分栏对比查看: 左栏=原文档（渲染展示），右栏=chunk 切片列表; 点击右栏 chunk → 左栏滚动定位并高亮对应原文位置（chunk→原文，用 pos/chunk_index 反向定位）; 点击左栏原文 → 右栏定位包含该位置的 chunk（原文→chunk，双向联动）。

要求:
1. 新增 mermaid 流程图（放入 RAG 模块章节，编号顺延）: 打开对比视图 → 加载原文档渲染 + chunk 列表 → 双向联动定位/高亮 → chunk 修改后刷新。画出关键分支: 原文档类型不同（文本类/表格/图片）的定位粒度差异（页码/行/图片区域）
2. 若 S2 时序图（文档上传→解析→切分→入库）末尾可加一步"进入对比查看"，加之（保持图不破裂）
3. 组件命名沿用现有 31 项契约（WebConsole、RAGService、DocParser、VectorStore 等），不引入新组件名; 对比查看属 WebConsole 前端功能 + 现有 RAGService 接口，无需新组件
4. 自查: mermaid 语法可用、图数+1 后文内图数统计更新
5. 完成后 kanban 标记完成，summary 给新增图编号与位置。只改 FLOW_DIAGRAMS.md
