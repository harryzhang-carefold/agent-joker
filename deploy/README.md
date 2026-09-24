# agent-joker — 部署与一键启动（S11 docker compose 集成）

> 单机 Docker Compose 自测环境（ARCHITECTURE §5.1/§5.2 拓扑，DECISION-018）。
> **验收标准 = 本地 compose 一键启动 + 功能正常**（不查 CI、不验远端）。
> 本机要求：Docker Engine + Compose v2（自测环境 Docker 29.7.2 / compose v5.5.0）。

## 1. 拓扑（6 容器 + mock 测试资产）

```
浏览器 / OpenAI SDK
   │ http://host:8080
   ▼
nginx (webconsole, nginx:1.27-alpine)          # 静态 dist + 反代 /api /v1 /mcp
   │
   ▼
bffgateway (python3.12-slim, 容器 8000)         # BFF 统一网关（限流/JWT/路由/OpenAI 兼容/ToolInterceptor/平台 MCP）
   │  api:8001（X-Auth-* HMAC，DECISION-009）
   ▼
platformapi (python3.12-slim, 容器 8001)        # 9 模块业务 API + 文档解析 worker（同容器，进程内队列）
   │
   ├──► pg (pgvector/pgvector:pg16, 5432 内部)  # 34 表 + 每库独立向量表（D-C）
   └──► redis (redis:7-alpine, 6379 内部)       # 限流计数/黑名单/短期记忆/工具 schema 缓存（关 AOF）

volumes: pgdata / redisdata / storage(/data/storage LocalFS) / obsidian(/data/obsidian-vault)

--profile mocks 测试资产（默认不启动）：
   mock-mcp (9100, 宿主+内部)      Streamable HTTP mock MCP server（echo/calc 双工具）
   mock-tp-agent (9200, 宿主+内部)  mock 第三方 agent（OpenAI 兼容 + /tool_results 回传）
   mock-llm (9301, 宿主+内部)       mock LLM（OpenAI 兼容，确定性闭环；真实 27B 不可达时用）
```

宿主端口：
- **8080** → webconsole（唯一业务入口：前端 + /api + /v1 + /mcp）
- **8000** → bff 直连（自测/调试）
- 9100/9200/9301 → mock 资产（仅 `--profile mocks`；9301 避开宿主 9300 旧测试资产）
- pg/redis **不发布宿主端口**（仅容器网络，避免与共享基础设施冲突）

## 2. 一键启动

```bash
cd <项目根>/deploy
cp .env.example .env          # 填 JWT_SECRET / INTERNAL_HMAC_SECRET / PG_PASSWORD（随机即可，无真实密钥要求）
                              # 自测建议填 LLM_FALLBACK_ENDPOINT/MODEL/API_KEY（真实 27B）；
                              # 不可达时 agent 对话仍可用 mock-llm 端点闭环（见验证清单 T5）
docker compose --profile mocks up -d --build
docker compose ps             # 等 bff/api/webconsole 变 (healthy)
```

> 镜像构建：Dockerfile.webconsole 多阶段 node22→nginx（构建期生成 dist，一键可复现）；
> Dockerfile.bff / Dockerfile.api 为 python3.12-slim + 项目 requirements。
> 首次构建需拉基础镜像 + npm ci + pip install（约 5-15 分钟，视网络）。

停止 / 重建：
```bash
docker compose --profile mocks down          # 保留 volumes（数据/库）
docker compose --profile mocks down -v       # 连同 volumes 清空（完全干净）
```

## 3. 配置（.env，全量变量见 .env.example）

| 关键项 | 说明 |
|---|---|
| `JWT_SECRET` / `INTERNAL_HMAC_SECRET` | 随机 64 位 hex，二者不同（DECISION-002/009） |
| `PG_PASSWORD` | PG 密码（compose 内注入） |
| `LLM_FALLBACK_ENDPOINT/MODEL/API_KEY` | 启动时幂等注册默认 27B chat 端点（OpenAI 兼容 base_url）；key Fernet 加密落库 |
| `LLM_LOCAL_FALLBACK_DIM` | 本地 fallback embedding 维度（默认 256，确定性 n-gram 哈希） |
| `BFF_RATE_LIMIT_TENANT_QPS/USER_QPS/LOGIN_IP_PER_MIN` | 限流默认 50/10/5（DECISION-013，运行时可经 API 即时调） |
| `TRACE_RETENTION_DAYS` / `AUDIT_RETENTION_DAYS` | 保留天数（默认 90，D-D，月分区 + DROP PARTITION） |
| `SEED_TENANT_CODE/SEED_ADMIN_USERNAME/SEED_ADMIN_PASSWORD` | 自测种子租户 admin（另有 globex 供跨租户验收） |
| `FERNET_KEY` | 留空=启动随机生成（**重启后旧密文不可解，生产必须固定 44 位 urlsafe base64**） |

密钥一律 `.env` 注入，不进镜像/日志（DECISION-012）。

## 4. 验证清单（S11 联调口径，逐条对应 INTEGRATION_REPORT.md）

1. **容器健康**：`docker compose ps` 全部 `Up (healthy)`（bff/api/webconsole/pg/redis）。
2. **前端**：浏览器 `http://localhost:8080` → 登录（种子 `acme` / `admin` / 密码=SEED_ADMIN_PASSWORD）→ 9 模块页面可访问（auth/iam/llm/rag/storage/mcp/skills/agents/trace）。
3. **RAG 全链**（经 8080→bff→api）：建库（local fallback embedding + D-A official tag）→ 上传 .txt → 状态机 `uploaded→parsing→splitting→embedded→ready` → 语义检索命中。
4. **agent 对话**：创建 simple agent（mock 27B 兼容端点 + KB + echo 工具）→ OpenAI SDK 直连 `http://localhost:8080/v1/chat/completions`（`model=<agent 名>`）块式 + SSE → 工具调用 100% 经 ToolInterceptor（trace tool_call 留痕）→ 官方来源强制引用。
5. **第三方 agent**（mock）：经 URL 代理对话 → 平台拦截 tool_calls 代执行 → 回传 → 最终答案（DECISION-008 闭环）。
6. **mock MCP server 注册**：`POST /api/mcp/servers`（url=http://joker-mock-mcp:9100/mcp，容器内）→ 注册即同步 echo+calc → agent 勾选后经拦截器调用。
7. **trace 全链路**：`GET /api/trace/sessions` + `/sessions/{id}/events`（{id}=PK）可检索 system→message→rag/tool_call 事件链。
8. **限流**：`POST /api/bff/rate-limits` 把 `user_qps` 调到 1 → 单用户连发 → 429（含 retry_after）；另一用户 200 不受影响。
9. **多租户隔离**：globex token 访问 acme 的 kb/agent/trace → 404/403（不泄露存在性）。

## 5. 已知问题（环境态，非产品缺陷）

- 真实 27B 端点（34.121.9.233:4000）在自测环境曾 401 不可达（S03/S07/S08 已记录）→
  agent 对话闭环走 `mock-llm`（`--profile mocks`），trace/工具/引用链路行为一致；
  端点恢复后 `.env` 的 LLM_FALLBACK_* 即生产口径（agent 改绑真实端点 ID 即可）。
- 宿主 8080 由 webconsole 占用；如需调试 api 直连，compose 注释处有 127.0.0.1:18080:8001 备用发布（默认关）。

> **生产部署**：必读 [`PROD_DEPLOY.md`](PROD_DEPLOY.md)（生产 .env 必填项/生成方式/安全 checklist/备份/与自测差异）。
