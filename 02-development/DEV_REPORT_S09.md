# DEV_REPORT_S09 — agent-joker Trace + 检索（全链路事件 + 会话检索 + 保留天数可配置[D-D] + 月分区清理 + 脱敏）（t_075d0bf0）

PROGRESS: 100% — S09 全部交付 + 镜像 `agent-joker-api:s09` 已构建部署（compose up -d api 平滑替换，8080 端口/卷/网络不变），
**S09 E2E 37/37 PASS**（05-temp/e2e_s09_run4.log）。修复 1 个真实产品 bug（retention 分区 DROP 的 relkind 判定）+ 1 个 mock LLM
通用化缺陷。API_NOTES 已同步。详见「部署」「自测」两节与 SERVER_REGISTRY 记录。

## 范围（TRACE-01/02 + D-D / DECISION-025 + DECISION-012）

| 项 | 状态 | 说明 |
|---|---|---|
| TRACE-01 全链路 trace 写入 | ✅ 代码完成 | `joker_shared.trace.TraceService`：`write_event`（统一入口，写失败不阻断主流程）/ `write_system_event`（会话 start/end）/ `ensure_trace_session`（取/建 trace_sessions，agent/user 回退语义）。事件类型 message/tool_call/rag/file/system；事件级明细表 `trace_events`（月分区，D-D） |
| 各组件写 trace 埋点 | ✅ 代码完成（复用既有） | SAR（S07）：message（轮次+token 用量）/ tool_call（经 ToolInterceptor 100% 留痕）/ rag（RAG 预检索 D-B 直调）/ file（附件）；BFF（S08）：拦截 tool_call；PlatformAPI（S01）：request/鉴权 → `api_audit_logs`（BASE-06，不进 trace_events）。本卡统一 trace 写入接口 + 按 (tenant_id, session_id/agent_id/trace_id) 检索 |
| TRACE-02 会话/事件检索 | ✅ 代码完成 | `list_sessions`（按 agent/用户/状态/时间，租户强制过滤）/ `get_session_row`（跨租户 403 判定用，不过滤 tenant）/ `list_events`（会话时间线 / agent / 事件类型 / 时间范围 / 关键词 payload_tsv tsvector 全文）。供 S12 前端会话详情 |
| 保留天数可配置（D-D / DECISION-025） | ✅ 代码完成 | `trace_events` + `api_audit_logs` 月分区；`ensure_partitions`（当前月 ±1 幂等建分区）+ `run_maintenance`（按 `TRACE_RETENTION_DAYS`/`AUDIT_RETENTION_DAYS` DROP 过期月分区，参数化非硬编码，每次读当前配置）+ `retention_loop`（启动即跑 + 每 `RETENTION_CHECK_INTERVAL_HOURS` 一次）。默认 90 天，.env 可配 |
| 脱敏（DECISION-012） | ✅ 代码完成 | 所有 trace_events payload 经 `redact_obj`（复用 audit 单一源）：敏感 key（password/token/secret/authorization/api_key/api-key/apikey/credential/access_key/secret_key/private_key，大小写不敏感）value → `***`（递归 dict/list）。覆盖 api_audit_logs（query_digest/request_digest）+ trace_events payload；tool_call 另剔除 access_token 入参 |
| 检索端点（TRACE-02） | ✅ 代码完成 | `services/api/app/routers/trace.py`：`/api/trace/healthz`（公开）/ `/api/trace/sessions` / `/api/trace/sessions/{sid}` / `/api/trace/sessions/{sid}/events` / `/api/trace/events`。scope `trace:read`；跨租户 403 不泄露 |

## 新增 API 端点清单（`/api/trace/*`，需 X-Auth-*（DECISION-009）+ scope `trace:read`）

- `GET /api/trace/healthz`（走 `/api/*` HMAC 校验，无签名 → 401）→ `{status, module: "trace", phase: "S09-trace"}`
- `GET /api/trace/sessions[?agent_id=&user_id=&status=&start=&end=&page=&page_size=]` → `{items, total, page, page_size}`（trace_sessions 汇总：event_count/tool_call_count/rag_call_count/file_event_count/total_tokens）
- `GET /api/trace/sessions/{sid}` → 会话详情（跨租户 → 403 不泄露存在性）
- `GET /api/trace/sessions/{sid}/events[?event_type=&start=&end=&page=&page_size=]` → 会话事件时间线（全链路；跨租户 → 403）
- `GET /api/trace/events[?session_id=&agent_id=&event_type=&start=&end=&keyword=&page=&page_size=]` → 事件多维检索（keyword 走 payload_tsv tsvector 全文）

完整参数/返回/脱敏说明见 `02-development/API_NOTES.md`「trace」章节（已同步，供 S10/S12 前端）。

## 表/索引变更（沿用 S01 init_schema.sql 既有结构，本卡无新增 DDL）

- `trace_events`（月分区，`PARTITION BY RANGE (created_at)`，PK `(id, created_at)`，UNIQUE `(session_id, seq, created_at)` 含分区键）：
  - `payload_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', payload::text)) STORED` + `idx_trc_events_payload_tsv GIN`（TRACE-02 关键词全文）
  - 索引 `idx_trc_events_session/type/tool/status`（均含 created_at）
- `api_audit_logs`（月分区，S01 已建）
- 月分区由 `init_schema.sql` `ensure_monthly_partitions(table, N)` 幂等创建（分区名 `<table>_YYYY_MM`，如 `trace_events_2026_09`）
- 配置：`joker_shared/config.py` 新增 `TRACE_RETENTION_DAYS=90` / `AUDIT_RETENTION_DAYS=90` / `RETENTION_CHECK_INTERVAL_HOURS=1`；`deploy/.env.example` + `deploy/docker-compose.yml` 已加三变量透传

## 部署

- **镜像**：`agent-joker-api:s09`（`cd deploy && docker build -f Dockerfile.api -t agent-joker-api:s09 ..`）。
  本轮重建 2 次：① 固化 retention 修复 + mock LLM 通用化；② 固化 mock LLM 工具名解析修复。
  mock LLM/MCP 容器由 e2e 从本镜像 `docker run`（S07/S08 同款闭环）。
- **平滑替换**：`docker compose up -d api`（joker-api 重建，8080 端口/卷/网络/数据不变；pg/redis 不动）。
- **无新增宿主端口**：trace 检索走既有 8080（api）/8000（bff 转发）。mock 容器自测端口 9301（LLM）/9101（MCP）仅 e2e 期间存在。
- **实际资源占用**（docker stats，2026-09-23，部署后）：
  | 容器 | 镜像 | 内存 | 备注 |
  |---|---|---|---|
  | joker-api | agent-joker-api:s09 | 151.5MiB/1GiB (14.8%) | healthy |
  | joker-bff | agent-joker-bff:s08 | 141.7MiB/512MiB (27.7%) | healthy |
  | joker-pg | pgvector/pgvector:pg16 | 98.6MiB/1GiB (9.6%) | healthy |
  | joker-redis | redis:7-alpine | 18.7MiB/256MiB (7.3%) | healthy |
  | joker-mock-llm-s09 | agent-joker-api:s09 | 25.8MiB | e2e 临时（e2e 后清） |
  | joker-mock-mcp-s09 | agent-joker-api:s09 | 43.1MiB | e2e 临时（e2e 后清） |
- **SERVER_REGISTRY.md**：已登记 s09 行（image/容器/端口/资源实际值/部署时间）。
- **retention 定时任务**：joker-api lifespan 启动 `retention_loop()`（启动即跑一次 + 每小时读当前配置 DROP 过期月分区），容器内后台 asyncio task，随 api 容器生命周期。

## 自测

**命令**：`python3 05-temp/e2e_s09.py`（真实 HTTP：BFF 8000 / API 8080 + 真实 PG/Redis + mock LLM + mock MCP）。
**结果**：**37/37 PASS**（05-temp/e2e_s09_final.log，复跑复现；前序 e2e_s09_run4.log 同款全绿）。

覆盖 S09 全部验收点：

| # | 验收点 | 结果 | 证据 |
|---|---|---|---|
| 1 | 一次 agent 对话产生完整 trace 链（request→轮次→tool_call→rag→token）可检索 | ✅ PASS | events=8，event_types={system, message, rag, tool_call}；token 用量在 message 事件（seq 4/7）；tool_call 筛选 count=1；关键词 `trace-s09-test` tsvector 命中 5 |
| 2 | 保留天数可配（改 TRACE_RETENTION_DAYS 后按新天数清理） | ✅ PASS | selftest_retention 隔离表：retention=90 仅 DROP 2020_01（保 2026_07/2026_09）→ 改 30 再 DROP 2026_07（保 2026_09）；drop_90=1 / drop_30=1 |
| 3 | 月分区表存在且过期分区可 DROP | ✅ PASS | trace_events 月分区 ≥3 个（2026_07/08/09）；建过期分区 2020_01 → run_maintenance 按当前配置 DROP（after 无 2020_01，保当月） |
| 4 | trace/审计中无明文密钥（脱敏生效） | ✅ PASS | 经 write_event 写含 api_key/password/auth_headers.Authorization 的 system 事件 → DB payload 三字段均为 `***`（testval_abc/xyz/tok 不落库）；api_audit_logs 无明文 |
| 5 | 跨租户 trace 检索 403 | ✅ PASS | globex 访问 acme trace 会话/事件 → 403；acme 本租户访问 → 200（对照组） |
| 6 | /api/trace/healthz 未鉴权被拒 | ✅ PASS | 无 X-Auth-* 签名头 → 401 |

**回归**：S07 场景 mock LLM 工具触发向后兼容（`mcp_<uuid>_s07_echo` → tool_call x=hello-s07；普通问答 → 退款答案），S12 重建容器不丢行为。

## 修复的真实缺陷（本轮）

1. **retention 分区 DROP 失效（产品 bug）**：`drop_expired_partitions`（joker_shared/audit.py）查询用
   `AND c.relkind = 'p'` 过滤子表，但 PostgreSQL 中**分区子表 relkind='r'（普通表），仅父表为 'p'**，
   导致查不到任何分区 → DROP 恒返回 0（隔离表 + 真实 trace_events 2020_01 都不被清理）。
   **修复**：改为 `AND c.relispartition`（正确判定「此表是某父表的分区」）。E2E 自测 drop_90/drop_30=1、
   真实 2020_01 被 DROP 验证通过。

2. **mock LLM 工具名解析（mock 资产缺陷，影响 S09 闭环）**：原 mock LLM 硬编码只认 `s07_echo`，
   且 base 名解析用 `rsplit("_",1)` 对 `mcp_<uuid>_<tool>`（UUID 无下划线）取错段（取到 `echo`），
   导致 S09 的 `s09_echo` 工具不触发 tool_call。
   **修复**（services/mocks/mock_llm/server.py）：通用化——取 tools 里 `*_echo` 工具，
   base 名 = `mcp_` 之后首个下划线后的段（UUID 边界，如 `s09_echo`）；用户消息含 base 名 → 发 tool_call，
   args.x 回显用户消息中形如 `x-y`（字母数字连字符）的值（如 `trace-s09-test`/`hello-s07`）。
   向后兼容 S07（已实测）。固化进 s09 镜像，S12 重建容器不丢。

## 遗留问题 / 已知约束

- 真实 27B LLM 端点 401 不可达（环境态，S03/S07/S08 已记录）→ E2E 自测走 mock LLM 容器闭环（card 允许）；
  生产/有端点时走真实 27B，trace 埋点路径一致（SAR runtime 统一写点）。
- `/mcp` BFF 直连无特定 agent → tool_call trace 回退租户首个 active agent（S08 已记录）；S09 未改，
  SAR/第三方 agent 路径有真实 agent_id。
- retention 清理为**整月粒度**（分区起始月 < now - retention_days 才 DROP），保证保留期内数据完整；
  非「精确到天」删除（月分区语义，D-D 设计如此）。
- 脱敏按**字段名**触发（敏感 key 的 value → ***），非值特征匹配；若业务把密钥放在非敏感字段名下需显式补充。

## 文件清单（本轮改动）

- `services/shared/joker_shared/audit.py`（retention relispartition 修复）
- `services/mocks/mock_llm/server.py`（通用 echo 工具触发 + UUID 工具名解析 + re 导入）
- `02-development/API_NOTES.md`（新增 trace 章节 + 占位表更新）
- `05-temp/e2e_s09.py`（harness 修复：mock LLM 端口 9301 避 9300 占用 + MOCK_LLM_PORT/MOCK_MCP_PORT 环境变量对齐内网监听端口 + healthz 无签名头测 401 + redact 查询简化 + agent 创建防御）
- `05-temp/probes_s09.py` / `reltest_s09.py` / `redact_dbg_s09.py` / `evdbg_s09.py` / `basetest*.py` / `s07_compat_s09.py`（诊断探针）
- `05-temp/build_s09_fix*.log` / `e2e_s09_run*.log` / `compose_up_api_s09fix.log`（构建/自测日志）

## 下一步

测试阶段（云天明 S12）+ 验收（褚岩 S13）。前端 S10 可据 API_NOTES「trace」章节接入会话详情展示。
