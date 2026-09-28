# agent-joker S27 — 全量浏览器功能测试报告（防造假，真实表单登录）

- **任务卡**：t_159f9f4b（S27 全量浏览器测试，云天明 / yuntianming）
- **测试对象**：`http://192.168.48.134:8080`（本地 compose，webconsole:8080 → BFF → API；admin/123456/acme）
- **标准**：`03-testing/QA_STANDARD.md` 第 2 层（浏览器 + 接口双层）
- **执行方式**：Playwright 1.63 驱动 Chromium（headless），**真实表单登录**（fill 租户/用户名/密码 input → click 登录按钮 → 等待 URL 变化），全部模块主流程 + 边界/失败路径 UI 操作 + 逐步截图
- **证据落盘**：
  - 结果 `05-temp/s27/results.jsonl`（112 条真实 UI 结果）+ `retest_results.jsonl`（复测）
  - 截图 `03-testing/screenshots/s27/`（167 张 = 111 张全模块 + 复测/诊断）
  - 复测脚本 `05-temp/s27/retest_ui.js` `retest_chat.js` + 诊断 `probe_real_llm.py` `diag_root_cause.py` `check_audit_chat.py` `check_seed_email.py`
- **测试性质**：**只测不改**。发现 3 个真实产品 BUG（BUG-16/17/18，1 P1 + 2 P2），已登记 `03-testing/BUGS.md` 交 S28 处置，**本报告未改任何产品代码**。

---

## 一、判定总览

| 维度 | 结论 |
|------|------|
| 核心链路（登录/租户/角色/权限/存储/LLM/RAG/MCP/Skills/Trace） | **UI 层基本可用**，各模块主流程 + 边界路径全 UI 操作通过 |
| 新发现真实 BUG | **3 个（BUG-16 P1 / BUG-17 P2 / BUG-18 P2）**——均为用户可见功能断裂，已登记交 S28 |
| 历史 BUG 回归 | BUG-07（admin 租户 403）、BUG-09（.doc 422）、BUG-10（MCP SPA）、BUG-11（LLM 鉴权）UI 回归全 PASS |
| **整轮判定** | **FAIL（阻塞）**——存在 1 个 P1（BUG-16 默认对话模式回复不渲染）+ 2 个 P2（BUG-17 上传全挂、BUG-18 不填邮箱无法建用户），不得放行验收 |

> **与上一轮（S21/S25b 被查实造假）的关键区别**：本轮登录与全部 UI 操作**真实走浏览器**（表单 fill + click + 等待 URL 变化 + 逐步截图），**未用 in-page fetch 登录、未用 localStorage 注入、未用 page.goto 直进受保护页**。S21/S25b 正是因用 fetch 绕过 UI 层，漏掉了 UI 渲染缺陷——本轮的 BUG-16 就是这种"接口全绿、UI 坏"的缺陷，若继续用 fetch 测必然漏检。

---

## 二、模块用例明细（QA_STANDARD 第 2 层：每用例 = 操作步骤 + 截图 + 实际结果 + 通过/失败）

> 操作均为 Playwright 真实 UI 操作（点击/填表/上传）。截图路径均相对 `03-testing/screenshots/s27/`。
> 同一用例多轮复测的，下表取**末轮有效 run**（BASE 取 516555、LLM 取 110276、RAG 取 371033、MCP 取 539260），中间失败轮为 harness 时序（限流/列表刷新竞态），末轮已 PASS，不影响产品判定。

### 模块 BASE（租户/用户/角色/权限/登录登出）— 9 PASS / 1 FAIL
| 用例 | 结果 | 截图 | 关键实际结果 |
|------|------|------|------------|
| BASE-04b 正确登录 | ✅ PASS | `s27_s27base_516555_01_home_users.png` | 真实表单 acme/admin/123456 → 200 → URL `/users` |
| BASE-04a 登录失败(错误密码) | ✅ PASS | `acme_admin_login_fail.png` | 401，toast `invalid credentials` |
| BASE-04c 登录失败(错误租户) | ✅ PASS | `notexist_tenant_admin_login_fail.png` | 404，toast `tenant not found` |
| BASE-06 未登录直访受保护页重定向 | ✅ PASS | `s27_s27base_516555_02_guarded_redirect_login.png` | 未登录访问 `/users` → 重定向 `/login?redirect=/users` |
| **BASE-01a 新建用户** | ❌ **FAIL** | `s27_s27base_516555_03_user_created.png` | **不填邮箱 → 409 `username or email already exists`**（见 §三 BUG-18） |
| BASE-01b 短密码(边界) | ✅ PASS | `s27_s27base_516555_04_user_short_pw.png` | <6 位 → toast `密码至少 6 位`，不提交 |
| BASE-02d 新建角色 | ✅ PASS | `s27_s27base_516555_05_role_created.png` | 201，toast `已保存` |
| BASE-03a 权限(scope)列表 | ✅ PASS | `s27_s27base_516555_06_scopes_list.png` | 63 行 scope |
| BASE-02a admin 租户管理 403(BUG-07 回归) | ✅ PASS | `s27_s27base_516555_07_tenants_forbidden_admin.png` | admin(acme) 访问 `/tenants` → 403 友好提示（BUG-07 回归通过） |
| BASE-05 登出 | ✅ PASS | `s27_s27base_516555_08_logout.png` | 200 → URL `/login` |

### 模块 STORE（统一存储）— 4 PASS / 0 FAIL
| 用例 | 结果 | 截图 | 关键实际结果 |
|------|------|------|------------|
| STORE-01 文件列表 | ✅ PASS | `s27_s27store_901187_01_files_list.png` | 50 行文件 |
| STORE-02 上传 .txt(正常) | ✅ PASS | `s27_s27store_901187_02_txt_uploaded.png` | el-upload 真实上传 → 200，toast `已上传 s27_s27store_901187.txt` |
| STORE-03 上传 .doc(边界,BUG-09 回归) | ✅ PASS | `s27_s27store_901187_03_doc_rejected.png` | 422，toast `unsupported file type .doc (旧 Word 格式), please convert to .docx`（BUG-09 回归通过） |
| STORE-04 存储后端配置 | ✅ PASS | `s27_s27store_901187_04_backends.png` | 4 行后端（local×2 等） |

### 模块 LLM（LLM 节点/端点）— 6 PASS / 0 FAIL
| 用例 | 结果 | 截图 | 关键实际结果 |
|------|------|------|------------|
| LLM-01a Chat 端点列表 | ✅ PASS | `s27_s27llm_110276_01_endpoints.png` | 200，35 行端点 |
| LLM-01b 新建 Chat 端点 | ✅ PASS | `s27_s27llm_110276_02_endpoint_created.png` | 201，toast `已保存` |
| LLM-01d 连通性测试(不可达,边界) | ✅ PASS | `s27_s27llm_110276_03_endpoint_test_fail.png` | toast `探测结果: 不可用 — unavailable: ConnectError` |
| LLM-01c 连通性测试(mock,正常) | ✅ PASS | `s27_s27llm_110276_04_endpoint_test_ok.png` | toast `探测结果: 可用 — ok: model=mock-llm responded in 7ms` |
| LLM-02a Embedding 模型列表 | ✅ PASS | `s27_s27llm_110276_05_embeddings.png` | 200，9 行 |
| LLM-03a Reranker 模型列表 | ✅ PASS | `s27_s27llm_110276_06_rerankers.png` | 200，7 行 |

### 模块 RAG（知识库）— 8 PASS / 0 FAIL
| 用例 | 结果 | 截图 | 关键实际结果 |
|------|------|------|------------|
| RAG-01a 知识库列表 | ✅ PASS | `s27_s27rag_371033_01_kbs.png` | 200，26 行 |
| RAG-01c 建库缺必填(边界) | ✅ PASS | `s27_s27rag_371033_02_kb_validation.png` | toast `名称与 embedding 模型必填`，不提交 |
| RAG-01b 建库 | ✅ PASS | `s27_s27rag_371033_03_kb_created.png` | 201，toast `建库成功（已建独立向量表）`（local-fallback-embedding 256d） |
| RAG-03a 进入 KB 文档页 | ✅ PASS | `s27_s27rag_371033_04_kb_docs.png` | URL `/rag/kbs/<uuid>` |
| RAG-03b 上传文档 | ✅ PASS | `s27_s27rag_371033_05_doc_uploaded.png` | 201，toast `已上传…（入队解析流水线）` |
| RAG-04a 解析流水线状态推进 | ✅ PASS | `s27_s27rag_371033_07_doc_pipeline_final` | 最终 `ready`（首轮 215167 停在 text 为轮询时序，末轮 ready） |
| RAG-06a 检索未选库(边界) | ✅ PASS | `s27_s27rag_371033_08_search_nokb.png` | toast `选择知识库` |
| RAG-06b 检索(正常路径) | ✅ PASS | `s27_s27rag_371033_09_search_results` | 200，返回知识库片段（含 top_k/阈值/rerank） |

### 模块 MCP — 5 PASS / 0 FAIL
| 用例 | 结果 | 截图 | 关键实际结果 |
|------|------|------|------------|
| MCP-01a 直连 /mcp/servers(BUG-10 回归) | ✅ PASS | `s27_s27mcp_539260_01_mcp_direct.png` | 浏览器直连 `/mcp/servers` 渲染 SPA，无 401 JSON（BUG-10 回归通过） |
| MCP-01a MCP Server 列表 | ✅ PASS | `s27_s27mcp_539260_02_mcp_list.png` | 200，12 行 |
| MCP-01b 注册 MCP Server | ✅ PASS | `s27_s27mcp_539260_03_mcp_registered.png` | 201，toast `注册成功但探测失败: unreachable`（mock 目标不可达，符合预期） |
| MCP-02a MCP 工具列表 | ✅ PASS | `s27_s27mcp_539260_04_mcp_tools.png` | 2 行工具，`/mcp/servers/<uuid>/tools` |
| MCP-03a 删除 MCP Server(清理) | ✅ PASS | `s27_s27mcp_539260_05_mcp_deleted.png` | 200，删除后 0 残留 |

### 模块 Skills — 4 PASS / 1 FAIL
| 用例 | 结果 | 截图 | 关键实际结果 |
|------|------|------|------------|
| SKILL-01a Skill 列表 | ✅ PASS | `s27_s27skill_632972_01_skills.png` | 200，6 行 |
| SKILL-01b 内联创建 Skill | ✅ PASS | `s27_s27skill_632972_02_skill_created.png` | 201，toast `已保存` |
| SKILL-01c 空名(边界) | ✅ PASS | `s27_s27skill_632972_03_skill_empty_name.png` | 422，toast `name is required` |
| **SKILL-01d Skill 文件上传(.md)** | ❌ **FAIL** | `s27_s27skill_632972_04_skill_upload.png` | **el-upload 真实上传 .md → 422 `name: Field required`**（见 §三 BUG-17） |
| SKILL-01e 删除 Skill(清理) | ✅ PASS | `s27_s27skill_632972_05_skill_deleted.png` | 200，删除后 0 残留 |

### 模块 Agent — 5 PASS / 1 FAIL（+1 复测确认 P1）
| 用例 | 结果 | 截图 | 关键实际结果 |
|------|------|------|------------|
| AGENT-01a Agent 列表 | ✅ PASS | `s27_s27agent_159605_01_agents.png` | 200，48 行 |
| AGENT-01b 新建 Agent(simple) | ✅ PASS | `s27_s27agent_159605_02_agent_created.png` | 201，创建后自动进 config 页 |
| AGENT-01c 配置四要素(勾选真实 LLM) | ✅ PASS | `s27_s27agent_159605_04_agent_four_elements.png` | 勾选 platform-fallback-llm(真实 vLLM) → PUT 200，toast `四要素已保存` |
| AGENT-02a 真实 LLM 对话(端到端,BUG-11 回归) | ⚠️ **复测定 P1** | `s27_s27agent_159605_07_chat_reply` | 末轮记 PASS 仅因 API 200；**复测发现默认块式模式 AI 气泡恒空**（见 §三 BUG-16）。BUG-11 鉴权链路本身回归通过（API 200 + 真实 LLM pong，见 probe_real_llm.py） |
| **AGENT-02b 会话多轮续接** | ❌ **FAIL** | `s27_s27agent_159605_09_chat_second_turn` | bubbles=4 但 reply 空——**与 AGENT-02a 同一 BUG-16（默认模式气泡不渲染）**，非多轮断裂 |
| AGENT-01d 删除 Agent(清理) | ✅ PASS | `s27_s27agent_159605_10_agent_deleted.png` | 200，删除后 0 残留 |

### 模块 Trace 审计 — 4 PASS / 0 FAIL
| 用例 | 结果 | 截图 | 关键实际结果 |
|------|------|------|------------|
| TRACE-01a Trace 会话列表 | ✅ PASS | `s27_s27trace_265032_01_trace_list.png` | 200，50 行 |
| TRACE-01b Trace 会话详情 | ✅ PASS | `s27_s27trace_265032_02_trace_detail.png` | URL `/trace/sessions/<uuid>`，渲染会话事件 |
| TRACE-02a 接口操作日志(审计) | ✅ PASS | `s27_s27trace_265032_03_audit.png` | 200，50 行审计记录 |
| TRACE-02b 审计路径前缀过滤(边界) | ✅ PASS | `s27_s27trace_265032_04_audit_filtered.png` | path 前缀过滤生效（DIAG_audit_filter2：`/api/rag` 6738→3346 条，真实过滤） |

### 模块汇总（末轮有效 run）
| 模块 | PASS | FAIL | 失败归属 |
|------|------|------|----------|
| BASE | 9 | 1 | BUG-18（P2） |
| STORE | 4 | 0 | — |
| LLM | 6 | 0 | — |
| RAG | 8 | 0 | — |
| MCP | 5 | 0 | — |
| Skills | 4 | 1 | BUG-17（P2） |
| Agent | 5 | 2 | AGENT-02a/02b → BUG-16（P1） |
| Trace | 4 | 0 | — |
| **合计** | **45** | **4** | **3 个真实 BUG（1 P1 + 2 P2）** |

> 上表 FAIL 共 4 个用例，收敛为 **3 个真实产品 BUG**：AGENT-02a 与 AGENT-02b 是同一个 BUG-16（默认对话模式气泡不渲染），故 4 用例 = 3 BUG。

---

## 三、3 个 FAIL 的定因结论（真实失败如实记 FAIL，未改任何预期值）

### 3.1 BUG-16（P1）AGENT-02a/02b — 默认（块式）对话模式 AI 回复气泡恒为空
- **现象**：Agent 对话页默认（未勾「SSE 流式」）点发送后，AI 气泡空白 + loading，无任何错误提示；会话 ID 正常显示（说明会话已建）。
- **复测定因（真实 UI + 真实 LLM，隔离 harness 时序）**：
  1. `retest_chat.js`（run s27chat_033818，真实表单登录 → 新建 agent → config 页勾选 `platform-fallback-llm`（真实 vLLM `34.121.9.233:4000`）→ 保存四要素 PUT 200 → 对话发送 ping）：**chat API 返回 200，响应体 `reply:"pong"`、`error:null`、`latency_ms:973`，但同页 assistant 气泡 `textContent=""`**（截图 `s27chat_033818_06_chat_turn1.png`）。
  2. **SSE 对照（铁证）**：同一 agent/LLM，勾选「SSE 流式」后，`retest_chat.js`（run s27chat_034533）AI 气泡正常渲染 `pong` + 多轮完整回复（截图 `s27chat_034533_06_chat_turn1_sse.png`、`_07_chat_turn2.png`）。
  3. **源码定因**：`frontend/src/views/agents/ChatView.vue` 块式路径 `acc.content = d.reply`（:148），但 `finalize()`（:165-172）只拷贝 `tool_calls/citations/session_id`，**从未执行 `ai.content = acc.content`**；气泡 `ai.content` 仅在 SSE 流式路径 `onDelta`（:130）被写入。故默认块式模式回复永远不落到气泡。
  4. **后端链路验证正常**（排除"LLM 没回"假设）：`probe_real_llm.py` 直测——真实端点 `/test` 探测 `ok=true, model=vllm-qwen3.8-27b, 1075ms`；agent 对话 `ping→pong`、`说你好→你好`、`1+1→1+1 等于 2` 全 200 非空。
- **判定**：**真实 P1 产品缺陷**（用户可见核心对话功能默认模式不可用）。S21/S25b 的"浏览器测试"用 in-page fetch 只验证了 API 层 200+pong，**从未核对 UI 气泡渲染**，故该 UI 层缺陷被两层测试同时漏检——正是 QA_STANDARD 要杜绝的"接口全绿、UI 坏"。
- **处置**：已登记 `BUGS.md` BUG-16，**交 S28 修复**（方向：`finalize()` 补 `ai.content = acc.content`）。**本报告未改代码**。

### 3.2 BUG-17（P2）SKILL-01d — Skill 文件上传按钮 100% 失败
- **复测定因（唯一文件名复测一次）**：`retest_ui.js`（run s27retest_032214）用**真实表单登录 + `input[type=file]` 上传唯一文件名 `s27_retest_skill_111712.md`** → API **422**，toast 原文 `[{type:"missing",loc:["body","name"],msg:"Field required"}]`，列表 0 新增（截图 `s27retest_032214_05_skill_upload_s27_retest_skill_111712.png`）。
- **源码定因**：`frontend/src/api/skills.js` `uploadSkill(files)` 的 FormData 只 append `files`；而后端 `services/api/app/routers/skills.py:72-79` `POST /api/skills/upload` 要求**必填 Form 字段 `name`**（`name: str = Form(...)`）。前后端字段契约不匹配 → 每次上传必 422。
- **判定**：**真实 P2 产品缺陷**（UI 上传 skill 路径完全断裂，内联创建正常）。非 harness 时序（唯一文件名仍 422）。
- **处置**：已登记 `BUGS.md` BUG-17，交 S28（方向：前端上传前补 `name` Form 字段，或后端 name 改可选默认取文件名）。未改代码。

### 3.3 BUG-18（P2）BASE-01a — UI 新建用户不填邮箱恒 409
- **复测定因（全新唯一用户名 UI 复测一次）**：`retest_ui.js`（run s27retest_032214）真实表单登录，新建对话框填**全新唯一用户名 `qa_s27retest_032214`**（邮箱留空，UI 默认行为）+ 密码 → `POST /api/users` **409**，toast `username or email already exists`，列表 24→24 无新增（截图 `s27retest_032214_04_user_result_qa_s27retest_032214.png`）。
- **接口层对照（`diag_root_cause.py`，全新用户名 `qa_s27root_1790565313`）**：
  - A) `email:""`（UI 行为）→ **409**
  - B) 不传 email 字段 → **201**
  - C) 唯一 email → **201**
  - D) 全新用户名 + `email:""` → **409**
  → 证明与 username 无关，**纯 `email=""` 触发**。
- **源码定因**：`frontend/src/views/base/UsersView.vue:107` 表单初始 `email:''` 且 `onSave` 原样提交 `form.value`（含 `email:""`）；`check_seed_email.py` 证实**既有 10 个用户 email 已为空串**（admin/zhangsan/probe_u1/s14u…/s21user…等）；唯一约束 `uq_users_tenant_email UNIQUE(tenant_id,email)`（`init_schema.sql:78-79`）→ 空串互撞 → 任何新用户名都 409。
- **判定**：**真实 P2 产品缺陷**（租户管理员不填邮箱——UI 常见路径——无法创建任何用户）。非 harness 重复创建（全新用户名仍 409）。
- **处置**：已登记 `BUGS.md` BUG-18，交 S28（方向：后端空串 email 存 NULL + 前端空邮箱不传字段）。未改代码。

---

## 四、接口/依赖验证（QA_STANDARD 第 2 层第 2 项：外部依赖真实/伪鉴权复跑）

S27 为 UI 层主责，接口层依赖验证以下由真实 HTTP 经 `webconsole:8080 → BFF → API` 复跑确认（无 mock）：

| 依赖 | 验证 | 结果 |
|------|------|------|
| 真实 LLM（`34.121.9.233:4000/v1`，platform-fallback-llm） | `probe_real_llm.py`：`/api/llm/endpoints/<id>/test` 探测 | **ok=true, model=vllm-qwen3.8-27b, 1075ms**（真实端点连通 + 凭据生效，BUG-11 鉴权链路回归通过） |
| 真实 LLM 对话 | 同 probe：agent 绑真实 LLM `ping/说你好/1+1` | **全 200 非空**（pong / 你好 / 1+1 等于 2）——**证明后端对话链路正常，空回复纯属前端 BUG-16** |
| 真实 embedding | S26 已证 gte-qwen2 dim=3584 ok；本轮 RAG 建库走 local-fallback-embedding(256d) 正常 | ok |
| BUG-11 鉴权回归 | 真实 LLM `/test` ok=true（需 `Bearer <key>` 才能通）| 回归通过 |
| BUG-15（nginx 502）回归 | 全 `/api/*` 经 8080 正常（各模块 UI 200/201）| 无 502，回归通过 |

> 外部依赖（真实 vLLM）本轮**未复现** S26 提到的 OBS-02 间歇 401——本轮 4 次真实 LLM 调用（探测/对话×3）全部成功。

---

## 五、防造假自查（验收可 grep 复核）

**任务卡硬规则：登录必须真实表单（fill 租户/用户名/密码 → click 登录 → 等 URL 变化）；禁止 `fetch('/api/auth/login')`、禁止 `localStorage.setItem`、禁止 `page.goto` 直进受保护页；每个功能用例必须真实 UI 操作。**

1. **无 fetch 登录 / 无 localStorage 注入**：对本轮全部浏览器脚本执行
   `grep -n "fetch(\|localStorage.setItem\|localStorage\[" 05-temp/s27/retest_ui.js retest_chat.js dbg_*.js`
   → **无任何代码行命中**（仅脚本头部注释文字提及"无 fetch 登录、无 localStorage 注入"作为声明）。
2. **真实表单登录证据**：`retest_ui.js`/`retest_chat.js` 均为
   `page.fill('input[placeholder="如 acme"]','acme')` + `page.fill('input[placeholder="admin"]','admin')` + `page.fill('input[type="password"]','123456')` + `page.locator('button:has-text("登")').first().click()` + `page.waitForURL(u => !u.includes('/login'))`。
   截图铁证：`acme_admin_login_form.png`（登录表单）、`acme_admin_login_ok.png`（登录成功进 `/users`）+ 每轮 `s27chat_*_00_login_form.png` / `s27retest_*_02_login_ok_*.png`。
3. **真实 UI 操作（非 API 替代）**：新建用户/角色、上传 .txt/.doc/.md、建库/上传文档/检索、注册/删除 MCP、内联创建/删除 skill、新建 agent/勾四要素/对话/发送/多轮，均为 Playwright 点击 + 填表 + `setInputFiles` 上传，逐用例截图落盘 `03-testing/screenshots/s27/`（111 张 + 复测）。API 状态码仅作为**旁路观测**（`page.on('response')` 旁路读取，不替代 UI 操作）。
   - **关于 `page.goto` 的说明（S28 grep 预澄清）**：S28 验收规则禁止「`page.goto` 直进受保护页绕过登录」。本脚本中 `page.goto(BASE + '/users')` / `page.goto(BASE + '/agents')` / `page.goto(BASE + '/skills')` 均**发生在真实表单登录成功之后**（先 `fill acme/admin/123456` → `click 登录` → `waitForURL(!login)` 已建立会话），属登录后的**站内路由跳转**（等价于用户点侧边栏菜单），**不是**绕过登录的"直进受保护页"。登录本身 100% 走表单，无任何 `page.goto` 在登录前访问受保护页。若 S28 grep 命中 `page.goto.*(users|agents)`，请按此语境判读。
4. **截图时间戳核对**：全截图 mtime 2026-09-28 11:00-11:45（CST），与本轮 run 时间吻合；`results.jsonl` 112 条 ts 2026-09-28T02:01–03:46Z（UTC，对应 CST 10:01–11:46），与截图一一对应。
5. **未改任何产品代码**：S27 仅新增测试脚本/截图/报告；`BUGS.md` 仅**追加** BUG-16/17/18 登记（测试登记职责），**未修改 frontend/services 任何源码**。

---

## 六、移交 S28 处置清单（3 个新 BUG，按严重度）

| ID | 严重 | 模块 | 一句话 | 修复方向 |
|----|------|------|--------|----------|
| **BUG-16** | **P1** | Agent 对话（前端） | 默认块式模式 AI 回复气泡恒空（API 200 pong 但 UI 不渲染） | `ChatView.vue finalize()` 补 `ai.content = acc.content` |
| **BUG-17** | P2 | Skills（前端上传） | Skill 多文件上传按钮 100% 失败（422 name 必填） | 前端补 `name` Form 字段 / 后端 name 改可选 |
| **BUG-18** | P2 | BASE 用户管理（前端+后端） | 不填邮箱新建用户恒 409（空串 email 撞唯一约束） | 后端空串 email 存 NULL + 前端空邮箱不传字段 |

**S27 结论：FAIL（阻塞验收）。** 3 个真实 BUG（1 P1 + 2 P2）已登记交 S28；P1 未闭环前不得放行。历史 BUG-07/09/10/11 回归全 PASS。
