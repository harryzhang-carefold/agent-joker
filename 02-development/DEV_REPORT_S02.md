# DEV_REPORT S02 — agent-joker 存储模块（STORE-01..07）

PROGRESS: 100% — 存储模块（local/GCS/OSS 后端 + 统一访问接口 + 上传记录 + 平台 MCP 三工具 + /internal/storage）全部交付并自测通过。

> 作者：章北海（开发工程师）｜ 2026-09-23 ｜ 卡 t_36f66f56（父 t_87ea6203，前置 t_a884eff3 S01）

## 范围（对照卡 body STORE-01..07）

| # | 要求 | 交付 |
|---|---|---|
| 1 | StorageService 统一接口（上传/下载/删除/列表，统一 URL 语义）+ StorageBackend 策略层三实现 | `joker_shared/storage/{base,local,gcs,oss,service}.py`；LocalFS（默认，volume /data/storage）/ GCS / OSS（DECISION-012 凭证 env 注入不进库） |
| 2 | 后端配置切换（STORE-03） | env `STORAGE_BACKEND=local\|gcs\|oss`（重启生效，**DECISION-027**）；行级 backend 分派（既有文件按行内 backend 从原后端读，不迁移——ARCH §9-13/DB_DESIGN §2 裁定） |
| 3 | 文件上传记录（STORE-05） | `storage_upload_records`（S01 init_schema 已建，本卡实装写入/查询；谁/何时/哪个 agent/用途/后端/路径齐全）；`GET /api/storage/upload-records` 支持时间范围/文件名/上传者/来源/状态筛选 |
| 4 | 平台 MCP 三工具（STORE-06/07） | **BFF 最小集**（`services/bff/`）：PlatformMCPServer 挂 `/mcp`（Streamable HTTP，DECISION-011，mcp SDK lowlevel Server + StreamableHTTPSessionManager stateless）；代码注册 `upload_doc`/`query_doc`/`rag_search`；工具=薄封装→ `/internal/storage/*`；`rag_search` stub 501（S05 接通，契约定死见 API_NOTES） |
| 5 | 内部凭证端点 `/internal/storage` | 供 PlatformMCPServer 以机器凭证（INTERNAL_HMAC_SECRET）代执行；DECISION-009 签名头；**中间件同步收紧：/internal/* 现在也强制 X-Auth-* 签名**（S01 遗留洞） |

## 新增 API 端点清单

### PlatformAPI（joker-api:8001，compose 发布 127.0.0.1:8080）

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| GET | `/api/storage/healthz` | —（签名头即可） | 模块健康 |
| GET | `/api/storage/backends` | storage:read | 后端配置状态（不含凭证）：active + local/gcs/oss 的 configured/error |
| POST | `/api/storage/files`（multipart `file`，query `source`/`agent_id`） | storage:write | 上传；同名 409 / 空 422 / >100MB 413 / 超配额 403 / 后端未配置 503 |
| GET | `/api/storage/files?prefix=&status=&source=&page=&page_size=` | storage:read | 本租户文件列表 |
| GET | `/api/storage/files/{file_name}` | storage:read | 按文件名下载（统一 URL 语义；不存在 404，跨租户由 tenant 行过滤天然 404） |
| DELETE | `/api/storage/files/{file_name}` | storage:manage | 软删（status=deleted）+物理删除；被 rag_docs 引用 → 409 |
| GET | `/api/storage/upload-records?file_name=&uploader_user_id=&source=&status=&start=&end=&page=&page_size=` | storage:read | 上传记录查询（STORE-05 筛选） |
| POST | `/internal/storage/upload`（multipart，query `source`/`agent_id`） | 签名头（scope 门禁留 S08） | 机器凭证代执行上传 |
| GET | `/internal/storage/files?file_name=` | 同上 | 按名/列表 |
| GET | `/internal/storage/files/{file_name}` | 同上 | 下载 |
| POST | `/internal/storage/rag-search` | 同上 | **501 stub（S05 实装）**，响应 detail 含输入/输出契约 JSON |

### BFF 最小集（joker-bff:8000，compose 发布 127.0.0.1:8000）

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/healthz` | — | 服务健康 |
| POST/GET/DELETE | `/mcp`（及 `/mcp/`） | `Authorization: Bearer <access JWT>` | MCP Streamable HTTP：initialize / tools/list（三工具）/ tools/call；无/错 token → 401 |

MCP 工具契约（`tools/list` 可见）：
- `upload_doc{file_name, content, source?, agent_id?, access_token?}` → `{id, file_name, size_bytes, backend, ...}`
- `query_doc{file_name? | prefix?, limit?}` → 文件列表（text/* 类型内联 `content`）
- `rag_search{kb_ids[], query, top_k?, score_threshold?}` → S05 前返回「not implemented (S05)」错误；契约 = items[{chunk_id, content, kb_id, doc_id, doc_file_name, pos, tag, score}] + total（S05 接通后 1:1 映射）

## 表/索引变更

无新增表/索引。`storage_files` / `storage_upload_records` 由 S01 init_schema.sql 已建（34 表骨架），本卡只实装读写语义。

## 关键实现决策

1. **DECISION-027（新增，已写 DECISIONS.md）**：存储后端切换 = env + 重启生效；行级 backend 分派保留原后端访问（不自动迁移）；云 SDK 为可选依赖（`services/requirements-cloud.txt`），未安装/配置缺失时**运行期返回明确配置错误（503 + 记录 failed upload_record）而非崩溃**。
2. **/internal/* 鉴权收紧**：S01 中间件只对 `/api/*` 验签，`/internal/*` 裸奔；本卡改为 `/api/*` ∪ `/internal/*` 强制 X-Auth-* HMAC（DECISION-009）。
3. **BFF 形态**：S02 交付 BFF 最小集（独立容器 joker-bff:8000，只含 /mcp + /healthz），不实现 S08 的限流/配置化路由/ToolInterceptor 管线（按卡约束「本卡只定义工具实现，拦截由 S08 统一接入」）。MCP 端点用根级 ASGI 分发而非 Starlette Mount（Mount 会 307 重定向 /mcp→/mcp/）。
4. **工具身份双路径**（ARCH §3.1）：生产路径 = ToolInterceptor 强制注入工具入参 `access_token`（S08）；自测/BFF 直连路径 = HTTP 层 Authorization 头校验后存 contextvar。两条路径共用同一薄封装与同一内部 HMAC 代执行，行为一致。
5. **同名文件策略**：租户内唯一，同名上传 → 409（附已存在提示），不自动版本化（ARCH §9-10 裁定）。
6. **单文件上限 100MB**【推测：闭环规模足够，超限 413】。
7. **配额**：tenants.storage_quota_mb（默认 1024MB）上传前校验，超限 403。

## 部署（compose 四容器）

```
joker-pg     pgvector/pg16        内部网络（不发布宿主端口）  healthy
joker-redis  redis:7-alpine       内部网络（DB0 + joker:* 前缀） healthy
joker-api    agent-joker-api:s02  127.0.0.1:8080→8001        healthy
joker-bff    agent-joker-bff:s02  127.0.0.1:8000→8000        healthy
```

- 新增 `deploy/Dockerfile.bff`（python:3.12-slim + requirements + requirements-cloud + bff/）
- `deploy/docker-compose.yml`：新增 bff 服务（8000 端口，mem 512m）；api 注入 GCS/OSS env 透传
- `deploy/entrypoint-api.sh`（新）：api 容器以 root 起 → `chown 1000:1000 /data`（named volume 首启属主为 root，修复非 root 进程写 /data/storage 权限）→ `gosu 1000` 降级跑 uvicorn。镜像装 gosu。
- `.env.example` 新增：`BFF_PLATFORM_API_BASE`；注释更新（DECISION-027）
- SERVER_REGISTRY.md 已登记 joker-bff（8000 端口，512Mi 限额）

## 自测（docker compose 实测，bash 05-temp/smoke_s02.sh）

27/27 PASS（2026-09-23）。覆盖：
1. local 上传/列表/下载/删除 curl 闭环（含内容一致性校验）
2. 同名 409 / 不存在 404 / 跨租户（globex 访问 acme 文件）404
3. 上传记录：成功(source=api) + 失败(409) 均留痕，按 file_name 筛选
4. 后端状态：local configured=true；gcs/oss configured=false + 明确错误信息（无云账号不崩溃）
5. /internal/storage：未签名 401；签名上传 200；rag-search 501（契约 JSON 在 detail）
6. /mcp：无 token 401；initialize 成功（serverInfo）；tools/list 含三工具；upload_doc 成功且留痕 source=mcp:platform；query_doc 返回内联内容；rag_search 返回 S05 stub 错误

自测命令：`bash 05-temp/smoke_s02.sh`（依赖 compose up 后 api+bff healthy；HMAC 密钥与种子密码从 deploy/.env 读取）

## 已知问题 / 遗留（交后续卡）

1. **rag_search 检索逻辑在 S05**：本卡 `/internal/storage/rag-search` 与 MCP `rag_search` 均为 501/错误 stub，契约已定死（API_NOTES.md），S05 接通后无需改工具侧。
2. **工具 scope 门禁 / ToolInterceptor 在 S08**：`/internal/storage/*` 目前只验签名头不验 scope；MCP 工具入参 access_token 的强制注入与 100% 拦截由 S08 统一接入（D-B）。当前工具内已自带 token 校验（无效 token → 错误语义），S08 接管后行为不变。
3. **BFF 最小集不含 S08 管线**：限流/配置化路由/OpenAI 兼容/完整拦截在 S08 实装；S08 将复用 `services/bff/` 现有 PlatformMCPServer 代码（build_server/MCPAuthMount 语义不变）。
4. **/mcp 直发宿主 8000**：S11 集成后改经 8080→nginx→bff（ARCH §5.2），届时 8000 收回容器内。
5. **大文件**：上传经内存 bytes（100MB 上限内足够）；>100MB 流式分片留迭代。
6. **删除为同步物理删除**（非「异步清理【推测】」）：闭环规模同步足够；若后续文件量大可改任务队列。
7. FERNET_KEY 跨重启随机问题（S01 遗留 5）：本卡未启用凭证加密（云凭证走 env），不受影响；S11 集成前仍须显式配置 FERNET_KEY（LLM endpoint key 加密需要）。

## 交付文件清单

```
services/shared/joker_shared/storage/{__init__,base,local,gcs,oss,service}.py   （新）
services/api/app/routers/storage.py                                             （新，/api/storage + /internal/storage）
services/api/app/routers/__init__.py                                            （storage 实装替换占位）
services/api/app/middleware.py                                                  （/internal/* 加入 HMAC 强制签名）
services/bff/app/{__init__,main,mcp_auth,platform_mcp}.py                       （新，BFF 最小集 + PlatformMCPServer）
services/requirements.txt                                                       （+mcp>=1.9,<2.0）
services/requirements-cloud.txt                                                 （新，google-cloud-storage/oss2 可选）
deploy/Dockerfile.bff                                                           （新）
deploy/Dockerfile.api                                                           （+云 SDK、gosu、entrypoint）
deploy/entrypoint-api.sh                                                        （新，卷属主修复 + 非 root）
deploy/docker-compose.yml                                                       （+bff 服务；api 云 env；镜像 s02）
deploy/.env.example                                                             （+BFF_PLATFORM_API_BASE）
02-development/API_NOTES.md                                                     （S02 段：storage + /internal + /mcp 三工具契约）
00-management/DECISIONS.md                                                      （+DECISION-027）
~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md                     （joker-bff 8000 登记）
05-temp/smoke_s02.sh、wait_health_s02.sh                                        （自测）
```

## 结论

S02 五项范围全部交付，卡内自测 27/27 PASS（docker compose 实测：local 闭环、409/404/跨租户隔离、上传记录可查、后端切换配置生效（无云账号明确报错不崩溃）、/internal/storage 机器凭证代执行、/mcp 三工具可列出且 upload_doc/query_doc 闭环、rag_search 按契约 stub）。未自行宣布项目完成——进入 S03（LLM 节点）由编排链自动派发。

## 续跑修复记录（2026-09-23，第 2 轮，断点续做）

上一轮耗尽 150 步预算时正卡在「上传 500」复测。本轮定位为 3 个真实缺陷（全部在 S02 交付代码/ schema 内，已修并复测通过）：

1. **`init_schema.sql` 触发器语法非法**：`CREATE TRIGGER IF NOT EXISTS ...` 在 PostgreSQL **不存在**（触发器无 `IF NOT EXISTS`）→ 启动种子 `apply_schema` 逐句执行时该句报错，**整事务回滚**，每次启动都刷 seed failed 日志（服务继续但 schema 靠持久卷旧数据掩盖）。已改为 25 处 `DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='...') THEN CREATE TRIGGER ...; END IF; END $$;`（与文件既有 DO 块同构，seed 分割器可解析）。已在**全新空库**验证 187/187 语句 fresh + 幂等通过（05-temp/validate_schema_s02.py）。
2. **`storage/service.py` 上传 SQL `:ct::text` 被 SQLAlchemy 丢弃**：SQLAlchemy `text()` 中**紧邻 `::` 的命名参数不被识别为绑定参数**（文档明确的 `::` gotcha）→ 字面 `:ct` 直达 asyncpg → `syntax error at or near ":"`。已改 `CAST(:ct AS text)`。
3. **`_record` INSERT 的 `CASE WHEN :f IS NULL THEN NULL ELSE CAST(:f AS uuid) END`**：asyncpg 对 `$3 IS NULL`（NULL 比较）无法推断 `$3` 类型 → `AmbiguousParameterError: could not determine data type of parameter $3`。已改直接 `CAST(:f AS uuid)`（NULL 可 cast 为 NULL）。

另修 BFF `platform_mcp.py` `query_doc`：内联文件内容的 `for` 循环误放在 `async with httpx.AsyncClient` 块**外**（client 已关闭）→ `Cannot send a request, as the client has been closed`。已把内容读取并入 client 作用域。

**给后续切片（S03..S11）的铁律**：写 `text()` 原始 SQL 时，**任何命名参数后紧跟 `::` 都会被 SQLAlchemy 当字面量丢弃**——类型转换一律用 `CAST(:p AS type)`，禁用 `:p::type`；可空 uuid 参数直接 `CAST(:p AS uuid)`，勿用 `CASE WHEN :p IS NULL`（asyncpg 类型推断会挂）。

自测脚本 `05-temp/smoke_s02.sh` 本轮加固为**可重复执行**（启动清理遗留自测文件 + 各上传站点用独立文件名避免交叉污染），并补 `s02_cleanup.py`。S01 自测复跑 21/21 PASS（确认 init_schema.sql 改动无回归）。
