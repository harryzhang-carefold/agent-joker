项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: 修订 01-product/FEATURES.md（你是原作者，按 5 份审阅 04-analysis/REVIEW_*.md 中涉及本文档的问题修改）。

【已定裁定——必须严格执行，所有文档统一口径】
D-A（official tag 文档级）: tag 落在文档级。rag_docs 将增加 tag 字段（可空，NULL 继承库级）。引用判定: 文档级 tag=official，或文档级为空且库 tag=official，判定为 official。
D-B（工具调用边界）: "工具调用" 定义为 MCP 工具调用（含平台内置 upload_doc/query_doc/rag_search）。RAG 检索与文件上传的内部 API 直调属于平台内部服务调用，不是 agent 工具调用，但必须: a) 校验用户身份(tenant/scope) + 校验 (agent_id, kb_id) 在 agent_knowledge_bases 已勾选（未勾选 403）; b) 落 trace 为 rag/file 事件（不产生 tool_call 事件）。

【必须修订的条目（来自审阅，逐条改并自查）】
1. RAG-01/AGENT-05: tag 粒度从库级改为文档级两级判定（D-A），删掉与 BRIEF 原文矛盾的"知识库 tag 字段"表述——你自己审阅中 P1-1
2. §0/§10.1: 「39 条原话需求」改为「BRIEF §2 共 41 条 bullet（其中 4 条含子项，展开为 45 个标准 ID），对照表按 45 个标准 ID 逐条覆盖」——你自己审阅中 P1-3
3. BFF-06 验收标准第 1 条: 写明排除项——「RAG 检索/文件上传的内部 API 调用以 rag/file 事件留痕，不产生 tool_call 事件；MCP 工具调用（含平台内置）100% 产生 tool_call 拦截记录」，并在功能描述中定义"工具调用"= MCP 工具调用——你自己审阅中 P1-2
4. 存储/上传相关功能点: 补充「后端切换采用保留原后端访问策略（按行内 backend 分派，不自动迁移）」——P2-1
5. 文档上传功能点: 补充「.doc 旧格式不支持，422 拒绝并提示转 .docx」——P2-2
6. RAG-08 验收 3「单次检索覆盖库默认 topK/阈值」: 定为设计决策——rag_search API 支持单次 topK/threshold 覆盖参数（标注为设计决定，非推测）——P2-4
7. §0/§10.3 功能点统计「48」改「47」（4+5+47=56，混合标注实为 5 项: BASE-04/05/RAG-03/AGENT-02/BFF-05）——zhangbeihai P2-6
8. 第三方 agent/MCP 相关功能点验收: 补充「黑盒验收依赖 mock 第三方 MCP server + mock 第三方 agent（DECISION-008 协议），mock 资产在开发阶段完成，列为开发→测试交接检查项」——yuntianming P2-7
9. 全文检索 "39 条" 字样统一口径

【要求】
- 修改后在文档头部加一行修订记录: 修订日期 + 依据 5 份 REVIEW
- 自查: 56 功能点总数不变（仅修描述/统计口径）、推测标注口径完整（推断必须标【推测】）
- 完成后 kanban 标记完成，summary 列出修订条目数
- 只改本文件，不动其他文档
