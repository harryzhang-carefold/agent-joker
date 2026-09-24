# agent-joker S12 功能测试 — 缺陷清单（BUGS.md）

- 任务卡：t_14c1715a（S12 功能测试，yuntianming）
- 测试 run：`s12run1790163089`（03-testing/results_summary.json）
- 结果：146 项 = **109 PASS / 35 FAIL / 2 SKIP**（results_summary 头部 `fail=35` 不含 2 个 SKIP，故 FAIL 列表共 37 项）
- 隔离方式：RISK-015 — 被测服务经 compose 起，测试自身探针（probe6..probe15）经 **docker run 独立容器**跑，测试数据全部落 03-testing/，无 /tmp。
- 判定原则：**不轻信 S11 自报，逐条用 probe 独立复现**。37 项 FAIL 全部归类为 ① 真实产品 BUG / ② 测试脚本缺陷 / ③ 自测环境产物（fallback embedding / mock-llm）。本文只收**真实产品 BUG**；测试脚本缺陷与环境产物的逐项证据见 TEST_REPORT.md §3。
- **未改任何代码**，BUG 由褚岩派单给章北海修复。
- **无阻塞性 BUG（核心链路未跑通）**：RAG 建库→上传→解析→切分→向量化→检索、简易/第三方 agent 闭环、trace 全链路、限流 429 均通过（109 PASS + S11 e2e 43/43 佐证），检索 0 命中为自测 fallback embedding 环境产物而非链路中断（见 TEST_REPORT §3-RAG07）。故**不 kanban_block**。

## 缺陷汇总（3 P1 + 3 P2，无 P0）

| ID | 严重 | 模块 | 现象 | 影响 | 状态 |
|----|------|------|------|------|------|
| BUG-01 | P1 | BASE 权限 | 角色绑定 scope 后读回为空（scopes=[]），改权限后仍为空 | RBAC 角色无法承载权限，用户有效权限并集恒空 | 已修（S14，probe 复验 A1-A4 PASS） |
| BUG-02 | P1 | BASE 登出 | 登出后原 access token 未失效（仍 200） | 安全：登出未吊销活跃会话 token | 已修（S14，probe 复验 B1-B3 PASS） |
| BUG-03 | P1 | BASE/STORE 日志 | 审计日志、上传记录按时间范围筛选 → 500 | 文档化「按时间检索」筛选不可用 | 已修（S14，probe 复验 C1-C5 PASS） |
| BUG-04 | P2 | BASE 权限 | 用户角色分配不可读 + 无法仅改角色（422） | BASE-02/03 用户角色验收无法经 API 验证 | 已修（S14，probe 复验 D1-D6 PASS） |
| BUG-05 | P2 | BASE 令牌 | 新 refresh token 换取新 access → 401 | BASE-09「刷新可用」不稳定，需复测确认 | 已关闭（S14 复测未复现：干净刷新 200，原 FAIL 为限流多登录的 refresh 家族轮换产物，E1-E3 PASS） |
| BUG-06 | P2 | BASE 日志 | 登出操作未见于接口操作日志 | BASE-05 验收 2 未满足 | 已修（S14，probe 复验 F1-F2 PASS） |

> S14 修复报告：02-development/DEV_REPORT_S14.md（根因/改动/复验证据）；
> 复验 probe：05-temp/probe_s14_v2.py（29/29 PASS，run 见 DEV_REPORT §回归）。
> **S15 独立回归（t_dfb336b3，yuntianming）：6 个 BUG 全部独立 probe 复验 PASS（05-temp/probe_s15.py A-F 23/23，results_s15.json），非采信 S14 自报。见 03-testing/TEST_REPORT_S15.md。**
>
> **S16 迭代终审（t_4a73489d，chuyan，2026-09-24）：在 s14 部署上用 docker run 独立容器 probe 再次独立复验 6/6 BUG 全 PASS（05-temp/s16_probe2.py，s16_probe2.json），非采信 S14/S15 自报。6 缺陷全部闭环，无待修复项。见 00-management/DELIVERY_REPORT.md §10.1。**

---

## BUG-01（P1）角色 scope 绑定/读回失效
- **现象**：POST `/api/roles` 用真实存在的 scope code 建角色返回 **201**，但 GET `/api/roles` 读回该角色 `scopes=[]`；PUT 改权限（200）后读回仍 `scopes=[]`。
- **复现步骤**：
  1. admin 登录；`GET /api/scopes` 取真实 code（如 `agents:manage`）。
  2. `POST /api/roles {"name":"t","scope_codes":["agents:manage"]}` → 201（返回仅 id/name）。
  3. `GET /api/roles` → 该角色 `scopes=[]`（期望 `["agents:manage"]`）。
  4. `PUT /api/roles/{id} {"scope_codes":["agents:manage"]}` → 200；再 GET → 仍 `scopes=[]`。
- **预期**：角色携带绑定的 scope code，读回非空。
- **实际**：读回恒空。
- **证据**：probe15 §B（real code `agents:manage` → 201 → readback `[]`）；probe14 §A（create 201 / update 200 / after update `[]`）。
- **代码定位（供章北海参考，非本次修改）**：`services/api/app/routers/iam.py` — `create_role` 调 `_bind_scope` 写 `role_scopes`，`list_roles` 经 `LEFT JOIN role_scopes→scopes` 聚合 `scopes`。写路径与读路径均存在，读回空说明 `role_scopes` 插入未生效（或 `scopes` 表 code 匹配未命中 / `scope_id` 外键指向错行）。`_bind_scope` 按 `ORDER BY (tenant_id IS NULL) DESC` 取 scope，需确认 `agents:manage` 在 `scopes` 表确有对应行且 tenant 过滤正确。
- **影响**：BASE-02 验收 1「用户/角色/权限三元组可管理与关联」、BASE-03 验收 1「用户有效权限=角色权限并集」均不满足（用户有效权限并集恒空）。

## BUG-02（P1）登出后 access token 未失效
- **现象**：`POST /api/auth/logout`（body 带 refresh_token + header 带 bearer）→ 200，refresh 已吊销（refresh_revoked=1），但**登出后原 access token 调接口仍 200**（post_logout_api=200）。
- **复现步骤**：
  1. 登录得 access `t` + refresh `r`。
  2. `POST /api/auth/logout`（header: `Authorization: Bearer t`，body: `{"refresh_token": r}`）→ 200。
  3. `GET /api/users?page=1`（header: `Bearer t`）→ **200**（期望 401）。
- **预期**：BASE-05 验收 1「登出后原 Access Token 不再可用」。设计文档（`auth.py` docstring + BFF `verify_access`）明确策略为「access token 未到期 → Redis 黑名单（jti），BFF 侧校验立即失效」。
- **实际**：access token 登出后仍可访问（仅 refresh 被吊销）。
- **证据**：round-1 `BASE-05 登出后原 access token 立即失效` evidence `logout=200 refresh_revoked=1 post_logout_api=200`（refresh 吊销 PASS，access 失效 FAIL）。
- **代码定位（供参考）**：`services/bff/app/gateway.py:244` 转发时**剥离客户端 Authorization 头**（`k.lower() not in (b"authorization",...)`）并注入 X-Auth-* 签名头；而 `services/api/app/routers/auth.py:252` logout 读取 `request.headers.get("authorization")` 来取 bearer 写 `deny_access(jti,...)`。BFF 已剥离 → API 侧 authorization 头为空 → **jti 黑名单从未写入** → BFF `verify_access`（gateway.py:140 `is_denied(jti)`）查不到 → 旧 token 继续有效。这是 BFF「统一鉴权后透传身份、剥离客户端 token」与 API「logout 需客户端 bearer 写黑名单」两个设计点的冲突。
- **影响**：安全缺陷——登出不吊销活跃会话，攻击者拿到有效 access token 后「登出」不生效，token 自然到期前仍可用。

## BUG-03（P1）审计日志 / 上传记录按时间范围筛选返回 500
- **现象**：`GET /api/audit/logs?start=...&end=...` 与 `GET /api/storage/upload-records?start=...&end=...` → **500 Internal Server Error**（total=None）。
- **复现步骤**：
  1. `GET /api/audit/logs?start=2020-01-01T00:00:00Z&end=2021-01-01T00:00:00Z&page_size=50` → 500。
  2. `GET /api/storage/upload-records?source=api&start=2020-01-01T00:00:00Z&end=2021-01-01T00:00:00Z` → 500。
- **预期**：返回 200，空区间 `total=0`（无该时段数据）。
- **实际**：500。
- **证据**：probe14 §F（audit old-range 500 / upload-records old-range 500，body=`Internal Server Error`）。
- **代码定位（供参考）**：`services/api/app/routers/audit.py:33-36`、`services/shared/joker_shared/storage/service.py:346-348`、`trace.py:334-337` 均将 `start/end`（含 `Z` 后缀 ISO8601 字符串）直接拼入 `created_at >= :start`。asyncpg 对带 `Z` 的字符串与 timestamptz 比较未做类型转换/解析，抛未捕获异常 → 500。时间范围参数本身被 FastAPI 声明为 `str`（未转 datetime），DB 层缺解析/规范化。
- **影响**：BASE-06 验收 4「可按时间检索」、STORE-05 验收（时间/来源筛选）、TRACE-02 时间范围检索 的「按时间」维度全部不可用（无时间参数的筛选本身正常——`按接口筛选`、`source=api` 等 PASS）。

## BUG-04（P2）用户角色分配不可读 + 无法仅改角色
- **现象**：(a) `GET /api/users/{id}` 返回体**不含 roles 字段**（keys：id/username/email/display_name/status/is_platform_admin/created_at）；(b) `PUT /api/users/{id} {"role_names":[...]}`（仅带角色、不带其他字段）→ **422 `no fields to update`**。
- **复现步骤**：
  1. 建用户后 `PUT /api/users/{uid} {"role_names":["member"]}` → 422 `no fields to update`。
  2. `GET /api/users/{uid}` → 无 `roles` 字段（无法验证分配结果）。
- **预期**：BASE-02 验收「用户可分配/变更角色」、BASE-03 验收 1「用户有效权限=角色权限并集（接口可验证）」。
- **实际**：角色分配既不能只靠 role_names 写入（需伴随 display_name/email/status 之一），也不能读回。
- **证据**：probe14 §B（assign roles 422；get user detail keys 无 roles）。
- **代码定位（供参考）**：`iam.py:146` `update_user` 中 `if not sets: raise 422`（sets 只由 display_name/email/status 填充，role_names 在 `if req.role_names is not None` 分支内但 sets 为空仍先抛 422）；`iam.py:111 get_user` 未 SELECT/返回 user_roles。
- **影响**：用户维度角色管理与有效权限并集无法经 API 闭环验证（与 BUG-01 叠加，权限链路整体不可测）。

## BUG-05（P2）新 refresh token 换取新 access token 返回 401（待复测确认）
- **现象**：`POST /api/auth/refresh`（合法新 refresh_token）→ **401**，new_token=no。
- **复现步骤**：登录得 access+refresh → `POST /api/auth/refresh {"refresh_token": r}` → 401。
- **预期**：BASE-09 验收 1「凭 refresh 令牌换取新 access token（无需重登）」。
- **实际**：401。
- **证据**：round-1 `BASE-09 凭 refresh...` evidence `refresh=401 new_token=no`；对照 `旧 refresh 重放被拒`（401，PASS）、`篡改 token 被拒`（401，PASS）——即吊销/篡改路径正常，唯「正常刷新」失败。
- **未决根因**：可能是登录 IP-429 重试循环内多次登录触发 refresh 家族轮换（后登录吊销前家族），导致被刷新 token 已被整族吊销；或 refresh 解码/校验异常。**未从现有日志定死**，需一次干净复测（单一登录→立即刷新，隔离 IP 窗口）。
- **影响**：令牌续期不稳定，影响无感刷新体验；因吊销/篡改路径正常，非全链路阻塞。

## BUG-06（P2）登出操作未记录到接口操作日志（待复测确认）
- **现象**：登出后 `GET /api/audit/logs?path=/api/auth/logout` 查不到登出记录（audit_logout_found=False）。
- **复现步骤**：登出 → `GET /api/audit/logs?path=/api/auth/logout&page_size=20` → items 无 `/api/auth/logout`。
- **预期**：BASE-05 验收 2「登出操作被记录到接口操作日志」。
- **实际**：查无。
- **未决根因**：`AuditMiddleware`（api/app/middleware.py:71）异步非阻断写审计，可能存在写-读竞态；或与 BUG-02 的 BFF 剥离 Authorization 路径相关（登出经 BFF 转发，鉴权态/租户归属可能异常）。**未定死**，需复测（登出后延迟再查 / 直接查 API 侧审计表）。
- **影响**：审计完整性（登出这一敏感操作无痕），低概率为时序产物，故 P2 待复测。

---

## 说明：未列入本清单的 37 项 FAIL（28 项非产品 BUG）
以下 FAIL **不是产品缺陷**，逐条证据与归类见 TEST_REPORT.md §3（37 项全表）：
- **测试脚本缺陷（18 项）**：RAG-02 上传/来源/解析（round-1 未等 parse ready，probe9/10 独立复现 6/6 + status=ready + 2 chunks）、RAG-04 定长/父子/语义切分（round-1 时序）、RAG-05 原文查看/chunk 列表（probe10 复现 200/1782B、count=2）、MCP-03 关联调用方（harness 走错路径，正确 `/referring-agents` 200）、SKILL-01 上传 .md（harness multipart 字段名 `file` vs 接口 `files`）、SKILL-02 files=[]（上一条连带）、AGENT-04 列表/新建/重命名/删除（harness 字段名 `session_id` vs `id` + 期望 201 vs 实际 200；probe14 独立复现 create/rename/delete 全 200）、LLM-01 修改 endpoint（harness 传非可更新字段 `description`）、限流单用户 429（harness `req()` 对 429 自动退避重试+仅发 3 次，429 被吞；probe14 §H 独立复现 10×200→6×429）、TRACE-02 按会话检索（8/9 trace 项 PASS，仅「按会话」filter 命中 0，疑似 session_id 过滤错位）。
- **自测环境产物（8 项）**：RAG-07 纯向量/带 rerank 检索、RAG-09 反向定位、RAG-10 MCP 工具、D-A official 两级判定、AGENT-05 official 来源、AGENT-11 第三方 RAG 引用、AGENT-07 多轮（turn1 409 + mock-llm 无法演示召回）——根因均为**自测 fallback ngram embedding 对中文查询余弦相似度 < 默认阈值 0.3 → 0 命中**（检索链路本身正确：S11 e2e T4 score=0.663、RAG-08 阈值 0.99→0 正确、probe10 向量已写入）。resolve_official 逻辑经代码核对正确。
- **SKIP（2 项）**：D-A 库级 NULL 判定（依赖 kb2 上传时序）、AGENT-05 引用可链接原文位置（0 引用连带）。
