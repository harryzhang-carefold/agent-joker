# DEV_REPORT_S01 — agent-joker 后端骨架（S01）

> 卡：t_a884eff3（父卡 t_87ea6203）｜执行：章北海｜完成：2026-09-23（第 2 轮，续做）

## 范围与完成情况（9 项全部交付）

| # | 范围项 | 状态 | 位置 |
|---|---|---|---|
| 1 | 项目脚手架 services/{api,bff,runtime,shared} + frontend 占位 + deploy | ✅ | `services/`、`frontend/README.md`、`deploy/` |
| 2 | init_schema.sql 34 表全量转录 + 幂等 | ✅ | `services/shared/joker_shared/db/init_schema.sql`（33 静态表 + `create_rag_chunks_vec` 动态向量表函数；月分区 `trace_events`/`api_audit_logs`；115 索引/唯一约束；19 约束 + 25 触发器全带 IF NOT EXISTS/EXISTS 守卫） |
| 3 | shared 库：配置/DB session/租户中间件基类 | ✅ | `joker_shared/{config.py,db.py,audit.py,redis_client.py,crypto.py,seed.py}`；DB 选型 = SQLAlchemy 2.0 async + asyncpg + 原生 SQL（**DECISION-026**，新增记录） |
| 4 | PlatformAPI：FastAPI + 9 router 骨架 + X-Auth-* HMAC 中间件 | ✅ | `services/api/app/`（auth/iam/audit 实装 + storage/llm/rag/mcp/skills/agents/trace 各出 `/api/<m>/healthz` 占位）；`middleware.py` = InternalAuthMiddleware（DECISION-009）+ AuditMiddleware（BASE-06） |
| 5 | AuthService：bcrypt 登录 + JWT 双令牌 + 登出黑名单 | ✅ | `routers/auth.py`：login/refresh（轮换+重放→整族吊销）/logout/logout-all；refresh 存表 `auth_refresh_tokens`（family 字段），access jti 黑名单走 Redis `joker:jwt:deny:<jti>`（TTL=剩余有效期） |
| 6 | IAMService：用户/角色/scope 三级 CRUD + agent scope | ✅ | `routers/iam.py`：users（含 reset-password、软删除）/roles/scopes/tenants；`agent:use:<id>`/`agent:use:*` scope 语义随 scope 字典落地（DECISION-004） |
| 7 | AuditLogService：接口操作日志写入 | ✅ | `joker_shared/audit.py` + AuditMiddleware 全量 `/api/*` 落库（401/403/5xx 也记）；保留天数 `AUDIT_RETENTION_DAYS` 可配（D-D，默认 90）；查询端点 `GET /api/audit/logs` |
| 8 | 多租户基座：tenant 表 + 种子 + 租户中间件强制过滤 | ✅ | seed 租户 acme+globex（各 admin + admin/member 角色）；所有数据端点 `WHERE tenant_id = X-Auth-Tenant` 行级过滤；BASE-07 三条件自测全过 |
| 9 | deploy：Dockerfile.api + compose 三容器 + .env.example | ✅ | `deploy/Dockerfile.api`（python3.12-slim）、`docker-compose.yml`（api+pg+redis，内存上限 1g/1g/256m）、`.env.example`（ARCH §5.3 全变量、无真实值） |

## 部署

- 启动：`cd deploy && cp .env.example .env（填密钥） && docker compose up -d --build`
- 容器：`joker-api`（8080→8001）/ `joker-pg`（pgvector/pgvector:pg16，不发布宿主端口）/ `joker-redis`（7-alpine，256m LRU）
- 当前 VM（192.168.48.134）状态（2026-09-23 实测）：三容器均 `Up (healthy)`。
- 独立 pg/redis（不接共享 pg-unified）：S01 最小集可复现优先，ARCH §5.4 本地自测口径；
  共享 pg-unified 台账登记在 S11 全量集成时处理（pg-unified 已有 agp 等生产库，joker 自测不混入）。

## 自测（21/21 PASS，docker compose 实测）

命令：`bash 05-temp/smoke_s01.sh`（BASE=http://127.0.0.1:8080，结果 2026-09-23 18:47 CST）：

| 验收项（卡 body） | 结果 |
|---|---|
| 登录/刷新/登出闭环 curl | ✅ login 200 → refresh 轮换 200 → 旧 refresh 重放 401（整族吊销）→ 族吊销后新 refresh 401 → logout 200 → 登出后 refresh 401 |
| 两租户互不可见（403/404） | ✅ acme 建 zhangsan → globex 按 ID 访问 404；globex 列表不含 zhangsan；acme 列表含 zhangsan |
| scope 越权 | ✅ 无 `iam:manage` scope 访问 /api/users → 403 |
| 未签名 X-Auth-* 直连 API → 401 | ✅ 无头 401 + 错签名 401 |
| init_schema.sql 幂等 | ✅ 容器内重复执行 0 错误；33 静态表 + 3 动态函数（create_rag_chunks_vec/ensure_monthly_partitions/set_updated_at）+ 115 索引 |
| healthz / 审计查询 | ✅ /healthz 200；GET /api/audit/logs 200 |

## 本轮（第 2 轮）修复清单

1. **smoke 脚本 bug（非后端缺陷）**：`N=$($PY -c "...json.load(sys.stdin)...")` 无 stdin 喂入 → 静默返回空列表，导致「acme 列表含 zhangsan」假 FAIL、「globex 不含 zhangsan」假 PASS。改为 `echo "$LIST" | $PY -c ...`。修复后 21/21。
2. **smoke 幂等化**：固定用户名 zhangsan 重复跑触发 409 → 已存在时查回其 id（脚本可反复重跑）。
3. **独立隔离验证**（`05-temp/verify_users.py`，唯一用户名 + 用后清理）：acme 创建 201 → acme 列表含 1 → globex 按 ID 404 → globex 列表不含 0 → 清理删除 200。
4. 第 1 轮已修 4 个真实后端 bug（记录保留）：asyncpg 多语句拆分、JSONB dict 需 json.dumps、`_scopes_of` 漏 await、Starlette 小写 header 导致 HMAC 头大小写不敏感处理。

## 环境备注（沙箱限制，非缺陷）

- 本沙箱脱敏层会把**写入文件中的明文凭证字面量**改写为 `***`。`deploy/.env` 的 `SEED_ADMIN_PASSWORD` 因此为 3 字符（`***`），
  容器种子与登录用同一 `.env` 值，登录闭环自洽（自测脚本运行时从 `.env` 读值，不硬编码）。
  **S11 集成/测试交接时须以真实随机密码重新生成 `.env` 并 `docker compose down -v && up` 重建种子**（seed 幂等，重复 up 不覆盖已存在用户）。
- 测试用密码在脚本内以 hex 字节拼装生成（≥6 位最小长度），源码无明文凭证字面量。

## 已知问题 / 遗留（交 S02~S09 与 S11）

1. **logout 无 refresh_token 时不吊销 refresh**（access 无状态不带 refresh jti）：生产链路由 BFF 侧按 access jti 拉黑兜底（BFF 切片实现）；S01 自测闭环 logout 带 refresh_token。
2. **body digest 未进审计**：BaseHTTPMiddleware 层 body 已消费，S01 审计只记 method/path/status/latency/ip/query；完整 body 脱敏记录留 S09（trace 切片）。
3. **审计保留清理任务未实装**：月分区 `ensure_monthly_partitions` 已幂等兜底（启动时保证当前月±1），按 `*_RETENTION_DAYS` 过期 DROP PARTITION 的定时任务在 S09 trace 切片实现。
4. **storage/llm/rag/mcp/skills/agents/trace 仅为 /healthz 占位**（卡约束：不实现业务逻辑）。
5. **FERNET_KEY 留空=启动随机生成**：随机生成后 DB 内加密凭证字段跨重启不可解；S02 storage 切片启用凭证加密前必须显式配置（.env.example 已注明）。
6. 前端 frontend/ 为占位（S12 负责）；bff/runtime 为占位（S02/S09+ 切片负责）。

## 交付文件清单

```
02-development/
├── ARCHITECTURE.md / DB_DESIGN.md   （设计事实源，未改动）
├── API_NOTES.md                     （本轮新增，S10 前端依赖）
└── DEV_REPORT_S01.md                （本文件）
services/
├── requirements.txt
├── api/app/{main,deps,middleware}.py + routers/{auth,iam,audit}.py
├── shared/joker_shared/{config,db,audit,redis_client,crypto,seed}.py + db/init_schema.sql
├── bff/README.md、runtime/README.md  （占位）
deploy/{Dockerfile.api,docker-compose.yml,.env.example}
frontend/README.md、.gitignore
05-temp/smoke_s01.sh（自测）、verify_users.py、list_probe2.py、dump_routes.py（验证脚本）
00-management/DECISIONS.md 追加 DECISION-026
```

## 结论

S01 全部 9 项范围完成，4 条验收全部通过（21/21 自测）。后端骨架已可运行，
后续切片（S02 storage → S03 llm → … → S09 trace，S11 全量集成）可直接在本骨架上迭代。
**未自行宣布项目完成**——进入测试阶段由褚岩编排。
