# TEST_REPORT_S21 — agent-joker 全功能浏览器测试 + 接口/依赖验证（新 QA 标准首用）

> 任务：TASK-S21（t_c9756857）｜测试：云天明｜日期：2026-09-24｜前置：S20（t_75684eb5，BUG-08 排查 + 前端静默 catch 修复）。
> 本报告**强制执行 `03-testing/QA_STANDARD.md` 第二节（测试）**，为 2026-09-24 用户新 QA 标准**首次落地**。
> 配套文档：`03-testing/BROWSER_TEST.md`（操作步骤+截图）、`03-testing/DEP_VERIFICATION.md`（伪鉴权+真实端点）、
> `03-testing/BUGS.md`（新增 BUG-09/10/11）、`03-testing/screenshots/`（56 张截图）。

## 0. 环境与方式
- 部署：docker compose（joker-webconsole:8080 / joker-bff:8000 / joker-api / joker-pg / joker-redis，均 healthy）。
- **浏览器测试**：Playwright 1.63 + headless Chromium（本机 `~/.cache/ms-playwright/chromium-1234`，视口 1440×900），
  对 9 大模块主流程**逐一实际点击操作**（非接口脚本替代），每功能截图 + ≥1 失败/边界路径。
- **接口/依赖验证**：按 QA_STANDARD §四"伪鉴权本地服务"模板复验 BUG-08 + 真实 LLM/embedding 端点。
- 账号：admin@acme（种子管理员）/ platform@system（平台管理员）。

## 1. 总体结论：**未通过（FAIL）— 不得进入验收/完成**
- 浏览器功能测试 35 项：**31 PASS / 4 FAIL**。
- 接口/依赖验证 4 项：**3 PASS / 1 FAIL**（BUG-11 直接命中）。
- 发现 **3 个新 BUG（BUG-09 P2 / BUG-10 P1 / BUG-11 P1）**，其中 **BUG-10、BUG-11 为 P1 阻塞项**，
  且 **BUG-11 证明 S20 声称"已修"的 BUG-08（探测带鉴权头）并未真正生效**（前端提示已修，凭据发送未修）。
- **QA_STANDARD §三验收门槛：P1 未关闭 → 验收打回，不得标记交付。** 故 S21 报告结论为 **FAIL / 阻塞**。

---

## 2. `## 浏览器功能测试`（BROWSER_TEST.md 摘要，带截图路径）

### 通过项（31）
| 模块 | 通过用例（主流程 + 边界） | 关键截图 |
|---|---|---|
| 登录/登出 | 登录失败错误提示、正确登录、登出重定向 | `01a_login_fail.png` `01b_login_success.png` `01c_logout.png` |
| 租户/用户/角色 | admin 访问租户管理 403 兜底（BUG-07 无回归）、平台管理员租户列表、新建租户、新建用户、短密码校验、新建角色 | `02a…02h` 系列 |
| 存储 | 上传 .txt 成功+列表过滤可见、存储后端配置(local) | `03a` `03b` `03d` |
| LLM 节点 | Chat/Embedding/Reranker 列表、新建端点、连通性 mock→ok、连通性不可达→错误提示（BUG-08 前端提示无回归） | `04a`–`04f` |
| RAG | 库列表、建库(独立向量表)、建库缺必填校验、上传文档、解析流水线→ready、检索未选库提示、**检索命中 2 条 score 72.6%** | `05a`–`05g` `09d_rag_search_results.png` |
| MCP | 侧边栏进入 Server 列表(12 台)、注册 Server(注册即同步)、工具列表、删除 Server | `06a` `06b` `06c` |
| Skills | 内联创建 Skill、空名校验 `name is required` | `07a` `07b` `07c` |
| Agent | 新建 Agent(API 层 5×201 验证)、Agent 对话(mock LLM 有回复)、会话多轮续接 | `08a`–`08e` |
| Trace/审计 | Trace 会话列表+详情事件流、接口操作日志(审计) | `09a` `09b_trace_detail.png` `09c_audit.png` |

### 未通过项（4）→ 关联 BUG
| 用例 | 实际 | 预期 | 关联 BUG |
|---|---|---|---|
| STORE-05b 上传 .doc | 200 落盘成功 | 422 拒绝并提示转 .docx（FEATURES P2-2） | **BUG-09** |
| MCP-01a 直连 /mcp/servers | BFF 401 JSON 页，SPA 未渲染 | SPA fallback 渲染 MCP 页 | **BUG-10** |
| LLM 带 key 节点探测（伪鉴权） | 探测请求无 Authorization，ok=false | 发出 Authorization 且 ok=true | **BUG-11** |
| Agent 绑真实带 key LLM 对话 | 502 AuthenticationError 401 | 200（端点 key 有效时） | **BUG-11**（连带） |

> 截图均在 `03-testing/screenshots/`；BUG 复现截图：`03c_doc_rejected.png`、`MCP_repro_direct.png`、`dep_verify_bug11.png`。

---

## 3. `## 接口/依赖验证`（DEP_VERIFICATION.md 摘要）

按 QA_STANDARD 第一条（测试侧复跑"真实/伪鉴权"）+ §四伪鉴权模板：

### 通过项（3）
| 项 | 结果 | 证据 |
|---|---|---|
| B 无 key 节点探测：无 Authorization、ok=false | PASS（行为正确区分） | `05-temp/s21_dep_result.json` `B_received_requests.has_auth=false` |
| C 真实 LLM 401 判定路径 | PASS（结构化 `ok=false "unavailable: HTTP 401"`）；key 当前持续 401 为**环境态**（OBS-02，需用户端点侧核查） | `05-temp/s21_dep_result.json` |
| D 真实 embedding（34.64.61.208:4000 gte-qwen2 dim=3584） | PASS（`ok=true dim=3584`） | `05-temp/s21_dep_result.json` |

### 未通过项（1）
| 项 | 结果 | 关联 BUG |
|---|---|---|
| A 带 key 节点探测应发出 Authorization 且 ok | **FAIL**：伪鉴权服务捕获 `has_auth=false`（未发凭据） | **BUG-11** |

> 截图：`03-testing/screenshots/dep_verify_bug11.png`；脚本/输出：`05-temp/s21_dep_verify.py` / `s21_dep_result.json` / `s21_bug11_proof.out`。

---

## 4. 新发现 BUG（详见 BUGS.md）
| 编号 | 严重度 | 标题 | 阻塞验收 |
|---|---|---|---|
| **BUG-11** | **P1** | LLM 节点已配 api_key，但探测 + agent 运行时均不发送 Authorization（`get_endpoint` 脱敏 pop `api_key_enc`）；BUG-08 修复未生效；绑带 key 真实 LLM 的 agent 对话 502 | **是** |
| **BUG-10** | **P1** | 直连 `/mcp/servers`（刷新/分享/URL）命中 nginx `^/(api|v1|mcp)` 代理 → BFF 401 JSON，SPA 未渲染，MCP 该入口不可用 | **是** |
| **BUG-09** | P2 | 上传 `.doc`（及 `.exe`/`.xls` 等）未 422 拒绝，200 落盘；后端格式白名单完全未校验 | 是 |

## 5. 观察项（非缺陷）
- **OBS-01**：BFF 用户级 QPS=10 对管理台连续操作偏敏感（连续点「新建 Agent」3-4 次即 429）；功能正确，建议默认值/豁免调整。
- **OBS-02**：真实 LLM 端点 34.121.9.233:4000 的 key 当前**持续 401**（与 S20 时"间歇 401/200"不同，疑似失效）——需用户在端点侧核查；与 BUG-11 叠加导致无法从平台侧单独判定。

## 6. 结论与后续
- **S21 判定：FAIL（阻塞）**。浏览器 + 接口双层按新 QA 标准执行完毕，3 个新 BUG（2 P1 + 1 P2）未关闭，不满足 QA_STANDARD §三"BUGS.md 中 P0/P1 全部关闭"。
- **下一步（需开发 S22）**：修复 BUG-11（凭据发送，最高优先，含 agent 运行时）、BUG-10（nginx/路由）、BUG-09（格式校验）；修复后 S23 回归（含 QA_STANDARD §四伪鉴权复验 + 浏览器复测 + 截图）。
- **用户需配合**：核查真实 LLM 端点 key（OBS-02），以便 BUG-11 修复后做"带 key 真实 LLM 对话 200"的完整端到端验证。

## 7. QA 证据清单（供验收抽查）
- 浏览器测试报告：`03-testing/BROWSER_TEST.md`
- 截图（56 张）：`03-testing/screenshots/*.png`（含 `dep_verify_bug11.png`、`MCP_repro_direct.png`、`03c_doc_rejected.png`）
- 依赖/伪鉴权验证：`03-testing/DEP_VERIFICATION.md` + `05-temp/s21_dep_verify.py` / `s21_dep_result.json` / `s21_bug11_proof.py` / `s21_bug11_proof.out` / `s21_bug12_check.py`
- BUG 明细：`03-testing/BUGS.md`（BUG-09/10/11，含复现步骤/根因/修复建议）
