# API_NOTES — agent-joker（S01 后端骨架 API 面）

> 前端（S10）与后续切片开发依赖此文件。S01 交付的 PlatformAPI 端点全量清单。
> 约定：
> - 服务端口：容器内 8001，compose 发布 127.0.0.1:8080（S01 最小集直接发布 API；
>   后续切片加 nginx/BFF 后改经 8080→nginx→bff→api）。
> - **内部鉴权**（DECISION-009）：除公开端点外，所有 `/api/*` 请求必须携带
>   `X-Auth-Tenant` / `X-Auth-User` / `X-Auth-Scopes` / `X-Auth-Nonce` / `X-Auth-Ts` / `X-Auth-Sig` 六个头，
>   否则 401。签名 = `HMAC-SHA256(INTERNAL_HMAC_SECRET, "{tenant_id}|{user_id}|{scopes_csv}|{nonce}|{ts}")`（hex）。
>   S01 最小集自测时由测试端直接生成；生产链路由 BFF 校验用户 JWT 后生成。
> - **安全不变量**：签名通过后 tenant 只信 `X-Auth-Tenant` 头，请求体中的 tenant 字段一律忽略（BFF-09 验收 3）。
> - 所有响应为 JSON；列表端点返回 `{"items": [...], "total": N, "page": p, "page_size": ps}`。
> - 错误格式：`{"detail": "..."}`（FastAPI HTTPException）。

## 公开端点（无需 X-Auth-*）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 服务健康（compose healthcheck 使用） |
| GET | `/openapi.json` / `/docs` / `/redoc` | OpenAPI 文档 |
| POST | `/api/auth/login` | 登录（凭据本身鉴权） |
| POST | `/api/auth/refresh` | refresh 轮换（refresh token 本身鉴权） |
| POST | `/api/auth/logout` | 登出（refresh/access token 本身鉴权） |

## auth（AuthService，DECISION-002，BASE-04/05/09）

### POST /api/auth/login
请求体：`{"tenant_code": "acme", "username": "admin", "password": "***"}`
响应 200：`{"access_token": "***", "refresh_token": "***", "token_type": "bearer", "expires_at": "<iso>"}`
- access = JWT HS256，15min，claims：`tenant_id / user_id / scopes[] / jti / exp`
- refresh = JWT HS256，7d，claims：`jti`（存表 `auth_refresh_tokens`，`family` 字段同族）
- 错误：401（租户不存在/用户名密码错误，统一 detail="invalid credentials"，不泄露原因细分）

### POST /api/auth/refresh
请求体：`{"refresh_token": "***"}`
响应 200：新的 access + refresh（**轮换**：旧 jti `replaced_by`=新 jti）。
- 旧 refresh 重放 → 401 + **整族吊销**（该用户所有未吊销 refresh 全部 revoked，BASE-09 重放检测）。
- 已吊销/过期 → 401。

### POST /api/auth/logout
请求头：`Authorization: Bearer <access>`（可选，用于拉黑 access jti）
请求体：`{"refresh_token": "***"}`（可选；提供=精确吊销，缺省=不吊销 refresh）
响应 200：`{"ok": true, "refresh_revoked": 1}`
- refresh 吊销（DB `revoked_at=now`，即时生效）+ access jti 写 Redis 黑名单 `joker:jwt:deny:<jti>`（TTL=剩余有效期）→ 登出后 refresh 401（BASE-05 自测闭环）。

### POST /api/auth/logout-all（需 X-Auth-*，scope 任意已认证用户）
吊销该用户全部 refresh token。响应：`{"ok": true, "revoked": N}`

## iam（IAMService，BASE-01/02/03 + DECISION-004）

> 全部需 X-Auth-*。**scope 门禁**：users/roles/scopes/tenants 管理端点要求 `iam:manage`（缺失 → 403）；GET /api/tenants 要求 `iam:manage`。
> 租户隔离：所有数据端点强制 `tenant_id = X-Auth-Tenant` 行级过滤（BASE-07）。

### 用户（users）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/users?page=1&page_size=50` | 本租户用户列表（含 roles 聚合） |
| POST | `/api/users` | 创建用户。体：`{"username","password"(≥6位, bcrypt),"email"?,"display_name"?,"role_names":[...]?}` → 201 `{id,...}`；409 username/email 已存在 |
| GET | `/api/users/{user_id}` | 详情；**跨租户 ID → 404**（不泄露存在性） |
| PUT | `/api/users/{user_id}` | 更新（email/display_name/status/role_names）；status ∈ active/disabled |
| DELETE | `/api/users/{user_id}` | 软删除（`deleted_at=now`） |
| POST | `/api/users/{user_id}/reset-password` | 管理员重置密码。体：`{"password"}`；重置后该用户全部 refresh 吊销 |

### 角色（roles）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/roles` | 本租户角色列表（含 scope 聚合） |
| POST | `/api/roles` | 创建。体：`{"name","description"?,"scope_names":[...]?}` → 201；409 重名 |
| PUT | `/api/roles/{role_id}` | 更新（name/description/scope_names 全量替换） |
| DELETE | `/api/roles/{role_id}` | 删除（有用户占用 → 409） |

### scope
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/scopes` | 全平台 scope 字典（平台级，不分租户） |
| POST | `/api/scopes` | 创建 scope。体：`{"name","description"?}`；内置 agent 访问控制 scope 语义：`agent:use:<id>` / `agent:use:*`（DECISION-004） |

### 租户（tenants）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tenants` | 租户列表（平台管理视角） |
| POST | `/api/tenants` | 创建租户。体：`{"code","name","status"?:active}` → 201（code 全局唯一） |
| PUT | `/api/tenants/{tenant_id}` | 更新 name/status（code 不可变） |

> S01 种子：租户 `acme` + `globex`（跨租户隔离验收用），各含 admin 用户（`SEED_ADMIN_USERNAME/PASSWORD`）
> 与 `admin`（全 scope）/ `member` 两个内置角色。

## audit（AuditLogService，BASE-06，D-D）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/audit/logs?path=&from=&to=&page=&page_size=` | 本租户审计日志查询（scope `trace:read`）。`path` 前缀过滤；月分区表 `api_audit_logs`，保留 `AUDIT_RETENTION_DAYS`（默认 90） |

审计写入：全部 `/api/*` 请求自动落库（401/403/5xx 也记），字段含 method/path/status/latency/client_ip/query（DB_DESIGN §1.8）。

## 占位模块（S03~S09 切片实装，S01 仅 /healthz）

| 模块 | 前缀 | 实装切片 |
|---|---|---|
| storage | `/api/storage` | **S02（已实装，见下）** |
| llm | `/api/llm` | **S03（已实装，见下）** |
| rag | `/api/rag` | **S04（已实装，见下）** |
| mcp | `/api/mcp` | **S05 BFF `/mcp` rag_search 已实装 + S06 注册管理已实装（见下「mcp」章节）** |
| skills | `/api/skills` | **S06（已实装，见下「skills」章节）** |
| agents | `/api/agents` | S07（已实装，见下「agents」章节）/ S08 BFF |
| trace | `/api/trace` | **S09（已实装，见下「trace」章节）** |

各占位端点：`GET /api/<module>/healthz` → `{"status":"ok","module":"<m>","phase":"S01-skeleton"}`。

---

## llm（LLMNodeService，S03 已实装，LLM-01/02/03）

> 平台级共享（DB_DESIGN §3 / ARCH §9-13）：三类节点全租户可见，**不做 tenant 行级过滤**
> （tenant_id 仅审计归属）。**scope 门禁**：列表/详情/本地 embed 无门禁；
> 增/删/改/连通性测试需 `llm:manage`（缺失 → 403）。
> **密钥**：`api_key` 入参 → Fernet 加密落 `api_key_enc`；响应只见 `api_key_set` 布尔；
> DB/日志/trace 永不出现明文（DECISION-012）。
> **即时生效**：服务无节点缓存，每次读库取最新——CRUD 后 RAG/Agent 立即用新配置。

### endpoint（chat 推理端点，OpenAI 兼容 /chat/completions）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/llm/endpoints?status=&supports_vision=` | 列表（平台级共享；status=active\|disabled，supports_vision 过滤） |
| GET | `/api/llm/endpoints/{id}` | 详情；404 |
| POST | `/api/llm/endpoints` | 创建（`llm:manage`）。必选 `name/base_url/model`；可选 `api_key`/`auth_scheme`(bearer\|api_key_header\|none)/`supports_vision`/`default_params`{temperature,max_tokens,...}/`timeout_seconds`/`status` → 201；重名 409 |
| PUT | `/api/llm/endpoints/{id}` | 部分更新；`api_key` 非空=替换，`clear_api_key=true`=清除；重名 409 |
| DELETE | `/api/llm/endpoints/{id}` | 删除；被 agent 勾选/视觉解析引用 → 409 + 引用清单（禁用代替硬删） |
| POST | `/api/llm/endpoints/{id}/test` | 连通性测试：轻量 "ping" 调用 → `{ok, latency_ms, summary}`（可用/不可用+错误摘要），写 `last_test_at/last_test_result` |

### embedding（模型，OpenAI 兼容 /embeddings）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/llm/embeddings?status=` | 列表（含启动自动注册的 `local-fallback-embedding`，provider=local，dim=`LLM_LOCAL_FALLBACK_DIM` 默认 256） |
| GET/POST/PUT/DELETE | `/api/llm/embeddings[/{id}]` | 同 endpoint 语义；必选 `name/dimensions`；可选 `provider`(api\|local)/`base_url`/`model`/`api_key`/`batch_size`/`status`；删除被知识库引用 → 409 |
| POST | `/api/llm/embeddings/{id}/test` | 连通性测试（local 节点走本地实现必 ok；api 节点发短文本，维度不符 → 不可用） |
| POST | `/api/llm/embeddings/local/embed` | 本地确定性 fallback embedding 直测：`{texts:[...], dim?}` → `{items: float[][], total, dim}`（同文本必同向量） |

### reranker（模型，Jina 兼容 /rerank 契约）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/llm/rerankers?status=` | 列表 |
| GET/POST/PUT/DELETE | `/api/llm/rerankers[/{id}]` | 同上；必选 `name/base_url/model`；可选 `api_key`/`max_candidates`/`status`；删除被知识库引用 → 409 |
| POST | `/api/llm/rerankers/{id}/test` | 连通性测试（发短文本 /rerank，校验 `results[].relevance_score`） |

### .env 配置化（S03 新增变量，见 .env.example）
- `LLM_FALLBACK_ENDPOINT` / `LLM_FALLBACK_MODEL` / `LLM_FALLBACK_API_KEY` / `LLM_FALLBACK_NAME`：
  启动时幂等注册默认 chat endpoint（供自测闭环；key 加密落 DB）。
- `LLM_LOCAL_FALLBACK_DIM`（默认 256）/ `LLM_PROBE_TIMEOUT_SECONDS`（默认 15）。
- `FERNET_KEY`：S03 起真正启用（LLM 节点密钥加密）；**必须是 44 位 urlsafe base64**
  （非法值=启动告警+随机生成；留空=自测随机生成，重启后旧密文不可解——生产必须固定）。

### 内部 Python 抽象（供 S04/S05/S07，joker_shared.llm）
- `get_llm_service().embed_texts(session, model_id, texts) -> list[list[float]]`
  （provider=local → 确定性 n-gram 哈希；api → 批量 /embeddings）
- `get_llm_service().rerank(session, model_id, query, documents, top_n?) -> [{index, score}]`

---

## rag（RAGService，S04 已实装，RAG-01/02/03/04/05/11 + 建库/向量化流水线）

> 全部 `/api/rag/*` 需 X-Auth-*（DECISION-009 签名头）。**scope 门禁**：
> 库/文档/chunk 管理（增删改/重切分/重嵌入/retry）要 `kb:manage`（缺失 → 403）；
> 读端点（列表/详情/原文/chunk 列表/定位/反查）`kb:manage` 或 `storage:read`。
> **租户隔离**：全部数据端点强制 `tenant_id = X-Auth-Tenant`（行级，跨租户 404 不泄露存在性）。
> **D-C 每库独立向量表**：建库时固化 `embedding_dim`（所选 embedding 模型维度快照）+
> 动态建 `rag_chunks_vec_<kb_id>`（HNSW，按实际维度）；检索只走本库表（S05）。
> **文档状态机**（DECISION-021 进程内队列，worker 单并发串行）：
> `uploaded→parsing→splitting→embedded→ready`，失败 → `failed`（`error_message` 摘要，可 retry）。
> **6 类文档**：txt / docx / xlsx / pdf / png / jpg（.jpg→jpg）。
> **.doc 旧格式 → 422**（提示转 .docx）；非支持类型/空文件 → 422。
> **视觉解析**（RAG-03）：图片/扫描页/内嵌图 → 调 `supports_vision=true` 的 LLM endpoint；
> 视觉不可用 → 降级（占位块 `[图片未解析: ...]` + `rag_doc_images.status=skipped` + 日志 RISK，**不阻断**流水线）。

### 知识库（kbs，RAG-01）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/rag/kbs?status=&page=&page_size=` | 本租户库列表 `{items[], total}`（含 `embedding_dim`/`vec_table`/`vec_table_exists`/`doc_count`/配置摘要）；status=active\|reindexing\|disabled |
| POST | `/api/rag/kbs` | 建库（`kb:manage`）。必选 `name`/`embedding_model_id`（来自 S03，active）；可选 `description`/`tag`(D-A 库级官方标记)/`reranker_model_id`/`top_k_default`(5)/`score_threshold`(0.3)/`recall_top_n`/`split_strategy_default`(fixed)/`split_params_default` → 201（含 `embedding_dim`=模型维度快照 + `vec_table` 已建）；404 embedding 不存在；409 模型 disabled / 库重名 |
| GET | `/api/rag/kbs/{kb_id}` | 详情（含 `vec_table`/`vec_table_exists`）；404 |
| PUT | `/api/rag/kbs/{kb_id}` | 更新配置（name/description/tag/top_k_default/recall_top_n/score_threshold/split_strategy_default/split_params_default/status）；409 重名 |
| DELETE | `/api/rag/kbs/{kb_id}` | 删库：级联删文档/chunk + **DROP 独立向量表**（D-C 物理释放）→ `{ok, deleted}` |
| POST | `/api/rag/kbs/{kb_id}/reindex` | 换 embedding 模型=全库重算（D-C 流程 c）：体 `{embedding_model_id}`；影子表（新维度）→全量重嵌入（status=reindexing，期间检索走旧表）→切换→DROP 旧表；异步，GET /kbs/{id} 查 status；409 已在 reindexing |

### 文档（docs，RAG-02）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/rag/kbs/{kb_id}/docs` | 上传（`kb:manage`）：multipart `file` + query `tag`?(D-A 文档级，NULL 继承库级)/`split_strategy`?/`split_params`?(JSON)；经 StorageService 落盘（source=kb，上传记录可查）→ rag_docs(status=uploaded) → 入队流水线 → 201；422 类型/.doc/空；409 同名文件 |
| GET | `/api/rag/kbs/{kb_id}/docs?status=&page=&page_size=` | 文档列表（含 status/parse_method/chunk_count/error_message/split_strategy/split_params） |
| GET | `/api/rag/kbs/{kb_id}/docs/{doc_id}` | 详情；404 |
| PUT | `/api/rag/kbs/{kb_id}/docs/{doc_id}` | 文档级更新：tag/split_strategy/split_params（重切分后生效） |
| DELETE | `/api/rag/kbs/{kb_id}/docs/{doc_id}` | 删文档：级联物理删 chunk（向量随 FK CASCADE）；原文件留存储 |
| POST | `/api/rag/kbs/{kb_id}/docs/{doc_id}/retry` | failed 文档重试（状态回 uploaded 重新入队）；409 非 failed |
| POST | `/api/rag/kbs/{kb_id}/docs/{doc_id}/resplit` | 重切分（RAG-04 验收 2）：体 `{split_strategy?, split_params?}`（省略=用当前文档/库配置）；删旧 chunk+重建向量，异步 → 200 status=splitting（完成后 ready）；409 非 ready/embedded/failed |
| GET | `/api/rag/kbs/{kb_id}/docs/{doc_id}/file` | 原文档二进制（RAG-05 验收 1 / RAG-11 左栏渲染源）：Content-Type 按 doc_type，`Content-Disposition: inline; filename=...`，经 StorageService 取回 |

### chunk（RAG-05 / RAG-11，ARCH §2.2.1 双向联动）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/rag/kbs/{kb_id}/docs/{doc_id}/chunks?page=&page_size=` | chunk 列表（右栏；按 chunk_index 升序）：`{items:[{chunk_id, chunk_index, content, pos, is_table, parent_id, split_strategy, edited_at, ...}], total}` |
| GET | `/api/rag/kbs/{kb_id}/docs/{doc_id}/chunks/{chunk_id}/location` | chunk→原文位置（右→左联动）：`{pos: <pos JSONB 全文>, chunk_id}` |
| GET | `/api/rag/kbs/{kb_id}/docs/{doc_id}/chunks/by-location?pos=<JSON>` | 原文位置→chunk 反查（左→右联动）：pos 按文档类型坐标（文本=page+char_start/char_end；表格=table_row{sheet,table,row_start,row_end,col_start?,col_end?}；图片=page）；返回包含该位置的全部 chunk（重叠多命中）+ `primary_chunk_id`（chunk_index 最小） |
| PUT | `/api/rag/kbs/{kb_id}/docs/{doc_id}/chunks/{chunk_id}` | 编辑 chunk 文本（RAG-05 验收 2/4）：体 `{content}`；更新 content + 重算向量写本库向量表（D-C）+ edited_at/updated_by 留痕；右栏刷新、左栏原文不可变；422 content 空 |

### 切分策略（RAG-04，DECISION-020；5 策略工厂，库级默认+文档级覆盖）
- `fixed` 定长：`chunk_size`(500)/`overlap`(50)；`parent_child` 父子：`parent_size`(2000)/`child_size`(500)/`overlap`(50)
- `semantic` 语义：`threshold`(0.25，相邻句 n-gram 向量余弦断点)/`chunk_size`(500)
- `structured_tree` 结构化文档树：`chunk_size`(500)/`overlap`(50)（按 section_path 标题层级分节）
- `table` 表格：`max_table_chars`(4000)/`row_group`(50)（整表=chunk，is_table=true；超大表按行组切，表头随行重复）
- 参数可配（建库 `split_params_default` / 上传 / 文档级 PUT / resplit），可重切分（resplit 删旧 chunk+重建向量）。
- parent_child / structured_tree 的父子关联经 chunk `parent_id` 引用（service 层按「组内首个=父」建引用）。

### 内部 / Python 抽象（joker_shared.rag）
- 无新增必填 env（视觉走 S03 已配置的 `supports_vision` endpoint；embedding 走 S03 节点）。
- `get_task_queue()`（进程内文档流水线队列）、`vec_table(kb_id)`（独立表名 `rag_chunks_vec_<kb_id 去连字符>`）、
  `create_rag_chunks_vec(kb_id, dim)`（SQL 函数：建表 + HNSW vector_cosine_ops）。

### 检索（S05 已实装，RAG-06/07/08/09）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/rag/search` | 知识库检索（scope `rag:search`，缺失 403）。体 `{kb_ids:UUID[]（必选，同租户）, query:str（必选）, top_k?:int, score_threshold?:float, use_rerank?:bool=true, agent_id?:UUID}`。语义：**D-C** 逐库查各自 `rag_chunks_vec_<kb_id>`（该库建库快照 embedding 模型向量化查询）后应用层合并；**RAG-07** 任一库配 active reranker 且未显式关闭 → 重排（端点不可用降级纯向量）；**DECISION-006 阈值双语义**：有 rerank 阈值作用 rerank 分数、无则作用余弦相似度；**RAG-08** top_k/阈值 单次覆盖，未传回落库级默认（多库取各库最大值=最严格）。出参 `{items:[{chunk_id, content, kb_id, doc_id, doc_file_name, chunk_index, pos, tag, is_official, score, parent_content?}], total, top_k, threshold, reranked}`。403 缺 scope；404 库不存在/跨租户；409 库非 active；422 空 query/kb_ids |
| POST | `/internal/rag/search` | 内部检索（DECISION-009 签名头，供 SAR/BFF 机器凭证调用；D-B 非拦截范围）。与 `/api/rag/search` 同一核心 + **agent_id 提供时 (agent_id,kb_id) 勾选校验**（未勾选 403）+ **落 trace `rag` 事件**（不产生 tool_call；user_id 为 None 时回退租户首个 active 用户落痕）。出参 = 上表 + `agent_id`。401 未签名/签名错 |
| POST | `/internal/storage/rag-search` | **S02 契约兼容别名**（S05 起已接通检索核心，非 501 stub）：1:1 同参同出参于 `/internal/rag/search`；规范路径 = `/internal/rag/search` |

> **RAG-09 反向定位**：每条 item 含 `chunk_index` + `pos`（原文坐标 JSONB：文本=char_start/char_end，表格=table_row，图片=page），与 chunk 表一致（RAG-11 切分对比/原文高亮用）。
> **D-A official 两级判定**：`is_official` = 文档级 `rag_docs.tag` 优先（=official→true / 其他值→false），NULL 继承库级 `rag_knowledge_bases.tag=official`（NULL+NULL→false）；供 S09 AGENT-05 引用来源判定。

---

## storage（StorageService，S02 已实装，STORE-01..07）

> 全部 `/api/storage/*` 需 X-Auth-*（DECISION-009 签名头）。**scope 门禁**：
> 上传要 `storage:write`；列表/下载/记录/后端要 `storage:read`；删除要 `storage:manage`。
> **租户隔离**：所有数据端点强制 `tenant_id = X-Auth-Tenant`（行级，跨租户文件 404，不泄露存在性）。
> 统一 URL 语义：调用方按**文件名**访问，永不感知物理路径/后端（STORE-04）。

### 后端切换（STORE-03，DECISION-027）
- env `STORAGE_BACKEND=local|gcs|oss`（重启生效）；`STORAGE_LOCAL_PATH`（默认 `/data/storage`）；
  `GCS_BUCKET`/`GCS_CREDENTIALS_PATH`、`OSS_ENDPOINT`/`OSS_BUCKET`/`OSS_ACCESS_KEY_ID`/`OSS_ACCESS_KEY_SECRET`（凭证 env 注入不进 DB，DECISION-012）。
- 切换后**新上传走新后端**；既有文件按 `storage_files.backend` 行内分派从原后端读（保留原后端访问、不迁移）。
- 无云账号/未装 SDK → 上传返回 **503** 明确配置错误（`storage backend not configured: ...`），不崩溃。

### 文件（files）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/storage/healthz` | 模块健康（签名头即可，无 scope 门禁） |
| GET | `/api/storage/backends` | 后端状态（不含凭证）：`{items:[{active}, {name, configured, root/bucket/error}]}` |
| POST | `/api/storage/files` | multipart `file`（必填）+ query `source`（api/mcp:platform/agent/kb/skill，默认 api）/`agent_id`? → 200 `{id, file_name, size_bytes, content_type, backend, checksum_sha256, upload_record_id}`；同名 409、空 422、>100MB 413、超配额 403、后端未配置 503 |
| GET | `/api/storage/files?prefix=&status=&source=&page=&page_size=` | 本租户文件列表 `{items[], total, page, page_size}` |
| GET | `/api/storage/files/{file_name}` | 下载：流式返回文件体，响应头 `X-Storage-Backend` / `X-Storage-File-Id`；不存在 404 |
| DELETE | `/api/storage/files/{file_name}` | 软删（status=deleted）+物理删除；被 rag_docs 引用 → 409 `{detail:"file referenced by N rag_docs"}` |

### 上传记录（upload-records，STORE-05）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/storage/upload-records?file_name=&uploader_user_id=&source=&status=&start=&end=&page=&page_size=` | 任意来源上传留痕（成功/失败/拒绝）；`file_name` 模糊、`start`/`end` ISO8601 |

### 内部端点（/internal/storage，机器凭证代执行，DECISION-009 签名头）
> 供 PlatformMCPServer 以机器凭证（INTERNAL_HMAC_SECRET）代执行。**无 scope 门禁**——
> scope 校验/工具拦截由 S08 ToolInterceptor 统一接入（D-B）。身份仍由签名头中的 tenant 决定（只信头不信体）。
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/internal/storage/upload` | multipart `file` + query `source`（默认 mcp:platform）/`agent_id`?（同 /api/storage/files） |
| GET | `/internal/storage/files?file_name=` | 传 file_name=精确取该文件；不传=列表 |
| GET | `/internal/storage/files/{file_name}` | 下载（同语义） |
| POST | `/internal/storage/rag-search` | **S05 已实装**（501 stub → 检索核心，见 rag 章节「检索」）：S02 契约兼容别名，1:1 同参同出参于 `/internal/rag/search`（含 chunk_index/pos/tag/is_official + total/top_k/threshold/reranked） |

### 平台 MCP 三工具（STORE-06/07，BFF `/mcp`，Streamable HTTP，DECISION-011）
> 端点：`http://<bff>/mcp`（S02 直发 127.0.0.1:8000；S11 后经 8080→nginx→bff）。
> 鉴权：`Authorization: Bearer <access JWT>`（无/错 token → HTTP 401）。
> 传输：Streamable HTTP（stateless 会话）。工具入参 `access_token` 由 S08 ToolInterceptor 强制注入
> （生产路径）；BFF 直连/自测路径回退到 HTTP 层 Authorization 头——两条路径同一薄封装。
> `tools/list` 列出 3 工具；工具调用经 `tools/call`。

| 工具 | 入参 | 出参（content/structuredContent） |
|---|---|---|
| `upload_doc` | `file_name`, `content`(UTF-8 文本), `source`?(默认 mcp:platform), `agent_id`?, `access_token`? | `{id, file_name, size_bytes, content_type, backend, checksum_sha256, upload_record_id}`（落 storage + 留痕 source=mcp:platform） |
| `query_doc` | `file_name`?（精确）或 `prefix`?/`limit`?（默认 20）, `access_token`? | `{items:[{id, file_name, content_type, size_bytes, backend, source, content?}], total}`（text/* 类型内联 content） |
| `rag_search` | `kb_ids[]`, `query`, `top_k`?（5）, `score_threshold`?, `agent_id`?, `access_token`? | **S05 已实装**（501 stub → 检索核心）：经 `/internal/rag/search`，出参 `{items:[{chunk_id, content, kb_id, doc_id, doc_file_name, chunk_index, pos, tag, is_official, score, parent_content?}], total, top_k, threshold, reranked, agent_id}`；未勾选 KB 的 agent → 工具错误（403） |

---


## mcp（MCPRegistryService，S06 已实装，MCP-01/02/03）

> 全部 `/api/mcp/*` 需 X-Auth-*（DECISION-009 签名头）。**scope 门禁**：
> 管理（注册/编辑/删除/刷新/工具启用禁用删除）要 `mcp:manage`（缺失 → 403）；
> 读（server 列表/详情/工具列表/工具缓存）`mcp:manage` 或 `mcp:tool`（对话级可见工具清单，供 S07 agent 配置界面候选列表）。
> **租户隔离**：数据端点强制 `tenant_id = X-Auth-Tenant`（跨租户 server 404 不泄露存在性）；
> 平台内置 server（`is_platform=true`，系统租户行 `joker-platform`）跨租户可见、**不可编辑/删除（409）**。
> **密钥**：`auth_headers`（对象，如 `{"Authorization":"***"}`）入参 → Fernet 加密落 `auth_headers_enc`；
> 响应只见 `auth_headers_set` 布尔；DB/日志/trace 永不出现明文（DECISION-012）。
> **注册即同步（MCP-01/DECISION-010）**：`POST /servers` 成功后立即 tools/list 探测 + 工具全量 upsert；
> 探测失败 → server 保留 `unreachable` + `sync.error`（不丢注册）。
> **工具状态**：`enabled`（bool，本侧启用/禁用）× `removed_remote`（bool，远端已移除反向标记）；
> `usable = enabled && !removed_remote && server.online`（agent 可见可用语义）。
> **removed_remote 反向同步（MCP-02/DECISION-010）**：refresh 时远端消失的工具**不删行**，
> 标 `removed_remote=true`（保留历史+agent 引用可追溯）；远端重新出现 → 复活（`removed_remote=false` 重新 upsert）。

### server（MCP-01）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/mcp/healthz` | 模块健康（公开） |
| GET | `/api/mcp/servers?status=` | 本租户 server 列表（含平台内置行）`{items[], total}`；status=online\|offline\|unreachable\|disabled；item 含 `name/url/transport/status/is_platform/auth_headers_set/usable_tool_count/last_sync_at/created_at/updated_at` |
| GET | `/api/mcp/servers/{server_id}` | server 详情；404（不存在/跨租户） |
| POST | `/api/mcp/servers` | URL 注册（`mcp:manage`）。必选 `name`/`url`；可选 `transport`(streamable_http\|sse，默认 streamable_http)/`auth_headers`(对象) → 201（注册即同步，出参含 `ok/status/tool_count`；探测失败 `ok=false`+`status=unreachable`+`error`）；409 本租户重名；422 缺字段 |
| PUT | `/api/mcp/servers/{server_id}` | 编辑（`mcp:manage`）：`name/url/transport/status`；`status=disabled`=禁用（工具全部不可用）/`online`=启用；url 变更后建议随后 `POST /refresh`；平台内置 409；重名 409 |
| DELETE | `/api/mcp/servers/{server_id}?confirm=` | 删除（`mcp:manage`）。有 agent 引用且 confirm=false → 409 + `referring_agents` 清单；confirm=true → 软删（`deleted_at`）+ 关联 agent 失去工具；平台内置 409 |
| POST | `/api/mcp/servers/{server_id}/refresh` | 手动刷新全量同步（`mcp:manage`，MCP-02/DECISION-010）：tools/list 探测 + upsert + removed_remote 反向标记 + 缓存失效 → `{server_id, ok, status, tool_count}`（探测失败 `ok=false`+`error`） |
| GET | `/api/mcp/servers/{server_id}/referring-agents` | 该 server 关联调用方（MCP-03，删除/禁用前提示）→ `{items:[{agent_id, agent_name, tool_count}], total}` |

### tools（MCP-02）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/mcp/servers/{server_id}/tools?status=&source=` | server 工具列表（含平台内置 `source=platform` + 远端 `source=remote`）`{server_id, server_status, items[], total}`；status=enabled\|disabled\|removed；item 含 `name/description/input_schema/required_scopes/source/status/enabled/removed_remote/usable` |
| POST | `/api/mcp/tools/{tool_id}/disable?confirm=` | 禁用工具（agent 侧不可调用）。有 agent 引用且 confirm=false → 409 + 清单 |
| POST | `/api/mcp/tools/{tool_id}/enable` | 启用工具（恢复可调用）。已 removed_remote → 409（需先 refresh 复活） |
| DELETE | `/api/mcp/tools/{tool_id}?confirm=` | 删除工具（平台侧移除，不删远端）。有 agent 引用且 confirm=false → 409 + 清单 |
| GET | `/api/mcp/tools/{tool_id}/referring-agents` | 该工具关联调用方（MCP-03） |

### 工具 schema 缓存（DECISION-010，S08 ToolInterceptor 消费入口）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/mcp/servers/{server_id}/tools-cache?refresh=` | 工具 schema/scope 快照（Redis TTL=`MCP_TOOL_CACHE_TTL` 默认 600s）。出参 `{server_id, server_status, tools:[...], total, cache:hit\|miss\|refreshed}`；refresh=true 强制重建。注册/refresh/工具增删改后缓存自动失效 |

### 平台内置 MCP server（joker-platform）
- 启动 hook（`main.py`）幂等注册：系统租户 `joker-platform`（is_platform=true），
  同步平台三工具（upload_doc/query_doc/rag_search，source=platform，required_scopes 见 platform_tools）。
- 跨租户只读（列表/详情/工具可见），管理操作 409。

## skills（SkillsService，S06 已实装，SKILL-01/02）

> 全部 `/api/skills/*` 需 X-Auth-*（DECISION-009 签名头）。**scope 门禁**：
> 写（创建/上传/更新/删除）要 `skills:manage`（缺失 → 403）；读（列表/详情）`skills:manage` 或 `skills:read`。
> **租户隔离**：数据端点强制 `tenant_id = X-Auth-Tenant`（跨租户 skill 404 不泄露存在性）。
> **存储**：多文件经 S02 StorageService 落盘（source=skill）；主文件（首文件）角色 `main`、其余 `asset`；
> `skill_files` FK→skills（CASCADE）。删除 skill → 主/资产文件**物理删除**（`files_deleted`，
> 被 RAG 文档引用的跳过 → `files_skipped`，不阻断）。
> **来源**：`source=manual`（`POST /api/skills` 内联 content）或 `source=upload`（`POST /api/skills/upload` 多文件）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/skills/healthz` | 模块健康（公开） |
| GET | `/api/skills?status=&source=&page=&page_size=` | 本租户 skill 列表 `{items[], total}`；status=active\|disabled；source=manual\|upload；item 含 `name/description/source/status/version/file_count/created_at/updated_at` |
| GET | `/api/skills/{skill_id}` | 详情（含 `files:[{file_name, role, size_bytes, content_type}]`）；404 |
| POST | `/api/skills` | 内联创建（`skills:manage`）。必选 `name`；可选 `description`/`content` → 201；409 本租户重名 |
| POST | `/api/skills/upload` | 多文件上传（`skills:manage`）：multipart `files[]`（≥1，.md/.txt 等）→ 201（主文件=首文件，存 storage source=skill，回写 file_count）；409 重名；422 空/非法类型 |
| PUT | `/api/skills/{skill_id}` | 更新（`skills:manage`）：`name/description/content/status`；重名 409 |
| DELETE | `/api/skills/{skill_id}` | 删除（`skills:manage`）：软删 + 物理删主/资产文件 → `{ok, files_deleted:[...], files_skipped:[...]}`；被 RAG 文档引用的文件跳过不删 |

### 内部 Python 抽象（joker_shared.skills / joker_shared.mcp）
- `get_skills_service().upload_skill(...)`（多文件经 storage，skill_files 先建 skill 行再挂文件）。
- `get_mcp_registry().probe_and_sync(...)`（tools/list 探测 + upsert + removed_remote 反向标记 + 缓存失效）。
- `get_mcp_registry().get_tools_cached(session, server_id, tenant_id, refresh?)`（Redis 快照，S08 消费）。

## agents（AgentService，S07 已实装，AGENT-01..11）

> 全部 `/api/agents/*` 需 X-Auth-*（DECISION-009 签名头）。**scope 门禁**（DB_DESIGN §1.2 / DECISION-004）：
> 管理（列表/详情/增删改）要 `agents:manage`（缺失 → 403）；
> 对话/读会话/读记忆要 `agent:use:<agent_id>` 或 `agent:use:*` 通配（缺失 → 403）。
> **动态授权**：创建 agent 自动 upsert 租户级 scope `agent:use:<id>` + 专属角色 `agent-user:<id>`
> 并授予租户全体 active 用户；删除级联清理（`delete_agent`）。
> **租户隔离**：全部数据端点强制 `tenant_id = X-Auth-Tenant`（跨租户 404 不泄露存在性）。
> **对话入口** `POST /api/agents/{id}/chat`：simple → SAR 运行时（LangChain tool-calling loop，
> DECISION-007）；third_party → URL 代理（DECISION-008 协议）。用户 Access Token 从
> `Authorization: Bearer <token>` 透传 → ToolInterceptor 强制注入工具入参（DECISION-015 ②）。

### 元数据（AGENT-01/02/03，`agents:manage`）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/agents/healthz` | 模块健康（公开） |
| GET | `/api/agents?status=&type=` | 列表 `{items[], total}`；status=active\|disabled；type=simple\|third_party |
| GET | `/api/agents/{agent_id}` | 详情 + **四要素回显**（A03 验收 2）：`llm_endpoint_ids[]`（恰好 1 条）/`knowledge_base_ids[]`/`mcp_tool_ids[]`/`skill_ids[]` + `session_count`；404 |
| POST | `/api/agents` | 创建（201）。必选 `name`（**租户内唯一**，=OpenAI model 标识 DECISION-016，重名 409）；可选 `type`（默认 simple）/`third_party_url`（type=third_party 必填 http/https，缺失 422）/`system_prompt`/`model_params`/`max_tool_rounds`（默认 8）/`show_citations_default`/`third_party_auth`（Fernet 加密落库）/四要素勾选（`llm_endpoint_ids`/`knowledge_base_ids`/`mcp_tool_ids`/`skill_ids`，候选不存在或 disabled → 422） |
| PUT | `/api/agents/{agent_id}` | 编辑（含四要素勾选变更，软删语义：空列表=解勾全部；仅传勾选键合法，无字段可更 400） |
| DELETE | `/api/agents/{agent_id}` | 软删（会话/消息保留可查）+ 四要素引用表清理 + 动态 scope/角色级联清理 |

### 对话（A04/A05/A06，`agent:use`）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/agents/{agent_id}/chat` | body `{message, session_id?, show_citations?, files?:[{file_name, content, content_type?}]}` → `{session_id, agent_id, agent_type, reply, citations, citations_forced_official, tool_calls, tokens, tool_rounds_used, rag_hits, files, error, latency_ms}`；agent 无 LLM endpoint 409 / agent disabled 409 / 会话属于别 agent 409 / 会话已关闭 409；**附件** `files[]`（{file_name, content, content_type?}）入 storage（source=agent）+ file 事件留痕，响应 `files:[{file_id, direction:"in", file_name}]`（A06） |

### 会话/消息（AGENT-04，`agent:use`）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/agents/{agent_id}/sessions?status=&page=&page_size=` | 本 agent 本用户会话列表 `{items[], total}` |
| GET | `/api/agents/{agent_id}/sessions/{session_id}/messages` | 完整消息流（含 `tool_calls`/`citations`/`file_ids` jsonb） |
| POST | `/api/agents/{agent_id}/sessions` | 新建会话（201） |
| PATCH | `/api/agents/{agent_id}/sessions/{session_id}` | 重命名 |
| POST | `/api/agents/{agent_id}/sessions/{session_id}/close` | 关闭 → **触发沉淀**（AGENT-07/08：LLM 提炼长期记忆 + obsidian 笔记双写，DECISION-019；third_party 跳过，平台不存其记忆 A09） |
| DELETE | `/api/agents/{agent_id}/sessions/{session_id}` | 软删（消息保留） |

### 记忆/笔记（AGENT-07/08，`agent:use`）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/agents/{agent_id}/memories?limit=` | 长期记忆（PG `agent_memories`，top N 跨会话注入） |
| GET | `/api/agents/{agent_id}/notes?limit=` | obsidian 沉淀笔记索引（PG `agent_obsidian_notes` + vault 文件 `file_path`） |

### 运行时要点（joker_shared.agents）
- **SAR 运行时**（`agents.runtime.SimpleAgentRuntime`）：LangChain `ChatOpenAI`（OpenAI 兼容端点）
  tool-calling loop ≤ `max_tool_rounds`；InterceptorTool 工厂为唯一工具注册路径（DECISION-015）；
  RAG 预检索走内部直调（D-B：不产生 tool_call，保留身份校验 + 勾选 403 + rag 事件留痕）；
  skills/长期记忆/RAG 注入 system prompt。
- **三层记忆**（`agents.memory`）：短期（Redis `joker:mem:short:<tenant>:<agent>:<session>`，
  TTL 30min 续期，故障退化单轮）+ 长期（PG `agent_memories`）+ 沉淀（obsidian vault + `agent_obsidian_notes` 索引）。
- **引用来源**（`agents.citations`）：D-A official 两级判定（`is_official` 命中强制附来源）+
  `show_citations` 显式 + LLM 意图兜底；回复末尾来源 markdown（可链接原文定位 URL，RAG-09）。
- **工具拦截**（`agents.interceptor`，S07 占位三动作，S08 替换统一动作链）：① scope 校验 ②
  access_token 强制注入 ③ 代理执行（平台工具 → `/internal/*` 机器凭证；远端 MCP → mcp client tools/call）
  + tool_call trace 留痕；100% 经 `execute_tool_call`（D-B 无裸执行路径）。
- **第三方 agent**（`agents.third_party.ThirdPartyAgent`，DECISION-008）：OpenAI 兼容 `/chat/completions`
  代理 + 平台回传 `POST {agent_url}/tool_results` 闭环（≤ max_tool_rounds）；工具标识
  `mcp:<server_id>:<tool_name>` / `platform:<name>`；工具 100% 经 ToolInterceptor；平台不注入记忆（A09）；
  不配置工具对话正常（A10 验收 3）。
- **mock 资产**（DECISION-008 可运行样例，S11 联调 / S12 测试闭环复用）：
  `services/mocks/third_party_agent/server.py`（/chat/completions + /tool_results，9200）；
  `services/mocks/mcp_server/server.py`（Streamable HTTP /mcp，9100，工具清单动态读 /tools.json）。

## BFFGateway（S08 统一网关，独立 FastAPI 服务，BFF-01..09）

> 端点：`http://<bff>/...`（S08 自测 127.0.0.1:8000；S11 后经 8080→nginx→bff）。
> BFF 是**统一入口层**：用户/SDK 请求先经 BFF，BFF 做完 鉴权/租户/限流/路由 后，
> 本地端点（/v1、/mcp、/api/bff/*、/docs）就地处理；其余 /api/*、/internal/* 转发
> PlatformAPI（注入 X-Auth-* HMAC 签名头，DECISION-009）。**业务服务不重复实现 token 校验**。
>
> **统一请求处理管线**（ARCH §4.1，固定顺序）：
> ① 限流（登录 IP 未鉴权即做；鉴权后 租户QPS+用户QPS）→ ② JWT access 校验 + Redis 登出黑名单
> → ③ 身份提取（**只信 token claims 的 tenant/user/scopes，绝不信任请求体**，BFF-09 验收 3）
> → ④ 配置化路由（routes.yml 最长前缀匹配）→ ⑤ scope 校验 → ⑥ OpenAI 协议转换 → ⑦ 审计/trace。
>
> 路径分派：`/healthz`=公开；`/api/auth/login`=公开入口（仅 IP 限流，直接转发，登录例外不注入签名头）；
> `/v1/*`、`/mcp`、`/api/bff/*`、`/docs`=鉴权+限流后委派 FastAPI/MCP ASGI（send 透传，支持 SSE）；
> `/api/*`、`/internal/*`=鉴权+限流后转发 PlatformAPI（X-Auth-* HMAC）；未知=404。

### BFF 本地端点（不经上游转发）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | BFF 健康 `{status, service: "bffgateway", phase: "S08-bff"}` |
| POST | `/v1/chat/completions` | **OpenAI 兼容**（BFF-04/DECISION-016）。`model`=agent 名称（租户内唯一，跨租户 404 不暴露存在性；缺 422）。`stream=false`→块式 `chat.completion`；`stream=true`→SSE `chat.completion.chunk` + `data: [DONE]`。需 `agent:use` scope（无 403）。标准 OpenAI SDK `client.chat.completions.create(model=<agent名>)` 可直接对接 |
| GET/POST | `/api/bff/rate-limits` | 限流配置（平台级 `iam:manage`/系统租户）。GET→当前生效阈值（DB→Redis→default 三级降级）；POST `{dimension, limit_value}`→运行时调整**即时生效**（DECISION-013）|
| GET | `/api/bff/routes` | 路由表只读（DECISION-014）`{routes[], count, source}` |
| POST | `/api/bff/routes/reload` | 路由热加载（平台级 `iam:manage`）→ `{ok, count}`；新增模块端点不改 BFF 代码 |

> 限流三维度（DECISION-013，Redis 固定窗口计数）：**租户 QPS 默认 50 / 用户 QPS 默认 10 / 登录 IP 5 次每分钟**。
> 超限 429 `{detail:"rate limit exceeded (<dim>)", retry_after, limit, count}`。

### 平台 MCP 对外暴露（/mcp，STORE-06/07/RAG-10，DECISION-011/015）

> 端点：`http://<bff>/mcp`（Streamable HTTP，stateless 会话）。暴露平台内置三工具
> `upload_doc` / `query_doc` / `rag_search`（schema 与 DB 注册行同源）。
> **工具调用 100% 经 ToolInterceptor 统一动作链**（BFF-06/07，D-B）：
> ① scope 校验（`mcp_tools.required_scopes` × 用户 scopes，未勾选 403 语义）
> ② Access Token 强制注入（入参 access_token 一律覆写为用户真实 token，BFF-09 验收 2）
> ③ 机器凭证代理执行（平台工具 → `/internal/*` HMAC 签名头，DECISION-009）
> ④ tool_call 事件落 trace（/mcp 直连无特定 agent → 回退租户首个 active agent 建 trace）。
>
> 身份来源两条路径（与 S02 同一薄封装）：工具入参 `access_token`（ToolInterceptor 注入）优先；
> /mcp HTTP 直连/自测回退 Authorization: Bearer 头。标准 MCP SDK（`streamablehttp_client`）可直接对接。

### 错误码约定（BFF 统一，ARCH §4.7）

| 码 | 场景 |
|---|---|
| 401 | 无/坏/过期/已登出 access token（`{detail, hint?}`）；MCP 无 Bearer 401 |
| 403 | 无所需 scope（如 /v1 无 `agent:use`；MCP 工具未勾选） |
| 404 | 跨租户访问 agent（不暴露存在性）；无匹配路由 |
| 409 | agent 名称租户内重复（创建时） |
| 422 | 请求体校验失败（如 /v1 缺 model） |
| 429 | 限流超限（含 `retry_after`） |
| 502/504 | 上游 PlatformAPI 不可达 / 超时 |

### BFF 部署（DECISION-018 双进程）

> `deploy/Dockerfile.bff`：uvicorn 起 BFFGateway（API + /mcp + /v1 同进程）；SAR 运行时
> 与拦截器同容器组共享 `joker_shared` 库（DECISION-015/018）。compose `bff` 直连 pg+redis，
> `BFF_ROUTES_FILE=/app/bff/routes.yml`。MCP 会话管理器 `run()` 每实例只进一次（MCP SDK v1.30），
> 由 BFFGateway 在 lifespan 进入，每请求走 `handle_request()`。

## trace（TraceService，S09 已实装，TRACE-01/02 + D-D / DECISION-025 + DECISION-012）

> 端点：`/api/trace/*`（PlatformAPI，经 BFF 转发或直连 8080）。全部需 X-Auth-*（DECISION-009）+
> scope `trace:read`（缺失 403）。租户隔离强制：跨租户访问 trace 会话/事件 → 403（不泄露存在性，TRACE-02 验收 3）。
> payload 一律脱敏（DECISION-012：api_key/password/token/authorization/secret 等 → `***`，复用 audit 单一源 `redact_obj`）。
>
> **全链路事件模型**（trace_events，月分区）：一次 agent 对话产生
> `system(start)` → `message(user)` → `rag`（RAG 预检索，D-B 直调不产生 tool_call）→
> `tool_call`（工具经 ToolInterceptor 100% 留痕）→ `message(assistant, token_usage)` →
> `system(end)`（会话关闭）。事件类型：`message`（交互+token 用量）/ `tool_call` / `rag` /
> `file`（附件）/ `system`（会话生命周期 marker）。
> request/鉴权事件走 `api_audit_logs`（BASE-06 接口操作日志，S01/S08 已写），不进 trace_events
> （trace_events.session_id NOT NULL，请求发生在会话建立之前）。
>
> **保留策略（D-D / DECISION-025）**：trace_events + api_audit_logs 月分区；启动即跑 + 每
> `RETENTION_CHECK_INTERVAL_HOURS` 读当前配置 DROP 过期月分区。保留天数 = 环境变量
> `TRACE_RETENTION_DAYS` / `AUDIT_RETENTION_DAYS`（默认 90，参数化非硬编码；改 .env 重启后按新天数清理）。
> 过期判定=分区起始月 < (now - retention_days)，整月粒度保守保留。

**端点**（全部 `trace:read`，租户强制过滤）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/trace/healthz` | 健康 `{status, module: "trace", phase: "S09-trace"}`（走 `/api/*` HMAC 校验，无签名 → 401） |
| GET | `/api/trace/sessions` | trace 会话列表（按 agent_id/user_id/status/start/end 过滤 + 分页；返回汇总：event_count/tool_call_count/rag_call_count/file_event_count/total_tokens） |
| GET | `/api/trace/sessions/{sid}` | 会话详情（trace_sessions 汇总；跨租户 → 403 不泄露） |
| GET | `/api/trace/sessions/{sid}/events` | 会话事件时间线（全链路；event_type/start/end 过滤 + 分页；跨租户 → 403） |
| GET | `/api/trace/events` | 事件多维检索（session_id/agent_id/event_type/start/end/keyword；keyword 走 payload_tsv tsvector 全文；租户强制过滤） |

**参数**：
- `session_id` / `agent_id` / `user_id` / `event_type`（`message|file|tool_call|rag|system`）/
  `status`（`active|ended|failed`）/ `start` `end`（ISO8601 UTC）/ `keyword`（payload 全文关键词）/
  `page`（≥1）/ `page_size`（sessions 50 默认≤500；events 100 默认≤1000）。
- 返回统一 `{items: [...], total, page, page_size}`；事件项含 `id/session_id/event_type/seq/payload/
  tool_name/rag_kb_id/file_id/message_id/token_usage/status/latency_ms/created_at`。

> **⚠️ `{sid}` 语义（S10 前端踩坑，务必遵守）**：`/api/trace/sessions/{sid}` 与 `/sessions/{sid}/events`
> 的 `{sid}` = **`trace_sessions.id`（表主键 PK）**，**不是**逻辑 `session_id` 列。
> 会话列表项**同时**返回 `id`（PK）与 `session_id`（逻辑会话 ID），二者是**不同的 UUID**（每行 id≠session_id）。
> 详情/事件按 PK 查行并判跨租户（`WHERE id = <sid>`），传逻辑 session_id 会查无行 → 误报 403「cross-tenant trace access denied」。
> **前端/测试定位详情必须用列表项的 `id` 字段**；展示给用户时可用 `session_id`（更可读）。

**脱敏（DECISION-012）**：写点统一 `redact_obj(payload)`——敏感 key（password/token/secret/
authorization/api_key/api-key/apikey/credential/access_key/secret_key/private_key，大小写不敏感）
的 value 替换为 `***`（递归 dict/list）。trace_events 与 api_audit_logs（query_digest/request_digest）
payload 均覆盖。tool_call 事件另剔除 `access_token` 入参（`_redact`）。

**内部接口**（供 S12 前端会话详情 / 其他服务）：`joker_shared.trace` 模块
`write_event / write_system_event / ensure_trace_session / list_sessions / get_session_row /
list_events / ensure_partitions / run_maintenance / retention_loop`。写失败不阻断主流程（容错策略同审计）。

## 数据模型速查（34 表，init_schema.sql 幂等初始化）

33 张静态表 + 每知识库动态向量表 `rag_chunks_vec_<kb_id>`（D-C / DECISION-024，
由 `create_rag_chunks_vec(kb_id, dim)` 函数建库时创建）。
月分区表：`trace_events` / `api_audit_logs`（`ensure_monthly_partitions(table, n)` 幂等补分区）。
全字段定义见 `02-development/DB_DESIGN.md`（唯一事实源）。
