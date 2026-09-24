# BROWSER_TEST — S21 全功能浏览器测试（TASK-S21，2026-09-24）

> QA_STANDARD §二.1 强制项：所有用户可见功能经**真实浏览器**（headless Chromium，
> Playwright 1.63 + chromium-1234，视口 1440×900）实际点击操作一遍，非接口脚本替代。
> 截图统一存 `03-testing/screenshots/`，下节列出每功能的操作步骤 + 截图路径。
> 测试入口：WebConsole `http://localhost:8080`（nginx → SPA + /api,/v1,/mcp → BFF）。
> 账号：admin@acme（种子管理员）/ platform@system（平台管理员）。

## 0. 测试执行方式
- 脚本：workspace `browser_test3.js` + 专项 `probe_mcp_spa.js` / `final_mcp_agent.js` /
  `rag_search_final.js`（Playwright headless Chromium，本机 `~/.cache/ms-playwright/chromium-1234`）。
- 每模块主流程实际点击：新建→保存→列表出现→（必要时）删除清理。
- 每模块 ≥1 条失败/边界路径，核对错误提示是否符合预期。
- 共 35 条浏览器用例（9 大模块 + 边界），结果：31 PASS / 4 FAIL（关联 BUG-09/10/11，见 §8）。
- 截图 55 张（含 BUG 复现截图），全部位于 `03-testing/screenshots/`。

## 1. 模块一：登录/登出（BASE-04/05）
| 用例 | 操作步骤 | 结果 | 截图 |
|---|---|---|---|
| BASE-04a 登录失败（边界） | 登录页填 acme/admin/错误密码 → 点「登录」 | PASS：错误提示 `invalid credentials`，未签发 token | `01a_login_fail.png` |
| BASE-04b 正确登录 | 填 acme/admin/种子密码 → 点「登录」 | PASS：toast「登录成功」，跳转 /users 管理台 | `01b_login_success.png` |
| BASE-05 登出 | 点右上角头像 →「退出登录」→ 确认弹窗 | PASS：调 /api/auth/logout + 重定向 /login | `01c_logout.png` |
| （登录页初始态） | 打开 /login | — | `01a_login_page.png` |

## 2. 模块二：租户/用户/角色管理（BASE-01/02）
| 用例 | 操作步骤 | 结果 | 截图 |
|---|---|---|---|
| BASE-02a 租户管理权限边界 | admin(acme) 直接访问 /tenants | PASS：403 兜底警告「无权限访问租户管理」+ 友好提示（BUG-07 修复项，无回归） | `02a_tenants_forbidden_admin.png` |
| BASE-02b 平台管理员租户列表 | platform@system 登录 → /tenants | PASS：3 个租户（acme/globex/system） | `02b_tenants_platform.png` |
| BASE-02c 新建租户 | 平台管理员「新建租户」→ 编码+名称 → 保存 | PASS：toast「已保存」，列表新增 | `02c_tenant_created.png` |
| BASE-01a 新建用户 | admin「新建用户」→ 用户名/密码/角色 → 保存 | PASS：toast「已创建」（重跑时 `username or email already exists` 为测试自身重名，非缺陷） | `02d_users_list.png` `02e_user_created.png` |
| BASE-01b 短密码（边界） | 新建用户密码填 3 位 | PASS：前端校验「密码至少 6 位」，不提交 | `02f_user_short_pw.png` |
| BASE-02d 新建角色 | 「新建角色」→ 名称 → 保存 | PASS：toast「已保存」，角色 44→45 | `02g_roles_list.png` `02h_role_created.png` |

## 3. 模块三：存储上传 + 文件列表（STORE）
| 用例 | 操作步骤 | 结果 | 截图 |
|---|---|---|---|
| STORE-05a 上传 .txt | 文件上传记录页「上传文件」选 s21_*.txt | PASS：toast「已上传」，列表出现 | `03a_files_list.png` `03b_file_uploaded.png` |
| STORE-05c 文件列表过滤 | 文件名模糊输入新文件名 | PASS：过滤后新文件行可见 | `03b_file_uploaded.png` |
| **STORE-05b 上传 .doc（边界）** | 选 .doc 旧格式文件上传 | **FAIL → BUG-09**：toast「已上传」+ API 200 落盘成功；FEATURES STORE 验收 3 明确要求「.doc 旧格式上传返回 422 拒绝并提示转 .docx」 | `03c_doc_rejected.png` |
| STORE-03a 存储后端配置 | /storage/backends | PASS：local 显示「当前」，gcs/oss 备用未配置 | `03d_backends.png` |

## 4. 模块四：LLM 节点（LLM-01/02/03）
| 用例 | 操作步骤 | 结果 | 截图 |
|---|---|---|---|
| LLM-01a Chat 端点列表 | /llm/endpoints | PASS：26+ 节点（含 platform-fallback-llm 真实端点） | `04a_endpoints_list.png` |
| LLM-01b 新建 Chat 端点 | 「新建」→ 名称/Base URL/模型 → 保存 | PASS：toast「已保存」，列表新增 | `04b_endpoint_created.png` |
| LLM-01c 连通性测试（mock，正常路径） | 新节点（joker-mock-llm:9301）点「连通性」 | PASS：toast「探测结果: 可用 — ok: model=mock-llm responded in 7ms」 | `04c_endpoint_test_ok.png` |
| LLM-01d 连通性测试（不可达，边界） | 新节点（127.0.0.1:59999）点「连通性」 | PASS：toast「探测结果: 不可用 — unavailable: ConnectError: All connection attempts failed」（BUG-08 前端错误提示修复项，无回归） | `04d_endpoint_test_fail.png` |
| LLM-02a Embedding 模型列表 | /llm/embeddings | PASS：8 个节点 | `04e_embeddings_list.png` |
| LLM-03a Reranker 模型列表 | /llm/rerankers | PASS：7 个节点 | `04f_rerankers_list.png` |
| **带 key 节点探测（伪鉴权）** | 见 DEP_VERIFICATION.md | **FAIL → BUG-11**：节点已配 api_key，探测请求**未携带 Authorization**，带鉴权端点永远探测失败 | `dep_verify_bug11.png` |

## 5. 模块五：RAG 知识库（RAG）
| 用例 | 操作步骤 | 结果 | 截图 |
|---|---|---|---|
| RAG-01a 知识库列表 | /rag/kbs | PASS：23 个库（含 official tag） | `05a_kbs_list.png` |
| RAG-01b 建库 | 「建库」→ 名称 + 选 embedding 模型 → 创建 | PASS：toast「建库成功（已建独立向量表）」（D-C 每库独立向量表） | `05b_kb_created.png` |
| RAG-01c 建库缺必填（边界） | 空表单直接「创建」 | PASS：校验提示「名称与 embedding 模型必填」 | `05c_kb_validation.png` |
| RAG-03a KB 上传文档 | 进入库文档页「上传文档」选 .txt | PASS：toast「已上传…（入队解析流水线）」，文档行出现 | `05d_kb_docs.png` |
| RAG-04a 解析流水线状态推进 | 上传后观察文档状态 | PASS：uploaded→…→**ready**（chunk 生成完成） | `05e_doc_pipeline.png` / `RAG_probe_doc_status.png` |
| RAG-06a 检索未选库（边界） | /rag/search 不选库直接「检索」 | PASS：友好提示「选择知识库」 | `05g_search_nokb.png` |
| RAG-06b 检索（正常路径） | 选 s07-e2e-kb → 查询「agent-joker 多租户 AI Agent 平台 RAG」 | PASS：结果 2 条，#1 score 72.6%（官方 tag 正确展示） | `09d_rag_search_results.png` |

## 6. 模块六：MCP（MCP-01/02/03）
| 用例 | 操作步骤 | 结果 | 截图 |
|---|---|---|---|
| **MCP-01a 直接访问 /mcp/servers** | 浏览器地址栏直接访问 /mcp/servers（刷新/分享链接场景） | **FAIL → BUG-10**：页面显示 BFF 返回的 401 JSON（`{"detail":"missing access token"}` +「美观输出」勾选框），**SPA 未渲染**；nginx `location ~ ^/(api|v1|mcp)(/|$)` 把前端路由 /mcp/servers 代理给了 BFF | `MCP_repro_direct.png` `MCP_probe_list.png` |
| MCP-01a' MCP Server 列表（侧边栏进入） | 管理台内点侧边栏 MCP → MCP Server | PASS：12 台 server（online）正常渲染 | `06a_mcp_list.png` `MCP_repro_sidebar.png` |
| MCP-01b 注册 MCP Server | 「注册 Server」→ 名称+URL(host.docker.internal:9100/mcp) → 注册 | PASS：注册即同步（MCP-01）：探测 online，新行出现 | `06c_mcp_registered.png` |
| MCP-02a 工具列表 | 新注册 server 点「工具」 | PASS：/mcp/servers/{id}/tools 渲染 2 个工具 | `06b_mcp_tools.png` |
| MCP-03a 删除 Server（边界/清理） | 新 server 点「删除」→ 确认 | PASS：删除成功，列表移除 | `06a_mcp_list.png`（删除后） |

## 7. 模块七：Skills（SKILL-01/02）
| 用例 | 操作步骤 | 结果 | 截图 |
|---|---|---|---|
| SKILL-01a 内联创建 Skill | 「内联创建」→ 名称+内容 → 保存 | PASS：toast「已保存」，3→4 | `07a_skills_list.png` `07b_skill_created.png` |
| SKILL-01b 空名（边界） | 空名称直接「保存」 | PASS：错误提示 `name is required` | `07c_skill_empty_name.png` |

## 8. 模块八：Agent（AGENT-01/02）
| 用例 | 操作步骤 | 结果 | 截图 |
|---|---|---|---|
| AGENT-01a 新建 Agent(simple) | 「新建 Agent」→ 名称/类型 simple → 创建 | PASS：API 层独立验证 5×201（间隔 4s）；浏览器内点击多次触发 BFF 用户级 QPS 限流（429）——限流为设计行为（BFF_RATE_LIMIT_USER_QPS=10），但 UI 连续操作即触发的体验问题记入观察项 OBS-01 | `08a_agents_list.png` `AGENT_created_final.png` |
| AGENT-02a Agent 对话（simple + mock LLM） | 列表点「对话」→ 输入问题 → 发送 | PASS：mock LLM 回复「好的，我已经收到你的消息…」 | `08c_chat_open.png` `08d_agent_reply.png` |
| AGENT-02b 会话多轮续接 | 同会话再发第二句 | PASS：4 条气泡，会话 ID 续接正常 | `08e_agent_second_turn.png` |
| **Agent 绑定带 key 真实 LLM 对话** | s08-e2e-agent（绑 platform-fallback-llm，真实 34.121.9.233:4000 + key）经 /v1/chat/completions 对话 | **FAIL → BUG-11 连带**：502 `LLM call failed (round 1): AuthenticationError: 401`——运行时同样经 `get_endpoint` 读 `api_key_enc`（被脱敏 pop），凭据丢失；对照组 mock LLM agent 同路径 200 正常 | 见 DEP_VERIFICATION.md §4 |

## 9. 模块九：Trace/审计（TRACE-01/02）
| 用例 | 操作步骤 | 结果 | 截图 |
|---|---|---|---|
| TRACE-01a Trace 会话列表 | /trace/sessions 点「查询」 | PASS：50 条会话（总数 117） | `09a_trace_list.png` |
| TRACE-01b 会话详情 | 点会话行 → 详情 | PASS：跳转 /trace/sessions/{sid} 事件流渲染 | `09b_trace_detail.png` |
| TRACE-02a 接口操作日志（审计） | /audit 点「查询」 | PASS：50 条审计记录（方法/路径/状态/耗时/IP/时间） | `09c_audit.png` |

## 10. 观察项（非缺陷，记录）
- **OBS-01 限流触发频率**：BFF 用户级 QPS=10（默认），浏览器 UI 一次页面操作含多个 /api 请求，
  连续点「新建 Agent」3-4 次即 429 `rate limit exceeded (user)`。功能上正确（S12 已验证限流生效），
  但默认阈值对管理台日常操作偏敏感，建议默认值上调或对管理类接口豁免。
- **OBS-02 环境态**：真实 LLM 端点 34.121.9.233:4000 的 key（Leaflong-0…o6EA8R0uXG）当前**持续 401**
  （容器/宿主、带/不带 key、8 连发全部 401，/v1/models 亦 401）——与 S20 结论（端点侧间歇 401、key 当时有效）
  相比已恶化为全 401，疑似 key 被轮换/失效或端点侧 worker 全部未配 key。**需用户在端点侧核查**（平台侧不可控）。

## 11. 结论
浏览器功能测试 35 项：**31 PASS / 4 FAIL**。4 个 FAIL 全部定位到 3 个新 BUG（BUG-09 .doc 未拒绝、
BUG-10 /mcp/servers SPA 路由被代理、BUG-11 凭据未随探测/运行时发送）。其余 8 大模块主流程 + 边界路径
经真实浏览器操作验证通过，9 张关键截图存 `03-testing/screenshots/`。
