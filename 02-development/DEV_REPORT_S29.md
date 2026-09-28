# DEV_REPORT S29 — 修复 BUG-16/17/18 + 自测证据

- 任务卡：t_24b08308（S29，zhangbeihai）
- 上游：S27 全量浏览器测试发现 3 个真实产品 BUG，S28（t_4b6efa6d，褚岩）独立复核定因全部成立，整轮 FAIL 打回
- 事实源：`03-testing/ACCEPTANCE_S28.md`、`03-testing/BUGS.md`（BUG-16/17/18 段）、`03-testing/QA_STANDARD.md`
- 本轮范围：**只修这 3 个 BUG 相关代码 + 证据/报告文件**，不做无关重构；**不 push**（终审后随 S30 轮一次推）

## 一、修改文件清单

| BUG | 文件 | 改动 |
|---|---|---|
| BUG-16 | `frontend/src/views/agents/ChatView.vue` | `finalize()` 补 `ai.content = acc.content`（块式路径回写），不破坏 SSE/onError 路径 |
| BUG-17 | `services/api/app/routers/skills.py` | `upload_skill` 的 `name: str = Form(...)` 改为 `name: str \| None = Form(None)`（必填→可选） |
| BUG-17 | `services/shared/joker_shared/skills/service.py` | `upload_skill` 签名 `name: str` → `name: str \| None`；未提供时默认取首文件名去扩展名 |
| BUG-18 | `services/api/app/routers/iam.py` | `create_user`/`update_user` 空串 email 归一化为 `NULL` |
| BUG-18 | `services/shared/joker_shared/seed.py` | 新增 `_normalize_empty_emails()`（启动幂等归一化既有 `''`→`NULL`），`seed_all()` 调用 |
| BUG-18 | `frontend/src/views/base/UsersView.vue` | 创建用户时空邮箱不传 `email` 字段（后端归一化双保险） |
| 文档 | `02-development/API_NOTES.md` | 同步 3 处接口契约（skills/upload、users POST/PUT） |
| 部署 | `deploy/docker-compose.yml` | 镜像标签 s25→s29（api/bff/webconsole 重建） |

## 二、逐 BUG 根因 / 改动 / 复验

### BUG-16（P1）Agent 默认块式对话模式 AI 气泡恒空
- **根因**：`ChatView.vue` 块式路径 `:148 acc.content = d.reply`，但 `finalize()` 只拷贝 `tool_calls/citations/sessionId`，**从未 `ai.content = acc.content`** → 气泡内容永远为空。SSE 路径 `onDelta` 直写 `ai.content` 故正常。后端返回完全正常（200 + `reply:"pong"`）。
- **改动**：`finalize()` 增加 `if (acc.content && !ai.content) ai.content = acc.content`。
  - 块式：`acc.content` 非空、`ai.content` 为空 → 回写 ✅
  - SSE：`onDelta` 已直写 `ai.content`（非空）→ 不覆盖（`!ai.content` 为 false）✅
  - onError：已先写 `ai.content='⚠️ ...'`（非空）、`acc.content` 为空 → 不覆盖错误提示 ✅
- **复验（Playwright 真实表单登录 + 默认块式模式真实 LLM 34.121.9.233）**：
  - 证据：`05-temp/s29/s29_bug16_results.jsonl`（7 条全 PASS）、`05-temp/s29/s29_bug16_run.log`
  - **核心判定 = AI 气泡 `textContent` 非空**（非 API 200）：块式 turn1 气泡渲染 `pong`、turn2 渲染 `pong 2`（同会话续接 `sameSession=true`）
  - SSE 对照无回归：勾选 SSE 后 turn3 正常渲染真实回复
  - 截图：`03-testing/screenshots/s29/s29bug16_043629_04_block_turn1.png`（块式 pong，SSE 未勾选）、`_05_block_turn2.png`（多轮）、`_06_sse_control.png`（SSE 对照）

### BUG-17（P2）Skill 文件上传 100% 422
- **根因**：`api/skills.js uploadSkill(files)` 只 `fd.append('files', f)`，后端 `POST /api/skills/upload` 要求必填 Form 字段 `name: str = Form(...)` → 100% 422 `name: Field required`。
- **决策（DECISION）**：采用**后端 `name` 改可选 + 缺省默认取首文件名去扩展名**（而非前端补 name）。理由：① 上传契约对所有客户端更友好（非仅本前端）；② 与内联创建 `name` 语义一致（skill 名 = 入口文件名）；③ OpenAPI 自动同步；④ 前端 `el-upload` 每次 `before-upload` 单文件触发，"取首文件"即当前文件，前端零改动即修好。
- **改动**：`skills.py` `name: str | None = Form(None)`；`service.py` `name` 可选，空时 `files[0].rsplit('.',1)[0]` 兜底，仍空→422。
- **复验（真实 HTTP，经 webconsole:8080→BFF→API）**：
  - 证据：`03-testing/dev_probe_s29_bug17_skills_upload.log`
  - A) 单文件不传 name → **201**，`name='s29bug17_a_…'`（首文件名去扩展名，正确落库，读回确认 `source=upload`、`content` 同步）
  - B) 多文件不传 name → **201**，`file_count=2`、`files=[main.md, asset.json]`
  - C) 显式 name → **201**，`name=显式值`
  - D) 重复 name → **409** `skill name already exists: …`（冲突行为明确记录）

### BUG-18（P2）不填邮箱新建用户恒 409
- **根因**：`UsersView.vue:107` 表单初始 `email:''` 原样提交（含 `email:""`），唯一约束 `uq_users_tenant_email UNIQUE(tenant_id,email)`（PG 下空串互撞、NULL 互不撞）→ 任何新用户名都 409。既有 1 个用户 email 为空串脏数据。
- **决策**：后端空串 email 归一化为 NULL（create/update）+ 前端空邮箱不传字段 + **既有空串 email 一次性归一化（幂等可重跑）**。
- **改动**：`iam.py` create/update `email=''`→`None`；`seed.py` `_normalize_empty_emails()`（启动幂等 `UPDATE users SET email=NULL WHERE email=''`）；`UsersView.vue` 创建时空邮箱 `delete body.email`。
- **复验（接口层真实 HTTP）**：
  - 证据：`03-testing/dev_probe_s29_bug18_users.log`
  - A) `email=''` → **201**（读回 `email=null`，归一化落库）
  - B) 不传 email → **201**（读回 `email=null`）
  - C) 唯一 email → **201**
  - D) 重复 email → **409** `username or email already exists`
  - E) 既有空串归一化：`joker-api` 启动日志铁证 `BUG-18 normalize: 1 users with empty-string email set to NULL`；psql 核对 `email=''` 行数 1→0、`email IS NULL` 行数 28
  - F) 幂等可重跑：重执行归一化语句 → `UPDATE 0`（no-op）
  - G) `PUT email=''` → **200**，读回 `email=null`（update 归一化）

## 三、自测证据汇总（QA_STANDARD 第 1 层）

| 证据文件 | 内容 | 结果 |
|---|---|---|
| `03-testing/dev_probe_s29_bug18_users.log` | BUG-18 接口层 A-G 真实 HTTP | 全 PASS |
| `03-testing/dev_probe_s29_bug17_skills_upload.log` | BUG-17 接口层 A-D + 读回真实 HTTP | 全 PASS |
| `05-temp/s29/s29_bug16_results.jsonl` | BUG-16 Playwright 7 条（真实表单登录+真实 LLM） | 7/7 PASS |
| `05-temp/s29/s29_bug16_run.log` | BUG-16 运行日志 | 7 PASS 0 FAIL |
| `03-testing/screenshots/s29/s29bug16_043629_04_block_turn1.png` | 块式模式 AI 气泡渲染 pong（SSE 未勾选） | vision 独立核验确认 |
| `03-testing/screenshots/s29/s29bug16_043629_00_login_form.png` | 真实表单登录铁证（租户/用户名/密码已填） | vision 独立核验确认 |

## 四、外部依赖真实性（禁 mock）
- BUG-16 对话走**真实 LLM** `34.121.9.233:4000/v1`（`platform-fallback-llm`）：块式 `ping`→`pong`、多轮 `ping 2`→`pong 2`、SSE `ping 3`→真实回复。非 mock 冒充。
- BUG-17/18 走本地 compose 服务（webconsole:8080→BFF→API→PG），真实 HTTP 状态码 + 落库读回。

## 五、防造假规则遵守
1. 浏览器自测真实表单登录（fill 租户/用户名/密码 → click 登录 → 等 URL 变化），无 in-page fetch、无 localStorage 注入、无 goto 受保护页。
2. BUG-16 核对 UI 气泡 `textContent` 渲染结果，API 200 不算通过。
3. 每个 PASS 有落盘证据（log/截图），无"已通过"空口。
4. 临时脚本/诊断一律放 `05-temp/s29/`（不入 git）。
5. 只改这 3 个 BUG 相关代码 + 证据/报告，无无关重构。

## 六、部署
- 镜像重建：`agent-joker-api:s29`、`agent-joker-bff:s29`、`agent-joker-webconsole:s29`（api 含后端 BUG-17/18 修复，webconsole 含前端 BUG-16/18 修复）。
- 容器：api/bff/webconsole 重建后全 healthy；`http://localhost:8080/healthz`=200、`http://localhost:8000/healthz`=200。
- 启动归一化日志确认 `_normalize_empty_emails` 生效（1 行 `''`→NULL）。
- 启动命令：`cd deploy && docker compose up -d`（s29 镜像）。

## 七、已知问题 / 说明
- 本轮不测试整轮（S30 云天明负责 UI 复测 + 历史回归 + 防造假自查）。
- 本轮不 push（终审后随 S30 轮一次推）。
- 无已知遗留问题：3 个 BUG 均已修复并通过接口层/浏览器层双层自测。
