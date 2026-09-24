项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: 修订 01-product/FLOW_DIAGRAMS.md（你是原作者，按 5 份审阅 04-analysis/REVIEW_*.md 中涉及本文档的问题修改）。

【已定裁定——必须严格执行，所有文档统一口径】
D-A（official tag 文档级）: tag 落在文档级。引用判定逻辑: 文档级 tag=official，或文档级为空且所属知识库 tag=official，判定为 official。本文档中所有 "tag=official 文档" 的判定描述（§3.4 检索、S3/S4 时序图）改为该两级判定逻辑。
D-B（工具调用边界）: "工具调用" 定义为 MCP 工具调用（含平台内置 upload_doc/query_doc/rag_search）。RAG 检索与文件上传的内部 API 直调属于平台内部服务调用，不是 agent 工具调用，但必须: a) 校验用户身份(tenant/scope) + 校验 (agent_id, kb_id) 在 agent_knowledge_bases 已勾选（未勾选 403）; b) 落 trace 为 rag/file 事件（不产生 tool_call 事件）。

【必须修订的条目（来自审阅，逐条改并自查）】
1. S3 时序图: 内部 RAG API 调用处补充 (agent_id, kb_id) 勾选校验（未勾选 403）——zhangbeihai P2-4
2. S3 时序图: ToolInterceptor 当前画成独立参与者+跨进程箭头，与 DECISION-015「进程内共享库」矛盾——把 TI 并入 SAR 泳道或明确标注「进程内调用」，并标注 trace 写点在 SAR 进程内——zhangbeihai P2-5
3. S3/S4 tag 判定描述改 D-A 两级判定——luoji P1-1
4. §3.5 MCP 删除/禁用关联调用方检测: 补充说明「检测范围限定为平台内 agent 勾选（agent_mcp_tools），第三方 agent 提供方的调用不在检测范围」——yuntianming P2-6
5. §1 组件清单: 若 TI 条目措辞仍暗示独立进程，与 DECISION-015 对齐
6. 全文检索 "39 条" 字样，统一为「45 个标准 ID（源自 BRIEF §2 的 41 条 bullet）」口径
7. 全文检查: 与 D-A/D-B 冲突的表述一并修

【要求】
- 修改后在文档头部加一行修订记录: 修订日期 + 依据 5 份 REVIEW
- 自查: mermaid 语法仍可用（21 张图不破坏）、组件命名契约 31 项不漂移
- 完成后 kanban 标记完成，summary 列出修订条目数
- 只改本文件，不动其他文档
