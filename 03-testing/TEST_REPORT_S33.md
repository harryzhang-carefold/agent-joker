# TEST_REPORT S33 — BUG-19（3584 维建库 500）修复后复测 + 回归（真实 UI）

- **测试人**：云天明（yuntianming），任务卡 t_28d8f1f7
- **日期**：2026-09-28（CST）
- **上游**：S32（zhangbeihai，t_892ebfc3）修复 BUG-19 + 自测（本地 commit fe1cb5a，未 push）
- **标准**：`03-testing/QA_STANDARD.md`（浏览器 + 接口双层）
- **事实源**：`BUGS.md`（BUG-19 段）、`DEV_REPORT_S32.md`、`00-management/RISKS.md`（RISK-019）
- **环境**：本地 compose（webconsole:8080 / bff:8000 / api / pg / redis 全 healthy），admin/123456/acme
- **工具**：Playwright chromium headless（NODE_PATH 全局）；**真实表单登录**（fill 租户/用户名/密码 → click 登录 → waitForURL 离开 /login）
- **部署核验**：api/bff 镜像 s32；容器内代码已验证含 S32 三处修复（`init_schema.sql:892 IF p_dim <= 2000`、`service.py:379 if new_dim <= 2000`、`service.py:232` 可读 500 提示）；PG 函数 `create_rag_chunks_vec` 体内含 `IF p_dim <= 2000 THEN ... hnsw ... END IF`（entrypoint 幂等重建生效）

> ## 整轮判定：PASS — BUG-19 复测通过 + 256 维 HNSW 分支回归无缺陷，交 S34 终审。
> 判据：3584 维建库 **201**（修复前 500，核心）+ 3584 无 HNSW / 256 有 HNSW（pg_indexes 独立铁证）+ 3584 顺序扫描检索命中（EXPLAIN = Seq Scan）+ 换模型 reindex 完成（256/active）+ 256 维 HNSW 分支全流水线回归 + KB 列表/详情正常。
> 全程遵守防造假规则（无 in-page fetch 登录 / 无 localStorage 注入 / 无 goto 受保护页绕登录）。
> **不采信 S32 自报**：索引/EXPLAIN 均独立复跑，截图经 vision 独立核验。

---

## 一、BUG-19 复测（核心）

> BUG-19（P1）：选 3584 维 embedding（gte-qwen2）建知识库恒 500。根因 = `create_rag_chunks_vec` 无条件建 HNSW，pgvector HNSW 硬上限 2000 维。S32 修复 = `>2000` 维不建 HNSW（降级顺序扫描），`<=2000` 维行为不变。

### 1.1 主 UI 复测（脚本 `s33_ui_test.js`，`03-testing/dev_probe_s33_ui.log`，**19/20 PASS**）

| # | 复测项 | 操作 | 实际结果 | 判定 | 截图 |
|---|---|---|---|---|---|
| 00 | 真实表单登录 | 填租户 acme / 用户名 admin / 密码 123456 → click 登录 | **200**，跳转 `/users` | PASS | `00_login_ok.png` |
| 01 | **建库 3584 维（真实模型行 `s26-gte-qwen2-real`）→ 201**（修复前=500，**核心判据**） | 建库弹窗填名称 → 选 `s26-gte-qwen2-real (3584d)` → 创建 | **POST /api/rag/kbs 201**，toast「建库成功（已建独立向量表）」，KB id 6b5509cb… | **PASS** | `01_create_3584real.png` |
| 02 | KB 列表 3584 行可见 + 向量维度=3584 | 列表定位新行 | 行显示 `s33_kb_3584real… 3584 rag_chunks_vec_6b5509… 5/0.3 active` | PASS | `02_kb_list_after_3584real.png` |
| 03 | 建库 3584 维（local provider `s32-local-3584`）→ 201 | 建库选 local 3584 模型 | **201**，id f61a9f22… | PASS | `03_create_3584local.png` |
| 04 | 进入 3584local KB 文档详情页 | 点「文档」 | URL `/rag/kbs/f61a9f22…`，详情页渲染 | PASS | `04_kb_detail_3584local_empty.png` |
| 05 | 上传文档 1（含唯一 marker A） | `setInputFiles` 唯一 .txt | **POST /docs 201**，toast「已上传…入队解析流水线」 | PASS | `05_doc_uploaded_1.png` |
| 06 | 上传文档 2（含唯一 marker B） | 同上 | **201** | PASS | `05_doc_uploaded_2.png` |
| 07 | 3584local 2 文档流水线 → ready（**无 HNSW 顺序扫描路径**） | 轮询文档状态 | 2 行均 `ready`（chunk_count=2） | PASS | `07_3584local_docs_ready.png` |
| 08 | **检索测试 3584local 命中（顺序扫描）** | /rag/search 选库 → 查询含 marker A → 检索 | **POST /search 200**，结果 4 条，**marker A 命中**，top1 score 0.535 | **PASS** | `08_search_3584_hit.png`（vision 独立核验：结果 4 条、库 3584d、marker 清晰） |
| 09 | 换模型 reindex 触发（3584→256） | 列表「换模型」→ 选 `local-fallback-embedding` → 开始重算 | **POST /reindex 200**，toast「已触发换模型重算（异步，状态 reindexing）」 | PASS | `09_reindex_triggered.png` |
| 10 | 换模型完成：status=active 且 dim=256 | 轮询（**初轮脚本缺陷**，见 §二） | 初轮 90s 内读到旧 `reindexing` 行 → **FAIL（测试伪报）** | FAIL→见§二 | `10_reindex_wait_*.png` |
| 13 | 回归 建库 256 维（HNSW 分支）→ 201 | 建库选 `local-fallback-embedding (256d)` | **201** | PASS | `13_create_256.png` |
| 13b | 回归 上传 256 文档 | `setInputFiles` | **201** | PASS | `14_256_doc_uploaded.png` |
| 14 | 回归 256 文档流水线 → ready（HNSW） | 轮询 | `ready` | PASS | `14_256_doc_uploaded.png` |
| 15 | 回归 检索 256 命中（HNSW） | /rag/search 选 256 库 | **200**，2 条命中，top1 0.625 | PASS | `15_search_256_hit.png` |
| 16 | KB 列表正常（3584+256 行可见） | 列表 | 36 行，含 3584 与 256 | PASS | `16_kb_list_all.png` |
| 17 | KB 详情正常（256） | 进 256 详情 | 显示 `dim 256 · active` + 文档状态机 | PASS | `17_kb_detail_256.png` |
| 18 | 删库（3584real / 3584local / 256） | 列表「删库」→ 确认 | 3× **DELETE 200**，toast「已删库」，向量表 DROP | PASS | `19_after_delete.png` |

### 1.2 索引 + 顺序扫描独立铁证（不采信 S32，独立复跑；脚本 `s33_index_probe.py` + `s33_index_check.sql`，`03-testing/dev_probe_s33_index.log` + psql 在容器内执行）

| # | 检查 | 实际结果 | 判定 |
|---|---|---|---|
| A | 3584 维库（local 3584 模型）`pg_indexes` | 仅 `…_pkey`（btree），**无 hnsw** | **PASS** |
| B | 256 维库 `pg_indexes` | `…_pkey`（btree）+ `idx_…_embedding`（**hnsw**） | **PASS** |
| C | 向 3584 无索引表插 3 条真实 3584 维向量 + 跑 `retrieval.py` 同款检索 SQL `EXPLAIN` | `Limit → Sort (Sort Key: embedding <=> q) → **Seq Scan**`（**非 Index Scan**） | **PASS** |
| D | 3584 无索引 top1 正确性 | 排序正确，最近向量命中 top1（sim≈1） | **PASS** |

**判定**：`>2000` 维不建 HNSW（3584 无索引）、`<=2000` 维建 HNSW（256 有索引）双分支均正确；无索引表引擎**确走顺序扫描**（EXPLAIN = Seq Scan），top1 正确 —— BUG-19 根因路径已按 S32 决策修复。

### 1.3 外部 3584 真实端点状态（RISK-019 复核，`dev_probe_s33_endpoint.log`）

| 检查 | 实际结果 |
|---|---|
| `GET http://34.64.61.208:4000/v1/models` | 200，仅服务 `gte-Qwen2-1.5B-instruct` |
| `POST /v1/embeddings model=gte-qwen2`（DB 行配置） | **404**「model `gte-qwen2` does not exist」 |
| `POST /v1/embeddings model=gte-Qwen2-1.5B-instruct` | 200，**embedding dims = 1536** |

**结论**：外部 3584 端点（DB 行 `s26-gte-qwen2-real` 指向 `34.64.61.208:4000`）**模型漂移仍未恢复**（现服务 1536 维 gte-Qwen2-1.5B-instruct，DB 行仍指 3584 维 gte-qwen2）—— **端点侧环境态，非平台代码缺陷**（与 S32 判断一致）。3584 维文档全链路（上传→向量化→检索）按 S32 既定方案用 **local 3584 provider** 闭环验证（§1.1 #03–#08 全 PASS），3584 真实端点文档链路待端点方恢复 3584 模型后再补测（RISK-019 维持 open，非阻塞）。

---

## 二、换模型 reindex 初轮 FAIL 的定因（测试伪报，非产品缺陷）

初轮 `s33_ui_test.js` 在 #10 报 FAIL：3584local 库 reindex 后 90s 内始终读到 `reindexing` 行。**经定因为测试脚本轮询缺陷，非产品缺陷**：

1. **API 容器日志铁证**：`07:35:42,162 INFO joker.rag: reindex done kb=f61a9f22…: shadow … → … (dim=256)` —— reindex **实际已完成**，距触发（07:35:41）仅 ~1s。
2. **DB 铁证**：该库最终 `embedding_dim=256`、`status=active`、`embedding_model_id` 已切 256 模型。
3. **缺陷根因**：初轮脚本在 `page.reload()` 之前反复读取**已加载表格的 `textContent()`**，而 KB 列表页**不会自动刷新**（仅在「刷新」按钮 / 行操作 / 导航时 reload），故读到 07:35 加载时的陈旧 `reindexing` 快照，90s 空转。

**复测铁证（`s33_retest_reindex.js`，`dev_probe_s33_reindex_retest.log`，**8/8 PASS**）**：改用**每次轮询 `page.reload()`** 取最新状态，3584local 建库→上传 2 文档→ready→换模型(→256)→**active+256 完成耗时 4.8s**，全程无卡住。补拍截图 `s33_reindex_row_done.png`（vision 独立核验：`s33s_kb_…` 行 = **256 / active**）。

**结论**：换模型 reindex（>2000→256，影子表 `new_dim<=2000` 建 HNSW 分支）功能正确、快速完成。初轮 FAIL 系测试脚本未刷新读取陈旧 UI 状态所致，**已修正复测通过**，不阻塞。
**非阻塞观察（记入 BUGS/观察，非缺陷）**：KB 列表页 reindex 进行中**无自动轮询/刷新**，用户须手动「刷新」才能看到 `reindexing → active` 状态推进。属 UX 体验优化项（P3），非 BUG-19 范围、非本轮回归引入（列表本无自动刷新逻辑）。

---

## 三、回归（256 维 HNSW 分支 + KB 列表/详情）

| 回归项 | 操作 | 实际结果 | 判定 |
|---|---|---|---|
| 256 维建库（HNSW 分支，`<=2000` 行为不变） | 建库选 256 模型 | 201 + `idx_…_embedding`（hnsw）存在（§1.2 B） | PASS |
| 256 文档上传→解析→ready（HNSW 检索路径） | 上传 .txt → 流水线 | 201 → ready | PASS |
| 256 检索命中（HNSW 索引） | /rag/search | 200，2 条，marker 命中 | PASS |
| KB 列表正常 | /rag/kbs | 36 行，维度/向量表/文档数/状态列渲染正常 | PASS |
| KB 详情正常 | /rag/kbs/:id | `dim 256 · active` + 文档状态机 + 上传入口 | PASS |

**判定**：S32 改动波及面（`init_schema.sql` create_rag_chunks_vec、`service.py` create_kb/reindex_kb）回归无新缺陷——`<=2000` 维 HNSW 路径、KB CRUD、文档流水线、检索均正常。

---

## 四、防造假自查（QA_STANDARD 逐条）

| 自查项 | 实际 | 结论 |
|---|---|---|
| 登录必须真实表单（fill 租户/用户名/密码 → click → waitForURL） | 全部脚本（s33_ui_test / s33_retest_reindex / s33_shot_reindex）`fill('input[placeholder="如 acme"]','acme')` + `fill('input[placeholder="admin"]','admin')` + `fill('input[type="password"]','123456')` + `click('button:has-text("登录")')` + `waitForURL(!/login/)` | ✅ 遵守 |
| 禁止 in-page fetch / localStorage 注入 / 直接 goto 受保护页 | 无任何 in-page fetch 登录 / token 注入；导航均从 /login 表单进入；无 goto 受保护页绕登录 | ✅ 遵守 |
| 不采信上游自报，独立复跑 | 索引/EXPLAIN 独立复跑（非用 S32 的 log）；截图经 vision 独立核验 | ✅ 遵守 |
| 失败如实记录，不改预期修通过 | 初轮 #10 FAIL 如实记录 + 定因（测试伪报）+ 修正复测，未改判据 | ✅ 遵守 |
| 截图落 `03-testing/screenshots/s33/` | **38 张**（登录/建库/上传/ready/检索命中/reindex/列表/详情/删库） | ✅ 落盘 |

---

## 五、已知 / 非阻塞事项

1. **RISK-019（维持 open，非阻塞）**：外部 3584 端点 `34.64.61.208:4000` 模型漂移（1536 维 gte-Qwen2-1.5B-instruct vs DB 行 3584 维 gte-qwen2）——端点侧环境态，非平台代码缺陷；3584 文档链路以 local provider 闭环证据为准，真实端点链路待端点恢复后补测。
2. **既有行为（非本轮引入，非缺陷）**：`delete_embedding_model` 对「仅被软删除 KB 引用」的模型返回 **409**（`embedding model in use (disable instead of delete)`，引用检查未过滤 `deleted_at`）。S33 清理阶段复现（DELETE 3584 model → 409）。S32 已记录为既有行为，维持。
3. **P3 UX 观察（非缺陷，非 BUG-19 范围）**：KB 列表页 reindex 状态（`reindexing → active`）无自动轮询/刷新，需用户手动刷新。建议后续加轮询或 toast 提示。

---

## 六、测试结论

- **测试结论**：**PASS**
- **是否满足验收标准**：**是**（BUG-19 复测全 PASS：3584 建库 201 + 3584 无 HNSW / 256 有 HNSW + 顺序扫描检索命中 + reindex 完成；256 维 HNSW 分支回归无新缺陷；KB 列表/详情正常）
- **阻塞性问题**：**无**
- **交 S34 终审**：代码 commit fe1cb5a（S32，未 push）随 S34 一次推送；本轮无新增代码改动（仅测试证据 + 报告）。

### 产物
- 报告：`03-testing/TEST_REPORT_S33.md`（本文件）
- 截图：`03-testing/screenshots/s33/`（38 张）
- 证据日志：`03-testing/dev_probe_s33_ui.log`（19/20）、`dev_probe_s33_reindex_retest.log`（8/8）、`dev_probe_s33_index.log` + `dev_probe_s33_index_check.sql`（索引/EXPLAIN 铁证）、`dev_probe_s33_endpoint.log`（RISK-019 端点状态）
- 脚本（`05-temp/s33/`）：`s33_lib.js` / `s33_ui_test.js` / `s33_retest_reindex.js` / `s33_index_probe.py` / `gen_idx_sql.py` / `s33_cleanup.py` / `endpoint_check.py` / `s33_shot_reindex.js`
