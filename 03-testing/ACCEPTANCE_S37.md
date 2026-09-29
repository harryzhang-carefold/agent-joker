# ACCEPTANCE S37 — 上传文档报错轮终审验收（S35 + S36）

- **验收人**：褚岩（chuyan），任务卡 t_62ee7dd0
- **日期**：2026-09-29（CST）
- **范围**：S35（t_c74de813，云天明，1536 维真实链路验证 + embedding 配置修复）+ S36（t_c343be35，章北海，failed 文档 retry 202 + UI toast）
- **方法**：不采信 S35/S36 自报，独立核查（防造假 grep / 原始响应逐字核对 / 容器实码 / 独立复跑铁证 / 截图 vision 抽样）

> ## 整轮判定：**PASS** — 证据完整覆盖，无造假，无缺口。一次 push main。

---

## 一、S35 防造假核查（不采信自报）

| # | 核查项 | 独立执行结果 | 判定 |
|---|---|---|---|
| 1 | grep S35 全部 5 个 UI 脚本（s35_ui_test.js / _v2 / _v3 / cleanup / 登录流程）`fetch(` / `localStorage` / `sessionStorage` | UI 脚本**零代码命中**；`fetch(` 仅出现在 2 个独立端点探测脚本（probe_endpoint.js / get_vec.js，直连 34.64.61.208 的 node 探测，属报告声明的"独立复核"手段，非 UI 内 fetch，不构成绕登录/造响应） | ✅ |
| 2 | grep 全部脚本 `page.goto` 逐条判读 | 15 处 goto：`/login`（4 个脚本各 1 次，登录后入口）+ 登录后站内跳转（`/llm/embeddings`、`/rag/kbs`、`/rag/kbs/{id}`、`/rag/search`），**无 goto 受保护页绕登录** | ✅ |
| 3 | 登录方式 | 四轮脚本均 `fill('input[placeholder="如 acme"]')` + `fill(password)` + `click('button:has-text("登录")')` + `waitForURL(!/login/)`，`POST /api/auth/login` 200 原始响应留档（api_raw 00_login_ok 对应） | ✅ |
| 4 | 截图与报告逐条对应 | 报告引用截图全部存在（`03-testing/screenshots/s35/` 47 张 ≥ 报告引用数；00/01/02/03/04/05/06/22/23/24/26/27/29/30/43/44/50 逐一在目录中） | ✅ |
| 5 | 关键截图独立 vision 核验 | 06_connectivity_test_result.png：toast「探测结果: 可用 — ok: model=gte-Qwen2-1.5B-instruct dim=1536 in 1228ms」+ 行配置一致（与 api_raw/02_test_emb.json 逐字一致）；29_docs_ready.png：s35-kb-1536（dim 1536，rag_chunks_vec_0f46…40）下 txt+pdf 两行 ready（与报告一致，pdf 首轮=vision 分支如实呈现） | ✅ |

**S35 原始 API 响应逐字核对（独立读取磁盘文件）**：

| 证据 | 独立核对 |
|---|---|
| `api_raw/01_edit_emb.json` | PUT 200，body：model=`gte-Qwen2-1.5B-instruct`、dimensions=1536、base_url=`http://34.64.61.208:4000/v1` 不变、api_key IS NULL ✅ |
| `api_raw/02_test_emb.json` | 200，`{"ok": true, "latency_ms": 1228, "summary": "ok: model=gte-Qwen2-1.5B-instruct dim=1536 in 1228ms"}` ✅ |
| `api_raw_v2/01_create_kb.json` | 201，kb `s35-kb-1536`，embedding_dim=1536，vec_table=`rag_chunks_vec_0f467b5d6cb346b789fe346a4ba72940` ✅ |
| `api_raw_v2/02_upload_txt.json` / `03_upload_pdf.json` | 均 201 ✅ |
| `api_raw_v2/04_search_A.json` | 200，top1 score=**0.694243**（独立重算确认），marker A 内容命中 ✅ |
| `api_raw_v3/02_search_B_fixed.json` | 200，pdf chunk（s35_probe_v2.pdf）score=**0.619924** 且 content 含完整 marker B（独立重算确认）；top1=txt 0.688149 与报告"排序合理"表述一致 ✅ |
| `api_raw_cleanup/01_delete_kb.json` | DELETE 200，deleted=0f467b5d… ✅ |
| `probe_endpoint.log` | 端点侧独立复核：/v1/models 200 仅 gte-Qwen2-1.5B-instruct；emb 200 dim=1536；旧 model 404 原文 ✅（与 RISK-019 端点漂移定因一致） |
| `hnsw_check.txt` | 向量表 `rag_chunks_vec_0f46…40` 存在 `idx_…_embedding USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')` ✅ |
| `explain_s35.txt` | `Index Scan using idx_0f467b5d…_embedding`，1536 维真实向量，BUG-19 `<=2000` HNSW 分支在 1536 维真实模型下工作 ✅ |

**S35 测试脚本自身缺陷（如实记录，非造假）**：v1 步骤 03 断言空读（受控 input value 取不到）但 04/05 四重铁证兜底；v3 步骤 42 轮询正则漏 token——报告均如实披露且与磁盘证据自洽。

## 二、S36 证据核查（真实 HTTP 日志 14 项）

**14 份 `03-testing/dev_probe_s36_*.log` 逐份独立读取**（每项含完整请求/响应体，经 8080→bff→api→pg 真实链路，localhost:8080 入口，零 mock）：

| # | 日志 | 独立核对 |
|---|---|---|
| 1 | 01_login | POST /api/auth/login 200 ✅ |
| 2 | 02_create_bad_emb | 201，provider=api，base_url=`http://127.0.0.1:9/v1`（不可达），dim=128 ✅ |
| 3 | 03_create_kb | 201，embedding_dim=128 快照，vec_table 存在 ✅ |
| 4 | 04_upload | 201，status=uploaded ✅ |
| 5 | 05_wait_failed | 200，**status=failed**，error_message=`ConnectError: All connection attempts failed`（真实连接失败，非造） ✅ |
| 6 | 06_retry_failed | **POST /retry → 202**，status=uploaded，error_message 清空 ✅ |
| 7 | 07_fix_emb_to_local | PUT 200，provider=local（端点恢复） ✅ |
| 8 | 08_wait_after_fix | 200，**status=ready**，chunk_count=5（worker 重跑成功） ✅ |
| 9 | 11_retry_ready_409 | **409** `only failed docs can be retried (status=ready)` ✅ |
| 10 | 12_search_marker | 200，top1 score=**0.770322**，content 含 marker（向量真实写入 128 维表） ✅ |
| 11 | 13_retry_pending_409 | **409** `(status=splitting)` ✅（脚本 probe_s36_retry.py L163-174 独立确认为 race 场景真实抓取 doc2 处理中状态，非构造） |
| 12 | 13b_retry_missing_404 | **404** `doc not found` ✅ |
| 13 | 14_disable_emb | PUT 200 disabled（清理） ✅ |
| 14 | 15_delete_kb | DELETE 200 ✅ |

## 三、代码 diff 独立审查（S36，commit 4d179da）

| 文件 | 改动 | 独立审查 |
|---|---|---|
| `services/api/app/routers/rag.py` | retry 端点 `status_code=202` + `JSONResponse(202, doc)` + docstring | 最小改动；service 层 404/409/状态重置+enqueue 逻辑未动（joker_shared/rag/service.py 既有实现）✅ |
| `frontend/src/views/rag/KbDetailView.vue` | `onRetry` 加 try/catch：成功 toast「已重新入队（202，当前状态 x）」+ 双次刷新；失败 toast `重试失败：<detail>` | 与任务要求一致 ✅ |
| `deploy/docker-compose.yml` | api/webconsole 镜像 tag → s36 | ✅ |

**容器实码独立核验（不采信 DEV_REPORT）**：
- `docker exec joker-api grep "status_code=202" /app/api/app/routers/rag.py` → 命中 L235/L246（retry 路由）✅
- `docker exec joker-webconsole`：`/usr/share/nginx/html/assets/KbDetailView-CRrQ3Qrg.js` 含「重试失败」×1、「已重新入队（202」×1（新 bundle 已部署）✅
- 容器状态：joker-api / joker-webconsole = `agent-joker-*:s36`，均 healthy ✅

**S36 DEV_REPORT 更正项核实**：S35 报告 L116 称「后端无 /retry 接口」——S36 指出该端点自初始 commit 即存在，实际差距为 200→202 + 前端无错误处理。**本终审判定：更正成立**（S35 观察的是当时部署的 s29 webconsole + 旧 api 行为表象，端点代码确在）；S35 整轮 PASS 判定不受影响（其判据均在，观察项表述瑕疵不构成造假，已在本报告如实记录）。

## 四、独立复跑铁证（本终审亲自执行，非重放）

`05-temp/s37_rerun.py`（16:57 CST，真实 HTTP 全链路 8080→bff→api→pg，唯一 marker `s37x_d5109a1b54`）：

| 步骤 | 结果 |
|---|---|
| 造 failed 文档（127.0.0.1:9 不可达端点） | failed，error=`ConnectError: All connection attempts failed` ✅ |
| **POST /retry（failed）** | **202**，status=uploaded，error 清空 ✅ |
| 端点恢复（provider=local）+ 轮询 | **ready**，chunk_count=5（1s 内） ✅ |
| POST /retry（ready） | **409** `(status=ready)` ✅ |
| POST /retry（不存在 doc） | **404** ✅ |
| POST /search | 200，top1=**0.890359**，marker 命中 ✅ |
| 清理（disable + delete kb） | 200/200 ✅ |

**结论：S36 修复行为在终审时点可复现，非一次性证据。** 留档 `05-temp/s37_rerun.log`。

## 五、证据交叉与覆盖完整性

| 任务要求 | S35 覆盖 | S36 覆盖 | 判定 |
|---|---|---|---|
| 1536 维建库 | 201 + dim 快照 + vec_table | — | ✅ |
| 1536 维上传 | txt+pdf 各 1 篇 201 → ready（4.5s） | — | ✅ |
| 1536 维检索 | marker A 0.694243 / B 0.619924 | — | ✅ |
| HNSW 铁证 | pg_indexes hnsw 索引 + EXPLAIN Index Scan（1536 真实向量） | — | ✅ |
| 连通性必须 200 | 200 ok=true dim=1536（真实端点 34.64.61.208） | — | ✅ |
| retry 202/409 | — | 202（failed）/ 409（ready+splitting）/ 404（missing）+ 独立复跑复现 | ✅ |
| UI 错误处理 | — | 前端 toast 成功/失败双分支 + 已部署 bundle 实码核验 | ✅ |

**缺口检查**：S36 前端未跑 Playwright 点按钮截图（DEV_REPORT 自述本地无 chromium，建议 S37 补）——**本终审裁定**：S36 任务卡判定口径为「API 层 202/409/404 真实命中 + 源码/已部署 bundle 代码核验」（任务允许 curl 触发 + 状态核验），UI toast 代码已在运行 bundle 中（实码 grep 命中），API 层全真实；该口径下**无缺项**。UI 点击截图列为 P3 观察项（OBS，随 KB 列表轮询观察项一并跟踪），不阻塞放行。

**P0/P1 检查**：本轮无新增 P0/P1。RISK-019（端点漂移）维持 OPEN（端点侧环境态，S35 已按更新 DB 行配置路径缓解 1536 维链路；3584 维真实端点链路待端点恢复补测，S32/S33 已用 local provider 闭环）。

## 六、交付与 push

- **PASS 放行**，一次 push main：S36 代码变更（4d179da，zhangbeihai 已 commit）+ S35 证据（TEST_REPORT_S35 + 47 张截图）+ 本验收报告 + BUGS/RISKS/PIPELINE/STATUS 回写。**不 push 05-temp**（.gitignore 排除）。
- 远端核验：push 前 `git ls-remote origin main` = `bf8b29e49feaa9ea6c39aa4f3122ee16fddafb37`（= 本地 HEAD 上一态 S34 收口 commit，一致）；push 后以 ls-remote 新值为准（见 STATUS.md 回写）。

## 七、遗留（不阻塞）

1. **RISK-019**（端点侧环境态）：34.64.61.208 仍不服务 3584 维 gte-qwen2；1536 维真实链路本轮已闭环；端点恢复 3584 模型后补测。
2. **OBS（P3，随 S35 六.2 既有项）**：KB 列表页无自动轮询，状态推进需手动刷新。
3. **OBS（P3，S36 新增）**：failed 文档 retry 的 UI 点击截图未跑（API 层 + bundle 实码已闭环）；后续回归轮可用 Playwright 补 UI 证据。
4. **OBS（既有，S36 记录）**：`delete_embedding` 引用检查不过滤已软删库（软删库后 DELETE 模型 409）——既有行为，非本轮引入。
5. RISK-016/018（用户轮换 vLLM key）维持 OPEN（用户操作项）。
