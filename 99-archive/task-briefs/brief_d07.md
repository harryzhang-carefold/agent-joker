项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: 修订 02-development/ARCHITECTURE.md 和 02-development/DB_DESIGN.md（你是原作者，按 5 份审阅 04-analysis/REVIEW_*.md 中涉及本两份文档的问题修改）。

【已定裁定——必须严格执行，所有文档统一口径】
D-A（official tag 文档级）: rag_docs 表增加 tag text 字段（可空）。引用判定: 文档级 tag=official，或文档级为空且所属知识库 tag=official，判定为 official。ARCH §4.5 引用规则 + DB rag_docs 字段表 + 相关索引说明同步修订。
D-B（工具调用边界）: "工具调用" 定义为 MCP 工具调用（含平台内置 upload_doc/query_doc/rag_search）。RAG 检索与文件上传的内部 API 直调属于平台内部服务调用，不是 agent 工具调用，但必须: a) 校验用户身份(tenant/scope) + 校验 (agent_id, kb_id) 在 agent_knowledge_bases 已勾选（未勾选 403）; b) 落 trace 为 rag/file 事件（不产生 tool_call 事件）。ARCH §1.1 与 §9 遗留问题第 7 行的矛盾表述统一为一处权威表述。

【ARCHITECTURE.md 必须修订的条目】
1. §1.1/§2.3/§4.3/§9-7: D-B 统一表述 + 内部 RAG 检索 API 补「校验 agent 对目标 KB 的勾选关系（agent_knowledge_bases），未勾选 403」——你自己审阅 P2-4
2. ToolInterceptor「进程内共享库」语义: 与 S3 时序图/§1.3 SAR 端口 8002 的跨进程语义混用——统一为「TI 是共享代码库，拦截在 SAR 进程内执行」，§2.3/§4.3 措辞收敛，trace 写点明确在 SAR 进程内——你自己审阅 P2-5
3. §7: 「39 条原话需求」改为「45 个标准 ID（源自 BRIEF §2 的 41 条 bullet，其中 4 条含子项）」——你自己审阅 P1-2
4. §2.2: 显式写入后端切换裁定「切换后端采用保留原后端访问（不迁移）: storage_files.backend 行级记录实际落点，访问按行分派；新上传走新后端」——P2-3
5. §2.2 DocParser: 补充「.doc 旧格式不支持（422 拒绝并提示转 .docx）」——luoji P2-2
6. §4.5: 引用规则改 D-A 文档级两级判定
7. OpenAI 兼容协议 model 参数语义: 三处不一致（agent_id/别名/名称）+ 跨租户解析路径未定义——统一为单一语义（建议: model=agent 别名，BFF 内校验该租户下存在且用户有访问权限，跨租户 404）并写明解析路径——shiqiang P2-4
8. 全文检索 "39 条" 字样统一口径

【DB_DESIGN.md 必须修订的条目】
1. §4 rag_docs 字段表: 增加 tag 字段行（text 可空 / 文档级官方标记，NULL 继承库级 / D-A 判定逻辑 / 关联 rag_knowledge_bases）+ 必要时补索引（tenant_id, kb_id, tag）
2. §7.2.1/7.2.2/7.2.4: 三张 agent 勾选表字段表逐行补 deleted_at 字段行（当前约束/级联描述引用了它但字段表漏列，违反文首「全部字段逐行列出」自设标准）——yuntianming P2-1
3. §9.2 trace_events 字段表: 补 payload_tsv 生成列行（tsvector GENERATED ALWAYS AS (...）+ GIN 索引说明）——yuntianming P2-2
4. rag_doc_images.image_file_id FK: 当前级联删除，与「被 RAG 文档引用的文件禁删（409）」矛盾——改 RESTRICT——shiqiang P2-5
5. §13 索引清单: agent_messages 主查询索引改 tenant 打头（tenant_id, session_id, created_at），与 §10.2 自声明口径对齐——shiqiang P2-6
6. §14: 「25 张表」改「33 张」，§14 标题「25+ 张表」同步改
7. 文首目录: 「§7 九张」补注「§7 共 9 张表 = 1 定义 + 4 勾选 + 4 会话/消息/记忆/obsidian」
8. §2: 后端切换策略句（保留原后端访问、不自动迁移）若 ARCH 已写则此处引用，未写则此处写
9. doc_type 枚举: 补 .doc 不支持（422）说明，与 ARCH 一致
10. 全文检查: 与 D-A/D-B 冲突的表述一并修（尤其 §4.1 tag 字段描述、§8 持久化裁定中工具拦截相关措辞）

【要求】
- 两份文档头部各加一行修订记录: 修订日期 + 依据 5 份 REVIEW
- 自查: 表总数 33 不变（rag_docs 只加字段不新表）、ER 图与字段表一致、索引清单与字段表一致
- 完成后 kanban 标记完成，summary 列出两份文档各自修订条目数
- 只改这两份文件，不动其他文档
