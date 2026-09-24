# DEV_REPORT_S14 — agent-joker 迭代修复：6 个 BASE 缺陷（BUG-01~06）

- 任务卡：t_437c008e（S14，zhangbeihai）
- 输入：03-testing/BUGS.md（S12 测试，146 项 = 109 PASS / 35 FAIL / 2 SKIP，6 个真实产品缺陷）
- 交付：代码修复 + 部署镜像（agent-joker-api:s14 / agent-joker-bff:s14）+ 逐项复验证据
- 原则：**只改必要代码，不重构无关模块**；每 BUG 修后独立 probe 复验。

## 修复总览

| ID | 严重 | 根因 | 改动文件 | 复验 |
|----|------|------|----------|------|
| BUG-01 | P1 | `_bind_role`/`_bind_scope` 是 async 但调用处**漏 await**，协程被静默丢弃 → role_scopes/user_roles 从未写入 | `services/api/app/routers/iam.py` | 角色 scope 读回非空（create+update 双路径） |
| BUG-02 | P1（安全） | **双重缺陷**：① BFF 转发剥离客户端 Authorization → API logout 拿不到 bearer 写黑名单；② BFF `verify_access` 黑名单 401 在 try 内被自己的 `except Exception` 自吞（fail-open）→ 即使黑名单写入也放行 | `services/bff/app/gateway.py`（2 处）、`services/api/app/routers/auth.py` | 登出后原 access 立即 401 |
| BUG-03 | P1 | start/end 带 `Z` 的 ISO8601 字符串直接拼 `created_at >= :start`，asyncpg 要求 datetime → DataError 500 | 新增 `joker_shared/timeutil.py`；`audit.py`、`storage/service.py`、`joker_shared/trace.py` | 三端点时间筛选 200（空区间 total=0） |
| BUG-04 | P2 | (a) `get_user` 未查/返回 roles；(b) `update_user` 的 422 判定在 role_names 分支之前（仅带角色即 422）；叠加 BUG-01 根因（_bind_role 漏 await） | `services/api/app/routers/iam.py` | 仅 role_names 更新 200 + 读回 roles |
| BUG-05 | P2 | **复测未复现**：干净单登录→立即刷新 = 200 + 新双令牌（原 FAIL 为登录 IP-429 重试循环多次登录触发 refresh 家族轮换，后登录吊销前家族——限流环境产物，非代码缺陷） | 无代码改动（代码复核确认逻辑正确） | 刷新 200；旧 refresh 重放 401（家族吊销正常） |
| BUG-06 | P2 | 登出经公开前缀（PUBLIC_PREFIXES）→ 无 X-Auth-* 签名头 → 审计行 tenant_id 落 NULL → 租户过滤查询（`WHERE tenant_id = :t`）查不到 | `services/api/app/middleware.py` | 登出后 2s 内审计查询命中（tenant 非空） |

---

## BUG-01（P1）角色 scope 绑定/读回失效

**现象**：POST /api/roles 带真实 scope code → 201，但 GET /api/roles 读回 `scopes=[]`；PUT 改权限后仍空。

**根因**：`iam.py` 中 `_bind_role`/`_bind_scope` 定义为 `async def`，但 4 处调用
（create_user / update_user / create_role / update_role）**漏写 await**——Python 只创建
协程对象不执行，role_scopes/user_roles 插入从未发生。201/200 返回正常，读回恒空。
DB 实证：S12 测试创建的角色 `t1790177877` 在 `role_scopes` 表 0 行。

**改动**：`services/api/app/routers/iam.py` — 4 处调用补 `await`：
- `create_user`：`await _bind_role(session, t, uid, rn)`
- `update_user`：`await _bind_role(session, t, user_id, rn)`
- `create_role`：`await _bind_scope(session, rid, sc)`
- `update_role`：`await _bind_scope(session, role_id, sc)`

**复验**（probe_fix_s14 §A）：admin 登录 → 取真实 scope `agents:manage` →
POST /api/roles → 201 → GET /api/roles 读回 `scopes=["agents:manage"]` ✓；
PUT 改 scope_codes 为 [agents:manage, trace:read] → 200 → 读回 2 个 ✓；
POST /api/users 带 role_names → user_roles 落库 ✓（连带修好用户侧绑定）。

**连带影响（正向）**：BASE-03「用户有效权限=角色权限并集」依赖 user_roles 落库，
此前恒空；修复后登录 scopes 并集生效（回归 §E 验证）。

---

## BUG-02（P1，安全）登出后 access token 未失效

**现象**：POST /api/auth/logout → 200（refresh 已吊销），但原 access token 调接口仍 200。

**根因（双重缺陷叠加）**：
1. **BFF 剥离 bearer**：`gateway._forward` 组装转发头时把客户端 `Authorization` 头
   剥离（`k.lower() not in (b"authorization",...)`）；API 侧 `auth.logout` 靠
   `request.headers.get("authorization")` 解码 bearer 拿 jti 写 Redis 黑名单 →
   BFF 一剥离 → API 拿到空头 → 黑名单从未写入。
2. **BFF 黑名单检查自吞异常（更隐蔽）**：`verify_access` 中
   `raise AuthError(401, "access token revoked")` 写在
   `try: ... is_denied(jti)` 块**内**，而外层 `except Exception` 把刚抛的
   AuthError（Exception 子类）自捕并 fail-open 放行 → **即使黑名单写入了，
   登出后 BFF 也永远返回 200**。复验时 redis 中确认 `joker:jwt:deny:<jti>`
   已存在（exists=1）、BFF 容器内 `is_denied()` 返回 True，但请求仍 200 ——
   即此自吞缺陷实锤。

**修法**：
1. `services/bff/app/gateway.py` — `_forward` 不再剥离 Authorization；
   新增 `PUBLIC_AUTH_PREFIXES`（login/refresh/logout，与 API 侧
   `middleware.PUBLIC_PREFIXES` 对齐）：这些公开前缀端点**不注入 X-Auth-\* 签名头**
   （保持 DECISION-009 登录例外语义，凭据本身鉴权），bearer 原样透传给 API。
   非公开端点行为不变（仍注入签名头；API 只信签名头、忽略请求体，安全不变量保持）。
2. `services/bff/app/gateway.py` — `verify_access`：`is_denied()` 结果先落到
   `denied` 变量（redis 异常才 fail-open），**AuthError 移到 try 块外抛出**，
   杜绝自吞。
3. `services/api/app/routers/auth.py` — `logout` 黑名单写入加 `ttl > 0` 守卫
   （已过期 token 无需拉黑；deny_access 本身也有 ttl<=0 返回，双保险）。

**安全边界核对**：
- 签名头端点（/api/users 等）：API 中间件只验 X-Auth-\* HMAC，Authorization 头存在
  也不被采信（`verify_internal_headers` 只读签名头）→ 无绕过面。
- 公开前缀端点：logout 黑名单只写不发权；refresh 靠有状态表校验；login 凭据即鉴权。
- BFF `verify_access`（客户端入口）在转发前已先查黑名单 → 登出后第一个请求就在 BFF 401。

**复验**（probe_fix_s14 §B）：登录 → POST /api/auth/logout（bearer+refresh）→ 200，
refresh_revoked=1 → 原 access 调 GET /api/users → **401**（`access token revoked`）✓；
refresh 重放 → 401 ✓。

---

## BUG-03（P1）时间范围筛选 500

**现象**：`GET /api/audit/logs?start=2020-...Z&end=2021-...Z`、
`/api/storage/upload-records?...`、`/api/trace/events?...` → 500
（asyncpg: `invalid input for query argument: '2020-01-01T00:00:00Z' (expected datetime, got str)`）。

**根因**：FastAPI 把 start/end 声明为 `str`，DB 层原样拼进
`created_at >= :start`；asyncpg 对 timestamptz 参数要求 datetime 实例，不隐式转换。

**修法**：
1. 新增 `services/shared/joker_shared/timeutil.py` — `parse_iso8601()`：
   统一处理 `Z` 后缀 / 带 offset（+08:00）/ 裸串（按 UTC），返回 aware datetime；
   解析失败抛 ValueError。
2. `services/api/app/routers/audit.py` — list_logs 的 start/end 经 parse_iso8601，
   无效 → 400（不再 500）。
3. `services/shared/joker_shared/storage/service.py` — list_upload_records 同上。
4. `services/shared/joker_shared/trace.py` — `list_sessions`（started_at）与
   `list_events`（te.created_at）同上，`_parse_time` 辅助统一 400。

**复验**（probe_fix_s14 §C）：旧区间（2020-2021）audit / upload-records / trace events
三端点全部 **200 + total=0** ✓；无效 start（`not-a-date`）→ 400 ✓；
带 offset 入参（+08:00）正常解析 ✓。

---

## BUG-04（P2）用户角色分配不可读 + 无法仅改角色

**现象**：(a) GET /api/users/{id} 无 roles 字段；(b) PUT 仅带 role_names → 422。

**根因**：
- `get_user` 未 SELECT user_roles，返回体无 roles；
- `update_user` 中 `if not sets: raise 422` 在 role_names 分支之前执行——
  只传 role_names 时 sets 空 → 直接 422，永远到不了角色绑定分支；
- 叠加 BUG-01 根因：即使走到 `_bind_role` 也漏 await 不生效。

**改动**（`services/api/app/routers/iam.py`）：
- `get_user`：补 user_roles→roles 聚合查询，返回体加 `roles` 字段；
- `update_user`：422 条件改为 `not sets and req.role_names is None`；
  仅改角色时跳过 UPDATE（只校验用户存在，跨租户仍 404 不泄露存在性），
  走 DELETE+重绑角色路径。

**复验**（probe_fix_s14 §D）：建用户 → PUT 仅 `{"role_names":["member"]}` → **200** ✓；
GET /api/users/{id} → `roles=["member"]` ✓；PUT 改 `["admin"]` → 读回 `["admin"]` ✓；
PUT 空体（无任何字段）→ 仍 422 ✓（语义保持）。

---

## BUG-05（P2）refresh 换新 access 401 — 复测未复现（非代码缺陷）

**复测过程**（probe_fix_s14 §E，干净单登录→立即刷新，隔离 IP 窗口）：
1. 登录 → 200 得 access+refresh
2. `POST /api/auth/refresh {"refresh_token": r}` → **200 + 新双令牌** ✓
3. 旧 refresh 重放 → **401**（replaced_by 非空 → 整族吊销，重放检测正常）✓
4. 篡改 refresh → 401 ✓

**结论**：原 S12 FAIL 根因是**限流环境产物**——S12 harness 对登录 429 做自动退避
重试，同一 IP 窗口内多次登录 → 每次登录签发新 refresh 家族；后一次登录使前一次
的 refresh 成为"已被轮换/整族吊销"态 → 被刷新时 401。代码路径（解码→查表→
状态校验→轮换）经代码复核 + 干净复测均正确，**无需改动**。
BUGS.md 标注的「待修/复测」按复测结果关闭。

---

## BUG-06（P2）登出未见于接口操作日志

**现象**：登出后 `GET /api/audit/logs?path=/api/auth/logout` 查不到登出记录。

**根因**：`/api/auth/logout` 在 API 侧 `PUBLIC_PREFIXES` 白名单 →
InternalAuthMiddleware 直接放行，**不设置 request.state.joker_tenant/user** →
AuditMiddleware 写审计时 tenant_id/user_id = NULL。而查询端
`list_logs` 强制 `WHERE tenant_id = :t`（租户过滤，BASE-07）→ NULL 行永远查不到。
（登出行确实写入了——DB 中可看到 tenant_null=t 的 logout 行，只是归属缺失。）

**改动**（`services/api/app/middleware.py` — AuditMiddleware）：
- `dispatch` 入口新增 `_try_fallback_identity(request)`：公开前缀下尽力解码
  Authorization bearer（只读 claims，不改变鉴权语义），把 jti/tenant/user 挂到
  request.state（`joker_access_jti/tenant/user`）；
- 审计写入的 tenant_id 改为「签名头 tenant → 回退 access tenant」；
  user_id 同理（`joker_user or joker_access_user`）。
- 非公开端点行为不变（签名头存在时回退值不会被写入，因 state 已有值且
  `if ... is None` 守卫）。

**复验**（probe_fix_s14 §F）：登录 → 登出 → 延迟 2s →
`GET /api/audit/logs?path=/api/auth/logout` → 命中登出记录，**tenant_id 非空** ✓。

---

## 回归（probe_fix_s14，S14 镜像部署后全跑）

| 组 | 项 | 结果 |
|----|----|------|
| A 权限三元组 | role create/update 读回 scopes / user roles 读回 / 登录 scopes 并集非空 | PASS |
| B 登出 | logout 200 + access 401 + refresh 吊销 + 重放 401 | PASS |
| C 时间筛选 | audit/upload/trace 旧区间 200 total=0 + 无效 400 + offset 正常 | PASS |
| D 用户角色 | 仅 role_names 200 / 读回 roles / 改角色 / 空体 422 | PASS |
| E refresh | 干净刷新 200 + 重放 401 + 篡改 401 | PASS |
| F 日志 | 登出审计命中（tenant 非空） | PASS |
| G 无回归 | /healthz、/v1 chat（mock-llm 链路）、/api/rag/kbs、/api/agents、/api/scopes、多租户 404 | PASS |

> 二次复验（run 2，s14 镜像部署后重新全跑，日志 `05-temp/probe_s14_v2_rerun.log`）：**29/29 PASS**，
> 与上表逐项一致（A1-A4 / B1-B3 / C1-C5 / D1-D6 / E1-E3 / F1-F2 / G1-G6），确认修复在当前
> 部署环境稳定有效，无回退。

## 部署

- 镜像：`agent-joker-api:s14`、`agent-joker-bff:s14`、`agent-joker-webconsole:s14`
  （Dockerfile.api / Dockerfile.bff 未变，仅代码层变更；webconsole 变更 nginx.conf
  加 resolver；compose 标签已更新为 s14）。
- 启动：`cd deploy && docker compose up -d --build`（.env 不变）。
- 验证：joker-api / joker-bff / joker-webconsole 均 healthy；复验 probe 经
  webconsole:8080 → bff:8000 → api:8001 全链路。

### 附带修复：webconsole nginx 上游 IP 缓存 502

compose 重建 bff 容器后，nginx（webconsole）仍缓存旧的 bff IP（172.21.0.8）
→ 反代 502（Connection refused）。修复：`deploy/nginx/nginx.conf` 加
`resolver 127.0.0.11 valid=10s ipv6=off;`（Docker 内置 DNS，上游域名动态解析，
10s 缓存），避免每次重建 bff 都要重启 webconsole。

## 已知问题 / 边界

1. **BUG-05 的限流根因未改**：登录 IP 限流（5/min）触发后 harness 重试仍会制造
   多家族 refresh 场景——属测试 harness 行为，产品语义正确（重放/整族吊销是安全特性）。
2. **历史脏数据**：BUG-01 修复前创建的测试角色（scope 未绑定）不会自动补绑；
   S12 测试数据留在 pg 卷内（tenant acme），不影响新数据。
3. **登出审计的 tenant 依赖 bearer 有效**：公开前缀下若客户端不带 bearer（纯
   refresh 登出）则审计行 tenant 仍为 NULL——BASE-05 验收路径（带 bearer 登出）已覆盖。
4. **webconsole 前端**未改：GET /users/{id} 新增 roles 字段为纯增量，前端不解析不受影响。
