# DEV_REPORT_S17 — agent-joker 迭代修复：BUG-07 租户管理 403 + 平台管理员不可登录 + 菜单权限控制

- 任务卡：t_dcd84e35（S17，zhangbeihai）
- 输入：用户实测 P1（2026-09-24 迭代反馈）——admin(acme) 点「租户管理」403；平台管理员无法登录（system 租户无种子用户）
- 交付：代码修复（种子 + 前端菜单权限 + 403 友好提示）+ 部署镜像（agent-joker-api:s17 / agent-joker-webconsole:s17；bff 无代码变更，沿用 s14 镜像 tag s17）+ 自测证据
- 原则：只改必要代码，不重构无关模块；种子幂等；权限判定「菜单隐藏 + 403 兜底」双层。

## 修复总览

| 项 | 根因 | 改动文件 | 复验 |
|----|------|----------|------|
| 平台管理员不可登录 | `seed.py` 只为 acme/globex 建 admin 用户；`system` 租户（init_schema.sql 已建租户+角色）无用户 → 登录路径不存在 | `services/shared/joker_shared/seed.py`、`services/shared/joker_shared/config.py` | A1-A4：platform@system 登录 200 + JWT tenant_id=系统租户 + iam:manage |
| 租户管理 403 无友好提示 | `_require_platform_admin` 403 detail 只有 "platform admin required" | `services/api/app/routers/iam.py` | B2-B3：403 + 友好提示 |
| 菜单对所有人可见 | `Layout.vue` 只按 scope 过滤，未按租户/平台权限 | `frontend/src/stores/auth.js`、`config/menu.js`、`router/index.js`、`components/Layout.vue`、`views/base/TenantsView.vue`、`views/LoginView.vue`、`api/iam.js` | s17 镜像 dist 含 platform_only/isPlatformAdmin/SYSTEM_TENANT_ID（bundle 核对） |
| 文档缺失 | 平台管理员口径未写入部署文档 | `deploy/README.md`、`deploy/PROD_DEPLOY.md`、`deploy/.env.example`、`deploy/docker-compose.yml` | 文档走查 |

## 1. 种子：system 租户平台管理员（核心修复）

**根因**：`init_schema.sql` 已建 system 租户（`00000000-...-0001`，code=system）+ 内置
admin/member 角色（admin 绑全部平台级 scope），但 `seed.py` 的 `SEED_TENANTS` 只含
acme/globex——system 租户没有任何用户，平台管理员登录路径不存在，「租户管理」
（`/api/tenants` 要求 `is_platform_admin` 或 tenant=系统租户）功能不可达。

**改动**：
- `config.py`：新增 `SEED_PLATFORM_ADMIN_USERNAME: str = "platform"`。
- `seed.py`：新增 `_ensure_platform_admin(conn, pw)`——`system` 租户内按
  `(tenant_id, username)` 幂等检查；不存在则创建用户（密码=SEED_ADMIN_PASSWORD，
  display_name=平台管理员）并绑 system 租户 `admin` 内置角色（role_scopes 由
  init_schema.sql 种子已绑平台级 scope，无需重复）；占位哈希场景补写真实 bcrypt。
  在 `ensure_seed_users()` 末尾调用（单事务内，与既有种子同事务提交）。
- `docker-compose.yml`：api 服务透传 `SEED_PLATFORM_ADMIN_USERNAME`（默认 platform）。

**幂等**：重启 api 容器后 seed 重复执行——已存在则跳过，`platform` 用户恒为 1 条
（实测 3 次重启，count 均=1，日志无重复创建）。

## 2. 前端：菜单权限控制 + 403 兜底

登录 JWT claims 已含 `tenant_id`/`tenant_code`（登录时写入 auth store），前端据此判定：

- `stores/auth.js`：
  - 导出 `SYSTEM_TENANT_ID = '00000000-0000-0000-0000-000000000001'`；
  - 新增 getter `isPlatformAdmin`：`tenant_code === 'system' || tenant_id === SYSTEM_TENANT_ID`。
- `config/menu.js`：「租户管理」条目加 `platform_only: true`（保留 `scope: 'iam:manage'`）。
- `components/Layout.vue`：`canSee(item)` 增加 `if (item.platform_only && !auth.isPlatformAdmin) return false`——
  非平台管理员（如 acme admin）菜单**不显示**「租户管理」。
- `router/index.js`：tenants 路由 meta 同步加 `platform_only: true`（与 menu 对齐，留作后续路由守卫扩展点）。
- `views/base/TenantsView.vue`：
  - 直接改 URL 访问（绕过菜单）时 `listTenants` 返回 403 → 页面显示 `el-alert` 友好提示
    「无权限访问租户管理」+ API detail（「需要平台管理员权限，请用 system 租户的平台管理员登录」），
    并隐藏表格/工具栏；
  - 请求改 `silent: true`，避免 403 再弹全局错误 toast（友好提示已足够）；
  - `api/iam.js` `listTenants(params, config)` 支持透传 config。
- `views/LoginView.vue`：登录页提示补一行「平台管理员（租户管理）：租户 system / 用户 platform（SEED_PLATFORM_ADMIN_USERNAME）」。

**双层防御**：菜单隐藏（体验层）+ 后端 403（安全层，BFF→API 强制，前端隐藏不可绕过）。

## 3. API：403 友好提示

`iam.py::_require_platform_admin`：403 detail 由 `"platform admin required"` 改为
「需要平台管理员权限，请用 system 租户的平台管理员登录（tenant_code=system +
SEED_PLATFORM_ADMIN_USERNAME，默认 platform）」。判定逻辑不变（`is_platform_admin` 或
tenant=系统租户），仅文案；对 acme admin 等仍 403。

## 4. 文档

- `deploy/README.md` §3 变量表：新增 `SEED_PLATFORM_ADMIN_USERNAME` 行（含「平台管理员 =
  tenant_code=system + SEED_PLATFORM_ADMIN_USERNAME（默认 platform）」口径）。
- `deploy/PROD_DEPLOY.md`：§2 变量表 + §5 生产 .env 模板同步补该变量。
- `deploy/.env.example`：补 `SEED_PLATFORM_ADMIN_USERNAME=platform`。

## 部署

- 镜像：`agent-joker-api:s17`、`agent-joker-webconsole:s17` 重建（node22 构建 dist 烘进 nginx）；
  `agent-joker-bff` 无代码变更，沿用 s14 镜像并 `docker tag` 为 s17（compose 标签统一）。
- 启动：`cd deploy && docker compose up -d api webconsole`（pg/redis/bff/mocks 不动，
  8080/8000 端口、卷、网络不变，无数据丢失——数据在 joker-pg 独立实例）。
- api 启动即跑 seed → 日志 `seed platform admin user platform@system created`（仅首次）。
- 健康：api/webconsole/bff/pg/redis 全部 `healthy`。
- **实测占用（docker stats）**：joker-api 74.3Mi/1Gi(7.3%)、joker-bff 76.0Mi/512Mi(14.9%)、
  joker-webconsole 7.4Mi/128Mi(5.8%)、joker-pg 83.8Mi/1Gi(8.2%)、joker-redis 18.7Mi/256Mi(7.3%)。
- 台账：`~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md` 已更新镜像 tag s14→s17 + 实测占用。

## 自测 / 回归（05-temp/probe_s17.py，经 webconsole:8080→bff→api 全链路）

**13/13 PASS**（`05-temp/results_s17.json`）：

- **A 组（平台管理员，platform@system）**
  - A1 登录 200；A2 返回 access+refresh；
  - A3 JWT `tenant_id`=系统租户 `00000000-...-0001`；A4 scopes 含 `iam:manage`（+11 平台级 scope + agent:use:*）；
  - A5 `GET /api/tenants` 200；A6 列表含 system/acme/globex；
  - A7 `POST /api/tenants` 201（新建测试租户）；A8 `PUT /api/tenants/{id}` 200；
  - A9 读回 plan=pro（更新生效）。
- **B 组（普通租户 admin@acme）**
  - B1 登录 200；B2 `GET /api/tenants` → **403**；
  - B3 403 detail 含友好提示（"system 租户的平台管理员登录"）；
  - B4 本租户 `GET /api/users` 200（回归：租户内 admin 权限不受影响）。
- **C 组（重启幂等）**：重建 api 容器 3 次，`platform` 用户 count 恒=1，
  绑 system admin 角色（user_roles 1 行），日志无重复创建。
- **前端 bundle 核对**：s17 webconsole dist 含 `platform_only`（menu.js）、`isPlatformAdmin`
  （auth.js/Layout.vue）、`SYSTEM_TENANT_ID`（auth.js）、`无权限访问租户管理`（TenantsView.vue）、
  登录页 platform 提示（LoginView.vue）。
- **清理**：自测新建的 s17 测试租户已从 tenants 表删除，租户列表恢复 acme/globex/system。

## 已知问题 / 给测试的提示

1. **浏览器 UI 未做真机点击验证**（本机 browser CLI 不可用）：菜单隐藏/403 页面逻辑已核对
   bundle 与源码，建议 S18 回归用浏览器走一遍：
   a) 登录 `platform@system`（密码=SEED_ADMIN_PASSWORD）→「基础」组应见「租户管理」→ 进入后表格正常；
   b) 登录 `admin@acme` → 侧边栏**无**「租户管理」→ 手动访问 `/tenants` → 黄色友好提示；
   c) 刷新页面（JWT 水合路径 hydrateFromToken）后菜单权限仍正确。
2. **平台管理员密码=SEED_ADMIN_PASSWORD**（与租户 admin 同密码，任务要求口径）；生产环境
   应在首次登录后经管理台改密（PROD_DEPLOY.md 已有此提示）。
3. **前端隐藏是体验层**：直接调 `/api/tenants` 的非平台用户仍 403（安全由后端保证），
   菜单隐藏不可作为安全边界对外宣传。
4. `tenants` 无 DELETE 端点（既有设计，S12 未列缺陷）；自测新建租户只能留档，
   本次已手工清理。S18 如需建/删测试租户注意 `uq_tenants`（name/code 全局唯一）。
5. 回归面：登录/刷新/登出（S14 修复的 BUG-02 路径）未受本次改动影响——B1 登录 +
   A1/A2 双令牌均验证通过；限流路径（429 退避）在 probe 中多次命中仍 PASS。
