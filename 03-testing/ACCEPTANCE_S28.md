# S28 — 全量重测验收报告（防造假核查 + 证据交叉 + 处置）

- **验收人**：褚岩（chuyan），任务卡 t_4b6efa6d
- **日期**：2026-09-28（CST）
- **验收对象**：S26（章北海，环境基线+全模块自测，t_c390a1b6）+ S27（云天明，全量浏览器测试，t_159f9f4b）
- **标准**：`03-testing/QA_STANDARD.md` 第 3 层（验收）
- **整轮判定**：## **FAIL — 打回修复（验收不通过，不 push，不交付）**

> 判定依据：QA_STANDARD §三第 2 项「BUGS.md 中 P0/P1 全部关闭」不满足 —— S27 新发现
> **BUG-16（P1，未闭环）** + BUG-17/18（P2，未闭环）。防造假核查全部通过（测试本身无造假），
> 但**测试发现 3 个真实产品缺陷未修复**，按标准不得放行验收。

---

## 一、防造假核查（本轮核心）— 3/3 PASS，测试无造假

### 1.1 脚本源码 grep（任务卡指定命令）

对 S27 全部浏览器脚本执行
`grep -n "fetch(|localStorage" 05-temp/s27/*.js 03-testing/e2e/*.js`（ripgrep 等价）：

| 检查项 | 结果 |
|---|---|
| in-page `fetch(` 登录 | **零命中**（05-temp/s27 14 个 .js + 03-testing/e2e 14 个 .js，共 28 个脚本） |
| `localStorage.setItem` / `localStorage[...]` 注入 | **零命中** |
| 直接 goto 受保护页绕过登录 | **不成立**（见 1.2 逐条判读） |

**`page.goto` 命中逐条判读（24 处，全部合规）**：
- `03-testing/e2e/s27_lib.js:38` → `page.goto(BASE + '/login')`：唯一登录入口，goto 的是**登录页本身**，随后 fill 租户/用户名/密码 → `click('button:has-text("登录")')` → `waitForResponse(/api/auth/login)` + `waitForURL(/users)`（s27_lib.js:37-67，真实表单全链路）。
- 其余 23 处 `page.goto('/users'|'/agents'|'/skills'|…)` **全部发生在 `realFormLogin()` 成功之后**（各模块脚本第 16-25 行先登录、第 56-113 行才 goto），属登录后的站内路由跳转（等价点侧边栏），非绕过登录。S27 报告 §五.3 已预澄清此语境，逐条核对与澄清一致。
- 复测脚本 `retest_ui.js`/`retest_chat.js` 登录实现逐行核验（retest_chat.js:25-34 / retest_ui.js:38-53）：`fill('input[placeholder="如 acme"]','acme')` + `fill('input[placeholder="admin"]','admin')` + `fill('input[type="password"]','123456')` + `click('button:has-text("登")')` + `waitForURL(!/login/)`，与报告 §五.2 声明完全一致。
- API 状态码采集方式为 `page.on('response')` **只读旁路观测**，不替代 UI 操作 —— 合规。

**结论：S27 无 fetch 登录、无 localStorage 注入、无 goto 绕登录。防造假规则零违反。**

### 1.2 截图抽查（5 张，画面内容与报告操作步骤逐一核对）

| 截图 | 文件时间戳 | 画面核验（vision 独立判读） | 与报告对应 |
|---|---|---|---|
| `acme_admin_login_form.png` | 09-28 11:02 | agent-joker WebConsole 登录页；三输入框已填 租户=`acme` / 用户名=`admin` / 密码=6 位掩码；蓝色「登录」按钮 | BASE-04b 登录表单，**真实表单铁证** ✅ |
| `s27chat_033818_06_chat_turn1.png` | 09-28 11:38 | 对话页：用户气泡 `ping`；**AI 气泡空白 + loading 三点动画**；会话 `s27_chat_033818`；SSE 流式未勾选（默认块式） | BUG-16 P1 铁证：默认模式气泡恒空 ✅ |
| `s27chat_034533_06_chat_turn1_sse.png` | 09-28 11:46 | 同一 agent/LLM，SSE 流式**已勾选**：用户气泡 `ping`，AI 气泡渲染 **`pong`**，会话 `s27_chat_034533` | SSE 对照组正常 → 缺陷定位前端块式路径 ✅ |
| `s27retest_032214_04_user_result_qa_s27retest_032214.png` | 09-28 11:22 | 用户管理页：红色错误 toast **`username or email already exists`**（409 语义）；对话框填用户名 `qa_s27retest_032214`、邮箱空；列表无新增行 | BUG-18 铁证 ✅ |
| `s27retest_032214_05_skill_upload_s27_retest_skill_111712.png` | 09-28 11:22 | Skills 页：红色错误 toast **`[{"type":"missing","loc":["body","name"],"msg":"Field required",...}]`**（422 校验报文）；6 行 skill 无新增 | BUG-17 铁证 ✅ |

时间戳 11:00-11:46 与 `retest_results.jsonl` 对应 run 的 UTC ts（03:22-03:46Z = CST 11:22-11:46）吻合；`results.jsonl` 112 条 ts 范围 02:01-03:02Z 与全量截图 mtime（10:01-11:02）吻合。截图数 167 张与报告声明一致。

### 1.3 S26 自测证据核对（真实端点，禁 mock）

`03-testing/dev_probe_s26_llm.log`（逐行读）：
- 真实 LLM 探测：`POST /api/llm/endpoints/<platform-fallback-llm>/test` → **200, 613ms, `{"ok":true,"summary":"ok: model=vllm-qwen3.8-27b responded in 613ms"}`**，端点 `base_url=http://34.121.9.233:4000/v1`（真实端点原始响应，非 mock）✅
- 真实 embedding：`POST /api/llm/embeddings/<gte-qwen2>/test` → **200, 330ms, `{"ok":true,"summary":"ok: model=gte-qwen2 dim=3584 in 330ms"}`**，端点 `http://34.64.61.208:4000/v1`（真实端点原始响应）✅
- 9 模块 10 份 `dev_probe_s26_*.log` 全在盘（auth/baseline/iam/storage/llm/rag/mcp/skills/agents/bff_trace），98/98 声明与 DEV_REPORT_S26 一致。
- **S27 侧真实 LLM 复核**（`probe_real_llm_run3.log`，09-28 11:15）：探测 1075ms ok=true + 真实 agent 对话 `ping→pong`(915ms) / `说你好→你好`(436ms) / `1+1→1+1 等于 **2**`(578ms) 全 200 非空 —— 后端链路正常，排除"LLM 没回"假设，空回复纯前端 BUG-16。
- 全 log 中未发现 mock 响应冒充真实端点响应（mock 端点均以 `joker-mock-llm-*` 命名且仅作功能逻辑验证，未用于连通性/鉴权验证）。

**S26 证据核查：PASS，无造假。**

---

## 二、3 个 FAIL 的源码定因复核（不采信自报，独立读源）

| BUG | 报告定因 | 独立复核（源码） | 结论 |
|---|---|---|---|
| BUG-16 (P1) | `ChatView.vue` 块式路径 `finalize()` 未拷贝 `ai.content = acc.content` | `frontend/src/views/agents/ChatView.vue:140-172` 逐行读：块式分支 :148 `acc.content = d.reply`，:165-172 `finalize()` 仅拷贝 `tool_calls/citations/sessionId`，**确无 `ai.content = acc.content`**；SSE 路径 :130 `onDelta` 直写 `ai.content`（故 SSE 正常） | 定因成立 ✅ |
| BUG-17 (P2) | `api/skills.js` 上传缺 `name` Form 字段 vs 后端必填 | `frontend/src/api/skills.js:9-13` `uploadSkill` 只 `fd.append('files', f)` 无 `name`；`services/api/app/routers/skills.py:72-79` `name: str = Form(...)` 必填 —— 前后端契约确不匹配 | 定因成立 ✅ |
| BUG-18 (P2) | `UsersView.vue` 表单初始 `email:''` 原样提交 → 空串撞唯一约束 | `frontend/src/views/base/UsersView.vue:107` `form = ref({… email: '' …})` 属实（:142 openCreate 同）；接口层 A/B/C/D 对照（`diag_root_cause.py`）纯 `email=""` 触发 409 已验证 | 定因成立 ✅ |

3 个 BUG 均为真实产品缺陷，定因准确，无 harness 时序误判（复测均用全新唯一用户名/文件名）。

---

## 三、证据清单交叉核对（QA_STANDARD §三）

| 核对项 | 要求 | 实际 | 判定 |
|---|---|---|---|
| 开发自测证据覆盖全部新增/修改接口 | S26 | 10 份 dev_probe 日志 + DEV_REPORT_S26，9 模块 98/98（真实端点） | ✅ |
| 浏览器测试报告存在且有截图佐证 | S27 | TEST_REPORT_S27.md（203 行）+ 167 张截图 + results.jsonl 112 条 + retest_results.jsonl 42 条 | ✅ |
| 外部依赖有真实/伪鉴权验证 | S26+S27 | 真实 LLM 34.121.9.233 + 真实 embedding 34.64.61.208 原始响应（§1.3） | ✅ |
| **BUGS.md 中 P0/P1 全部关闭** | — | **BUG-16（P1）未闭环**；BUG-17/18（P2）未闭环 | ❌ **不满足** |
| 模块覆盖完整性 | 全模块 | S26 接口层 9 模块 + S27 浏览器层 8 模块（BASE/STORE/LLM/RAG/MCP/Skills/Agent/Trace）+ 登录登出/权限/边界路径；BUG-15 回归 PASS（nginx 变量式 proxy_pass 已在 `deploy/nginx/nginx.conf:56-57` 确认） | ✅ |

**证据交叉结论：测试工作质量与覆盖合格（45 PASS 项有效），但「P0/P1 全关闭」项不满足 → 按 QA_STANDARD §三第 3 项：验收打回，不得标记交付。**

> 附注（retest 记录瑕疵，不影响产品判定）：SSE 对照 run（s27chat_034533）中 AGENT-02a/02b 记录 `pass:false, api:[]` —— 因 SSE 流式响应不产生完整 `/api/` POST response 事件，net 数组为空，属**脚本断言口径瑕疵**；UI 侧 `reply1=["pong"]` + 多轮完整回复 + 截图证明 SSE 路径渲染正常。此瑕疵仅影响该两条记录的 pass 标记，不改变「SSE 正常 / 块式不渲染」的产品结论。

---

## 四、push 决策

**本轮不 push main。**
- 任务规则「通过项 push main」——本轮整轮判定 FAIL（P1 未闭环），且 S26 修复（BUG-15 nginx / BUG-13 / BUG-14，本地 commit `23f8d41`/`07866bf`，远端 origin/main 停在 `e303f02`）需连同 S29 的 BUG-16/17/18 修复一起形成完整修复轮后再推，避免远端出现「含 P1 缺陷的中间态」。
- S27 证据（TEST_REPORT_S27.md / dev_probe_s26_*.log / BUGS.md 追加 / 167 截图）已本地 commit（见下方 commit hash），随 S29 修复轮一并推送。
- 05-temp 诊断脚本按规则不入库（.gitignore `05-temp/` 已排除）。

**S28 本地 commit（证据落档，未推远端）**：见交付报告 metadata（ACCEPTANCE_S28.md + PIPELINE/STATUS/RISKS/DECISIONS 更新 + S27 测试证据）。

---

## 五、遗留问题清单（交用户 + 下一轮）

| # | 级别 | 问题 | 处置 |
|---|---|---|---|
| 1 | **P1** | **用户生产 LLM key 已在聊天中多次明文暴露，需轮换 vLLM（34.121.9.233:4000）API key**。轮换后需同步更新本地 `.env`/DB 中 `platform-fallback-llm` 端点 key（API 侧 Fernet 加密存储，改 key 走 UI 编辑端点即可） | **用户操作**：到 vLLM 服务端换 `--api-key`；换完告知，S30 回归前更新平台端点配置 |
| 2 | P1 | BUG-16 默认对话模式气泡恒空 | S29 修复（zhangbeihai） |
| 3 | P2 | BUG-17 Skill 上传 422 | S29 修复（zhangbeihai） |
| 4 | P2 | BUG-18 不填邮箱建用户 409（含既有 10 个空串 email 脏数据迁移） | S29 修复（zhangbeihai） |
| 5 | 环境态 | OBS-02 真实 LLM 间歇 401 历史（本轮未复现） | 与 #1 联动：轮换 key 后若再 401 属端点 worker 配置 |
| 6 | P3 | OBS-01 限流 QPS 敏感 | 生产按实际 QPS 调 `RATE_LIMIT_*`（不阻断） |

## 六、编排动作

- 已建 **S29**（zhangbeihai）：修复 BUG-16/17/18 + 自测证据（防造假硬规则随卡）。
- 已建 **S30**（yuntianming，parent=S29）：3 BUG UI 复测 + 历史回归 + 防造假自查，出 TEST_REPORT_S30。
- S30 PASS 后回我终审（推远端 = S26 修复 + S29 修复 + 全部证据一次推送）。

**S28 判定：FAIL（打回修复）。** 防造假核查通过（测试无造假）；验收不通过原因 = 3 个真实产品 BUG 未修复（1 P1 + 2 P2），证据真实有效、定因准确、模块覆盖完整。
