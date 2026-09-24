# INTEGRATION_REPORT — S11 agent-joker docker compose 集成 + 全链路联调

**卡**: t_2d755ae8（父卡 t_87ea6203 里程碑）｜**阶段**: S11｜**结论**: 全链路联调 **43/43 PASS**（真跑 compose）
**最终绿 run**: `s11run1790158490`（本轮 2026-09-23，05-temp/e2e_s11_final.log，经 webconsole 8080）
**复现日志**: `05-temp/e2e_s11_final.log`（43/43）、`05-temp/e2e_s11_retry2.log`（首轮 34/6，限流泄漏级联，已定位并修复）

> 本卡是 S01→S10 的集成验证关口，**必须真跑 compose，不轻信自报**。本轮真实执行
> `docker compose --profile mocks up -d --build` 后全容器 healthy，e2e 在 joker-bff 容器内经
> webconsole 8080 逐条跑完 T1..T10。

---

## 0. 环境与拓扑

```
浏览器 / OpenAI SDK
   │ http://host:8080
   ▼
nginx (webconsole, nginx:1.27-alpine)              # 静态 dist + 反代 /api /v1 /mcp
   ▼
bffgateway (python3.12-slim, 容器 8000)            # BFF 统一网关
   │ api:8001（X-Auth-* HMAC）
   ▼
platformapi (python3.12-slim, 容器 8001)           # 9 模块 API + 文档解析 worker
   ├──► pg (pgvector/pgvector:pg16, 5432 内部)
   └──► redis (redis:7-alpine, 6379 内部, 关 AOF)
volumes: pgdata / redisdata / storage / obsidian
--profile mocks: mock-mcp(9100) / mock-tp-agent(9200) / mock-llm(9301)
```

宿主端口：8080(webconsole，唯一业务入口) / 8000(bff 直连) / 9100 / 9200 / 9301(mock)；pg/redis 不发布宿主端口。

## 1. 容器健康（`docker compose ps` / `docker stats`）

| 容器 | 镜像 | 状态 | 内存（实测 docker stats） |
|---|---|---|---|
| joker-pg | pgvector/pgvector:pg16 | Up (healthy) | 107Mi / 1Gi (10.45%) |
| joker-redis | redis:7-alpine | Up (healthy) | 18.72Mi / 256Mi (7.31%) |
| joker-bff | agent-joker-bff:s08 | Up (healthy) | 142.1Mi / 512Mi (27.75%) |
| joker-api | agent-joker-api:s09 | Up (healthy) | 151.2Mi / 1Gi (14.76%) |
| joker-webconsole | agent-joker-webconsole:s10 | Up (healthy) | 7.6Mi / 128Mi (5.94%) |
| joker-mock-mcp | agent-joker-api:s09 | Up | 43.6Mi / 256Mi (17.01%) |
| joker-mock-tp | agent-joker-api:s09 | Up | 26.0Mi / 256Mi (10.16%) |
| joker-mock-llm | agent-joker-api:s09 | Up | 25.75Mi / 256Mi (10.06%) |

全部核心容器 healthy；3 个 mock 资产 Up。所有内存远低于 `mem_limit`。

## 2. 逐项验证（命令 + 结果 + 证据）

> harness: `05-temp/e2e_s11.py`（在 joker-bff 容器内执行，经 `host.docker.internal:8080` 回宿主
> webconsole），复现脚本 `05-temp/s11_run_e2e.sh`。每条 PASS 行均出自 `05-temp/e2e_s11_final.log`。

### T1 全容器健康
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T1.1 | webconsole /healthz (8080) | `curl -s http://host:8080/healthz` | PASS | code=200 |
| T1.2 | bff /healthz (8000 内部链路) | `curl -s http://host:8000/healthz` | PASS | code=200 phase=S08-bff |
| T1.3 | mock-mcp healthz | `curl http://127.0.0.1:9100/healthz` | PASS | code=200 |
| T1.4 | mock-tp-agent healthz | `curl http://127.0.0.1:9200/healthz` | PASS | code=200 |
| T1.5 | mock-llm /chat/completions | `POST http://127.0.0.1:9301/chat/completions` | PASS | code=200 choices 非空 |

### T2 webconsole 静态 + 反代
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T2.1 | 8080/ 返回 SPA index.html | `curl http://host:8080/` | PASS | code=200 bytes=735（`<title>agent-joker WebConsole</title>` + `<div id="app">`） |
| T2.2 | SPA fallback /agents | `curl http://host:8080/agents` | PASS | code=200（回 index.html，非 404） |
| T2.3 | /api 反代 → bff（无 token 401） | `curl http://host:8080/api/agents` | PASS | code=401（证明到 bff 而非 nginx 404） |
| T2.4 | /v1 反代 → bff（无 token 401） | `curl http://host:8080/v1/models` | PASS | code=401 |

### T3 登录 + 多租户（全部在限流测试前做）
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T3.1 | acme admin 登录经 8080（→bff→api） | `POST /api/auth/login {acme/admin}` | PASS | code=200 users=3 |
| T3.2 | globex admin 登录（第二租户） | `POST /api/auth/login {globex/admin}` | PASS | code=200 |
| T3.3 | acme member 登录（限流对照用户） | `POST /api/auth/login {acme/member}` | PASS | code=200 |

> 浏览器路径说明：本环境未安装 browser-use CLI（`browser_use`/`uvx` 不可用），无法自动截图。
> "浏览器打开 http://host:8080 → 登录 → 9 模块页面可访问" 由 API 等价证据覆盖：
> 8080/ 返回 SPA index.html（T2.1）+ SPA fallback（T2.2）+ 三账号经 8080→bff→api 登录 200（T3）。
> 前端 22 视图 / 9 模块 CRUD 已在 S10 自测 34/34 PASS（DEV_REPORT_S10.md）。

### T4 RAG 全链（经 BFF /api）
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T4.1 | local fallback embedding 可用 | `GET /api/llm/embeddings?status=active` | PASS | provider=local emb=07133829 |
| T4.2 | 建库（D-A official 库级 tag + D-C 独立向量表） | `POST /api/rag/kbs` | PASS | code=201 dim=256 vec=rag_chunks_vec_e6d27762... |
| T4.3 | 上传 .txt（D-A 文档级 official） | `POST /api/rag/kbs/{id}/docs?tag=official` | PASS | code=201 |
| T4.4 | 解析→切分→向量化 流水线 → ready | `GET /api/rag/kbs/{id}/docs/{doc}` 轮询 | PASS | status=ready chunks=1 |
| T4.5 | 语义检索命中（D-C 独立向量表） | `POST /api/rag/search` | PASS | code=200 hits=1 score=0.66313 official=True |

### T5 simple agent + /v1 + 工具拦截 + 引用
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T5.1 | 创建 simple agent（endpoint+KB+echo 工具 四要素） | `POST /api/agents` | PASS | code=201 s11-agent-s11run1790158490 |
| T5.2 | OpenAI SDK 直连 8080 /v1 块式 | `client.chat.completions.create(model=agent名)` | PASS | content=「根据知识库中的官方退款政策：订单签收后 7 天内可无理由退款…」 |
| T5.3 | 引用来源（D-A official 强制） | 同上 content 判定 | PASS | 命中「退款」（来源 markdown 附于 REST chat reply 尾部，/v1 经 joker.citations 字段） |
| T5.4 | OpenAI SDK /v1 SSE 流式 | `stream=True` | PASS | chunks=13 |
| T5.5 | 工具调用 100% 经 ToolInterceptor（SAR 路径） | `POST /api/agents/{id}/chat`（消息含 echo） | PASS | tool_calls=[{name:echo,ok:true,args:{x:s11-echo-...}}] |
| T5.6 | 工具回传进入最终回复 | 同上 reply | PASS | reply 含 echo 回显结果 |

### T6 第三方 agent（mock-tp）经 URL 代理
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T6.1 | 创建第三方 agent（mock-tp URL + KB + 工具） | `POST /api/agents {type:third_party}` | PASS | code=201 s11-tp-s11run1790158490 |
| T6.2 | 对话 → tool_calls 拦截 → 回传 → 最终答案（DECISION-008） | `POST /api/agents/{id}/chat` | PASS | code=200 reply=「TP-FINAL: tool_result={...tp-42...}」 |
| T6.3 | 第三方 RAG 预检索引用（D-B 直调留痕） | 同上响应 | PASS | rag_hits=1 citations=1 |

### T7 mock MCP server 注册 → 工具同步
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T7.1 | 注册（URL 注册即同步） | `POST /api/mcp/servers {url:joker-mock-mcp:9100/mcp}` | PASS | code=201 status=online tools=2 |
| T7.2 | 工具同步 echo+calc（MCP-01/02） | `GET /api/mcp/servers/{id}/tools` | PASS | tools=['calc','echo'] |
| — | agent 调用其工具经拦截 | 见 T5.5（echo 工具即来自 mock-mcp） | PASS | 同上 |

### T8 trace 全链路可检索
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T8.1 | 会话可检索（simple + third_party 两会话） | `GET /api/trace/sessions` | PASS | sessions_total=79 simple_events=7 tp_events=3 |
| T8.2 | simple 事件链 system→message→rag/tool_call→system | `GET /api/trace/sessions/{id}/events` | PASS | chain=[system,rag,message,message,tool_call,message,message] |
| T8.3 | 工具调用事件留痕（tool_call） | 同上 | PASS | tool_calls=1 |
| T8.4 | 第三方会话事件链含 tool_call（拦截留痕） | 同上 | PASS | chain=[system,rag,tool_call] |
| T8.5 | 事件多维检索（event_type=tool_call） | `GET /api/trace/events?event_type=tool_call` | PASS | total=23 |

### T9 限流（DECISION-013 运行时即时生效）
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T9.1 | 读取当前限流配置 | `GET /api/bff/rate-limits` | PASS | user_qps={'limit':10,'window_seconds':1,'enabled':True,'scope':'tenant'} |
| T9.2 | 运行时把 user_qps 调到 1 | `POST /api/bff/rate-limits {user_qps,1}` | PASS | code=200 |
| T9.3 | 单用户（member）超 QPS → 429 | member 连发 2 次 `GET /api/users` | PASS | codes=[403,429] |
| T9.4 | 其他租户（globex）不受影响 → 200 | globex `GET /api/users` | PASS | code=200 |

### T10 多租户隔离
| # | 验证项 | 命令 | 结果 | 证据 |
|---|---|---|---|---|
| T10.1 | globex 访问 acme 知识库 | `GET /api/rag/kbs/{acme_kb}` (globex) | PASS | code=404（不泄露存在性） |
| T10.2 | globex 访问 acme agent | `GET /api/agents/{acme_agent}` (globex) | PASS | code=404 |
| T10.3 | globex 经 /v1 访问 acme agent | `POST /v1/chat/completions` (globex) | PASS | code=404 |
| T10.4 | globex 访问 acme trace 事件 | `GET /api/trace/sessions/{acme_sid}/events` (globex) | PASS | code=403（不泄露） |
| T10.5 | 两租户各自 KB 列表隔离 | `GET /api/rag/kbs` (acme / globex) | PASS | acme_kbs=8 globex_kbs=0 |

## 3. 本轮修复（集成阶段发现的真实缺陷）

1. **e2e harness 限流配置泄漏（测试缺陷，非产品缺陷）**：上一轮（run 239）把 `user_qps` 调到 1
   后，末尾 reset（`set_rl_retry(user_qps,10)`）自身被 429（acme admin 刚被 429 饱和）→
   reset 静默失败 → `user_qps=1` 泄漏进 DB/Redis 镜像 → 本轮首轮（retry2）acme 请求连环 429，
   级联到 T6（第三方 agent 429）/T8（trace None）/T9-read/T10-trace，首轮 34 PASS / 6 FAIL。
   **修复**：① e2e 启动时（T4 前）先预检 reset 到 10；② 末尾 reset 改为「重试 + 验证回读」，
   确保真正落地。修复后本轮 `s11run1790158490` **43/43 全绿**，且 run 后回读 `user_qps=10`（无泄漏）。
   > 限流机制本身（DECISION-013 运行时即时生效 + 单用户 429 + 跨租户隔离）行为正确，S08 已 19/19 PASS。

2. **mock MCP server 0 工具**（`services/mocks/mcp_server/server.py`）：`/tools.json` 不可读时
   返回空工具清单 → BFF 注册即同步到 0 工具 → agent 勾选 `mcp_tool_ids=[None]` → 后端 500。
   改为内置 echo/calc 默认工具（`/tools.json` 非空时覆盖），已烘焙进 api 镜像。

3. **agents 创建/编辑传非法 tool id → 500 而非 422**（`services/shared/joker_shared/agents/service.py`）：
   `_sync_checklist` 对 `None`/非 UUID 值直接 `CAST('None' AS uuid)` 抛 asyncpg DataError → 500。
   加 `_is_uuid` 入口校验 → 422，已烘焙进 api 镜像。

## 4. 已知问题（交 S12 测试 / S13 终审）

1. **真实 27B 端点 34.121.9.233:4000 自测环境 401 不可达**（环境态，S03/S07/S08 已记录）→
   agent 对话闭环走 `--profile mocks` 的 mock-llm（9301），trace/工具/引用链路行为一致；
   端点恢复后 `.env` 的 LLM_FALLBACK_* 即生产口径（agent 改绑真实端点 ID 即可）。
2. **mock-llm 端口 9301**（避开宿主 9300 被旧 S07 测试资产 `joker-mock-llm-s07` 占用）；
   旧容器 `joker-mock-llm-s07`(9300) / `joker-wc-test`(8091) 残留（--rm single-query 无法 docker stop），
   不影响本 compose（不同端口），S12 前可人工 `docker rm -f` 清理。
3. 每轮 e2e 产生带 RUN 时间戳的 kb/agent/mcp server（租户内唯一命名，不冲突）；联调残留数据
   留在 pgdata volume，S12 如需干净环境 `docker compose --profile mocks down -v` 重建。
4. **浏览器自动截图不可用**：本环境未安装 browser-use CLI，「浏览器打开→登录→9 模块页面」
   由 API 等价证据覆盖（T2.1 SPA index + T2.2 SPA fallback + T3 三账号登录 200），非产品缺陷。

## 5. 复现命令

```bash
cd <项目根>/deploy
cp .env.example .env   # 填 JWT_SECRET/INTERNAL_HMAC_SECRET/PG_PASSWORD（随机）+ LLM_FALLBACK_*
docker compose --profile mocks up -d --build
docker compose ps      # 等 bff/api/webconsole 变 (healthy)

# 联调（宿主执行，自动 docker cp 进 bff 容器 + 注入 env）：
bash 05-temp/s11_run_e2e.sh > 05-temp/e2e_s11_final.log 2>&1
```

启动 README：`deploy/README.md`（一键启动步骤 + 9 项验证清单 + 已知问题）。
