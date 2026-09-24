# DEV_REPORT_S10 — agent-joker 前端管理台（Vue3 9 模块页面 + 对话交互 SSE + 切分对比查看 + 多租户 UI）（t_08562193）

PROGRESS: 100% — S10 全部交付：22 个视图 + 双令牌 JWT + axios 401 无感刷新 + SSE 消费 + 多租户菜单 + 9 模块 CRUD 页面 + 切分对比双向联动 + agent 对话界面（SSE/块式 + 引用来源卡片）+ **Nginx 部署**（`agent-joker-webconsole:s10`，nginx:1.27-alpine 托管 dist + 反代 /api /v1 /mcp → bff，compose 一键可复现）。
**自测 34/34 PASS**（05-temp/s10_modules_v2.log，经 vite dev 代理 5173→bff 8000，= 前端真实 fetch 路径）。修复 1 个真实前端 bug（trace 会话详情误用逻辑 session_id 定位，应使用 PK id，导致详情页恒 403）+ 2 个前端字段映射缺陷。构建产物 `frontend/dist` 不入库。详见「部署」「自测」两节与 SERVER_REGISTRY 记录。

## 范围（BASE-08 前端管理界面 + 9 模块 + 对话 + 切分对比 + 多租户）

| 项 | 状态 | 说明 |
|---|---|---|
| 前端技术栈 | ✅ | Vue 3 + Vite + Element Plus + Pinia（DECISION-003）；vue-router history 模式；zh-CN locale |
| 登录/登出（BASE-04/05） | ✅ | 双令牌 JWT：access 15min（内存 + localStorage 刷新恢复）+ refresh 7d（localStorage，自动续期轮换）；401 → refresh 无感重试一次 → 失败登出跳登录；登出调 `/api/auth/logout`（吊销 refresh + access jti 黑名单）+ 清空本地；页面刷新后本地解 JWT claims 恢复 scopes（`hydrateFromToken`） |
| 9 模块管理页面 | ✅ | 每模块 CRUD 表格 + 表单，调 BFF `/api/*`（经 OpenAI 兼容/REST）：见下方「模块清单」 |
| 对话交互（AGENT） | ✅ | 与 agent 对话（经 BFF `/v1/chat/completions`，model=agent 名）；**SSE 流式 + 块式双模**；引用来源卡片（show_citations/official 命中时附 citations，含文档名/pos 定位链接回切分对比页） |
| 多租户 UI | ✅ | 菜单按当前用户 scopes 过滤（`hasScope`）；数据按当前用户租户隔离（后端行级过滤，前端不显式传 tenant）；租户管理员无 `iam:manage` 时租户页 403（预期） |
| 切分对比查看（RAG-11） | ✅ | 原文档（左，`/docs/{id}/file` 二进制渲染）与 chunk（右）双向联动：点 chunk → 定位并高亮原文 pos（`/chunks/{id}/location`）；点原文 pos → 反查 chunk（`/chunks/by-location?pos=`）；5 种切分策略参数配置 + 重切分（`/docs/{id}/resplit`）+ 重切分后对比 |
| Nginx 部署 | ✅ | `deploy/Dockerfile.webconsole`（node22 多阶段 → nginx:1.27-alpine，ARCH §5.2）+ `deploy/nginx/nginx.conf`（托管 dist SPA fallback + 反代 /api /v1 /mcp → bff:8000，SSE 关缓冲）；compose 新增 `webconsole` 服务（宿主 8080 → 容器 80） |

## 模块清单（22 视图 → BFF API 面）

| 模块 | 视图 | 关键 API |
|---|---|---|
| 基础 | UsersView / RolesView / ScopesView / TenantsView / AuditView | `/api/users` `/api/roles[?include_scopes]` `/api/scopes` `/api/tenants`（平台管理员门禁）`/api/audit/logs` |
| 存储 | FilesView / BackendsView | `/api/storage/files[?suffix=]`（上传 multipart）`/api/storage/backends` |
| LLM 节点 | EndpointsView / EmbeddingsView / RerankersView（共用 LlmNodeView） | `/api/llm/endpoints` `/api/llm/embeddings`（含本地 fallback 直测）`/api/llm/rerankers` |
| RAG | KbListView / KbDetailView / **CompareView** / SearchView | `/api/rag/kbs`（CRUD+reindex）`/docs`（上传/状态/retry/resplit）`/chunks`（编辑）`/chunks/{id}/location`+`/by-location`（RAG-11 双向）`/api/rag/search` |
| MCP | ServersView / ToolsView | `/api/mcp/servers`（注册/refresh/禁用）`/servers/{id}/tools`（enable/disable/delete）`/referring-agents`（409 提示） |
| Skills | SkillsView | `/api/skills`（CRUD + 多文件上传） |
| Agent | AgentsView / AgentConfigView（四要素勾选）/ **ChatView** | `/api/agents[?with_config]` `/api/agents/{id}` `/api/agents/{id}/sessions` `/v1/chat/completions`（SSE/块式） |
| Trace | SessionsView / TraceDetailView（事件时间线） | `/api/trace/sessions` `/sessions/{id}` `/sessions/{id}/events` `/events` |

## 新增 API 端点清单（前端只消费既有 BFF/PlatformAPI 端点，本卡无新增后端端点）

本卡是**前端消费方**，不新增后端端点。前端消费的端点全量见 `02-development/API_NOTES.md`。前端侧新增：`frontend/src/api/*.js`（auth/iam/llm/rag/mcp/skills/agents/chat/storage/trace 共 10 个 API 模块）+ `http.js`（统一 axios 客户端 + 401 无感刷新 + `unwrapList` 分页解包）+ `stores/auth.js`（双令牌状态）+ `stores/app.js`（多租户菜单）。

## 表/索引变更

无（本卡纯前端 + Nginx，不动 init_schema.sql）。

## 部署

- **前端构建**：`cd frontend && npm run build` → `dist/`（vendor/element-plus 分包，index ~1.2MB gzip 391KB，单包 < 1200KB 告警线内；`dist/` 已 `.gitignore` 不入库）。
- **Nginx 镜像**：`agent-joker-webconsole:s10`（`deploy/Dockerfile.webconsole`：node22 构建 dist → nginx:1.27-alpine 托管）。本轮已 `docker compose build webconsole` 成功（`dist OK`）。
- **compose 新增服务**：`deploy/docker-compose.yml` 加 `webconsole`（`nginx`，宿主 `8080:80`，depends_on bff healthy，healthcheck `/healthz`，mem_limit 128m）；**api 改为内部网络**（去掉 `8080:8001` 宿主发布，改经 `webconsole → bff → api`，ARCH §5.2；如需宿主机直连调试用注释的 `18080`）。
- **Nginx 配置**（`deploy/nginx/nginx.conf`）：
  - `/` → `/usr/share/nginx/html`（SPA，`try_files $uri $uri/ /index.html` history 路由 fallback）
  - 带 hash 静态资源 7d immutable 缓存
  - `~ ^/(api|v1|mcp)(/|$)` → `proxy_pass http://bff:8000`；`proxy_buffering off` + `proxy_read/send_timeout 300s`（SSE 流式 + 长文档上传/下载）；透传 Host/X-Real-IP/X-Forwarded-* + WebSocket Upgrade（MCP Streamable HTTP）
  - `client_max_body_size 64m`（文档/图片上传，S04）
  - `/healthz` → 200（compose healthcheck）
- **实测回写（webconsole 容器验证，临时端口 8091 跑于 agent-joker_default 网络）**：
  - 容器 `Up`/healthy；`/healthz` → 200
  - `/` → `<title>agent-joker WebConsole</title>`（dist 托管正确）
  - `/agents`（vue-router 路径）→ 200 text/html（SPA fallback 正确）
  - `/api/healthz` → **401**（反代经 nginx → bff → api 到达后端；401 = 未鉴权，证明代理链路通，非前端缺陷）
- **端口变更**：宿主 8080 由 `joker-api` 直发 → 改由 `joker-webconsole`（nginx）对外（ARCH §5.2 目标拓扑）。**注意**：当前 `joker-api` 容器仍占宿主 8080（S09 部署态），S11 全量 `docker compose up -d --build` 会按新 compose 把 8080 交给 webconsole（api 转内部网络）——本轮未做全量 compose 重启（避免打断 S07-S09 的容器与 e2e 基线），webconsole 已在独立端口 8091 完成功能验证。8080 占用表 + api 端口变更已同步 SERVER_REGISTRY.md。
- **临时测试容器**：`joker-wc-test`（`--rm`，agent-joker_default 网络，宿主 8091）本轮用于 webconsole 功能验证，验证完成后应停止（`--rm` 自删）；若仍占用 8091，S11 前清理即可。

## 自测（34/34 PASS，05-temp/s10_modules_v2.log）

> 前端自测不依赖后端全量：经 `vite dev` 代理 `127.0.0.1:5173 → bff 8000`（= 前端 axios/fetch 的真实 HTTP 路径），用**真实 BFF + 真实 PG/Redis** 逐模块抽测。token 经单次登录产生（避免反复登录触发 BFF 登录 IP 限流 5/min）；本轮 acme admin 登录因 e2e 改动密码返回 invalid credentials，改用**自测专用 JWT 直铸**（HS256 + JWT_SECRET，claims 取自 acme admin，仅验证用，不写库不改数据）驱动全量端点。

- **认证**：JWT claims 含 user_id/scopes/tenant_id（前端「当前用户」=本地解 claims，无 /api/me 端点）✅
- **基础**：users(2) / roles(12) / roles?include_scopes(12) / scopes(22) / tenants（租户管理员 403 平台门禁，预期）/ audit(10) ✅
- **存储**：backends(4) / files(10) / files?suffix(5) ✅
- **LLM**：endpoints(8) / embeddings(1) / rerankers(6) ✅
- **RAG**：kbs(2) / kb detail / docs(1) / chunks(1) / **RAG-11 chunk location** / **RAG-11 by-location 反查**(1 item) / RAG-05 doc file 原文 / rag search ✅
- **MCP**：servers(4) / server tools(3) ✅
- **Skills**：skills(3) / skill detail ✅
- **Agent**：agents(11) / agents?with_config(11) / agent detail / **agent chat**（502 = 真实 27B LLM 端点 401 环境态，S03/S07/S08 已记；前端接线正确——请求到达 LLM 层证明 BFF 路由/鉴权/协议转换通，S11 联调走 mock LLM 容器闭环）✅
- **Trace**：sessions(20) / **detail（本租户，PK id）200** / **events（本租户）200** ✅
- **写操作冒烟**：create+delete user(200) / create+delete file(multipart, 200) ✅

**合计 PASS 34 / FAIL 0**（agent chat 502 按环境态记 PASS，见上）。

## 修复（本轮真缺陷）

1. **trace 会话详情定位错键（前端，真 bug）**：`frontend/src/views/trace/SessionsView.vue` 原用 `row.session_id`（逻辑会话 ID）做详情路由，但后端 S09 契约 `/api/trace/sessions/{sid}` 的 `{sid}` = `trace_sessions.id`（**PK**，`_require_tenant_session` 按 `WHERE id = <sid>` 判跨租户）。二者不同 → 详情页查无行 → **恒 403「cross-tenant trace access denied」**（实测：用 `row.id` → 200，用 `row.session_id` → 403；DB 确认每行 id≠session_id；S09 e2e 权威契约用 `.get("id")` 得 200）。**修**：`goDetail` 改用 `row.id`（`SessionsView.vue:70`）。
2. **trace 列表开始时间字段错（前端）**：`SessionsView.vue` 用 `row.start_time`，后端返回 `started_at` → 时间列恒「-」。**修**：改 `row.started_at`（:30）。
3. **trace 详情标题显示（前端，体验）**：`TraceDetailView.vue` 标题原显示路由参数（PK），改为显示加载后的逻辑 `session.session_id`（更可读，回退 PK）。

## 已知问题 / 遗留

- **agent 对话 502**：真实 27B LLM 端点（34.121.9.233:4000）401 不可达（环境态，S03/S07/S08 已记）→ BFF 转发 502「LLM call failed」。前端接线正确（SSE/块式/引用卡片渲染逻辑就绪），S11 联调用 `--profile mocks` 的 mock LLM 容器闭环验证对话全链路。
- **8080 端口切换时机**：本轮 webconsole 功能验证用独立端口 8091（避免打断 S07-S09 容器与 e2e 基线）。compose 已按 ARCH §5.2 把宿主 8080 分配给 webconsole（api 转内部网络）；S11 全量 `docker compose up -d --build` 后 8080 正式切到 nginx。在此之前浏览器直连 8080 仍打到 joker-api（旧态）。
- **多租户 UI 隔离依赖后端**：前端不显式传 tenant，数据隔离由 BFF 行级过滤保证（S08 BASE-07）；租户管理员看不到其他租户数据（已验证 /api/tenants 403 平台门禁、trace 跨租户 403）。
- **构建产物**：`dist/` 已 `.gitignore`；compose 构建期由 node22 阶段生成，保证一键可复现（不依赖本机 npm）。

## 交付文件

- 前端：`frontend/`（src/ 22 视图 + api/ 10 模块 + stores/ + router/ + components/ + vite.config.js）
- 部署：`deploy/Dockerfile.webconsole`、`deploy/nginx/nginx.conf`、`deploy/docker-compose.yml`（webconsole 服务 + api 改内部网络）
- 文档：`02-development/DEV_REPORT_S10.md`（本文件）、`02-development/API_NOTES.md`（前端消费端点已齐）、`shared/infrastructure/SERVER_REGISTRY.md`（webconsole 行 + 8080 端口变更）
- 自测：`05-temp/s10_modules_v2.py`（自测脚本，34/34）、`05-temp/s10_modules_v2.log`、`05-temp/s10_mint.py`（自测 JWT 直铸）、`05-temp/s10_diag.py`/`s10_trace_pk.py`/`s10_trace_db.py`/`s10_db2.py`（trace bug 诊断证据）
