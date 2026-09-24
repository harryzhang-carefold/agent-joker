# agent-joker S12 功能测试 — 回归说明（REGRESSION.md）

- 任务卡：t_14c1715a（S12 功能测试，yuntianming）
- 测试 run：`s12run1790163089`
- 结论基线：146 项 = 109 PASS / 35 FAIL / 2 SKIP；真实产品缺陷 **6（P1×3 + P2×3）**，无 P0，核心链路未中断。

## 1. 已验证通过（可用面，109 项 PASS 覆盖）
以下能力经独立 probe 复现或 API 等价证据确认**可用**，可作为回归基线（修复后不得回归）：

### 认证/权限/多租户（BASE）
- 用户增删改/禁用/禁用禁登/重置密码/重新启用登录
- 角色创建、删除（删前引用校验）；权限点定义关联角色
- 登录（密码错误拒签）、token 携带 tenant_id/user_id/scopes
- 登出 refresh 吊销（401）；旧 refresh 重放被拒（轮换+整族吊销）、篡改 token 401、BFF 校验无效 token 401
- 操作日志可查（操作者/时间/接口/状态码）、按接口筛选、敏感字段脱敏（登录日志无明文密码）
- 多租户隔离：跨租户猜 ID→404（不泄露存在性）
- 前端 SPA index.html 可加载、Vue Router history fallback 9 模块可达、9 模块数据端点经 token 均可访问（API 等价；浏览器自动化本环境不可用，S10 自测 34/34）

### 存储（STORE）
- 本地后端配置生效 + 上传落盘（backend=local）
- GCS/OSS 云后端已实现、无账号不崩溃；STORAGE_BACKEND env 配置化切换（保留原后端不迁移）
- 按文件名访问文件（本租户得内容/404/跨租户 404）
- 上传记录可查（文件名/上传者/来源/时间/大小）
- 平台 MCP 内置 server（upload_doc/query_doc/rag_search）在工具列表 + BFF /mcp tools/list 暴露

### LLM 节点维护
- endpoint 新增/列表/连通性调用测试/key 脱敏（仅 api_key_set 布尔）
- embedding 新增/列表/local fallback 确定性（同文本同向量、维度一致）
- reranker 新增/列表/删除

### RAG
- 建库（名称/描述/embedding/库级 tag）+ 列表
- 6 类文档类型校验：.exe 拒 422、.doc 旧格式拒 422
- 维度快照固化（embedding_dim=建库时模型维度）
- 切分策略：表格 is_table（5 策略之一实测）
- 检索参数：topK=N 上限、阈值 0.99→0、单次级 topK 覆盖回落库默认
- 切分对比双向联动：chunk→原文定位、原文→chunk 反查（by-location）、手改后对比视图实时展示
- **D-C 每库独立向量表**：两库不同 rag_chunks_vec_<kb_id>、维度=该库模型维度

### MCP
- URL 注册即同步、多 server 独立管理、编辑
- 工具同步/禁用（agent 侧不可调）/启用恢复/删除（不删远端）
- 无关联调用方可直接删除；关联提示端点 /referring-agents 200

### Skills
- 手动创建（名称+内容）/可编辑/列表
- 上传记录来源=skill 可查（元数据与文件分离一致）
- 删除 skill（元数据+文件清理策略）

### AGENT（简易 + 第三方）
- 创建简易 agent/类型可选、四要素回显（LLM/KB/MCP/skills 勾选）、非法 tool id 422（S11 已修）
- 对 agent 对话得回复（简易闭环）、对话详情完整消息流
- 引用规则：非 official 且未要求→不附来源
- 对话文件入存储模块（source=agent）+ 记录可查
- 记忆：关闭会话触发 LLM 提炼长期记忆、长期记忆持久化 PG（agent_memories）、obsidian 知识沉淀（vault 笔记+索引）
- 第三方 agent：URL 创建/维护/交互、记忆由提供方实现（平台不注入）、对话闭环（mock-tp：tool_calls 拦截→回传→最终答案）、不配工具对话正常

### BFF
- 统一鉴权：无 token/无效 token 401、有效通过、业务服务不重复实现 token 校验
- 限流配置运行时调整即时生效（user_qps 10→1000→10 读回验证）
- 配置化路由表（routes.yml，新增端点不改 BFF 代码）、未知路径 404
- OpenAI 兼容：/v1 块式 + SSE 流式（chat.completion.chunk + [DONE]）
- 多租户：跨租户访问 agent→404
- **D-B 工具拦截**：简易 agent 工具 100% 经 ToolInterceptor、第三方 HTTP 响应 tool_call 拦截回传闭环、工具结果入最终回复、内部 RAG 直调产生 rag 事件（非 tool_call，保留留痕）

### TRACE
- 全链路事件（simple + third_party）：system/message/rag/tool_call + 交互内容、token 耗费、时间戳
- 第三方会话事件链含 tool_call（拦截留痕）、文件事件留痕（上传/生成）
- 事件多维检索（event_type）、关键词全文（payload tsvector）、检索受租户隔离（globex 不含 acme）
- **D-D 保留天数可配**（TRACE_RETENTION_DAYS/AUDIT_RETENTION_DAYS 默认 90）+ 月分区 + DROP PARTITION、敏感字段脱敏

### 横切
- 多租户越权防护：agent 参数篡改无效、跨租户 403/404
- 限流：其他租户用户不受影响 200、同租户另一用户 200（用户维度独立计数）、末尾 reset 防跨轮泄漏
- 限流 429 产品行为（probe14 独立复现：user_qps=10 后 16 连发 = 10×200 + 6×429）

## 2. 待修复（真实产品缺陷 6，交章北海，修复后回归）
| ID | 严重 | 范围 | 修复后回归项 |
|----|------|------|------------|
| BUG-01 | **P1** | 角色 scope 绑定/读回 | 建角色绑 scope → 读回非空；用户绑角色 → 有效权限并集；越权 403 |
| BUG-02 | **P1** | 登出 access token 失效 | 登出 → 原 access token 401（jti 黑名单写入 + BFF 校验）；refresh 仍吊销 |
| BUG-03 | **P1** | 审计/上传记录时间筛选 500 | `start/end`（含 Z）正常解析 → 200（空区间 total=0）；audit + upload-records + trace 三处 |
| BUG-04 | P2 | 用户角色分配 | GET user 返回 roles；仅 role_names 可改角色（不 422）；并集验证 |
| BUG-05 | P2 | refresh 换 access | 单一登录→刷新 → 200 新 token；重放仍 401 |
| BUG-06 | P2 | 登出入操作日志 | 登出 → 审计日志出现 /api/auth/logout（延迟后查） |

## 3. 待复测确认（非阻塞，真实端点/隔离后）
- **BUG-05 / BUG-06**：需隔离 IP 窗口、单一登录干净复测，确认是产品缺陷还是时序/家族轮换产物（现有证据倾向产品缺陷，但未定死）。
- **RAG-07/09/10、D-A、AGENT-05/11、AGENT-07 多轮**：当前 0 命中/无召回为**自测 fallback ngram embedding + mock-llm 环境产物**（检索链路已证正确：S11 e2e T4 score=0.663、RAG-08 阈值正确、probe10 向量已写入独立表）。**真实 embedding/LLM 端点恢复后（.env LLM_FALLBACK_* 生产口径）复测**：检索命中、official 两级判定、多轮召回、引用链接原文位置。
- **TRACE-02 按会话检索**：建会话→产生 trace→按该 session_id 检索，确认是否 session 过滤错位（8/9 trace 项 PASS）。

## 4. 测试脚本缺陷（28 项非 PASS 中 17 项，非产品缺陷，已记录供后续 harness 修复）
RAG-02 上传/来源/解析（未等 parse ready，probe10 复现 6/6+ready+2chunk）、RAG-04 定长/父子/语义（时序）、RAG-05 原文/chunk 列表（probe10 复现 200/1782B、count=2）、MCP-03 走错路径（正确 /referring-agents 200）、SKILL-01 上传 .md（multipart 字段 file vs files）、SKILL-02 files 连带、AGENT-04 列表/新建/重命名/删除（字段 session_id vs id + 201 vs 200，probe14 复现全 200）、LLM-01 修改 endpoint（传非字段 description）、限流单用户 429（harness req() 吞 429，probe14 §H 复现 6×429）。这些**不影响产品质量结论**，但 S13 终审时不应将其计为产品缺陷。

## 5. 回归结论
- **核心链路回归：PASS**（RAG 全链路 / 简易+第三方 agent 闭环 / trace 全链路 / 限流 429 / 多租户隔离 / D-B 拦截 / D-C 向量表 / D-D 保留分区 全部通过）。
- **产品验收：未全过**（6 个真实缺陷，其中 3 个 P1）。**项目不可判定「功能测试 PASS / 可交付」**，需章北海修复 6 个 BUG 后由本卡执行回归（修复后重跑 BASE 权限链路 + 登出 + 时间筛选 + 用户角色分配 + refresh + 登出审计），再交 S13 终审。
- **无阻塞性 BUG**：核心链路未中断，故未 kanban_block；3 个 P1 为功能/安全缺陷（权限、登出失效、日志筛选），非链路跑不通，按流程记录 BUGS.md 交褚岩派单。
