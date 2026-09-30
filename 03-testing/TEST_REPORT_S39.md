# TEST_REPORT S39 — agent-joker RAG 三缺陷修复复测（md 支持 / reindex 状态一致性 / 检索 502 容错）（真实 UI）

- **测试人**：云天明（yuntianming），任务卡 t_d5ad526f
- **日期**：2026-09-30（CST）
- **上游**：S38（t_bda82f31，zhangbeihai）RAG 三缺陷修复（本地 commit ac49755，未 push，待 S40 终审）
- **标准**：`03-testing/QA_STANDARD.md`（真实 UI + 原始 API 响应双层证据；防造假硬规则）
- **环境**：本地 compose（joker-api:s38 / joker-webconsole:s38 / bff:s32 / pg / redis 全 healthy），webconsole:8080 → bff → api → pg
- **工具**：Playwright chromium headless；**真实表单登录**（fill 租户/用户名/密码 → click 登录 → waitForURL 离开 /login）
- **RUN**：s39929677（最终成功 run；前两次 run s39061876 / s39639732 因脚本缺陷中断，产物已清理）
- **截图**：`03-testing/screenshots/s39/`（32 张，关键截图经 vision 独立核验）
- **原始 API 响应**：`05-temp/s39/api_raw/`（浏览器 /api/ 全流水，58 份，含完整请求/响应体）
- **脚本**：`05-temp/s39/s39_ui_test.js`（可复跑）；清理 `s39_cleanup{,2,3}.js`

> ## 整轮判定：**PASS** — S38 三缺陷修复全部复测通过，无产品代码缺陷，满足验收标准，无阻塞项。
> 判据（全部真实 UI 操作 + 原始 API 响应，不采信 S38 自报）：
> ① **md 支持**：1536 维 gte-Qwen2-1.5B 库上传 `.md` → **201**（doc_type=md, parse_method=text）→ **ready** → 检索命中唯一 marker（top1 **0.449167**）→ 「对比」按钮可点 → 对比页正常渲染（左=md 原文标题/列表/代码块, 右=chunk 切片）。
> ② **reindex 状态一致性**：256 维坏端点库上传 txt → 文档 **failed**（ReadTimeout）→ 换 1536 real 模型 reindex → 库 **active**(1536) → **failed 文档【自动】重算变 ready（全程零手动 retry）**（API 日志铁证 `reindex: requeued 1 failed docs` → `doc ready`）→ 检索命中（top1 **0.696454**）。
> ③ **检索 502 容错**：不可达 1536 端点库检索 → **502**（非裸 500）→ detail 可读中文「embedding 服务暂时不可用（已自动重试 1 次仍失败）…」无 traceback 泄露 → 前端 toast 同文可读 → **连续 5 次查询（好库）全 200 无 500**。
> 全程遵守防造假硬规则：无 in-page fetch / 无 localStorage 注入 / 无 goto 受保护页绕登录（仅 goto /login 入口，其余全部站内导航+点击）。

---

## 一、背景与复测范围

S38 修复的 3 个 RAG 缺陷（用户真实 UI 上报，主 agent 本地复现定因）：

| # | 缺陷 | S38 修复 | 本轮复测重点 |
|---|---|---|---|
| ① | RAG 不支持 md（上传 `.md` → 422 unsupported file type） | parser `SUPPORTED_TYPES`/`DOC_TYPE_BY_EXT` 加 md，md 走 `_parse_txt` 纯文本 | 上传 md → ready → 检索命中 → 对比页渲染 |
| ② | reindex（换 embedding 模型）后 failed 文档不刷新 → 永久 failed + 对比按钮 disabled | service 新增 `_requeue_failed_docs`：reindex 完成切 active 后该库 failed 文档自动重入队重算 | 坏端点文档 failed → reindex → **自动** ready（无手动 retry） |
| ③ | 检索首次 500（embedding 端点瞬时连接失败 → 裸 ASGI 500 + traceback） | retrieval 新增 `_embed_query_with_retry`：1 次重试 2s 退避，仍失败 → 502 可读中文 | 不可达端点 → 502 可读 + 无 traceback + 前端 toast；多次查询无 500 |

> ② 与 ③（用户报的"对比按钮不可点"）是同一根因两面：文档 failed 卡死 → 无 chunk → 检索命中不到 + 对比按钮 disabled。S38 修 ② 后对比按钮随文档 ready 自动恢复（本轮已验证）。

## 二、测试环境与防造假声明

- **真实 UI**：Playwright chromium headless，真实表单登录（`input[placeholder="如 acme"]`/`admin`/`123456` → click「登录」），登录后全部操作为站内菜单点击 + 表单填写 + 文件选择器 + 按钮点击。
- **零 mock / 零 in-page fetch**：所有 API 交互由前端自身发出，脚本仅通过 `page.on('response')` 旁路**捕获**原始响应留档（不注入、不伪造）。`s39_ui_test.js` 全文 `grep fetch(` / `localStorage` 零命中（除 Playwright API）。
- **无 goto 受保护页**：`grep page.goto` 仅 1 处 = `/login` 登录入口；其余导航全部 `page.click`（侧栏菜单 / 按钮）。
- **真实 embedding 端点**：`34.64.61.208:4000/v1`（1536 维 gte-Qwen2-1.5B-instruct，S35 已闭环的真实端点）；坏端点用 TEST-NET-1 不可达 IP（`192.0.2.123:59999` / `192.0.2.234:59999`）制造确定性连接失败，非平台代码缺陷。
- **证据三层**：真实 UI 截图（关键 5 张 vision 独立核验）+ 原始 API 响应（浏览器捕获 JSON）+ API 容器日志铁证（`docker logs joker-api`）+ psql 终态复核。

## 三、测试步骤与结果（真实 UI + 原始响应）

### Phase A — reindex 状态一致性（缺陷 ②，核心）

脚本 `05-temp/s39/s39_ui_test.js` Phase A。

| # | 操作（真实 UI） | 原始响应/结果 | 判定 | 截图/证据 |
|---|---|---|---|---|
| 00 | 真实表单登录 acme/admin | `POST /api/auth/login` **200** → `/users` | PASS | `00_login_ok.png` |
| 01 | LLM 节点→Embedding 模型：建 3 模型（256 坏 / 1536 坏 / 1536 real） | 3×`POST /api/llm/embeddings` **201** | PASS | `01_emb_form_*` |
| 03 | RAG→知识库：用 256 坏端点模型建库 `s39-kb-a` | `POST /api/rag/kbs` **201** dim=256 | PASS | `02_kb_form_-a` |
| 04a | 进库上传自造 txt（`s39txt_929677.txt`，含唯一 marker） | `POST .../docs` **201** | PASS | `03a_upload_txt.png` |
| 05a | 轮询文档状态至终态 | status=**failed**，error=`ReadTimeout`（坏 256 端点连接超时） | PASS | `04a_txt_failed.png` |
| 06a | 回列表→「换模型」对话框选 1536 real → 开始重算 | `POST .../reindex` **200** `{ok:true,status:reindexing}` | PASS | `05a_reindex_dialog.png` |
| 07a | 轮询库状态至 active | status=**active** dim=**1536** | PASS | `06a_kb_active_after_reindex.png` |
| 08a | 进文档页，轮询文档状态（**全程零手动 retry**） | status=**ready**，error 清空（旧=ReadTimeout） | PASS | `07a_txt_auto_ready_after_reindex.png` |
| 09a | 检索测试页选 KB_A 查 txt marker | `POST /api/rag/search` **200**，1 hit，top1 **score=0.696454**，content 含 `s39txt_dragon_titanium_marker_9a4c` | PASS* | `08a_search_kbA.png` + `raw_027.json` |

**缺陷 ② 铁证（API 容器日志，`docker logs joker-api`，RUN s39929677 KB_A `005640e3…`）**：
```
09:02:17,404 doc uploaded s39txt_929677.txt → kb 005640e3… (fb644cb1…)
09:02:43,715 reindex done kb=005640e3…: shadow …_reindex → … (dim=1536)
09:02:43,717 reindex: requeued 1 failed docs for kb=005640e3…: ['fb644cb1…']   ← S38 _requeue_failed_docs 生效
09:02:45,319 doc ready fb644cb1…: 1 chunks (strategy=fixed, dim=1536)            ← 自动重算，无手动 retry
```
**psql 终态复核**：`s39-kb-a_s39929677` status=active embedding_dim=1536，文档 `s39txt_929677.txt` doc_type=txt status=**ready** parse_method=text chunk_count=1 error_message=NULL。

> *09a 脚本判定字段读错（脚本取 `body.data.items`，实际响应体为 `body.items`），判定 FAIL 为**脚本解析缺陷**非产品缺陷；原始响应 `raw_027.json` 逐字证实 200 + 1 hit + marker 命中（见 §五 脚本缺陷定因）。

### Phase B — md 主链路 + 对比按钮（缺陷 ①）

| # | 操作（真实 UI） | 原始响应/结果 | 判定 | 截图/证据 |
|---|---|---|---|---|
| 01 | 复用 1536 real 模型（已存在） | 跳过创建 | PASS | — |
| 03 | 用 1536 real 模型建库 `s39-kb-b` | `POST /api/rag/kbs` **201** dim=1536 | PASS | `02_kb_form_-b` |
| 10b | 进库上传自造 `.md`（`s39md_929677.md`，含标题/段落/列表/代码块 + 唯一 marker） | `POST .../docs` **201**（**修复前=422 unsupported**） | PASS | `09b_upload_md.png` |
| 11b | 轮询文档至终态 | status=**ready**，doc_type=**md**，parse_method=**text**，chunk=1，error=NULL | PASS | `10b_md_ready.png` |
| 12b | ready 文档行「对比」按钮状态 | `:disabled` 逻辑 → **enabled=true**（可点击） | PASS | `11b_compare_button_enabled.png` |
| 13b | 点击「对比」→ 对比页渲染 | 左栏=md 原文（标题`# S39 验证文档`/列表`-`/代码块```` ``` ````），含 marker；右栏=chunk 切片(1)；顶部 tag `md`+`ready` | PASS | `12b_compare_page.png` |
| 14b | 检索测试页选 KB_B 查 md marker | `POST /api/rag/search` **200**，1 hit，top1 **score=0.449167**，content 含 `s39md_krait_quartz_marker_7f2e` | PASS* | `13b_search_md_hit.png` + `raw_045.json` |

**缺陷 ① 铁证**：md 上传 201（非 422）+ doc_type=md + parse_method=text + ready + 检索命中真实 md 内容（含标题/列表/代码块）+ 对比页左栏完整渲染 md 原文。

> *14b 同 09a，脚本取 `body.data.items`（实际 `body.items`）致判定 FAIL；原始响应 `raw_045.json` 逐字证实 200 + 1 hit + marker 命中。

### Phase C — 检索 502 容错 + 多次查询（缺陷 ③）

| # | 操作（真实 UI） | 原始响应/结果 | 判定 | 截图/证据 |
|---|---|---|---|---|
| 01 | 用 1536 坏端点模型（已存在）建库 `s39-kb-c` | `POST /api/rag/kbs` **201** dim=1536 | PASS | `02_kb_form_-c` |
| 15c | 检索测试页选 KB_C 查询 | `POST /api/rag/search` **502**（非裸 500） | PASS | `14c_search_502.png` + `raw_053.json` |
| 16c | 502 响应体可读性 | detail=`embedding 服务暂时不可用（已自动重试 1 次仍失败）：请检查 embedding 端点连通性后重试检索。（ReadTimeout）`；body **无** Traceback/httpcore/asyncpg 泄露 | PASS | `raw_053.json` |
| 17c | 前端 toast 可读 | 红色 toast 同文（中文可读，非 traceback） | PASS | `14c_search_502.png`（vision 核验） |
| 18c | 重试退避 | elapsed=32.1s（含 2s 退避 + 端点连接超时，≥1.9s） | PASS | run log |
| 19c | 切到好库 KB_B 连续 5 次查询 | statuses=**200,200,200,200,200**（**无 500**），无错误 toast | PASS | `15c_search_bulk5.png` + `raw_054..058.json` |

**缺陷 ③ 铁证（原始响应 `raw_053.json` 逐字）**：
```json
{ "status": 502, "body": { "detail": "embedding 服务暂时不可用（已自动重试 1 次仍失败）：请检查 embedding 端点连通性后重试检索。（ReadTimeout）" } }
```
- 无裸 500 ASGI traceback（body 无 `Traceback`/`httpcore`/`asyncpg`/`site-packages`）；
- 前端 toast 同文可读（vision 独立核验截图）；
- 连续 5 次查询（好库）全 200，证明真实链路下无回归 500。

## 四、整轮结论

| 缺陷 | 复测判定 | 证据 |
|---|---|---|
| ① md 支持 | **PASS** | md 201→ready(parse=text)→检索 0.449167 命中→对比页渲染（真实 UI + raw_045 + 12b 截图 vision 核验） |
| ② reindex 状态一致性 | **PASS** | failed→reindex→**自动** ready（API 日志 `requeued 1 failed docs`→`doc ready`，零手动 retry）+ 检索 0.696454 命中（真实 UI + 容器日志 + psql 终态） |
| ③ 检索 502 容错 | **PASS** | 502 可读中文（无 traceback）+ 前端 toast 可读 + 5 次查询全 200 无 500（真实 UI + raw_053 + 14c 截图 vision 核验） |

- **测试结论**：**PASS**
- **是否满足验收标准**：**是**（三缺陷全部复测通过，真实 UI 全链路闭环，无产品代码缺陷）
- **阻塞性问题**：**无**
- **新发现产品 BUG**：无（本轮 3 个脚本 FAIL 均为测试脚本 JSON 解析缺陷，已定因，不影响产品判定）
- **回归**：无新回归（md/txt 主链路、reindex、检索、对比、502 容错、连续查询均正常；前序 S35/S36/S37 已闭环项未触碰）

## 五、脚本缺陷定因（3 个 FAIL 非产品缺陷，透明披露）

脚本 `s39_ui_test.js` 判定逻辑 3 处读错响应体结构，导致 3 项判定 FAIL，但**原始 API 响应（防造假 ground truth）逐字证实产品行为正确**：

| 脚本判定 | 脚本错误 | 原始响应铁证（产品实际行为） | 产品结论 |
|---|---|---|---|
| 09a FAIL | 取 `body.data.items`，实际响应体为 `body.items`（BFF 未包 data 层） | `raw_027.json`：status=200，items[0].score=**0.696454**，content 含 `s39txt_dragon_titanium_marker_9a4c` | 检索命中 ✓ |
| 14b FAIL | 同上 | `raw_045.json`：status=200，items[0].score=**0.449167**，content 含 `s39md_krait_quartz_marker_7f2e` | 检索命中 ✓ |
| 01 (Phase C) FAIL | 复用已存在的坏 1536 模型时二次创建 → 409（脚本未判"已存在"） | `raw` 显示 409，但随后 `POST /api/rag/kbs` 建 KB_C **201**（用已存在模型）正常 | 建库成功 ✓，409 为脚本重复创建，非产品缺陷 |

> 说明：09a/14b 的 `score` 已从原始响应 `raw_027.json`/`raw_045.json` 精确读出并记入本报告（0.696454 / 0.449167），任务要求的"记录 top1 分数"满足。Phase A 的 08a（自动重算 ready）、Phase B 的 11b/12b/13b、Phase C 的 15c/16c/17c/18c/19c 均一次判定 PASS（这些步骤未依赖 `body.data` 路径）。

## 六、清理（真实 UI）

测试产物已全部清理（防环境污染，供 S40 终审/后续复测干净环境）：
- 3 个测试库 `s39-kb-{a,b,c}_*` → 真实 UI「删库」→ 级联删文档/chunk + DROP 向量表（psql 复核 0 个 active s39 库）；
- 9 个测试 embedding 模型（含前两次中断 run 遗留 6 个）→ 真实 UI 编辑→状态 disabled→保存（PUT 200，psql 复核全 disabled）。

## 七、交付 / 交接

- 报告：`03-testing/TEST_REPORT_S39.md`（本文件）
- 截图：`03-testing/screenshots/s39/`（32 张；关键 5 张 vision 独立核验：00_login_ok / 07a_txt_auto_ready / 10b_md_ready / 12b_compare_page / 14c_search_502）
- 原始 API 响应：`05-temp/s39/api_raw/`（58 份，RUN s39929677 09:02–09:04，含完整请求/响应体）
- 脚本：`05-temp/s39/s39_ui_test.js`（可复跑）+ `s39_cleanup{,2,3}.js`
- 环境终态：joker-api/webconsole s38 healthy；S38 三缺陷复测全 PASS；测试产物已清理；**S38 commit 仍未 push**（push 由 S40 终审 chuyan 统一）
- 交接 S40（终审）：S38 修复复测 PASS，可进入终审。建议终审关注：① md 检索 top1 分数偏低（0.449，阈值 0.3 之上，命中正常但余量小——md 纯文本解析不做语义切分的已知边界，S38 已声明）；② 502 重试 1 次 + 2s 退避为任务要求的最小语义（4xx 不重试，保留 404/409 语义）。
