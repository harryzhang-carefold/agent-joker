# DEV_REPORT_S36 — agent-joker failed 文档可重试（retry 接口 + UI 按钮）

- 任务：S36（t_c343be35，zhangbeihai）
- 日期：2026-09-29
- 上游：S35（t_c74de813，TEST PASS 交 S36）

## 1. 任务与现状核对

任务要求：
1. 后端 `POST /api/rag/kbs/{kb_id}/docs/{doc_id}/retry`：failed → pending 重新入队（复用现有 worker），
   返回 202 + doc 状态；仅 failed 可重试，其余 409。
2. 前端 KbDetailView：failed 行「重试」按钮，点击调 retry，toast 结果。
3. 自测（真实端点）：造 failed 文档 → retry → 状态变 ready；对 pending/ready 文档 retry → 409。
4. 证据：`03-testing/dev_probe_s36_*.log`（真实 HTTP 原始响应，禁止 mock）。

**核对发现（重要）**：S35 报告称「后端无 /retry 接口」——**该判断有误**。
retry 端点自初始 commit（a120497）即存在于代码，且部署运行的 s32 镜像容器内
（`docker exec joker-api grep /app/api/app/routers/rag.py` → 命中 L235）同样存在。
前端「重试」按钮 + `api.retryDoc` 也已存在。S35 观察到的真实差距是：
- 端点返回 **200**，任务要求 **202**；
- 前端 `onRetry` 无错误处理（409/500 时静默失败、无错误 toast）。

因此 S36 实际改动 = 202 状态码 + 前端 toast 结果 + 全链路真实自测。

## 2. 代码改动（3 文件）

| 文件 | 改动 |
|---|---|
| `services/api/app/routers/rag.py` | retry 端点 `status_code=202`；`JSONResponse(202, doc)`；docstring 更新（仅 failed 可重试/409/轮询语义）；import `JSONResponse` |
| `frontend/src/views/rag/KbDetailView.vue` | `onRetry` 加 try/catch：成功 toast「已重新入队（202，当前状态 x）」+ 刷新列表（2s 后再刷一次跟上流水线）；失败 toast `重试失败：<detail>`（409 提示"only failed docs can be retried (status=…)"） |
| `deploy/docker-compose.yml` | 镜像 tag `api:s32→s36`、`webconsole:s29→s36` |

后端 service 层 `retry_doc`（`joker_shared/rag/service.py:1090`）**无需改动**：
已实现 404（doc 不存在）/ 409（非 failed）/ 状态回 `uploaded` + `get_task_queue().enqueue()`（复用现有 worker，从 parsing 重跑，断点续做逻辑天然支持）。
worker 对 failed 态的处理（L817-819：直接跳过，等 retry 重置）也符合设计。

BFF 无需改动：`/api/` 前缀统一转发 platformapi（`services/bff/app/routes.py:39`）。

## 3. 部署

```
cd deploy && docker compose build api webconsole && docker compose up -d api webconsole
```
- `agent-joker-api:s36` / `agent-joker-webconsole:s36`，两容器 **healthy**（bff s32 未动）。
- 容器实码核验：`joker-api` 内 `grep -c "status_code=202" /app/api/app/routers/rag.py` = 2（retry 路由）；
  `joker-webconsole` 内新 bundle 含「重试失败」「已重新入队（202」文案（`KbDetailView-*.js`）。
- 说明：镜像里 `assets/` 有两个 `rag-*.js`（api 模块 + rag utils 模块，hash 不同），
  是 vite 正常产物（同 s29 镜像即如此），非新旧混杂——`npm run build` 会清 dist。

## 4. 自测（真实 HTTP 全链路，localhost:8080 → bff → api → pg，零 mock）

脚本 `05-temp/s36/probe_s36_retry.py`，结果 **ALL PASS**（14 条原始 HTTP 响应日志
`03-testing/dev_probe_s36_01..15`，含完整请求/响应体）：

| # | 步骤 | 结果 |
|---|---|---|
| 1 | 登录 acme/admin | 200 |
| 2 | 建坏 embedding 模型（provider=api，base_url=`http://127.0.0.1:9/v1` 不可达，dim=128） | 201 |
| 3 | 用该模型建库 s36-kb-retry-67856 | 201（embedding_dim=128 快照） |
| 4 | 上传 txt | 201（status=uploaded） |
| 5 | 流水线 → **failed** | error_message=`ConnectError: All connection attempts failed`（1s 内） |
| 6 | **POST /retry（failed）** | **202**，响应体 status=`uploaded`，error_message 清空 |
| 7 | 恢复端点：PUT 该模型 `provider=local`（本地确定性实现，dim 仍 128 与库快照一致） | 200 |
| 8 | worker 重跑 → **ready** | 1s 内（status=ready，chunk_count=5） |
| 9 | **POST /retry（ready 文档）** | **409** `only failed docs can be retried (status=ready)` |
| 10 | **POST /retry（splitting 处理中文档）** | **409** `only failed docs can be retried (status=splitting)` |
| 11 | POST /search（重试后的文档） | 200，top1=**0.770322** 命中 marker（向量真实写入 128 维表） |
| 12 | POST /retry（不存在 doc） | 404 |
| 13 | 清理：PUT 坏模型 disabled（200）+ DELETE 库（200） | 完成 |

前端按钮验证口径（任务允许 curl 触发 + 状态核验）：按钮/`retryDoc`/toast 代码在源码与
已部署 bundle 中（第 3 节容器实码核验）；API 层 202/409/404 全真实命中。
未跑 Playwright（本地无 chromium 依赖），真实 UI 点按钮截图建议由 S37 回归轮补（非阻塞）。

## 5. 已知问题 / 观察

- **OBS（既有行为，非 S36 引入）**：`delete_embedding` 的引用检查不过滤已软删库——
  软删库后模型 DELETE 仍 409（提示引用 `kb=['s36-kb-retry-67856']`）。清理时只能
  disable 代替 delete。已在 probe 注释与本报告记录，不属 S36 范围。
- **S35 报告更正**：TEST_REPORT_S35.md L116「后端无 /retry 接口」与事实不符
  （代码与运行容器均有该端点）；请测试/验收时按本报告第 1 节口径。
- retry 语义细节：返回 202 时 status 为 `uploaded`（即将进 parsing），非"pending"
  字样——文档状态机无 pending 态，"重置为 pending 并重新入队"实现为 `uploaded` + enqueue，
  与任务意图一致（重新走完整流水线）。

## 6. 交付物

- 代码：3 文件（上述），本地 commit（未 push，等验收轮统一 push）。
- 证据：`03-testing/dev_probe_s36_*.log` ×14（真实 HTTP 原始响应）。
- 部署：api/webconsole s36 镜像运行中（healthy），启动 `cd deploy && docker compose up -d --build`。
- 临时文件：`05-temp/s36/`（probe 脚本 + 清理 SQL + 构建日志）。
