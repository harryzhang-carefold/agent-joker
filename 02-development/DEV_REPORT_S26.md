# DEV_REPORT_S26 — 环境基线 + 全模块接口自测（真实端点，禁 mock）

**卡**：t_c390a1b6（S26，zhangbeihai，2026-09-28）
**入口**：全部走真实生产入口 `webconsole:8080 → BFF(8000) → API(8001)`，真实 HTTP（urllib），无 mock、无 in-page fetch。
**结论**：**基线 11/11 + 9 模块共 98/98 check PASS**。发现并修复 1 个 P1 部署缺陷（BUG-15），验证 BUG-13/14 修复生效，两条真实 LLM 端到端链路（agent chat + OpenAI-compat 经 BFF）真实返回 `pong`。

---

## 一、基线（s26_01_baseline.py，11/11）

| 项 | 结果 | 证据 |
|---|---|---|
| healthz 8080 / bff 8000 | 200 / 200（bffgateway S08-bff） | dev_probe_s26_baseline.log |
| login admin@acme / platform@system | 200，token 四件套 | 同上 |
| 错密码 | 401 invalid credentials（预期负例） | 同上 |
| GET /api/llm/endpoints | 200，total=34 | 同上 |
| **LLM 真实端点 34.121.9.233:4000 探测** | **ok=true，511ms**（BUG-08 修复证明） | 同上 |
| **embedding 真实端点 34.64.61.208:4000 gte-qwen2** | **ok=true，dim=3584，308ms** | 同上 |
| local-fallback-embedding | 200，同输入同向量（确定性） | 同上 |

## 二、模块自测汇总（98/98）

| 模块 | 脚本 | 结果 | 关键证据 |
|---|---|---|---|
| M1 认证 | s26_m1_auth.py | **11/11** | A1 登录/A2 双 token 同 jti/A3 自验证/A4 刷新轮换+旧 refresh 重放整族吊销/A5 黑名单 logout/A6 无 token 401/A7 垃圾 token 401/A8 租户隔离 403/A9 **logout-all revoked:2**（BUG-13/14 验证）/A10 吊销后 refresh 401/A11 refresh 无 token 401 |
| M2 IAM | s26_m2_iam.py | **21/21** | 用户 CRUD+重置密码+禁用登录 401；角色 CRUD+scope 集比对（12 平台 scope）；租户 T1-T3（unique name、TenantCreate 全字段、PUT 回读一致） |
| M3 存储 | s26_m3_storage.py | **10/10** | 上传 txt 200 / 重复 409 / 列表 / 下载回读一致 / .exe 422（BUG-09 不回归）/ 删除后 404 / healthz |
| M4 LLM | s26_m4_llm.py | **11/11** | 端点 CRUD+test（**真实 34.121.9.233:4000 613ms ok**）+404；embedding CRUD+test（**真实 gte-qwen2 330ms dim=3584**）+404 |
| M5 RAG | s26_m5_rag.py | **12/12** | KB 建（local-fallback-embedding dim=256）→ 文档上传 → parse→embed→**ready** → doc 详情/chunks → **search 真实召回命中**（含 query 关键词）→ KB 删 |
| M6 MCP | s26_m6_mcp.py | **9/9** | 注册 **真实 mock MCP（joker-mock-mcp:9100，streamable_http）** → tools 同步 2 个（calc/echo）→ 工具列表 → 更新 → refresh → 删 |
| M7 Skills | s26_m7_skills.py | **7/7** | 列表 / 手工创建（name+content）/ get 内容回读 / update / 重名 409 / 删 |
| M8 Agent | s26_m8_agents.py | **10/10** | Agent CRUD+四要素配置回读；**真实对话：acme agent 绑 platform-fallback-llm（34.121.9.233:4000，BUG-11 运行时通道）→ 200 + reply='pong'**；删除 |
| M9 BFF/trace/audit | s26_m9_bff_trace.py | **9/9** | **OpenAI-compat `/v1/chat/completions` 经 webconsole→BFF 网关全链路 → 200 + content='pong'**（真实 LLM）；trace sessions+events（含 chat 事件）；audit logs 可查；BFF rate-limits admin 列表（4 维配置） |

**两条真实 LLM 端到端链路均真实执行**（非 mock）：
1. `POST /api/agents/{id}/chat` → agent 运行时 `get_endpoint_internal`（BUG-11 修复通道）→ 真实 vLLM 34.121.9.233:4000 → `pong`
2. `POST /v1/chat/completions`（OpenAI-compat）→ webconsole→BFF 网关→进程内 runtime→同一真实端点 → `pong`

## 三、发现并修复的缺陷

### BUG-15（P1，本卡新发现）— S26 重建后全 `/api/*` 502

- **现象**：S26 重建容器后，经 8080 的所有 REST 接口全部 502（连 baseline 都挂）。
- **根因**：webconsole(nginx) 的 `proxy_pass http://bff:8000;` 用**字面量主机名**。nginx 对字面量 `proxy_pass` 只在容器启动时解析一次并缓存 IP，之后永不重解析——`resolver` 指令只对**变量**形式生效（nginx 官方文档语义）。compose 重建 bff 后其 IP 变化（172.21.0.10 变成 api），nginx 仍向旧 IP `172.21.0.10:8000` 连接 → `connect() failed (111: Connection refused)` → 502。S23 加的 `resolver 127.0.0.11` 因 proxy_pass 是字面量形式而**无效**。
- **铁证**：webconsole 日志 `upstream: "http://172.21.0.10:8000"` + `111: Connection refused`；同时 8080 上非代理路径（SPA/healthz 本地）正常，仅 BFF 代理路径 502。
- **修复**：`deploy/nginx/nginx.conf` 改为变量形式：
  ```
  set $bff_upstream bff;
  proxy_pass http://$bff_upstream:8000;
  ```
  每次请求经 `resolver 127.0.0.11 valid=10s` 重解析 bff 当前 IP。重建 webconsole 后全 `/api/*` 恢复 401（正确鉴权要求），9 模块+基线全 PASS。
- **状态**：已修（S26），已 commit（见 git log）。

### BUG-13/14 修复验证（上轮修复 commit 07866bf，本轮独立复验）

- BUG-13（refresh 死锁）：A4 刷新轮换 PASS——旧 access 过期场景下 refresh 独立可用（BFF `PUBLIC_AUTH_EXACT` 免 access 前置），轮换后旧 refresh 重放整族吊销。
- BUG-14（logout-all 误判公开）：A9 `logout-all` 200 `revoked:2` + A10 两会话 refresh 全 401 PASS——精确匹配后 logout-all 正确走常规 JWT+签名头。
- 本轮同时把 BUG-13/14/15 补登 `03-testing/BUGS.md`（上轮修复时未登记）。

## 四、部署

- **变更**：仅 webconsole 重建（BUG-15 修复，`docker compose up -d --build webconsole`）；其余 6 容器（joker-api / joker-bff / joker-pg / joker-mock-mcp 等）未动，全 healthy。
- **端口关系**：8080(webconsole nginx)→8000(bff)→8001(api)；mock MCP joker-mock-mcp:9100（docker 内网）。
- **验证**：重建后 `GET /api/*` 401（非 502）、`/healthz` 200、SPA 首页 200 text/html；基线+9 模块全量自测通过（即本报告的运行证据）。
- **台账**：`~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md` 已更新 webconsole 条目（nginx 变量式 proxy_pass + 资源占用实测）。
- **环境未变项**：真实 LLM 34.121.9.233:4000、真实 embedding 34.64.61.208:4000 保持可用（本轮多次真实调用成功，OBS-02 端点侧 401 未复现）。

## 五、已知问题 / 移交测试

1. **无阻塞缺陷**。M1-M9 + 基线全 PASS。
2. OBS-02（真实 vLLM 端点侧间歇 401，环境态非代码）本轮 4 次真实调用（baseline 1 + M4 1 + M8 1 + M9 1）全部成功，未复现；按 S25b 结论维持"环境态，不据以判缺陷"。
3. 移交 S27（云天明 浏览器全量测试）关注点：
   - BUG-15 修复后**多次 compose 重建/重启**场景下 8080 代理稳定性（resolver valid=10s 窗口）；
   - 前端页面对 M1-M9 各模块的可视化验收（本报告为接口层，未覆盖 UI）；
   - 真实 LLM 对话在前端 Agent 页面的端到端体验。
4. 自测脚本归档在 `05-temp/s26/`（10 个脚本 + 库），日志在 `03-testing/dev_probe_s26_*.log`（10 个），可复跑。
