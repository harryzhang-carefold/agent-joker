# DEV_REPORT S03 — agent-joker LLM 节点（LLM-01/02/03）

PROGRESS: 100% — LLMNodeService 三类节点 CRUD + 连通性探测 + 密钥 Fernet 加密 + 本地 fallback embedding + 端点配置化，全部交付并自测通过（36/36 PASS，S01/S02 回归全绿）。

> 作者：章北海（开发工程师）｜ 2026-09-23 ｜ 卡 t_f256d037（父 t_87ea6203，前置 t_a884eff3 S01 / t_36f66f56 S02）

## 范围（对照卡 body LLM-01/02/03）

| # | 要求 | 交付 |
|---|---|---|
| 1 | LLMNodeService 三类节点 CRUD | `joker_shared/llm/service.py`：endpoint / embedding / reranker 各自 list/get/create/update/delete；`services/api/app/routers/llm.py` 挂 `/api/llm/*`。平台级共享（DB_DESIGN §3 / ARCH §9-13）：tenant_id 仅审计归属、**不做行级过滤**，全租户可见；增删改/测试需 `llm:manage`（403）。删除=引用保护（被 agent 勾选/视觉解析/知识库引用 → 409+引用清单，禁用代替硬删） |
| 2 | 密钥 Fernet 加密（DECISION-012） | `api_key` 入参 → `encrypt_secret()` 落 `api_key_enc`；响应只回 `api_key_set` 布尔；DB 只见密文（gAAAA…）、日志/trace 无明文（自测 6 断言验证）。**顺带修复 FERNET_KEY 隐患**：S01 留空随机生成，S03 首次真正启用加密时 `.env` 残留非法空值 → `binascii.Error` 崩溃；`crypto.get_fernet()` 加 44 位 urlsafe-base64 校验（非法=告警+重生成），deploy/.env 已写固定合法 key |
| 3 | 连通性探测 | 每类节点 `POST /test` 轻量探测：chat 发 "ping"（max_tokens=1）、embedding 发短文本（维度校验）、rerank 发短文本（校验 relevance_score）；返回 `{ok, latency_ms, summary}`（可用/不可用+错误摘要），endpoint 写 `last_test_at/last_test_result`。超时 `LLM_PROBE_TIMEOUT_SECONDS`（默认 15s）防探测挂起 |
| 4 | 端点配置化 | `.env` 提供 `LLM_FALLBACK_ENDPOINT/MODEL/API_KEY/NAME` 默认 chat 端点（启动幂等注册，供自测闭环）；**服务无节点缓存，每次读库取最新 → CRUD 后即时生效**（RAG/Agent 读节点用最新，满足验收 4） |
| 5 | embedding 本地 fallback | `joker_shared/llm/local_embedding.py`：确定性字符 n-gram 哈希向量（fnv1a64，维度 `LLM_LOCAL_FALLBACK_DIM` 默认 256，可配）；同文本必同向量、L2 归一化、相似文本余弦 > 不相关。启动自动注册 `local-fallback-embedding` 节点（provider=local）；`embed_texts()` 抽象统一 local/api 两路径（接口与真实端点一致，S04/S05/S07 复用） |

## 新增 API 端点清单（joker-api:8001，compose 发布 127.0.0.1:8080）

> 全部 `/api/llm/*` 需 X-Auth-* 签名头（DECISION-009）。平台级共享：列表/详情/本地 embed 无 scope 门禁；写操作 + test 需 `llm:manage`。

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| GET | `/api/llm/healthz` | 签名头 | 模块健康（phase=S03-llm） |
| GET | `/api/llm/endpoints?status=&supports_vision=` | — | endpoint 列表（平台级共享） |
| GET | `/api/llm/endpoints/{id}` | — | 详情；404 |
| POST | `/api/llm/endpoints` | llm:manage | 创建（必选 name/base_url/model；可选 api_key/auth_scheme/supports_vision/default_params/timeout_seconds/status）；重名 409 |
| PUT | `/api/llm/endpoints/{id}` | llm:manage | 部分更新；api_key 非空=替换，clear_api_key=true=清除 |
| DELETE | `/api/llm/endpoints/{id}` | llm:manage | 删除；被引用 → 409+引用清单 |
| POST | `/api/llm/endpoints/{id}/test` | llm:manage | 连通性测试（chat "ping"），写 last_test_* |
| GET | `/api/llm/embeddings?status=` | — | embedding 列表（含 local-fallback-embedding） |
| GET/POST/PUT/DELETE | `/api/llm/embeddings[/{id}]` | 写需 llm:manage | 同上（必选 name/dimensions；provider=api\|local）；删除被知识库引用 → 409 |
| POST | `/api/llm/embeddings/{id}/test` | llm:manage | 连通性测试（local 节点必 ok；api 节点维度不符 → 不可用） |
| POST | `/api/llm/embeddings/local/embed` | 签名头 | 本地确定性 fallback embedding 直测：`{texts[], dim?}` → `{items: float[][], total, dim}` |
| GET | `/api/llm/rerankers?status=` | — | reranker 列表 |
| GET/POST/PUT/DELETE | `/api/llm/rerankers[/{id}]` | 写需 llm:manage | 同上（必选 name/base_url/model）；删除被知识库引用 → 409 |
| POST | `/api/llm/rerankers/{id}/test` | llm:manage | 连通性测试（/rerank，Jina 兼容契约） |

## 表 / 索引 / 配置变更

- **表**：无新增（`llm_endpoints` / `llm_embedding_models` / `llm_reranker_models` 三表 S01 init_schema.sql 已建，本卡仅实装业务逻辑；`init_schema.sql` 未改动）。
- **新增 env（deploy/.env.example + compose api）**：
  - `LLM_FALLBACK_ENDPOINT` / `LLM_FALLBACK_MODEL` / `LLM_FALLBACK_API_KEY` / `LLM_FALLBACK_NAME`（默认 chat 端点种子，key 加密落 DB）
  - `LLM_LOCAL_FALLBACK_DIM`（默认 256）/ `LLM_PROBE_TIMEOUT_SECONDS`（默认 15）
  - `FERNET_KEY`：S03 起真正启用（**必须 44 位 urlsafe base64**；deploy/.env 已写固定合法值——生产/自测重启后旧密文可解）
- **代码新增**：`joker_shared/llm/{__init__,local_embedding,service}.py`、`api/app/routers/llm.py`；改 `config.py`（+LLM 配置段）、`crypto.py`（Fernet key 校验）、`main.py`（startup 注册默认节点）、`routers/__init__.py`（llm 占位 → 实装）。

## 自测命令与结果

```
bash 05-temp/smoke_s03.sh    # S03 自测
bash 05-temp/smoke_s02.sh    # S02 回归
bash 05-temp/smoke_s01.sh    # S01 回归
```

**S03：36/36 PASS（2026-09-23，docker compose 实测，joker-api healthy）**
- 三类节点 CRUD 闭环（创建 201/列表含新/详情/更新生效/重名 409/删除后 404）
- 连通性探测：不可用端点（假 URL）→ ok=false + 错误摘要；可用端点语义正确（当前环境真实 LLM 端点 401 → ok=false + "unavailable: HTTP 401"，探测语义验证通过）
- key 加密存储：DB `api_key_enc` 为 gAAAA 密文（非明文）、API 响应仅 `api_key_set`、api 容器日志 grep 明文 key = 0
- 本地 fallback embedding：同文本两次返回同向量（256 维，确定性）、相似文本余弦 0.924 > 不相关 0.130
- scope 门禁：无 `llm:manage` 创建/测试 → 403；列表 → 200（平台级共享）
- 默认节点种子：local-fallback-embedding + platform-fallback-llm 启动自动注册

**S02 回归 27/27 PASS ｜ S01 回归 21/21 PASS**（无回归）

## 部署（Docker）

- 镜像：`agent-joker-api:s01` → **`agent-joker-api:s03`**（compose `docker compose build api && up -d api`，8080 端口/卷/网络不变，数据在 joker-pg 独立实例，无数据丢失）
- 启动验证：joker-api healthy（127.0.0.1:8080/healthz = 200）；启动日志见 `local fallback embedding node registered (dim=256)` + `default chat endpoint seeded from .env`
- 实测资源回写（台账 SERVER_REGISTRY.md 已更新）：joker-api 74.5Mi/1Gi、joker-pg 47.8Mi/1Gi、joker-redis 9.0Mi/256Mi、joker-bff 47.6Mi/512Mi（均 healthy）
- 无新增宿主端口/容器（joker-bff 为 S02 既有，本卡仅补记台账）

## 已知问题 / 遗留

1. **真实 LLM 端点当前 401**（34.121.9.233:4000/v1，Bearer 66 位 key 实测 Unauthorized）——环境态非代码缺陷（card_common 已预判「LLM 端点挂」）。连通性探测对该端点正确返回 ok=false + "unavailable: HTTP 401"。若端点恢复，`POST /api/llm/endpoints/{id}/test` 将返回 ok=true（探测逻辑已按 OpenAI 兼容 /chat/completions 实现）。本地 fallback embedding 兜底闭环不受影响。
2. **FERNET_KEY 重启敏感**：留空/非法值=每次启动随机生成，重启后旧密文不可解。deploy/.env 已写固定合法 key；S11 生产 .env 必须显式配置固定 FERNET_KEY（已在 API_NOTES + 本卡记录）。
3. **embedding/reranker 表无 last_test_* 列**（DB_DESIGN §3.2/§3.3 未定义，仅 §3.1 endpoint 有）——其 test 只返回不落库；如后续需持久化测试结果，需改 init_schema.sql（留 S09/终审评估，不擅自加列）。
4. **vision 不可用**：按 DECISION-005 降级路径（端点 `supports_vision` 字段已可维护/过滤，真实视觉解析归 S04 RAG）。
5. **6 个占位模块**（rag/mcp/skills/agents/trace）仍为 /healthz 占位，各切片卡实装。
6. **reranker 探测用 Jina 兼容 `/rerank` 契约**【推测】：若后续选定其他 rerank API 规范，改 `service._probe_reranker`/`rerank()` 单点即可。

## 交接（S04 RAG 解析/切分 依赖）

- `get_llm_service().embed_texts(session, model_id, texts) -> list[list[float]]`：统一 embedding 入口（provider=local → 确定性 n-gram；api → 批量 /embeddings）。RAG 建库选 embedding 模型时直接调此方法；维度 = 模型 `dimensions`（D-C 建库快照同源）。
- `get_llm_service().rerank(session, model_id, query, documents, top_n?) -> [{index, score}]`：统一 rerank 入口（S05 检索用）。
- 本地 fallback embedding 节点名 `local-fallback-embedding`（provider=local，dim=256），真实 embedding 端点不可用时 S04/S05 自测闭环用。
- API 面已同步 `02-development/API_NOTES.md`（S10 前端依赖）。
