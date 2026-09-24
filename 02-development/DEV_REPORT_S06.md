# DEV_REPORT_S06 — agent-joker MCP 注册管理 + Skills（t_d2e1eaf0）

PROGRESS: 100% — 全部交付 + 自测 69/69 PASS + 回归全绿（S05 44/44 / S02 27/27 / S01 21/21），可进入 S07（agents）

## 范围（MCP-01/02/03 + SKILL-01/02）

| 项 | 状态 | 说明 |
|---|---|---|
| MCP-01 server 注册管理 | ✅ | `joker_shared.mcp.registry`：URL 注册（streamable_http/sse，auth_headers Fernet 加密落 `auth_headers_enc`，响应只回 `auth_headers_set`）+ 编辑/禁用/删除（软删）+ **注册即同步**（连通性探测 + 工具全量 upsert；探测失败保留 `unreachable`+`sync.error` 不丢注册） |
| MCP-02 工具同步与管理 | ✅ | `POST /refresh` 全量同步：tools/list 探测 + upsert + **removed_remote 反向标记**（远端消失不删行、重出现复活）+ 缓存失效；工具 enable/disable/delete（平台侧移除不删远端）；`usable = enabled && !removed_remote && server.online` |
| MCP-03 关联调用方提示 | ✅ | server/工具级 `referring-agents`（agent_mcp_tools 勾选反查）；删除/禁用有引用且 confirm=false → 409 + 清单，confirm=true 放行 |
| DECISION-010 工具 schema 缓存 | ✅ | Redis `joker:mcp:tools:<tenant>:<server>`，TTL `MCP_TOOL_CACHE_TTL`（默认 600s）；注册/refresh/工具增删改自动失效；出参 `cache=hit\|miss\|refreshed`；Redis 抖动降级 DB 不阻断（S08 ToolInterceptor 消费入口） |
| 平台内置 server | ✅ | `main.py` 启动 hook 幂等注册系统租户 `joker-platform`（is_platform=true，同步平台三工具 source=platform）；跨租户只读、管理操作 409；平台工具跨租户可见（`s.is_platform = true` 参与 JOIN） |
| SKILL-01 skill CRUD | ✅ | `joker_shared.skills.service`：列表/详情/内联创建/更新/删除；`skills:manage`（写）/`skills:read`（读）门禁；租户行级隔离 |
| SKILL-02 多文件上传 | ✅ | `POST /api/skills/upload` multipart `files[]` 经 S02 StorageService 落盘（source=skill）；首文件=main 其余=asset（skill_files FK→skills）；删除 skill → 文件物理删除（被 RAG 文档引用跳过 → `files_skipped` 不阻断） |

## 新增 API 端点清单

全部 `/api/mcp/*`、`/api/skills/*` 需 X-Auth-*（DECISION-009）。API 面已同步 `02-development/API_NOTES.md`（新增「mcp」「skills」两章节 + 占位表更新）。

**mcp（MCPRegistryService）**：
- `GET /api/mcp/servers[?status=]`（`mcp:manage` 或 `mcp:tool`）/ `GET /servers/{id}`
- `POST /servers`（`mcp:manage`，201，注册即同步）/ `PUT /servers/{id}` / `DELETE /servers/{id}?confirm=` / `POST /servers/{id}/refresh`
- `GET /servers/{id}/referring-agents`（MCP-03）/ `GET /servers/{id}/tools[?status=&source=]`
- `POST /tools/{id}/disable?confirm=` / `POST /tools/{id}/enable` / `DELETE /tools/{id}?confirm=` / `GET /tools/{id}/referring-agents`
- `GET /servers/{id}/tools-cache?refresh=`（DECISION-010 缓存）

**skills（SkillsService）**：
- `GET /api/skills[?status=&source=]`（`skills:manage` 或 `skills:read`）/ `GET /{skill_id}`
- `POST /api/skills`（201 内联）/ `POST /api/skills/upload`（201 multipart 多文件）/ `PUT /{skill_id}` / `DELETE /{skill_id}`

## 表/索引变更

无新增表（34 表骨架 S01 已建）。本切片启用/依赖：
- `mcp_servers` / `mcp_tools`（MCP-01/02；`deleted_at` 软删过滤全路径）
- `agent_mcp_tools`（MCP-03 反查引用）
- `skills` / `skill_files`（SKILL-01/02；FK CASCADE）
- `storage_files` / `storage_upload_records`（source=skill 留痕，S02 复用）
- Redis key `joker:mcp:tools:<tenant>:<server>`（DECISION-010）

## 关键实现与修复（本轮迭代）

1. **cyextension Row 字符串下标 500**：`joker-shared` 用 cyextension SQLAlchemy，`Row` 不支持 `row["key"]`，统一改 `row._mapping["key"]`（registry.py 全量 16 处；`GET /servers`、`probe_and_sync` 首跑 500 的根因）。
2. **jsonb 绑定 cast 语法**：`input_schema = :s::jsonb` 在该绑定路径报错 → 改 `CAST(:s AS jsonb)`（3 条 INSERT/UPDATE mcp_tools）。
3. **skill_files FK 顺序**：上传原先插 skill_files 后插 skills（FK 违反映射 500）→ 改为**先插 skills 行再挂 skill_files**，file_count 最后回写。
4. **`_fetch_tool` 密文泄漏**：原 `SELECT *` join server 会把 `auth_headers_enc` 拉进工具响应 → 改 `SELECT t.*` 只取工具列。
5. **`_fetch_server` 软删过滤**：补 `deleted_at IS NULL`（软删后仍 200 的 bug）。
6. **`GET /servers` 读门禁**：补 `require_scope("mcp:manage", "mcp:tool")`（与 tools/tools-cache 一致，缺 scope → 403）。

## 部署

- 镜像：`agent-joker-api:s05`→`s06`（`docker build -f Dockerfile.api` 重建，镜像内已验证含新代码）；`agent-joker-bff:s05` 不变（BFF 无 S06 代码变更）。
- 启动命令：`cd deploy && docker compose up -d`（api 平滑替换，8080/8000 端口/卷/网络不变，无数据丢失——数据在 joker-pg 独立实例）。
- 实测回写（`docker stats`，2026-09-23）：joker-api 89.1Mi/1Gi、joker-bff 73.6Mi/512Mi、joker-pg 89.3Mi/1Gi、joker-redis 18.1Mi/256Mi（均 healthy）。无新增宿主端口。
- 台账 `~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md` 已更新（joker-api 镜像版本 s06 + 项目关系行 + S06 部署更新记录）。

## 自测命令与结果

- **S06 E2E：`python3 05-temp/e2e_s06.py` → 69/69 PASS**（`05-temp/e2e_s06_run.log`）。真实 HTTP（127.0.0.1:8080 api / 127.0.0.1:8000 bff）+ 真实 PG + **真实 mock MCP 容器**（`05-temp/mock_mcp_server.py`，Streamable HTTP，工具集由 `/tools.json` 驱动可热切换；用 api 镜像跑，避免宿主 venv 被安全扫描拦截）。覆盖：
  - 平台内置 server：列表含 joker-platform / is_platform=true / 管理操作 409
  - 注册（连通性探测 + 全量同步 3 工具）/ 不可达 URL 保留 unreachable / 本租户重名 409 / 缺 url 422
  - refresh upsert（mock 工具集 [alpha,delta] → beta/gamma 标 removed_remote + delta 新增）→ 再切回 [alpha,beta]（beta 复活、delta removed）
  - 工具缓存：首读 miss 回填 / 二读 hit / 禁用后失效 miss 且 enabled=false / refresh=true 强制 rebuilt
  - MCP-03：seed agent + agent_mcp_tools 勾选 → referring-agents 命中；禁用/删除被引用工具 confirm=false → 409 含清单、confirm=true 放行
  - server 编辑/禁用（status=disabled → 工具 usable=false）/ 软删后 404
  - Skills：内联创建 / 多文件上传（main+asset，storage source=skill 留痕 + 文件字节可下载）/ 列表+status/source 过滤 / 更新 / 删除（2 文件物理删除 + 记录 404）
  - scope 门禁：无 mcp:manage 注册 403 / 无 skills:manage 写 403 / 缺 mcp:manage 列表 403
  - 跨租户：globex 租户看 acme server 404
  - S05 回归：BFF `/mcp` 三工具可调用（upload_doc/query_doc/rag_search）+ 无 token 401
- **S05 回归：`python3 05-temp/e2e_s05.py` → 44/44 PASS**
- **S02 回归：`bash 05-temp/smoke_s02.sh` → 27/27 PASS**
- **S01 回归：`bash 05-temp/smoke_s01.sh` → 21/21 PASS**

## 遗留问题 / 风险

- **SSE transport** 已接受入参（`transport=sse`）但 E2E 只覆盖 streamable_http（mock server 仅 streamable_http 实现）；S08 ToolInterceptor 实装时需补 SSE 探测路径验证。
- **工具调用拦截（D-B）** 未在本切片范围：`enabled=false`/`removed_remote` 目前只影响 `usable` 语义与缓存快照，实际拒绝调用由 S08 ToolInterceptor 按缓存判定（MCP-02 验收 2 的「agent 侧不可调用」闭环在 S08）。
- **skill 与 agent 绑定**（agent 选用 skill）归 S07（agents 切片），本切片 skills 表暂无 agent 反查端点。
- 平台内置 `joker-platform` 的工具行 `required_scopes` 由 `platform_tools.PLATFORM_TOOL_SCOPES` 固化（upload_doc/query_doc/rag_search），与 BFF 实装三工具一致；S08 接入时以缓存快照为准。
- 真实 LLM 端点（34.121.9.233:4000/v1）当前 401（S03 已记环境态）；S06 链路不依赖 LLM，E2E 全部真实 HTTP 无 mock 断言。
