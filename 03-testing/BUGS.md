# agent-joker S12 功能测试 — 缺陷清单（BUGS.md）

- 任务卡：t_14c1715a（S12 功能测试，yuntianming）
- 测试 run：`s12run1790163089`（03-testing/results_summary.json）
- 结果：146 项 = **109 PASS / 35 FAIL / 2 SKIP**（results_summary 头部 `fail=35` 不含 2 个 SKIP，故 FAIL 列表共 37 项）
- 隔离方式：RISK-015 — 被测服务经 compose 起，测试自身探针（probe6..probe15）经 **docker run 独立容器**跑，测试数据全部落 03-testing/，无 /tmp。
- 判定原则：**不轻信 S11 自报，逐条用 probe 独立复现**。37 项 FAIL 全部归类为 ① 真实产品 BUG / ② 测试脚本缺陷 / ③ 自测环境产物（fallback embedding / mock-llm）。本文只收**真实产品 BUG**；测试脚本缺陷与环境产物的逐项证据见 TEST_REPORT.md §3。
- **未改任何代码**，BUG 由褚岩派单给章北海修复。
- **无阻塞性 BUG（核心链路未跑通）**：RAG 建库→上传→解析→切分→向量化→检索、简易/第三方 agent 闭环、trace 全链路、限流 429 均通过（109 PASS + S11 e2e 43/43 佐证），检索 0 命中为自测 fallback embedding 环境产物而非链路中断（见 TEST_REPORT §3-RAG07）。故**不 kanban_block**。

## 缺陷汇总（4 P1 + 4 P2，无 P0）

| ID | 严重 | 模块 | 现象 | 影响 | 状态 |
|----|------|------|------|------|------|
| BUG-01 | P1 | BASE 权限 | 角色绑定 scope 后读回为空（scopes=[]），改权限后仍为空 | RBAC 角色无法承载权限，用户有效权限并集恒空 | 已修（S14，probe 复验 A1-A4 PASS） |
| BUG-02 | P1 | BASE 登出 | 登出后原 access token 未失效（仍 200） | 安全：登出未吊销活跃会话 token | 已修（S14，probe 复验 B1-B3 PASS） |
| BUG-03 | P1 | BASE/STORE 日志 | 审计日志、上传记录按时间范围筛选 → 500 | 文档化「按时间检索」筛选不可用 | 已修（S14，probe 复验 C1-C5 PASS） |
| BUG-04 | P2 | BASE 权限 | 用户角色分配不可读 + 无法仅改角色（422） | BASE-02/03 用户角色验收无法经 API 验证 | 已修（S14，probe 复验 D1-D6 PASS） |
| BUG-05 | P2 | BASE 令牌 | 新 refresh token 换取新 access → 401 | BASE-09「刷新可用」不稳定，需复测确认 | 已关闭（S14 复测未复现：干净刷新 200，原 FAIL 为限流多登录的 refresh 家族轮换产物，E1-E3 PASS） |
| BUG-06 | P2 | BASE 日志 | 登出操作未见于接口操作日志 | BASE-05 验收 2 未满足 | 已修（S14，probe 复验 F1-F2 PASS） |
| BUG-07 | P1 | BASE 租户管理 | admin(acme) 点「租户管理」菜单 403；平台管理员无法登录（system 租户无种子用户） | 租户管理功能不可达，非平台用户菜单无权限控制 | 已修（S17，probe 复验 A1-A9/B1-B4 13/13 PASS） |
| BUG-08 | P2 | LLM 节点（前端+环境态） | LLM 端点连通性测试 HTTP 401（端点本身通）；前端保存/测试/删除失败静默无提示 | 用户误判「平台坏了/没保存成功」；端点侧 401 为外部 vLLM 服务间歇拒绝（非代码缺陷） | 前端已修（S20，回归 8/8 PASS）；端点侧 401 为环境态，需用户在端点侧核查（见 DEV_REPORT_S20 §五） |
| BUG-09 | P2 | STORE 存储 | 上传 `.doc` 旧格式未返回 422 拒绝（200 落盘成功） | 违反 FEATURES STORE 验收 3（P2-2 设计裁定：.doc 仅指 .docx，.doc 应 422 拒绝并提示转换）；不支持格式绕过白名单 | 已修（S23，commit 5dcaea8）：storage.upload_file 加扩展名 allowlist，.doc→422 提示转 .docx、.exe/.xls→422、.txt→200；证据 `03-testing/dev_probe_upload_whitelist.log` |
| BUG-10 | P1 | 前端路由/nginx | 浏览器直接访问 `/mcp/servers`（刷新/分享/直连 URL）→ BFF 401 JSON 页面，SPA 未渲染，MCP 模块不可用 | nginx `location ~ ^/(api|v1|mcp)(/|$)` 把前端 SPA 路由 /mcp/* 代理到 BFF；仅侧边栏站内跳转可用 | 已修（S23，commit 5dcaea8）：nginx 正则 `^/(api|v1|mcp)(/|$)` 收窄为 `^/(api|v1)(/|$)`，/mcp 前端 SPA 路由不再误代理 BFF；证据 `03-testing/dev_probe_mcp_spa.log`（GET /mcp/servers → 200 text/html） |
| BUG-11 | P1 | LLM 节点/Agent 运行时 | 节点已配置 api_key，但「连通性探测」与 agent 运行时 LLM 调用均**不发送 Authorization 凭据**（凭据在 get_endpoint 脱敏时被 pop） | 绑定带 key 真实 LLM 的 agent 对话必然 401/502（核心链路断裂）；带鉴权端点永远探测失败；**BUG-08「探测带鉴权头」修复未生效** | 已修（S23，commit 5dcaea8）：`_row_to_node(keep_secret)` + 内部专用取 key 通道（get_endpoint/embedding/reranker_internal），探测/agent 运行时/嵌入/重排内部链路取回 api_key_enc 正常注入；对外 REST 保持脱敏（DECISION-012）。伪鉴权自测：带 key `has_auth=true`+`ok=true`、无 key `has_auth=false`+`ok=false`（BUG-08 凭据发送路径复核同证）；证据 `03-testing/dev_probe_bug11_pseudoauth.log` |

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

## BUG-07（P1）租户管理 403 + 平台管理员不可登录（system 租户无种子用户）+ 菜单无权限控制
- **现象**（用户实测，2026-09-24 迭代反馈）：
  1. `admin`（acme 租户）登录后点「租户管理」菜单 → 报 403。
  2. 平台管理员无法登录——`system` 租户（`init_schema.sql` 已建租户 + admin/member 角色）没有种子用户，登录路径不存在。
  3. 前端 `Layout.vue` 菜单对所有登录用户都显示「租户管理」，未按当前租户/权限控制。
- **根因**（已定位）：
  1. `services/api/app/routers/iam.py::_require_platform_admin` 要求 `is_platform_admin` 或 `tenant_id==系统租户 00000000-...-0001`。acme 租户 admin 不满足 → 403（设计正确，但缺平台管理员账号）。
  2. `services/shared/joker_shared/seed.py` 的 `SEED_TENANTS` 只含 acme/globex，`system` 租户无种子用户 → 平台管理员登录路径不存在，租户管理功能不可达。
  3. 前端 `frontend/src/config/menu.js` + `Layout.vue` 的「租户管理」条目只按 `iam:manage` scope 过滤，未区分租户 → 非平台用户也可见（点了才 403）。
- **修复**（S17，zhangbeihai，t_dcd84e35）：
  1. **种子**：新增 env `SEED_PLATFORM_ADMIN_USERNAME`（默认 `platform`，`.env.example` 同步）；`seed.py::_ensure_platform_admin` 在 `system` 租户创建平台管理员用户（密码=`SEED_ADMIN_PASSWORD`，绑 system 租户 admin 角色），**幂等**（重启不重复建）。
  2. **前端**：登录 JWT claims 含 `tenant_id`/`tenant_code`——`Layout.vue` 的「租户管理」菜单仅当 `tenant_code==system` 或 `tenant_id==系统租户` 时显示（`isPlatformAdmin` getter + `menu.js` `platform_only` 标记），其他用户不显示。`TenantsView` 直接改 URL 访问时保留 403 兜底并显示友好提示（「需要平台管理员权限，请用 system 租户的平台管理员登录」）。
  3. **API**：`_require_platform_admin` 403 detail 改为友好提示（含 `tenant_code=system + SEED_PLATFORM_ADMIN_USERNAME` 说明）。
  4. **文档**：`deploy/README.md`、`deploy/PROD_DEPLOY.md`、`.env.example` 补「平台管理员 = tenant_code=system + SEED_PLATFORM_ADMIN_USERNAME（默认 platform）」。
- **复验**（S17，probe `05-temp/probe_s17.py` 13/13 PASS，run 见 DEV_REPORT_S17 §回归）：
  - A) `platform@system` 登录 200，JWT `tenant_id`=系统租户 + `iam:manage`；`GET/POST/PUT /api/tenants` 200/201/200（列表含 system/acme/globex，新建租户可更新回读）。
  - B) `admin@acme` 登录 200，`GET /api/tenants` → **403 + 友好提示**；本租户 `/api/users` 仍 200（回归，租户内 admin 权限不受影响）。
  - C) 重启幂等：重建 api 容器后 `platform` 用户仍唯一（count=1，不重复建）。
  - 前端：s17 镜像 dist 含 `platform_only` / `isPlatformAdmin` / `SYSTEM_TENANT_ID`（已核对 bundle）。
- **S18 独立回归**（t_d939b9e2，yuntianming，2026-09-24，不轻信 S17 自测）：
  - 独立 probe `05-temp/probe_s18.py` **26/26 PASS** + 回归组 `probe_s18b.py` **15/15 PASS**（报告 03-testing/TEST_REPORT_S18.md，REGRESSION.md §6）。
  - 种子幂等独立验证：s17 镜像全新进程 `seed_all()` ×3，`platform` 恒=1、角色绑定恒=1（`05-temp/s18_seed_idem.py`）。
  - 补验安全边界：直接 API（不带 BFF 内部 X-Auth-* 头）`/api/tenants` → 401 internal auth（前端菜单隐藏不可绕过，BFF HMAC + API 双层保证）。
  - 无回归：refresh 轮换/登出失效/跨租户 404/多租户（S14/S15 口径）全过。
  - SKIP：浏览器真机点击（环境无 browser CLI），逻辑层三层核对闭环（bundle + 源码 canSee + API 安全边界）。
- **影响闭环**：租户管理功能可达（平台管理员 `platform@system`）；非平台用户菜单隐藏 + 直接访问 403 友好提示；与 S12 既有 6 BUG 无回归。

---

## BUG-08（P2）LLM 端点连通性测试 HTTP 401 + 前端静默吞错（用户实测，S20 排查）
- **现象**（用户实测，2026-09-24）：在 LLM 节点页新增/配置真实 vLLM 端点后点「连通性」→ 报 401 不可用，但用同一 key 直连该端点本身是通的；且前端保存/测试/删除失败时无任何提示，用户无法判断「是不是没保存成功」。
- **排查**（S20，zhangbeihai，t_75684eb5，严格按用户指定 6 步，证据脚本 05-temp/s20_*.py）：
  1. **新增端点**：`POST /api/llm/endpoints`（真实 key/base_url/model）→ **201**，`api_key_set=true`（明文不回显，DECISION-012 合规）。
  2. **查库核对**：宿主 psql 直查 `llm_endpoints`，新节点行存在且与旧种子 `platform-fallback-llm` 是不同行 → **写入的是新节点，非读旧种子**。
  3. **测试连通性**：`POST /api/llm/endpoints/{id}/test` → 200 + `{ok:false, summary:"unavailable: HTTP 401"}`；`joker-api` 日志可见探测请求 `POST .../v1/chat/completions "HTTP/1.1 401 Unauthorized"`（请求确实发出）。
  4. **容器内取 key 逐字节比对**：在 `joker-api` 容器内连库取 `api_key_enc`（Fernet 184 字符），用应用同款 `decrypt_secret` 解密 → 与提交 key **逐字节相等**（len=66，前缀 `Leaflong-0` / 后缀 `o6EA8R0uXG` / `repr` 全一致，`byte-equal: True`）→ **加解密链路正确，无截断/改写/Fernet 漂移**。
  5. **用库中 key 直连端点**：容器内直连 34.121.9.233:4000 间歇 401/200；**同窗口同 key 宿主直连亦 401/200**；40 连发对照：容器 `{401:37, RST:3, 200:0}` vs 宿主 `{401:36, RST:4, 200:0}`（401 平均延迟 ~605ms vs ~528ms）→ **401 与请求来源（容器 NAT/IP/源端口）无关**；host-network 容器、容器绑低源端口(888) 同分布；容器内访问 embedding 端点 34.64.61.208:4000=200（容器出站+认证正常）；401 响应 `server:uvicorn`+真实 GMT date（来自远端真实服务，非本地 MITM）；容器无 proxy 环境变量、无 DNS 劫持。
  6. **宿主同 key 拿到 200 + 真实 completion**（`chatcmpl-...`，模型 `vllm-qwen3.8-27b` 返回内容）→ **key 本身有效**。
- **结论**：
  - **平台代码链路正确**（写入/存储/Fernet 加解密/探测请求构造/同 key 端点侧可成功），**非平台代码 bug**。
  - **401 = 端点侧（外部 vLLM 34.121.9.233:4000）对同一有效 key 的间歇性拒绝，与来源无关**。根因假设（推测）：端点侧 vLLM 经 LB 分发到多 worker，**部分 worker 未配/配错 `--api-key`**（命中配对的=200，命中未配对的=401），或端点侧按来源/令牌的临时鉴权抖动（偶发 RST）。需用户在端点侧 vLLM/LB 处核实（平台侧无法从外部直接验证内部 worker key 配置）。
- **真实平台代码问题（已修）**：`frontend/src/views/llm/LlmNodeView.vue` 的 `onSave`/`onTest` `catch(e){}` 静默吞错、`onDelete` 无 catch → 保存/测试/删除失败用户无感知（误判「没保存成功」）。**修复**：三处补 `ElMessage.error` 提示具体原因（`e?.response?.data?.detail || e?.message`）。s17 镜像重建 + 容器重建（healthy，`/healthz`=200）。
- **复验**（S20，`05-temp/s20_regression.py` **8/8 PASS**）：webconsole healthz(8080)=200 / bff healthz(8000)=200 / 登录 acme admin=200 / 列 LLM 端点=200 / bundle 含「保存失败，数据未写入」=1 / **bundle 无 `catch(e){}` 静默块**（silent_catches=0）/ 连通性测试接口返回结构化 `{ok,summary}`=200 / 删除测试节点=200。
- **报告**：02-development/DEV_REPORT_S20.md（6 步完整证据链 + 代码正确性证明 + 端点侧根因假设 + 用户可操作建议）。
- **影响/闭环**：前端静默吞错已闭环（用户能看出「没保存成功」+ 具体原因）；端点侧 401 为**环境态非平台缺陷**——端点侧修好 key 配置后，平台侧无需改代码，`/test` 自动 `ok:true`（探测逻辑已证明正确）。端点不可用时 agent 走 mock-llm/本地 fallback 兜底（S03/S07 既有设计），平台功能闭环不受影响。
- **用户可操作建议**（DEV_REPORT_S20 §五）：① 核对 34.121.9.233:4000 的 vLLM 部署，多 worker/副本/LB 时确保每个副本 `--api-key` 完全一致；② 若端点侧按来源限流/鉴权，确认平台容器出口 IP（36.24.190.41，经 NAT）在白名单；③ 端点侧修好后平台侧无需改代码；④ 不可控时把 base_url 指向单实例/同网段可达的 vLLM。

---

## BUG-09（P2）上传 `.doc` 旧格式未 422 拒绝（S21 浏览器+接口双重复现）
- **现象**：存储模块上传 `.doc`（旧 Word 格式）→ 浏览器 toast「已上传 s21_r362429_bad.doc」+ API `POST /api/storage/files` 返回 **200**，文件落盘成功（`backend=local`，`content_type=application/msword`）。
- **预期**（FEATURES STORE 验收 3，P2-2 设计裁定 2026-09-22，原文「`.doc` 旧格式不在支持范围（'word' 仅指 `.docx`）：上传 `.doc` 返回 422 拒绝并提示转 `.docx`」）：应 **422** 拒绝 + 提示转 `.docx`。
- **复现步骤**：
  1. 浏览器：WebConsole 存储→文件上传记录→「上传文件」选任意 `.doc` → 提示「已上传」，列表出现该文件。
  2. 接口（等价）：`POST /api/storage/files?source=api`（multipart file=s21f.doc, content-type=application/msword）→ **200** + 文件记录。
  3. 扩展核对（`05-temp/s21_bug12_check.py`）：`.exe` / `.xls` 同样 **200** 落盘——**格式白名单在后端完全未校验**（不止 .doc）。
- **根因（推测，需开发确认）**：`services/api/app/routers/storage.py` `upload_file`（L43-54）未对扩展名/content-type 做 allowlist 校验（前端 `accept=".txt,.md,.docx,.xlsx,.pdf,.png,.jpg"` 仅是浏览器选择框提示，非强制），故任意扩展名直传 API 均 200。
- **影响**：违反文档化验收点（P2-2）；不支持格式（含 .exe 等可执行文件）可写入平台存储，属功能缺失 + 潜在安全隐患（存储内可存任意二进制）。
- **严重度**：P2（功能/验收缺失 + 安全弱项）。**阻塞验收**（QA_STANDARD §三：P2 未关闭不得交付）。
- **修复建议**：后端 `upload_file` 增加扩展名 allowlist（与前端 accept 一致）+ 内容 sniff 校验，非白名单返回 422 + detail「不支持的格式，.doc 请转为 .docx」。
- **S23 已修复（commit 5dcaea8）**：`services/api/app/routers/storage.py` 新增 `ALLOWED_UPLOAD_EXTS={.txt .md .pdf .docx .xlsx .csv}` + `_check_upload_ext()`，`upload_file` 入口调用（.doc→422 提示转 .docx、其余非白名单→422）；前端 `FilesView.vue` `accept` 对齐。真实 HTTP 自测（webconsole→bff→api）：`.doc/.exe/.xls`→422、`.txt`→200，`BUG09_FIXED=true`，证据 `03-testing/dev_probe_upload_whitelist.log`（脚本 `05-temp/s23a_probe_bug09_upload.py`）。

---

## BUG-10（P1）浏览器直接访问 `/mcp/servers` 命中 BFF 401，SPA 未渲染（nginx 路由冲突）
- **现象**：在浏览器**地址栏直接输入/刷新/分享** `http://<host>/mcp/servers` → 页面显示 BFF 返回的 **401 JSON**（`{"detail":"missing access token"}` +「美观输出」勾选框的 API 响应查看器），**SPA 布局（侧边栏/菜单）完全未渲染**，MCP 模块在该入口不可用。
  - 对照：管理台内**侧边栏点击**进入 MCP Server → 正常渲染 12 台 server（SPA 客户端路由生效）。
  - 对照：直接访问 `/agents` 等其他 SPA 路由 → 正常渲染。
- **预期**：SPA history 路由应 fallback 到 `index.html`（nginx `location / { try_files $uri $uri/ /index.html; }`），`/mcp/servers` 应加载 SPA 并在登录态下展示 MCP 列表。
- **根因（代码级确认）**：`deploy/nginx/nginx.conf:43`
  ```
  location ~ ^/(api|v1|mcp)(/|$) { proxy_pass http://bff:8000; }
  ```
  正则 `^/(api|v1|mcp)(/|$)` 把**前端 SPA 路由 `/mcp/servers`、`/mcp/servers/{id}/tools`** 也匹配进去代理到 BFF；BFF 无该路由的匿名处理 → 401 JSON 直接返回给浏览器。前端 MCP 路由（`/mcp/servers`、`/mcp/servers/:serverId/tools`）与 API 前缀 `/api/mcp` 撞车（API 走 `/api/mcp`，但 SPA 路由用了 `/mcp`）。
- **复现步骤**：
  1. 登录 WebConsole（任一有效账号）。
  2. 地址栏直接输入 `http://localhost:8080/mcp/servers` 回车（或在 MCP 页按 F5）→ 得到 401 JSON 页（非管理台）。
  3. 截图：`03-testing/screenshots/MCP_repro_direct.png`（401 JSON）vs `MCP_repro_sidebar.png`（侧边栏进入正常）。
- **影响**：MCP 模块对用户**仅能靠侧边栏站内跳转**访问；刷新/收藏/分享 `/mcp/*` 链接全部坏掉；用户误以为平台未登录或坏了。属**用户可见功能不可达**（QA_STANDARD §三验收阻断项级别）。
- **严重度**：P1（用户可见功能在常见操作路径下不可用）。**阻塞验收**。
- **修复建议（二选一，推荐 A）**：
  - A. nginx 正则改为仅匹配 API 前缀：`location ~ ^/(api|v1)(/|$)`（MCP 的 API 均在 `/api/mcp` 下，`/mcp` 代理分支可移除）——最小改动，消除冲突。
  - B. 前端 MCP 路由改前缀（如 `/mcp-servers`）避开 `/mcp`——需改路由+菜单。
  - 修复后回归：直连 `/mcp/servers` 应渲染 SPA（未登录→跳 /login，登录后→MCP 列表）。
- **S23 已修复（commit 5dcaea8，方案 A）**：`deploy/nginx/nginx.conf` 正则 `^/(api|v1|mcp)(/|$)` → `^/(api|v1)(/|$)`，移除 `/mcp` 分支（MCP 的 REST 都在 `/api/mcp` 下，`/mcp` 为前端 SPA 路由，现由 `location /` fallback 渲染）。真实 HTTP 自测（宿主 8080 直连）：`GET /mcp/servers` → **200 text/html**（SPA 壳），`/mcp/servers/123/tools` 与 `/` 同 200 text/html，`BUG10_FIXED=true`，证据 `03-testing/dev_probe_mcp_spa.log`（脚本 `05-temp/s23a_probe_bug10_mcp_spa.py`）。

---

## BUG-11（P1）LLM 节点已配 api_key，但连通性探测与 agent 运行时均不发送 Authorization 凭据（BUG-08 修复未生效 + agent 链路断裂）
- **现象**（QA_STANDARD §四「伪鉴权本地服务」复验，**直接命中**）：
  1. 建 LLM endpoint 节点 `base_url=http://127.0.0.1:9981/v1` + **`api_key=s21fakekey123456`** → 点「连通性」。
  2. 伪鉴权服务（强制要求 Authorization 头，收到则 `ok=true`）捕获到的请求：**`has_auth=false`（空 Authorization）** → 探测返回 `ok=false "unavailable: response has no choices"`。
  3. **预期**（QA_STANDARD §四）：`has_auth=true` + `ok=true`。
  4. 对照组（无 key 节点）：`has_auth=false`、`ok=false`——与带 key 节点**完全无法区分**，证明平台把"带 key 节点"当成"无 key 节点"处理。
- **连带（更严重）**：agent 运行时同样中招（`05-temp/s21_bug11_proof.py` 复现）：
  - agent `s08-e2e-agent-1790138772`（四要素绑定 `platform-fallback-llm` = 真实 34.121.9.233:4000/v1 + key）经 BFF `/v1/chat/completions`（浏览器对话同款入口）→ **502 `LLM call failed (round 1): AuthenticationError: 401`**。
  - 对照组（绑 mock LLM，无需鉴权）同路径 → **200** 正常回复。
  - 即：**绑定"带 key 真实 LLM"的 agent，对话必然 401/502，核心对话链路断裂**。
- **根因（代码级定位，joker-api 容器 /app 实码）**：
  1. `joker_shared/llm/service.py:48` `_row_to_node`：`enc = d.pop("api_key_enc", None)` → 脱敏时**把加密 key 从 node dict 删除**，只留 `api_key_set` 布尔（DECISION-012 合规的"响应脱敏"，但此处被内部调用复用）。
  2. `service.py:431` `probe_endpoint`：`node = await self.get_endpoint(...)` → 走 `_row_to_node` → node **已无 `api_key_enc`**。
  3. `service.py:348` `_probe_chat`：`headers=self._auth_header(node.get("api_key_enc"), …)`；`_auth_header`（L321）对 `None` → `return {}` → **探测请求不带 Authorization**。
  4. `joker_shared/agents/runtime.py:436`：`node = await llm_svc.get_endpoint(...)` → 同样脱敏；`runtime.py:443` `if node.get("api_key_enc"):` 恒 False → `api_key=None` → `ChatOpenAI(api_key="not-needed")` → 真实 LLM 401。
- **与 BUG-08 关系**：S20 声称"连通性探测带鉴权头"已修（前端静默 catch 已修、回归 8/8），但**探测请求构造路径上的凭据丢失未被发现**——S20 的 6 步证据链证明的是"key 存对、解密正确、请求发出"，其第 5 步用"库中 key 直连端点"验证的是**外部端点行为**，从未验证"**平台发出的探测请求里是否带 key**"。QA_STANDARD §四伪鉴权模板正是为暴露此类"mock 全绿、真鉴权路径从未执行"而设——本次复验直接命中。
- **复现/证据**：
  - 伪鉴权：`05-temp/s21_dep_verify.py`（容器内运行）→ `05-temp/s21_dep_result.json`（A_received_requests `has_auth=false`）。
  - agent 502：`05-temp/s21_bug11_proof.py` → `05-temp/s21_bug11_proof.out`。
  - 截图：`03-testing/screenshots/dep_verify_bug11.png`。
- **影响**：① 任何**需鉴权的真实 LLM/embedding/reranker 端点**，平台「连通性」永远判失败（用户误判节点不可用）；② **绑定带 key 真实 LLM 的 agent 对话必然 401/502**（核心链路）；③ 与 BUG-08 同源，说明 S20 的"已修"结论**部分不成立**（前端提示已修，但凭据发送未修）。
- **严重度**：P1（核心链路 + 用户可见功能不可用 + 安全凭据丢失）。**阻塞验收**（QA_STANDARD §三）。
- **修复建议**：区分"响应脱敏"与"内部取 key"两条路径——
  - 方案 A（推荐）：`get_endpoint` 保持脱敏（对外安全），**内部** `probe_endpoint`/`runtime` 改用带 key 的库行查询（如新增 `get_endpoint_internal` 返回含 `api_key_enc` 的原始行，仅限进程内使用、绝不外发响应）。
  - 方案 B：`_row_to_node` 增加 `keep_secret` 参数，内部调用传 True。
  - 修复后回归（QA_STANDARD §四）：伪鉴权服务 A 项应 `has_auth=true` + `ok=true`；B 项保持 `has_auth=false`/`ok=false`；绑真实带 key 端点的 agent 对话在端点侧 key 有效时应 200。
- **依赖**：真实端点 key 当前失效（OBS-02），完整端到端"带 key 真实 LLM 对话 200"需用户在端点侧确认/更新 key 后复测；但**伪鉴权 A 项不依赖外部端点，已充分证明凭据未发送**。
- **S23 已修复（commit 5dcaea8，方案 A+B 结合）**：`joker_shared/llm/service.py` `_row_to_node(row, keep_secret=False)`（默认 REST 脱敏 pop `api_key_enc`，`keep_secret=True` 保留）+ 新增内部专用取 key 通道 `get_endpoint_internal` / `get_embedding_internal` / `get_reranker_internal`（**仅进程内调用，绝不进 REST**）；`probe_endpoint/probe_embedding/probe_reranker/chat_completion/embed_texts/rerank` 改走 internal 通道；`joker_shared/agents/runtime.py` agent 运行时改 `get_endpoint_internal`，`api_key_enc` 正常 `decrypt_secret` 注入 `ChatOpenAI`。对外 REST 保持脱敏（DECISION-012 不变）。QA_STANDARD §四 伪鉴权自测（宿主 `127.0.0.1:9981` 强制 Authorization 捕获）：**带 key `has_auth=true`+`ok=true`、无 key（对照）`has_auth=false`+`ok=false`**，`BUG11_FIXED=true` —— 凭据确认已发出（BUG-08 凭据发送路径复核同证）。证据 `03-testing/dev_probe_bug11_pseudoauth.log`（run s23a43135，脚本 `05-temp/s23a_probe_bug11_inapi.py` + `s23a_host_pseudoauth.py`）。真实端点 34.121.9.233:4000 持续 401 为环境态 OBS-02，不据此下结论。

---

## 说明：未列入本清单的 37 项 FAIL（28 项非产品 BUG）
以下 FAIL **不是产品缺陷**，逐条证据与归类见 TEST_REPORT.md §3（37 项全表）：
- **测试脚本缺陷（18 项）**：RAG-02 上传/来源/解析（round-1 未等 parse ready，probe9/10 独立复现 6/6 + status=ready + 2 chunks）、RAG-04 定长/父子/语义切分（round-1 时序）、RAG-05 原文查看/chunk 列表（probe10 复现 200/1782B、count=2）、MCP-03 关联调用方（harness 走错路径，正确 `/referring-agents` 200）、SKILL-01 上传 .md（harness multipart 字段名 `file` vs 接口 `files`）、SKILL-02 files=[]（上一条连带）、AGENT-04 列表/新建/重命名/删除（harness 字段名 `session_id` vs `id` + 期望 201 vs 实际 200；probe14 独立复现 create/rename/delete 全 200）、LLM-01 修改 endpoint（harness 传非可更新字段 `description`）、限流单用户 429（harness `req()` 对 429 自动退避重试+仅发 3 次，429 被吞；probe14 §H 独立复现 10×200→6×429）、TRACE-02 按会话检索（8/9 trace 项 PASS，仅「按会话」filter 命中 0，疑似 session_id 过滤错位）。
- **自测环境产物（8 项）**：RAG-07 纯向量/带 rerank 检索、RAG-09 反向定位、RAG-10 MCP 工具、D-A official 两级判定、AGENT-05 official 来源、AGENT-11 第三方 RAG 引用、AGENT-07 多轮（turn1 409 + mock-llm 无法演示召回）——根因均为**自测 fallback ngram embedding 对中文查询余弦相似度 < 默认阈值 0.3 → 0 命中**（检索链路本身正确：S11 e2e T4 score=0.663、RAG-08 阈值 0.99→0 正确、probe10 向量已写入）。resolve_official 逻辑经代码核对正确。
- **SKIP（2 项）**：D-A 库级 NULL 判定（依赖 kb2 上传时序）、AGENT-05 引用可链接原文位置（0 引用连带）。
