# DEV_REPORT — S08 agent-joker BFF 统一网关（BFF-01..09 + 平台 MCP 对外）

`PROGRESS: 100% — S08 BFF 网关全部交付并自测通过（19/19 + 回归全绿），可进测试阶段`

## 范围（本切片交付）

BFF 独立 FastAPI 服务作为**统一入口/网关层**（ARCH §4），用户/SDK 请求先经 BFF：
统一鉴权 + 多租户隔离 + 限流 + 配置化路由 → 本地端点就地处理 / 其余转发 PlatformAPI（X-Auth-* HMAC，DECISION-009）。
业务服务不重复实现 token 校验；PlatformAPI 只信签名头中的 tenant（防越权）。

覆盖 BFF-01..09 + 平台 MCP server 对外暴露（STORE-06/07/RAG-10）：

1. **BFFGateway**（`services/bff/app/gateway.py`）：根级 ASGI 分发（**非 BaseHTTPMiddleware**，
   以支持 /v1 SSE 与 /mcp Streamable HTTP 的原生 `send` 透传）。统一管线（ARCH §4.1，固定顺序）：
   ① 限流 → ② JWT 鉴权 + Redis 登出黑名单 → ③ 身份提取 → ④ 配置化路由转发 → ⑤ scope → ⑥ 协议转换 → ⑦ 审计。
2. **统一鉴权（BFF-01）**：JWT access 本地校验（HS256 + exp）+ Redis 登出黑名单（jti）；
   业务服务不重复实现 token 校验；BFF 校验后透传签名身份头。
3. **多租户（BFF 侧）**：从 JWT claims 取 tenant，**绝不信任请求体 tenant 字段**（BFF-09 验收 3）。
4. **限流（BFF-02，DECISION-013）**：`rate_limit.py`，Redis 固定窗口计数，三维度
   租户 QPS 默认 50 / 用户 QPS 默认 10 / 登录 IP 5 次每分钟；阈值可配
   （`bff_rate_limit_configs` 表 + Redis 镜像，DB→Redis→default 三级降级，运行时调整即时生效）；超限 429。
5. **配置化路由（BFF-03，DECISION-014）**：`routes.py` + `services/bff/routes.yml`，
   路径前缀 → 目标服务 + 路径模板，最长前缀匹配，启动加载 + 热加载 API；新增模块端点不改 BFF 代码。
6. **OpenAI 兼容（BFF-04，DECISION-016）**：`openai_compat.py`，`/v1/chat/completions`
   块式（`chat.completion`）+ SSE 流式（`chat.completion.chunk` + `data: [DONE]`）双模式；
   `model` 字段 = agent 名称（租户内唯一，跨租户 404 不暴露存在性）；标准 OpenAI SDK 可直接对接。
7. **ToolInterceptor 统一动作链（BFF-06/07，D-B / DECISION-023 / DECISION-015）**：
   ① scope 校验（`mcp_tools.required_scopes` × 用户 scopes，未勾选 403）
   + ② Access Token 强制注入（入参 access_token 一律覆写为用户真实 token，BFF-09 验收 2）
   + ③ 机器凭证代理执行（平台工具 → `/internal/*` HMAC 签名头）
   + ④ tool_call 事件落 trace。100% 经 `execute_tool_call`（D-B 无裸执行路径）。
   模式②（第三方 agent，BFF 进程内）：拦截 HTTP 响应中 Tool Call 意图 → 拦截器 →
   机器凭证代执行 MCP 工具 → POST {agent_url}/tool_results 回传。
8. **平台 MCP 对外暴露（STORE-06/07/RAG-10，DECISION-011）**：`mcp_endpoint.py`，
   `/mcp`（Streamable HTTP，stateless）暴露平台内置三工具 upload_doc/query_doc/rag_search
   （S02/S05 已实装工具），经 ToolInterceptor 统一动作链，标准 MCP SDK 可直连。
9. **BFF 管理端点（`admin.py`）**：GET/POST `/api/bff/rate-limits`、GET `/api/bff/routes`、
   POST `/api/bff/routes/reload`（平台级 `iam:manage`/系统租户）。
10. **错误码约定（BFF 统一，ARCH §4.7）**：见 API_NOTES.md「BFFGateway」章节。

## 新增 API 端点（BFF 本地，不经上游转发）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | `{status, service:"bffgateway", phase:"S08-bff"}` |
| POST | `/v1/chat/completions` | OpenAI 兼容（DECISION-016），model=agent 名，块式+SSE，需 `agent:use` |
| GET/POST | `/api/bff/rate-limits` | 限流配置只读/运行时调整（即时生效） |
| GET | `/api/bff/routes` | 路由表只读 |
| POST | `/api/bff/routes/reload` | 路由热加载 |
| POST | `/mcp` | 平台 MCP（Streamable HTTP，三工具经 ToolInterceptor） |

> 其余 `/api/*`、`/internal/*` 经 BFF 鉴权+限流后**转发 PlatformAPI**（注入 X-Auth-* HMAC）；
> `/api/auth/login` 为公开入口（仅 IP 限流，直接转发，登录例外不注入签名头）。

## 表 / 索引变更

无新增表。使用既有：`bff_rate_limit_configs`（限流阈值，S01 建）；`trace_events`（tool_call/rag 留痕，月分区）；
`mcp_tools`/`mcp_servers`（平台工具解析）。无 init_schema.sql 变更。

## 修复的本轮真缺陷（重点）

1. **`/mcp` 500「run() can only be called once」**：MCP SDK v1.30 规定
   `StreamableHTTPSessionManager.run()` 每实例只能进入一次（创建 task group，生命周期=整个 app）。
   原 `build_mcp_asgi()` 在**每请求**内 `async with manager.run()` → 第二请求即抛
   `RuntimeError`，`/mcp` 全挂（tools/list + tools/call 均 500）。
   **修复**：拆成 `build_mcp_manager()`（只建一次）+ `make_mcp_request_handler(manager)`
   （每请求走 `manager.handle_request()`），`run()` 改由 `BFFGateway.__call__` 在 **lifespan** 里
   进入一次（task group 覆盖 app 生命周期），`create_app()` 装配三者。
2. **mock LLM `/chat/completions` 500（`RuntimeError: coroutine raised StopIteration`）**：
   `services/mocks/mock_llm/server.py` 中 `echo_tool = next((...))` 无 default，当 tools 为空
   （无工具 simple agent，S08 的 /v1 正是这种）时 `next()` 抛 `StopIteration`，Python 3.12 把它
   升级成 `RuntimeError` 致 500。**修复**：补 `None` default（`next((gen), None)`）。
   （此为 mock 资产 bug，真实 27B 端点不受影响，但闭环自测依赖它，必须修。）

## 自测（docker compose 实测，真实 HTTP + 真实 PG/Redis + mock-llm 容器）

**命令**：`python3 05-temp/e2e_s08.py`（日志 `05-temp/e2e_s08_run3.log`）

**S08 BFF E2E：19/19 PASS**
- 登录经 BFF 转发 PlatformAPI（BFF-03 配置化路由）
- 无 token 401 / 坏 token 401 / 有效 token 200（BFF-01 统一鉴权）
- GET `/api/bff/rate-limits`（BFF-02 配置 API）+ 运行时调 login_ip 阈值=2 即时生效 + 登录 IP 限流 429
- GET `/api/bff/routes`（count=2, src=routes.yml）+ POST `/api/bff/routes/reload` 热加载
- 创建 simple agent（经 BFF）+ **/v1 块式 200（chat.completion）** + **/v1 SSE 流式 200（chunk + [DONE]）**（BFF-04）
- 跨租户访问 agent → 404（不暴露存在性）+ model 缺失 → 422
- **/mcp tools/list 三工具（upload_doc/query_doc/rag_search）** + **/mcp tools/call upload_doc 经 ToolInterceptor**
  （①scope ②token 强注入 ③代执行）+ **tool_call trace 留痕（DB count≥1，BFF-06 验收 1 / D-B）**

**回归（api 侧未改，仅 BFF + shared interceptor + mock LLM 修复）**：
- S07 回归 **60/60 PASS**（`e2e_s07_regress_s08.log`）
- S06 回归 **69/69 PASS**（`e2e_s06_regress_s08b.log`；首轮 2 处 FAIL 系 S07 自测遗留 orphan skill
  污染 skill 计数断言——已知 harness 行为，`clean_orphan_s07_skills.py` 清理后复跑全绿）
- S05 回归 **44/44 PASS**（`e2e_s05_regress_s08.log`）

## 部署

- **compose**：`deploy/docker-compose.yml` `bff` 服务直连 pg+redis（`agent-joker_default` 网络），
  `BFF_ROUTES_FILE=/app/bff/routes.yml`；image tag `agent-joker-bff:s08`。
  **双进程/单容器**（DECISION-018）：uvicorn 起 BFFGateway（API + /mcp + /v1 同进程），
  SAR 运行时与拦截器同容器组共享 `joker_shared` 库（DECISION-015）。
- **Dockerfile**：`deploy/Dockerfile.bff`（python:3.12-slim，COPY services/shared + services/bff，
  非 root uid1000 运行，EXPOSE 8000）；`deploy/Dockerfile.api`（COPY services/mocks，mock LLM 修复随镜像固化）。
- **本轮重建**：
  1) `docker compose build bff` + `up -d bff`（8000 端口/卷/网络不变，无数据丢失）；
  2) **`docker compose build api` + `up -d api`**——mock LLM 容器（`joker-mock-llm-s07`）由 e2e 从
     api 镜像 `python /app/mocks/mock_llm/server.py` 拉起，**旧 api 镜像含 bug 代码**（`next()` 无 default），
     每重建 mock 容器即回退 → 重 build api 把 `services/mocks/mock_llm/server.py` 的 StopIteration 修复
     **烘进镜像**（`COPY services/mocks`），S12 测试重建 mock 容器不再丢修复；mock 容器从新镜像 recreate。
- **健康验证**：`curl :8000/healthz` → `{"status":"ok","service":"bffgateway","phase":"S08-bff"}`；
  BFF 容器 healthy；`/mcp` initialize 200（text/event-stream）；mock LLM 容器内文件确认含 `None,` default。
- **实测资源回写（docker stats）**：joker-bff 141.7Mi/512Mi、joker-api 147.7Mi/1Gi、
  joker-pg 95.7Mi/1Gi、joker-redis 18.7Mi/256Mi、joker-mock-llm-s07 25.7Mi/7.7G（均 healthy）。
  无新增宿主端口（8000 为 S02 既有；pg/redis 仅容器网络）。

## 文档

- `02-development/API_NOTES.md`：新增「BFFGateway（S08 统一网关）」章节（本地端点表 / 限流三维度 /
  平台 MCP 对外 / 错误码约定 / 部署）。
- `shared/infrastructure/SERVER_REGISTRY.md`：新增 joker-bff 组件行（s08）+ S08 部署日志（实测资源）。
- 本文件 `02-development/DEV_REPORT_S08.md`。

## 已知问题 / 遗留

- **真实 27B LLM 端点 401 不可达（环境态，S03 已记录）**：/v1 自测走 mock LLM 容器闭环
  （card 允许「mock LLM 或真实 27B」）。生产/有端点时自动走真实 27B（`pick_llm_endpoint` 先 test 真实端点）。
- **/mcp 直连无特定 agent → tool_call trace 回退租户首个 active agent**（/mcp 直连路径本身无 agent 上下文；
  SAR 进程内 / 第三方 agent 路径有真实 agent_id，trace 归属正确）。S09 trace 切片可细化归属。
- **S06 回归首轮 orphan skill 污染**：S07 自测遗留的 manual skill 会污染 S06 skill 计数断言；
  已用 `05-temp/clean_orphan_s07_skills.py` 清理。S07/S06 交替跑时注意（S07 已记录此 known issue）。
- **ToolInterceptor 模式①（SAR 进程内 LangChain Tool 回调）与模式②（第三方 agent HTTP 拦截）**
  的完整链路在 S07 已覆盖（SAR tool-calling loop + TP 代理 tool 闭环）；本卡聚焦 BFF 侧统一动作链
  与 /mcp 对外暴露（BFF 进程内代执行），两模式共用 `execute_tool_call` 统一入口。
