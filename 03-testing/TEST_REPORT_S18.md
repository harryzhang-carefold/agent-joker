# agent-joker S18 迭代回归测试 — 测试报告（TEST_REPORT_S18.md）

- 任务卡：t_d939b9e2（S18 迭代回归，yuntianming）
- 上游：t_dcd84e35（S17 修复，zhangbeihai）— BUG-07（P1）修复 + s17 镜像部署（api/webconsole s17，bff 沿用 s14 内容 tag s17）
- 被测对象：`agent-joker-api:s17 / agent-joker-bff:s17 / agent-joker-webconsole:s17`（compose 已部署，5 核心容器全 healthy，2026-09-24 11:00 核验）
- 测试 run：`s18run20260924_111227`
  - probe A：`05-temp/probe_s18.py` → `05-temp/results_s18.json`（26 项）
  - probe B：`05-temp/probe_s18b.py` → `05-temp/results_s18b.json`（15 项）
  - 种子幂等：`05-temp/s18_seed_idem.py` → `05-temp/results_s18_seed.json`（3 次全新启动）
- 判定原则：**不轻信 S17 自报**（S17 的 13/13 由开发自测），独立重写 probe 复验 + 覆盖 S17 自报中「浏览器 UI 未真机点击」的缺口（bundle 核对 + 前端源码逻辑核对 + API 等价验证）。

## 0. 总览

| 指标 | 值 |
|------|-----|
| 回归项总数 | **41** |
| PASS | **41**（100%） |
| SKIP | 1 项**浏览器真机点击**（环境受限，见 §4，非 FAIL 计入口径） |
| FAIL | **0** |
| BUG-07（P1）三症状 | **全部独立复验 PASS**（平台管理员可登录 / 403 友好提示 / 菜单权限控制） |
| 种子幂等（3 次全新启动） | **PASS**（platform 用户恒=1，角色绑定恒=1） |
| 相邻路径回归（S14/S15 已修口径） | **无回归**（refresh/登出失效/成员 403/跨租户 404/多租户） |
| 新增产品 BUG | **0** |
| 严重度 | P0 **0** / P1 **0** / P2 **0**（未修复项） |

**测试结论：PASS。**
**是否满足验收标准：是**（BUG-07 修复的三症状全部验收 + 种子幂等 + 无回归）。
**阻塞性问题：无。**（BUG-07 P1 闭环，无 P0/P1 未修复缺陷；浏览器真机点击为环境受限 SKIP，见 §4，不影响放行——逻辑层已三层核对）

> 口径：41 项 = BUG-07 复验 26 项（A1-A10 / B1-B4 / C1-C3 / D1-D4 / E1 / F1-F3）+ 相邻路径回归 15 项（R0-R5b）。浏览器 UI 点击走查为独立 1 项 SKIP（环境无浏览器 CLI），不计入 41 项口径。

## 1. BUG-07 三症状独立复验（A–B，经 webconsole:8080→bff→api 全链路）

S17 声称已修「admin(acme) 点租户管理 403 / 平台管理员无法登录 / 菜单无权限控制」。本卡独立 probe 复现：

| 症状 | 复验项 | 结果 | 证据 |
|------|--------|------|------|
| ① 平台管理员无法登录（system 租户无种子用户） | A1 platform@system 登录 **200** / A2 双令牌 / A3 JWT `tenant_id`=系统租户 `0000...0001` / A4 scopes 含 `iam:manage`（+11 平台级 scope） | **PASS** | probe_s18 A1-A4 |
| ① 租户管理功能可达 | A5 `GET /api/tenants` **200** / A6 列表含 system/acme/globex / A7 `POST` **201** / A8 `PUT` **200** / A9 读回 plan=pro | **PASS** | probe_s18 A5-A9（新建测试租户已清理 A10） |
| ② admin(acme) 点租户管理 403 无友好提示 | B1 admin@acme 登录 200 / B1b JWT `tenant_id`≠系统租户 / B2 `GET /api/tenants` → **403** / B3 403 detail=「需要平台管理员权限，请用 system 租户的平台管理员登录（tenant_code=system + SEED_PLATFORM_ADMIN_USERNAME，默认 platform）」 | **PASS** | probe_s18 B1-B3 |
| ③ 菜单对所有人可见（无权限控制） | D1-D4 bundle 核对 + 前端源码逻辑核对（见 §3） | **PASS** | probe_s18 D1-D4 + §3 |
| 回归：租户内 admin 权限不受影响 | B4 admin@acme 本租户 `/api/users` **200** | **PASS** | probe_s18 B4 |

## 2. 种子幂等独立验证（F + s18_seed_idem.py）

S17 声称「重启 3 次恒唯一」。本卡**不依赖容器重启**（避免扰动已部署环境），改用 s17 镜像 `docker run` 全新进程执行 `seed_all()` **3 次**（等价于 3 次全新启动），每次后查库：

| 启动 | platform 用户 count | 角色绑定数 | 角色名 | 结论 |
|------|------|------|------|------|
| START 1 | **1** | **1** | admin | 不重复建 |
| START 2 | **1** | **1** | admin | 幂等 |
| START 3 | **1** | **1** | admin | 幂等 |

- 回归：acme/globex 租户 admin 用户数各 **1**（seed 未重复建既有种子用户）。
- probe_s18 F1-F3 再核验部署库：platform count=1、绑定 1 角色、角色名=admin。**PASS。**

## 3. 菜单权限控制（D–E + 源码核对）

S17 自报缺口：「浏览器 UI 未做真机点击」。本卡三层核对（bundle 存在性 + 源码逻辑 + 安全边界独立验证）：

1. **bundle 核对**（s17 webconsole dist，probe_s18 D1-D4/E1）：
   - `platform_only`（menu.js 租户管理条目标记）✓
   - `isPlatformAdmin`（auth.js getter + Layout.vue canSee）✓
   - `SYSTEM_TENANT_ID = '00000000-0000-0000-0000-000000000001'` 常量 ✓
   - TenantsView 403 友好提示文案「无权限访问租户管理」✓
   - 登录页 platform 提示（含 `SEED_PLATFORM_ADMIN_USERNAME`）✓
2. **源码逻辑核对**（frontend/src）：
   - `auth.js::isPlatformAdmin` = `tenant_code==='system' || tenant_id===SYSTEM_TENANT_ID`；
   - `Layout.vue::canSee`：`if (item.platform_only && !auth.isPlatformAdmin) return false` —— 非平台用户（acme admin / globex admin / 普通成员）**均不显示**「租户管理」；
   - `menu.js`：`/tenants` 条目 `platform_only: true` + `scope: 'iam:manage'` 双条件；
   - `router/index.js` tenants 路由 meta 同步 `platform_only`（守卫扩展点）；
   - 刷新水合路径 `hydrateFromToken` 从 JWT claims 恢复 `tenant_id`/`scopes`，菜单判定不丢。
3. **安全边界独立验证**（probe_s18 C1-C3）：前端隐藏仅为体验层——直接调 API（绕过 webconsole/bff，不带 BFF 内部 X-Auth-* 头）`GET /api/tenants` → **401 internal auth failed**；经 BFF 但非 system 租户 → **403 友好提示**。即菜单隐藏不可被绕过，安全由后端双层保证（BFF HMAC + API `_require_platform_admin`）。**PASS。**

## 4. 相邻路径回归（R 组，S14/S15 已修口径不得回归）

S17 改动面：seed.py / config.py / iam.py / 前端 7 文件 / 部署文档。以下确认未引入回归：

| 项 | 口径来源 | 结果 |
|----|----------|------|
| R1 refresh 轮换 200 + 新双令牌（带 access，S15 E1 口径） | S15 BUG-05 | **PASS** |
| R2 旧 refresh 重放 401（整族吊销 `replay detected, family revoked`） | S15 BUG-05 | **PASS** |
| R2b-c 登出 200 → 原 access **401**（`access token revoked (logged out)`） | S15 BUG-02 | **PASS** |
| R2d 登出后 refresh 重放 401 | S15 BUG-02 | **PASS** |
| R3d 普通成员（临时建/删 s18mem*）`GET /api/tenants` 403 友好提示 | 本卡新增 | **PASS** |
| R3e 普通成员 `/api/users` 403（无 iam:manage，租户内也拦） | BASE-02 | **PASS** |
| R4 acme admin 用 globex 用户 id → **404**（跨租户不泄露存在性） | S12 基线 | **PASS** |
| R5 globex admin 登录 200 + 本租户 `/api/users` 200（多租户回归） | S12 基线 | **PASS** |

## 5. SKIP / 已知残留（非缺陷，不影响 PASS 判定）

| 项 | 说明 | 处置 |
|----|------|------|
| 浏览器真机点击走查（S17 建议的 a/b/c 三步） | 本环境 browser CLI 不可用（`browser-use`/`uvx` 均缺失，已确认）；且无 chromium/node 可做 headless | **SKIP（环境受限）**。逻辑层已 §3 三层核对（bundle + 源码 + API 安全边界），S17 已知问题#1 实质闭环；建议下迭代有浏览器环境时补一次真机点击留档 |
| 平台管理员密码 = SEED_ADMIN_PASSWORD（与租户 admin 同密码） | 任务要求口径；生产首登后应改密（PROD_DEPLOY.md 已有提示） | 残留提示，P3 级，不阻塞 |
| tenants 无 DELETE 端点（既有设计，S12 未列缺陷） | 本卡测试租户用 SQL 直删/软删清理 | 维持既有设计 |

## 6. 测试数据清理

- probe_s18：新建测试租户 `s18t*`（POST/PUT 验证后）**SQL 删除**，租户列表恢复 acme/globex/system。
- probe_s18b：临时成员 `s18mem*`（建/登/测/删全链路）经 API **DELETE 200**（软删 disabled）。
- 种子幂等 3 次启动：`--rm` 容器已自动回收，无残留卷。
- 部署环境：joker-api/webconsole/bff/pg/redis 全 healthy，未做任何容器重启/数据迁移。

## 7. 回归结论

- **BUG-07（P1）：修复有效，独立复验 PASS**（三症状全闭环 + 种子幂等 + 双层安全边界）。
- **无回归**：S14/S15 已修的 refresh 轮换/登出失效/跨租户隔离/多租户路径全部复测通过。
- **BUGS.md BUG-07 状态维持「已修」**，本卡独立证据替换 S17 自测证据（不轻信自报原则）。
- **测试结论：PASS。是否满足验收标准：是。阻塞性问题：无。** 可交 S19 终审（t_cb525a29）。
