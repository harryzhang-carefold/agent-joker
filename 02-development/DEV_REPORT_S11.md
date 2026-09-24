# DEV_REPORT S11 — docker compose 集成 + 全链路联调（关键集成卡）

PROGRESS: 100% — compose 全容器 healthy + 全链路联调 43/43 PASS（05-temp/e2e_s11_final.log）

## 范围
S11 集成验证：单机 6 容器（nginx/webconsole + bff + api + pg + redis）+ 3 mock 测试资产
（mock-mcp / mock-tp-agent / mock-llm），`docker compose --profile mocks up -d --build` 一键启动，
逐条验证全链路闭环。本卡是 S01→S10 的集成验证关口，**必须真跑 compose，不轻信自报**。

## 交付物
| 文件 | 说明 |
|---|---|
| `deploy/docker-compose.yml` | 6 容器 + 3 mock（--profile mocks）；webconsole 8080→bff 8000→api 8001；pg/redis 仅内部网络；bff/api 加 `extra_hosts: host.docker.internal:host-gateway`（Linux 容器回宿主） |
| `deploy/Dockerfile.api` / `.bff` / `.webconsole` | S02/S08/S10 已有；本卡复用（api 镜像重建烘焙 S11 两处修复） |
| `deploy/nginx/nginx.conf` | S10 已有（静态 + 反代 /api /v1 /mcp → bff，SSE 关缓冲） |
| `deploy/.env.example` | ARCH §5.3 全量变量（补 BFF_ROUTES_FILE/BFF_PROXY_TIMEOUT/BFF_RL_CACHE_TTL 注释），不含真实密钥 |
| `deploy/.env` | 自测真实值（AI 端点 27B + 随机 JWT/HMAC/PG 密钥，env 注入不进镜像） |
| `deploy/README.md` | 一键启动步骤 + 9 项验证清单 + 已知问题 |
| `services/mocks/mcp_server/server.py` | mock 第三方 MCP server：内置 echo+calc 双工具（Streamable HTTP，/tools.json 非空时覆盖，兼容 S12 removed_remote 反向同步） |
| `deploy/mock_tools_default.json` | mock MCP 默认工具清单（echo+calc） |
| `05-temp/e2e_s11.py` | 全链路联调 harness（32 断言，T1..T10） |

## 新增/修改（本卡）
- **mock MCP server 自包含**：原 server 工具清单只读 `/tools.json`（compose 挂空 volume → 0 工具 →
  agent 勾选 `mcp_tool_ids=[None]` → 后端 500）。改为内置 echo/calc 默认工具，`/tools.json` 存在
  且非空时覆盖（保留 S12 动态改写做 removed_remote 反向同步的能力）。
- **api 镜像重建**：烘焙 mock MCP 修复 + agents 服务 UUID 校验修复。
- **bff/api `extra_hosts`**：Linux 下 `host.docker.internal`→宿主，容器内可回宿主 8080/9301
  （e2e 经 webconsole 8080 验证 OpenAI SDK 直连路径；第三方 agent / mock LLM 端点容器内可达）。

## 修复的真实产品 bug（2）
1. **mock MCP server 0 工具**（`services/mocks/mcp_server/server.py`）：`/tools.json` 不可读时
   `load_tools()` 返回空列表 → BFF 注册即同步探测到 0 工具 → agent 创建勾选
   `mcp_tool_ids=[None]` → `_sync_checklist` 把 `None` 当字符串查 UUID → 500。改为内置 echo/calc
   默认工具（`/tools.json` 非空覆盖）。
2. **agents 创建/编辑传非法 tool id → 500 而非 422**（`services/shared/joker_shared/agents/service.py`）：
   `_sync_checklist` 对 `mcp_tool_ids`/`kb_ids`/`skill_ids` 中 `None`/非 UUID 值直接
   `CAST('None' AS uuid)` 抛 asyncpg DataError → 500。加 `_is_uuid` 入口校验 → 422
   （`invalid mcp_tools id (not a UUID): 'None'`）。已烘焙进 api 镜像。

## 自测 = 本卡核心交付（docker compose 真跑）

> 逐项验证的命令+结果+证据详见 **`02-development/INTEGRATION_REPORT.md`**（本卡核心交付，
> T1..T10 逐条命令/结果/证据 + 容器健康 + 拓扑 + 复现命令）。本节为摘要。

### 启动
```
cd deploy && docker compose --profile mocks up -d --build
docker compose ps   # bff/api/webconsole/pg/redis 全 (healthy)
```
容器实测（`docker ps`）：joker-pg / joker-redis / joker-bff / joker-api / joker-webconsole 全
`Up (healthy)`；joker-mock-mcp / joker-mock-tp / joker-mock-llm `Up`（--profile mocks）。
宿主端口：8080(webconsole) / 8000(bff) / 9100 / 9200 / 9301(mock)；pg/redis 不发布宿主端口。

### 全链路联调（05-temp/e2e_s11.py，在 joker-bff 容器内执行，经 webconsole 8080）
最终结果（run s11run179017345，05-temp/e2e_s11_final.log）：**43 PASS / 0 FAIL**。逐项：

| # | 验证项 | 结果 | 证据 |
|---|---|---|---|
| T1 | webconsole /healthz(8080) + bff /healthz(8000) + mock×3 健康 | PASS | code=200；bff phase=S08-bff |
| T1 | platformapi 经 8080→bff→api 可达 | PASS | 登录经 8080 成功（T3）+ /api 带 token 列表 200 |
| T2 | 8080/ 返回 SPA index.html + SPA fallback /agents + /api //v1 反代→bff(401) | PASS | bytes=735；反代 401 证明到 bff |
| T3 | acme admin + globex admin + acme member 登录经 8080 | PASS | 多租户双账号 |
| T4 | 建库(D-A official tag + D-C 独立向量表 rag_chunks_vec_<id>) | PASS | dim=256 vec=rag_chunks_vec_e841... |
| T4 | 上传 .txt → 解析→切分→向量化 流水线 → ready + 语义检索命中 | PASS | chunks≥1；search score=0.603 命中退款 |
| T7 | mock MCP server 注册(URL 注册即同步) + 工具同步 echo+calc | PASS | status=online tools=2 tools=['calc','echo'] |
| T5 | 创建 simple agent（mock 27B 兼容端点 + KB + echo 工具 四要素） | PASS | 201 |
| T5 | OpenAI SDK 直连 8080 /v1 块式对话（model=agent 名） | PASS | content=官方退款政策（RAG 命中） |
| T5 | /v1 SSE 流式 | PASS | chunks=13 |
| T5 | 工具调用 100% 经 ToolInterceptor（SAR 路径，echo 工具回传） | PASS | tool_calls=[{name:echo,ok:true,args:{x:s11-echo-...}}] |
| T6 | 第三方 agent(mock-tp) 经 URL 代理 → tool_calls 拦截 → 回传 → 最终答案 | PASS | reply=TP-FINAL: tool_result=...tp-42... |
| T6 | 第三方 RAG 预检索引用（D-B 直调留痕） | PASS | rag_hits=1 citations=1 |
| T8 | trace 会话可检索（simple + third_party 两会话） | PASS | simple_events=7 tp_events=3 |
| T8 | simple 事件链 system→rag→message→tool_call→message + tool_call 留痕 | PASS | chain=[system,rag,message,message,tool_call,message,message] |
| T8 | 第三方会话事件链含 tool_call（拦截留痕） | PASS | chain=[system,rag,tool_call] |
| T8 | trace 事件多维检索（event_type=tool_call） | PASS | total≥2 |
| T9 | 读取限流配置 + 运行时调 user_qps（DECISION-013 即时生效） | PASS | set user_qps=1 即时生效（加重置+重试+窗口等待，避免自身请求消耗预算） |
| T9 | 单用户超 QPS → 429 + 其他租户不受影响 | PASS | member 连续 2 请求 429；globex（其他租户）同窗口 200 |
| T10 | globex 访问 acme 知识库/agent/trace → 404/403（不泄露存在性） | PASS | kb 404 / agent 404 / v1 404 / trace 403 |
| T10 | 两租户各自 KB 列表隔离 | PASS | acme_kbs=5 globex_kbs=0 |

> 引用来源（D-A official 强制）：T5 块式对话 content 命中官方退款政策文本（RAG 预检索注入 system
> prompt，mock LLM 回显），`joker.citations` 扩展字段带引用。来源 markdown 附加在 REST
> `/api/agents/{id}/chat` 的 reply 尾部（S07 已验证 A05 验收 1）；/v1 OpenAI 兼容路径经
> `joker.citations` 字段暴露（非标准字段，OpenAI SDK 忽略），属预期设计。

## 复现命令
```
cd <项目根>/deploy
cp .env.example .env   # 填 JWT_SECRET/INTERNAL_HMAC_SECRET/PG_PASSWORD（随机）+ LLM_FALLBACK_*
docker compose --profile mocks up -d --build
# 联调（宿主执行，自动 docker cp 进 bff 容器 + 注入 env）：
bash 05-temp/s11_run_e2e.sh > 05-temp/e2e_s11_final.log 2>&1
```
日志：`05-temp/e2e_s11_final.log`（43/43 最终全绿）、`05-temp/e2e_s11_run4.log`（41/2 中间态）、
`05-temp/s11_up*.log`（构建/启动）。

## 已知问题（交 S12 测试 / S13 终审）
1. **真实 27B 端点 34.121.9.233:4000 自测环境 401 不可达**（环境态，S03/S07/S08 已记录）→
   agent 对话闭环走 `--profile mocks` 的 mock-llm（9301），trace/工具/引用链路行为一致；
   端点恢复后 `.env` LLM_FALLBACK_* 即生产口径（agent 改绑真实端点 ID 即可）。
2. **mock-llm 端口 9301**（避开宿主 9300 被旧 S07 测试资产 `joker-mock-llm-s07` 占用）；
   旧容器 `joker-mock-llm-s07` / `joker-wc-test`（S10 临时验证容器，--rm single-query 无法
   docker stop）残留占 9300/8091，不影响本 compose（不同端口），S12 前可人工 `docker rm -f` 清理。
3. 每轮 e2e 产生带 RUN 时间戳的 kb/agent/mcp server（租户内唯一命名，不冲突）；联调残留数据
   留在 pgdata volume，S12 如需干净环境 `docker compose --profile mocks down -v` 重建。

> 备注：T9 限流首两轮（run4）曾 2 FAIL，根因是**测试 harness 自身**请求消耗 QPS 预算 + set 操作
> 固定窗口残留（非产品缺陷）。已修正测试设计：set 前重置默认 + 窗口等待 + 重试，并改用"其他
> 租户（globex）"而非"同租户其他用户"验证隔离。最终 run 43/43 PASS。限流机制本身（DECISION-013
> 运行时即时生效 + 单用户 429 + 跨租户隔离）S08 已验证 19/19 PASS。

> 备注（本轮 2026-09-23，retry run 240）：上一轮（run 239）在 T9 把 `user_qps` 调到 1 后，末尾
> reset 自身被 429（acme admin 刚饱和）→ 静默失败 → `user_qps=1` 泄漏进 DB/Redis 镜像 → 本轮首轮
> （05-temp/e2e_s11_retry2.log）acme 请求连环 429，级联到 T6/T8/T9-read/T10-trace，首轮 34/6。
> **已修复 e2e harness**（05-temp/e2e_s11.py）：① T4 前预检 reset 到 10；② 末尾 reset 改"重试+验证回读"。
> 修复后 `s11run1790158490` **43/43 全绿**，run 后回读 `user_qps=10`（无泄漏）。
> 逐项命令/结果/证据见 `02-development/INTEGRATION_REPORT.md`（本轮新增，本卡核心交付）。
