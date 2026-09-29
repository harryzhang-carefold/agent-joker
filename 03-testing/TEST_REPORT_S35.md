# TEST_REPORT S35 — embedding 端点模型名变更修复 + 1536 维真实链路验证（真实 UI）

- **测试人**：云天明（yuntianming），任务卡 t_c74de813
- **日期**：2026-09-29（CST）
- **上游**：主 agent 已复现定因（2026-09-29）：用户报"RAG 上传文档报错"，本地复现 = 建库(3584维)→上传 hello.txt→201 但文档 failed，错误 `HTTPException: 502: embedding endpoint error: HTTP 404`
- **标准**：`03-testing/QA_STANDARD.md`（真实 UI + 原始 API 响应双层证据）
- **环境**：本地 compose（webconsole:8080 / bff:8000 / api / pg / redis 全 healthy），租户 acme / admin
- **工具**：Playwright chromium headless；**真实表单登录**（fill 租户/用户名/密码 → click 登录 → waitForURL 离开 /login）
- **截图目录**：`03-testing/screenshots/s35/`（21 张，关键截图经 vision 独立核验）
- **原始 API 响应**：`05-temp/s35/api_raw*/`（每步 HTTP 状态 + 完整 body 留档）+ `05-temp/s35/api_raw*_all.json`（全程 /api/ 响应流水）

> ## 整轮判定：PASS — 配置修复 + 1536 维真实链路（建库→上传→流水线→检索→HNSW）全通过，无产品代码缺陷。
> 判据（全部真实 UI 操作 + 原始响应）：
> ① UI 编辑 `s26-gte-qwen2-real` → model=`gte-Qwen2-1.5B-instruct` + dimensions=1536（PUT 200，DB 复核一致，base_url 未变、无 key）；
> ② 页面「连通性」→ **HTTP 200 + ok=true + summary `model=gte-Qwen2-1.5B-instruct dim=1536 in 1228ms`**（任务要求"必须 200"，满足）；
> ③ 用该 1536 维模型建库 `s35-kb-1536` → **201**（embedding_dim=1536 快照正确）；
> ④ 上传 txt + pdf 各 1（自造）→ 2×**201** → 两文档 **ready**（耗时 4.5s）；
> ⑤ 检索双 marker 命中：txt top1 **0.694243**、pdf 0.619924；
> ⑥ psql 铁证：该 KB 向量表有 **HNSW 索引**（1536<2000，BUG-19 修复后 HNSW 分支正确），EXPLAIN = **Index Scan** 走该索引；
> ⑦ 清理删库 200（embedding 配置修复按任务要求**保留**）。
> 全程遵守防造假硬规则：无 in-page fetch / 无 localStorage 注入 / 无 goto 受保护页绕登录。

---

## 一、背景与根因（主 agent 定因 + 本测试独立复核）

用户报"RAG 上传文档报错"。定因链路：

1. embedding 端点 `http://34.64.61.208:4000`（vLLM）**重启后换了模型**：`/v1/models` 现仅 `gte-Qwen2-1.5B-instruct`；
2. DB 行 `s26-gte-qwen2-real` 仍配 `model=gte-qwen2` + `dimensions=3584` → 向量化调用 404 → 文档 failed，错误 `embedding endpoint error: HTTP 404`；
3. 修复方式（本任务）：**改 DB 行配置对齐端点现状**（平台 UI 支持编辑，无需改代码）。

本测试独立复核端点状态（`05-temp/s35/probe_endpoint.js`，原始响应 `probe_endpoint.log`）：

| 检查 | 结果 |
|---|---|
| `GET /v1/models` | **200**，仅 `gte-Qwen2-1.5B-instruct`（max_model_len=16384） |
| `POST /v1/embeddings` model=`gte-Qwen2-1.5B-instruct` | **200**，**dim=1536**，无 key 可用 |
| `POST /v1/embeddings` model=`gte-qwen2`（DB 行旧配置） | **404** `{"error":{"message":"The model `gte-qwen2` does not exist.","code":404}}` |

**结论**：端点侧模型漂移属实（与主 agent 复现一致）；属**端点侧环境态**，非平台代码缺陷——上传 201 入队、流水线 failed、错误可读，均按设计工作（failed 可重试入口缺失见 S36 改进项）。

## 二、步骤 1：UI 修复 embedding 配置（LLM 节点 → Embedding 模型）

脚本 `05-temp/s35/s35_ui_test.js`，日志 `05-temp/s35/s35_ui_run.log`。

| # | 操作（真实 UI） | 原始响应/结果 | 判定 | 截图 |
|---|---|---|---|---|
| 00 | 真实表单登录 acme/admin | `POST /api/auth/login` **200** → `/users` | PASS | `00_login_ok.png` |
| 01 | 进入 `/llm/embeddings`，定位 `s26-gte-qwen2-real` 行（修复前快照） | 行文本：`s26-gte-qwen2-real · http://34.64.61.208:4000/v1 · gte-qwen2 · 3584 · api · 未设 · active` | PASS | `01_emb_list_before_edit.png` |
| 02-03 | 点行「编辑」→ 弹窗填 模型=`gte-Qwen2-1.5B-instruct`、维度=1536；Base URL 不动；API Key 留空（不变） | 弹窗截图独立核验：Base URL=`http://34.64.61.208:4000/v1`、模型=`gte-Qwen2-1.5B-instruct`、维度=1536、Key=空 | PASS | `02_edit_dialog_open.png` / `03_edit_dialog_filled.png` |
| 04 | 点「保存」 | `PUT /api/llm/embeddings/b13b0706-…` **200**，toast「已保存」（原始响应 `api_raw/01_edit_emb.json`） | PASS | `04_after_save.png` |
| 05 | 列表行刷新核验 | 行文本：`s26-gte-qwen2-real · http://34.64.61.208:4000/v1 · **gte-Qwen2-1.5B-instruct** · **1536** · api · 未设 · active`；**psql 独立复核**：`model=gte-Qwen2-1.5B-instruct, dimensions=1536, base_url 不变, api_key_enc IS NULL` | PASS | `05_emb_row_after_edit.png` |
| 06 | 页面点「连通性」测试 | `POST /api/llm/embeddings/b13b0706-…/test` **HTTP 200**，body `{"ok": true, "latency_ms": 1228, "summary": "ok: model=gte-Qwen2-1.5B-instruct dim=1536 in 1228ms"}`，toast「探测结果: 可用」（原始响应 `api_raw/02_test_emb.json`） | **PASS（任务硬判据：必须 200）** | `06_connectivity_test_result.png` |

**测试脚本缺陷（非产品缺陷）**：v1 脚本步骤 03 的"弹窗已填值"断言读到空（`allTextContents` 对受控 input 未取到 value），但步骤 04/05 的 PUT 200 + 行刷新 + psql 复核 + 连通性 200 四重铁证已证明填写与保存真实生效。

## 三、步骤 2：1536 维模型新建 KB + 2 文档上传 + 流水线 + 检索

脚本 `05-temp/s35/s35_ui_test_v2.js`（日志 `s35_ui_v2_run.log`）+ `s35_ui_test_v3.js`（pdf 修正，`s35_ui_v3_run.log`）。

| # | 操作（真实 UI） | 原始响应/结果 | 判定 | 截图 |
|---|---|---|---|---|
| 21 | `/rag/kbs` 点「建库」→ 名称 `s35-kb-1536` → Embedding 模型下拉过滤选中 `s26-gte-qwen2-real (1536d)` | 下拉选项文本 `s26-gte-qwen2-real (1536d)`（1536d 证明读到的是修复后的维度快照） | PASS | `22_create_kb_model_selected.png` |
| 22 | 点「创建」 | `POST /api/rag/kbs` **201**：`{"id":"0f467b5d-6cb3-46b7-89fe-346a4ba72940","name":"s35-kb-1536","embedding_model_id":"b13b0706-…","embedding_dim":1536,"status":"active","vec_table":"rag_chunks_vec_0f467b5d6cb346b789fe346a4ba72940","vec_table_exists":true}`，toast「建库成功（已建独立向量表）」（`api_raw_v2/01_create_kb.json`） | PASS | `23_create_kb_result.png` |
| 23 | KB 列表行核验 | 行：`s35-kb-1536 · 1536 · rag_chunks_vec_0f467b5d… · 5 / 0.3 · active` | PASS | `24_kb_list_row_1536.png` |
| 24 | 进入 KB 详情，上传文档 1（自造 txt，唯一 marker A `s35kz_vortex_lattice_A_s35v2385280`） | `POST /api/rag/kbs/{id}/docs` **201**，toast「已上传…入队解析流水线」 | PASS | `26_doc1_txt_uploaded.png` |
| 25 | 上传文档 2（自造 pdf，唯一 marker B） | `POST /api/rag/kbs/{id}/docs` **201**（`api_raw_v2/03_upload_pdf.json`） | PASS | `27_doc2_pdf_uploaded.png` |
| 26 | 轮询刷新（每次 reload 取最新）文档流水线 | 2 文档均 **ready**（txt parse_method=text / pdf 首轮=vision，见下），**耗时 4.5s**（07:20:03 上传 → 07:20:07 ready） | PASS | `29_docs_ready.png` |
| 27 | 检索测试（/rag/search，阈值 0，选 s35-kb-1536，查询 `vortex lattice <marker A>`） | `POST /api/rag/search` **200**，2 条，**marker A 命中**，**top1 score=0.694243**（`api_raw_v2/04_search_A.json`） | PASS | `30_search_A.png` |
| 28 | 检索测试 pdf（查询 `s35kz vortex lattice <marker B>`） | 见 v3 修正：pdf chunk 命中，score **0.619924**（rank 2） | PASS（经 v3 修正闭环） | `44_search_B_hit.png` |

### 3.1 pdf 首轮未命中 marker 的定因（测试产物，非产品缺陷）

- 首轮自造 pdf 内容流 dict 漏声明 `/Filter /FlateDecode` → pymupdf `get_text()` 读不到文本层 → 解析器走**扫描页视觉分支**（`parse_method=vision`，chunk 内容=「（图片为空白，无内容可转录）」，score 0.26）。**平台行为正确**：无文本层 pdf 按设计走视觉分支，且文档状态仍 ready（非 failed）。
- 修正 pdf（补 `/Filter /FlateDecode`）后用**平台同款解析器**（API 容器内 pymupdf）预验文本层可读 → 重新上传（`s35_probe_v2.pdf`）→ **ready + parse_method=text**（`43_pdf_ready_text.png`）→ 检索命中 marker B，原始响应 `api_raw_v3/02_search_B_fixed.json`：pdf chunk 内容含完整 marker B 文本、**score=0.619924**（rank 2，top1 为 txt 0.688149——两文档语义相近，排序合理）。
- v3 脚本步骤 42 的"FAIL"为**脚本轮询正则缺陷**（正则漏了文件名与 parse_method 之间的 `ready` 状态 token，66s 空转后 break）；同一次运行的表格文本本身即为铁证：`s35_probe_v2.pdf · pdf · ready · text · 1 chunk`。

## 四、步骤 3：1536 维 HNSW 分支核验（BUG-19 修复后，psql 独立铁证）

`docker exec joker-pg psql`，输出 `05-temp/s35/hnsw_check.txt`：

```
select indexname, indexdef from pg_indexes
 where tablename = 'rag_chunks_vec_0f467b5d6cb346b789fe346a4ba72940';

 rag_chunks_vec_0f467b5d6cb346b789fe346a4ba72940_pkey | CREATE UNIQUE INDEX … USING btree (chunk_id)
 idx_0f467b5d6cb346b789fe346a4ba72940_embedding       | CREATE INDEX … USING hnsw (embedding vector_cosine_ops)
                                                        WITH (m='16', ef_construction='64')
```

**判定：PASS** — 1536 维（<2000）建库走 HNSW 分支，向量表存在 hnsw 索引（S33 曾对 256 维库验证过同一分支；本轮是 1536 维真实端点模型的独立复证）。

补充铁证（`05-temp/s35/explain_s35.txt`）：用真实端点现取的一条 1536 维向量跑检索 SQL：

```
EXPLAIN (COSTS OFF) SELECT * FROM rag_chunks_vec_0f467b5d…
 ORDER BY embedding <=> '[…1536 维真实向量…]'::vector LIMIT 5;

 Limit
   ->  Index Scan using idx_0f467b5d…_embedding on rag_chunks_vec_0f467b5d…
```

**引擎确走 HNSW Index Scan**（非顺序扫描），BUG-19 的 `<=2000` 分支在 1536 维真实模型下工作正常。

## 五、清理

| # | 操作 | 结果 | 截图 |
|---|---|---|---|
| 50 | 真实 UI「删库」s35-kb-1536（psql 核验完成后） | `DELETE /api/rag/kbs/0f467b5d-…` **200**（`api_raw_cleanup/01_delete_kb.json`） | `50_after_delete_kb.png` |

**embedding 配置修复保留**（`s26-gte-qwen2-real` = `gte-Qwen2-1.5B-instruct` / 1536 / 原 base_url / 无 key）——这是本任务要求的修复项，非测试残留。

## 六、观察项（非缺陷，已转 S36 开发任务）

1. **failed 文档无重试入口**（S36，zhangbeihai，t_c36 已排队）：若 embedding 端点再次漂移，文档 failed 后用户只能删了重传；前端文档行虽渲染「重试」按钮但禁用条件仅 `status==='failed'` 且**后端无 `/retry` 接口**（KbDetailView `onRetry` 无对应端点）——产品改进项，非本轮链路缺陷。
2. **KB 列表页无自动轮询**（S33 已记 P3 观察项，本轮再次命中：需手动刷新/reload 看状态推进）——UX 优化，非缺陷。
3. **RISK-019 状态更新**：外部端点 `34.64.61.208:4000` 模型漂移已按"更新 DB 行配置"路径缓解（本轮完成）；端点仍**不服务 3584 维 gte-qwen2**，3584 维真实端点链路仍不可用（3584 链路 S32/S33 已用 local provider 闭环验证）——风险维持 OPEN（端点侧环境态），非平台代码缺陷、非阻塞。

## 七、防造假自查

| 规则 | 执行情况 |
|---|---|
| 登录必须真实表单（fill 租户/用户名/密码 → click → waitForURL） | v1/v2/v3/cleanup 四轮脚本均 `fill('input[placeholder="如 acme"]','acme')` + `fill('input[placeholder="admin"]','admin')` + `fill('input[type="password"]','123456')` + `click('button:has-text("登录")')` + `waitForURL(!/login/)`，`POST /api/auth/login` 200 原始响应留档 | ✅ 遵守 |
| 禁止 in-page fetch / localStorage 注入 / 直接 goto 受保护页 | 无任何 in-page fetch / token 注入；所有导航从 /login 表单进入；无 goto 受保护页绕登录 | ✅ 遵守 |
| 证据 = 真实 UI 操作 + 原始 API 响应 | 每步 UI 操作（click/fill/setInputFiles）+ 响应状态与完整 body 留档 `05-temp/s35/api_raw*/`；关键截图（编辑弹窗字段、文档表 ready、建库弹窗选中）经 vision 独立核验；psql 独立复核 DB 状态（不采信 UI 自报） | ✅ 遵守 |
| 不采信上游自报 | 端点 404/200/dim=1536 由本测试独立 probe 复核（`probe_endpoint.log`）；HNSW 索引/EXPLAIN 独立 psql 复跑 | ✅ 遵守 |

## 八、结论

- 任务 5 项要求**全部满足**：① UI 修复配置 + 连通性 200；② 1536 维建库 + 2 文档（txt+pdf）ready（4.5s）+ 检索命中（top1 0.694243 / 0.619924）；③ HNSW 索引 psql 铁证（+Index Scan EXPLAIN）；④ 本报告 + 截图；⑤ 无 UI 卡点（编辑/连通性/建库/上传/检索/删库全部可达）。
- **整轮判定：PASS**，无阻塞性问题。"上传文档失败"根因（端点模型漂移 vs DB 行配置）已按任务指定方式修复并全链路闭环验证。
- 交下游：S36（t_c343be35，zhangbeihai，failed 文档重试改进）解除依赖；RISK-019 维持 OPEN（端点侧环境态，非阻塞）。
