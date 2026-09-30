# TEST_REPORT_S42 — 对比页全类型文档复测（7 类型，保留测试数据）

> 云天明（yuntianming）| 2026-09-30 | 任务 t_2e466e41
> 范围：S41 修复（对比页左栏 docx/xlsx 原文不显示）的**全类型复测**，覆盖全部 7 种文档类型。
> 环境：本地 compose（webconsole:**s41** / api:s38 / bff:s32 / pg / redis 全 healthy），webconsole:8080 → bff → api → pg。
> 库：既有 1536 维库 `upload-repro-01`（embedding 模型 `s26-gte-qwen2-real`，真实端点 `http://34.64.61.208:4000/v1`，dim=1536）。
> **测试数据保留**：本轮上传的 7 个文档全部保留在库中，**未删除**（用户 S42 指定）。

## 1. 测试结论

**整轮判定：FAIL（不满足全部验收标准）**

| 验收项 | 结果 |
|---|---|
| S41 主目标：对比页左栏 7 类型原文真实渲染 | ✅ **7/7 PASS**（docx/xlsx 本轮新验证 + txt/md/pdf/png/jpg 回归不坏） |
| 每类型右栏 chunk 列表正常 | ✅ 7/7 PASS |
| 对比页右→左联动（点 chunk → 左栏高亮，ARCH R06/R09 正式需求） | ❌ **FAIL**（txt/md 点 chunk 触发 500，左栏永不高亮） |
| 7 文档全部 ready（embedding 入库） | ✅ 7/7（txt/xlsx 首轮瞬时 ReadError，重试后 ready） |

**判定依据**：S41 的前端修复（docx/xlsx 左栏真实渲染）经全类型复测**闭环有效**，7 类型左栏均有实际内容 + 右栏 chunk 列表正常。但本轮独立复测（不采信 S41「txt/md 本就正常」的自报）**发现一个 P1 真实产品 BUG**：对比页**右→左联动**（点右栏 chunk → 左栏高亮原文）对 txt/md **完全不可用**——点 chunk 触发 `GET .../chunks/undefined/location` → **500**，左栏永不高亮，且页面顶部弹「Internal Server Error」红色横幅。该功能为 ARCH §2.2.1 R06/R09 的**正式需求**，S39/S41 均只验证「左栏渲染 + chunk 列表」而**从未验证「点 chunk 高亮」**，故此前未暴露。存在 P1 未闭环缺陷 → 不得报告 PASS。

## 2. 7 类型全复测结果（真实 UI，Playwright 真实表单登录 acme/admin，零 mock）

测试脚本：`05-temp/s42/s42_ui_test.js`（上传轮）+ `05-temp/s42/s42_verify.js`（验证轮）。
证据：`03-testing/dev_probe_s42_ui.log` / `dev_probe_s42_verify.log` / `dev_probe_s42_file.log` / `dev_probe_s42_api.log` + `03-testing/screenshots/s42/`。
自造真实文件：`05-temp/s42/files/`（docx/xlsx/pdf 在 joker-api 容器内用 python-docx/openpyxl/pymupdf 生成；png/jpg 用 ImageMagick；txt/md 文本）。`file` 命令核验全部为真二进制（非假二进制）。

| # | 类型 | 文件 | ready | 左栏实际内容 | 左栏 tag | 右栏 chunk | 截图 | 判定 |
|---|---|---|---|---|---|---|---|---|
| 1 | txt | s42_txt_probe.txt | ✅(重试后) | 真实原文（标题/段落/marker） | 可高亮 | 2 | cmp_txt.png | ✅ |
| 2 | md | s42_md_probe.md | ✅ | 真实原文（标题/列表/代码块/marker） | 可高亮 | 2 | cmp_md.png | ✅ |
| 3 | docx | s42_docx_probe.docx | ✅ | **真实 Word 文档**（标题/段落/4×3 表格） | 已渲染 | 7 | cmp_docx.png | ✅ |
| 4 | xlsx | s42_xlsx_probe.xlsx | ✅(重试后) | **真实表格**（Inventory/Orders/Returns 三 tab + SKU/Name/Qty 等 34 cells） | 已渲染 | 3 | cmp_xlsx.png | ✅ |
| 5 | pdf | s42_pdf_probe.pdf | ✅ | **iframe 预览**（headed 真实渲染 3 页：1/3 工具条+缩略图+正文） | PDF 预览 | 3 | cmp_pdf_headed.png | ✅ |
| 6 | png | s42_png_probe.png | ✅ | **img 直显**（真实图片 naturalWidth=520） | 图片直显 | 1 | cmp_png.png | ✅ |
| 7 | jpg | s42_jpg_probe.jpg | ✅ | **img 直显**（真实图片 naturalWidth=560） | 图片直显 | 1 | cmp_jpg.png | ✅ |

**左栏渲染 7/7 全通过**（关键截图经 vision 独立复核：docx 真实 Word 文档+表格、xlsx 三 tab 表格+真实 cell、png/jpg 真实图片、txt/md 真实原文、pdf headed 3 页）。

### 2.1 左栏 `/file` 端点原始响应取证（真实登录 token，原始二进制）
`dev_probe_s42_file.log`：7 文档 `/file` 均 **200**，content-type 正确 + 真实 binary magic：
- txt `text/plain` 521B magic=`5334322054`（"S42 T"）
- md `text/markdown` 623B magic=`2320533432`（"# S42"）
- docx `application/vnd.openxmlformats-officedocument.wordprocessingml.document` 37148B magic=`504b0304`（PK/OOXML）
- xlsx `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` 6098B magic=`504b0304`
- pdf `application/pdf` 3545B magic=`255044462d`（%PDF-）
- png `image/png` 33268B magic=`89504e470d`
- jpg `image/jpeg` 10563B magic=`ffd8ffe000`

## 3. 发现的问题（BUG）

### BUG-24（P1）对比页右→左联动对 txt/md 失效：点 chunk 触发 `chunks/undefined/location` → 500，左栏永不高亮 + 顶部「Internal Server Error」横幅
- **严重度**：P1（核心功能失效 + 用户可见 500 错误横幅）。
- **现象**：txt/md 文档点对比页右栏任一 chunk → 顶部弹红色「Internal Server Error」横幅，**左栏原文无高亮**。截图 `cmp_txt_chunk_hl.png`（红横幅 + 左栏无高亮）、`cmp_md_chunk_hl.png`。
- **复现步骤**：登录 → 1536 库 upload-repro-01 文档页 → txt/md 文档点「对比」→ 点右栏 chunk #0。
- **预期**：左栏原文按 chunk 字符区间高亮（`<mark>`），仅被点 chunk 显示 active。
- **实际**：前端 `onChunkClick()` 调 `api.getChunkLocation(kbId, docId, c.chunk_id)`，但**右栏 chunk 列表 API 返回的字段是 `id`，无 `chunk_id` 字段**（`_chunk_dict` 直接 `dict(row._mapping)`，列名即 `id`）→ `c.chunk_id === undefined` → 请求打到 `.../chunks/undefined/location` → 后端 500 → 前端 `catch(e){/*忽略*/}` 吞错 → 左栏无高亮 + 全局错误横幅。
- **根因**（前端字段不匹配，**非 S41 引入，属既有缺陷**）：
  - `frontend/src/views/rag/CompareView.vue`（**含 S41 之前的 CompareView.orig 即如此，pre-existing**）：模板 `:key="c.chunk_id"`、`:class="{active: selectedChunk?.chunk_id===c.chunk_id}"`、`onChunkClick` 里 `api.getChunkLocation(kbId, docId, c.chunk_id)`、`openEdit`/`updateChunk` 用 `editTarget.chunk_id`——**全部读 `c.chunk_id`**。
  - `services/shared/joker_shared/rag/service.py` `list_chunks` → `_chunk_dict`：返回字段为 **`id`**（非 `chunk_id`）。
  - 证据（`dev_probe_s42_api.log`）：chunks 列表 API chunk #0 `keys` 含 `id`、**`chunk_id=None`**；location API 用**正确 id** 调 → **200**（`pos.char_start=0`）；用 **`undefined`** 调（前端实际发送值）→ **500**。
- **连带影响（同源）**：
  1. **active 态视觉 BUG**：`selectedChunk?.chunk_id === c.chunk_id` → `undefined === undefined` → 对**所有** chunk 为 true → 点任 chunk 后**所有 chunk 都显示 active 蓝边框**（截图 `cmp_txt_chunk_hl.png` 两 chunk 均蓝边、`cmp_docx_chunk_hl.png` #0-#5 均蓝边，#6 因 `is_table` 橙边）。
  2. **chunk 编辑功能（`openEdit`/`updateChunk`）同样读 `c.chunk_id`/`editTarget.chunk_id`** → 大概率同样打 `undefined`（本轮未单独验证，同源缺陷）。
- **为何 docx 高亮「看似正常」**：docx/xlsx 的 chunk 高亮走 `highlightQuery`（渲染后 DOM 文本流 `indexOf` 最佳努力匹配），**不调 location API**，故 docx 点 chunk 能高亮（截图 `cmp_docx_chunk_hl.png` 首段黄底）——但这恰好掩盖了 `c.chunk_id` 字段缺陷；且 docx 同样有 active 态全亮问题。
- **为何此前未暴露**：S39 只验证「对比页渲染（左栏原文 + chunk 列表）」，S41 只验证「docx/xlsx 左栏渲染 + 回归 md 原文 / pdf iframe」——**均无「点 chunk 验证高亮」步骤**。本字段缺陷自初始构建（a120497）起即存在，S41 未引入也未被其自测覆盖。
- **修复建议**（前端，二选一）：
  - A. 后端 `list_chunks` 在序列化时补 `chunk_id` 字段（或前端改用 `c.id`）；
  - B. 前端 `CompareView.vue` 全量把 `c.chunk_id` → `c.id`（模板 `:key`/`:data-cid`/`active` 判定、`onChunkClick`、`openEdit`、`updateChunk`），并确认 `chunk_location` 返回的 `chunk_id`/`primary_chunk_id` 与列表 `id` 同源（`chunks_by_location` 已返回 `chunk_id`，需核对字段一致性）。
- **状态**：未修复，交 S43 终审/章北海修复，修复后需回归。

### BUG-25（P3 · 观察）embedding 端点瞬时 `ReadError` 无重试，批量上传时文档落 failed
- **严重度**：P3（非本轮对比页范围；本轮已用真实 UI「重试」恢复，功能可用）。
- **现象**：7 文档批量上传时，txt/xlsx 的 rag worker 在调**远程** embedding 端点（34.64.61.208:4000）时抛 `httpcore.ReadError`（连接瞬时中断），文档落 `status=failed`（`error_message="ReadError:"`）。`api` 日志铁证：`rag doc worker failed ... httpx.ReadError`。
- **定因**：远程 embedding 端点**瞬时连接抖动**（端点侧环境态，非平台代码缺陷；随后 `reach_check` 实测端点 200/dim=1536 恢复）。文档已正确切分（txt=2/xlsx=3 chunks 已落库），仅向量化中断。
- **影响**：批量/并发上传时，任一 embedding 请求瞬时断连即整文档 failed，**无自动重试**，需用户手动点「重试」。
- **建议**：rag worker 对 embedding 调用加有限次重试 + 指数退避（仅对瞬时网络错误，非 4xx/5xx）。
- **状态**：观察项，记 BUGS.md，待后续排期（非对比页验收范围，不阻塞本轮主目标）。

### 附注：pos 字符偏移疑似字节/字符错位（潜在，待 BUG-24 修复后复验）
txt 文件 521 字符，但 `pos.char_end=1021`（> 521，越界）；md 623 字符，`pos.char_end=1123`（>623，越界）。**即使修好 BUG-24 的 `c.chunk_id` 字段**，前端 `t.slice(s,e)` 用越界区间仍可能高亮错误/无高亮。疑为切分器存的是**字节偏移**而非**字符偏移**（与 UTF-8/换行处理相关）。**本轮不据此下最终结论**（BUG-24 字段缺陷已先行阻断，无法验证高亮正确性），记为**待 BUG-24 修复后独立复验**的潜在缺陷，避免与 BUG-24 混淆。

## 4. 回归影响（S41 修复不坏既有类型）
| 类型 | S41 前行为 | S41 后（本轮） | 回归 |
|---|---|---|---|
| txt | 左栏原文直读 | 左栏原文直读（可高亮 tag） | ✅ 不坏 |
| md | 左栏原文直读 | 左栏原文直读（可高亮 tag） | ✅ 不坏 |
| pdf | iframe 预览 | iframe 预览（headed 3 页正常） | ✅ 不坏 |
| png/jpg | img 直显 | img 直显（naturalWidth 正常） | ✅ 不坏 |
| docx | **仅降级提示（S41 修的）** | **真实 Word 文档渲染** | ✅ 已修 |
| xlsx | **仅降级提示（S41 修的）** | **真实表格渲染（多 tab）** | ✅ 已修 |

**S41 主目标（docx/xlsx 左栏真实渲染）闭环有效，其余类型回归不坏。** 唯一回归外的新缺陷是 BUG-24（右→左联动 txt/md），该缺陷**非 S41 引入**（pre-existing），但由本轮全类型复测首次暴露。

## 5. 防造假自查（硬规则遵守）
- **登录真表单**：全部脚本 `page.goto(BASE + '/login')` 唯一入口 + `page.fill` 填 tenant/username/password + 点「登录」按钮，`waitForResponse('/api/auth/login')` 校验 200。**仅 /login 入口**，其余为站内点击导航（RAG→知识库→文档→对比）。
- **禁止 in-page fetch / localStorage / goto 受保护页**：UI 测试脚本（s42_ui_test.js / s42_verify.js / pdf_retest.js / pdf_headed.js）**零** `page.evaluate(fetch)`、**零** localStorage 注入、**零** goto 受保护页。原始 API 取证（api_evidence.sh / file_evidence.sh）走**宿主 curl + 真实登录 token**（非 in-page、非注入），为独立证据源。
  - 注：诊断脚本 `diag2.js` 曾含 in-page fetch（仅用于取证确认，未用于任何判定结论）；**所有判定结论均基于真实 UI 点击 + 宿主 curl 原始 API 响应 + DB psql 三层证据**，diag2 不参与定论。
- **证据 = 真实 UI + 原始 API 响应**：7 类型左栏=真实 UI 截图（vision 独立复核）+ `/file` 原始二进制响应；BUG-24=真实 UI 500 横幅截图 + location API 原始响应（正确 id 200 vs undefined 500）+ DB psql（pos 值）+ 源码 grep（`c.chunk_id` vs `id`）。

## 6. 交付物
| 文件 | 说明 |
|---|---|
| `03-testing/TEST_REPORT_S42.md` | 本报告 |
| `03-testing/BUGS.md` | 新增 BUG-24（P1）/ BUG-25（P3） |
| `03-testing/screenshots/s42/` | 7 类型对比页 + chunk 高亮 + pdf headed + 诊断截图 |
| `03-testing/dev_probe_s42_{ui,verify,file,api}.log` | 自测/验证/文件端点/location 取证日志 |
| `05-temp/s42/` | 自造真实文件 + 测试脚本 + 取证脚本（可复跑） |

## 7. 交接
- **S41 主目标（docx/xlsx 左栏真实渲染）闭环有效**，7 类型左栏 + chunk 列表全通过。
- **交章北海修复 BUG-24（P1，右→左联动 txt/md 500）**：前端 `CompareView.vue` 的 `c.chunk_id` → `c.id` 字段不匹配（+ active 态全亮、chunk 编辑同源）。修复后**必须回归**（BUG-24 + 附注 pos 越界复验）。
- **交褚岩（S43 终审）**：本轮整轮判定 **FAIL**（P1 未闭环）；S41 主目标 PASS 可交付，但对比页**完整验收（含右→左联动）须待 BUG-24 修复 + 回归后再终审 push**。
- **测试数据保留**：upload-repro-01 现含 S42 7 文档（txt/md/docx/xlsx/pdf/png/jpg，全 ready）+ S41 历史文档，**均未删除**。
