# ACCEPTANCE_S43 — 对比页全类型终审验收（防造假）+ push 决策

> 褚岩（chuyan / PM·终审）| 2026-09-30 | 任务 t_2b8109d5
> 范围：S41（对比页左栏 docx/xlsx 原文不显示修复）+ S42（全类型复测）
> 原则：**不采信 S41/S42 自报，独立核查**（源码 grep / 原始日志逐字读 / git 实码 / ls-remote），任何环节缺口即退回。

---

## 1. 整轮终审判定

**整轮判定：FAIL（P1 未闭环）→ 本次不放行、不 push。**

| 验收项 | 结果 | 依据（本终审独立核查） |
|---|---|---|
| 防造假核查（测试是否真实） | ✅ **PASS** | §2 逐项；diag2.js 的 in-page fetch 系**报告主动披露的诊断取证**，未参与任何判定 |
| S41 主目标：对比页左栏 7 类型原文真实渲染 | ✅ 7/7 PASS | S42 验证轮 log 21 PASS（7 类型左栏 tag/leftTextLen/cells/tabs/iframeSrc/naturalWidth 逐条）+ 原始 `/file` 二进制 magic + S41 commit 810d390 实码含真实 docx-preview/xlsx 依赖 |
| 每类型右栏 chunk 列表 | ✅ 7/7 PASS | S42 验证轮 chunkCount 与 DB 期望逐条相等（txt2/md2/docx7/xlsx3/pdf3/png1/jpg1） |
| 对比页右→左联动（点 chunk → 左栏高亮，ARCH R06/R09 正式需求） | ❌ **FAIL** | **BUG-24（P1）**：txt/md 点 chunk 触发 `chunks/undefined/location` → 500，左栏永不高亮 + 顶部红横幅。本终审源码独立 grep + API log 独立复核，根因成立 |
| 7 文档全部 ready（embedding 入库） | ✅ 7/7 | S42 验证轮 log「7 文档全部 ready」+ 原始响应逐字（txt/xlsx 首轮瞬时 ReadError 重试后 ready） |

**判定依据**：S41 的前端修复（docx/xlsx 左栏真实渲染）经全类型复测**闭环有效**（S41 主目标 PASS，可交付）；但本轮独立复测暴露 **P1 真实产品缺陷 BUG-24**（对比页右→左联动对 txt/md 完全不可用，用户可见 500 横幅），属 ARCH §2.2.1 R06/R09 正式需求，S39/S41 均只测「左栏渲染 + chunk 列表」而从未测「点 chunk 高亮」，故此前未暴露。**QA_STANDARD §三「P0/P1 全关」不满足 → 对比页完整验收不得放行、不 push**（同 S28 先例：P1 未闭环 → 建修复-回归链，终审后另起终审+push 卡）。

---

## 2. 防造假核查（独立执行，非采信 S42 自查）

| # | 核查项 | 结果 | 独立证据 |
|---|---|---|---|
| 1 | UI 测试脚本零 in-page fetch/localStorage/page.evaluate | ✅ PASS | grep `s42_ui_test.js`/`s42_verify.js`/`pdf_retest.js`/`pdf_headed.js`/`debug_upload.js`：`fetch(`/`localStorage`/`page.evaluate`/`mock`/`intercept` **零代码命中**（仅脚本头注释声明「无 in-page fetch」） |
| 2 | 全部 `page.goto` 均为登录入口，无绕登录 | ✅ PASS | 7 个脚本共 7 处 `page.goto(BASE + '/login')`，逐条判读全为登录入口；其余导航（RAG→知识库→文档→对比）为真实站内点击 |
| 3 | `diag2.js` 的 in-page fetch 定性 | ✅ 合规（非造假） | `diag2.js` L54-74 含 `page.evaluate(fetch)` + `localStorage.getItem('token')`——**仅用于根因取证**（用正确 id 调 location API 证 200、用 `undefined` 证 500，以坐实「字段不匹配是唯一原因」）；**报告 §5 L98 已主动披露**「diag2 曾含 in-page fetch（仅用于取证确认，未用于任何判定结论）」「所有判定结论均基于真实 UI 点击 + 宿主 curl 原始 API 响应 + DB psql 三层证据，diag2 不参与定论」→ 透明披露，属诊断工具，**不构成造假** |
| 4 | 7 类型 `/file` 原始响应真实二进制 | ✅ PASS | `dev_probe_s42_file.log` 逐字：7 文档全 200，magic 真实——txt `5334322054`/md `23205332`/docx+xlsx `504b0304`(PK·OOXML)/pdf `255044462d`(%PDF-)/png `89504e470d`/jpg `ffd8ffe000` |
| 5 | 原始 API 取证（BUG-24 定因）真实 | ✅ PASS | `dev_probe_s42_api.log` 逐字：location API 正确 id → **200**（`pos.char_start=0`）；`undefined` id → **500**；chunks 列表 keys 含 `id`、**`chunk_id=None`**（宿主 curl + 真实登录 token，非 in-page） |
| 6 | 7 类型截图与报告对应 + 真实 UI | ✅ PASS | `03-testing/screenshots/s42/` 26 张与报告 §2 表格逐行对应（login/kb/7 类型 cmp/7 chunk_hl/pdf headed+retest/diag）；`dev_probe_s42_ui.log` 7 类型上传全 201、RUN=s42612369 真实表单登录 |

**防造假结论：6/6 PASS。S42 测试真实、无造假、无绕登录、无 mock；diag2.js 的 in-page fetch 为主动披露的诊断取证，不影响任何判定。**

---

## 3. 7 类型证据表（S42 复测 × 本终审独立交叉）

> 交叉源：S42 验证轮 `dev_probe_s42_verify.log`（21 PASS/2 FAIL）+ 原始 `/file` 二进制 `dev_probe_s42_file.log` + location API `dev_probe_s42_api.log` + S41 commit 810d390 实码。

| # | 类型 | 文件 | ready | 左栏实际内容（验证轮 log 逐字） | 右栏 chunk | 截图 | 本终审判定 |
|---|---|---|---|---|---|---|---|
| 1 | txt | s42_txt_probe.txt | ✅(重试后) | 真实原文 leftTextLen=520 `S42 TXT Probe ===…` | 2（=DB） | cmp_txt.png | ✅ 左栏/chunk 通；**点 chunk 高亮 FAIL（BUG-24）** |
| 2 | md | s42_md_probe.md | ✅ | 真实原文 leftTextLen=622 `# S42 MD Probe…` | 2（=DB） | cmp_md.png | ✅ 左栏/chunk 通；**点 chunk 高亮 FAIL（BUG-24）** |
| 3 | docx | s42_docx_probe.docx | ✅ | 真实 Word 渲染 leftTextLen=197759 tables=1 | 7（=DB） | cmp_docx.png | ✅（S41 已修）；docx 点 chunk 走 highlightQuery 最佳努力，marks=1 |
| 4 | xlsx | s42_xlsx_probe.xlsx | ✅(重试后) | 真实表格 cells=34 tabs=[Inventory,Orders,Returns] firstCell=SKU | 3（=DB） | cmp_xlsx.png | ✅（S41 已修）；xlsx 点 chunk 最佳努力 marks=0（不报错） |
| 5 | pdf | s42_pdf_probe.pdf | ✅ | iframe 预览 iframeSrc=blob:…（headed 3 页） | 3（=DB） | cmp_pdf_headed.png | ✅ |
| 6 | png | s42_png_probe.png | ✅ | img 直显 naturalWidth=520 | 1（=DB） | cmp_png.png | ✅ |
| 7 | jpg | s42_jpg_probe.jpg | ✅ | img 直显 naturalWidth=560 | 1（=DB） | cmp_jpg.png | ✅ |

**S41 主目标（docx/xlsx 左栏真实渲染）闭环有效；7 类型左栏 + chunk 列表全通过。** 唯一未闭环 = BUG-24（右→左联动 txt/md，P1）。

---

## 4. S41 修复独立核验（commit 810d390，非采信自报）

- **commit**：`810d390883f4da4c5971d5e5b6f2ee0629d4c6d7`（本地 main HEAD，领先 origin 1，**未 push**）。
- **实码核验（独立 git show）**：
  - 新增真实依赖 `docx-preview@0.4.1` / `xlsx@0.18.5`（非假引用）。
  - `frontend/src/views/rag/CompareView.vue`：`import { renderAsync } from 'docx-preview'` + `import * as XLSX from 'xlsx'`；docx `renderAsync` 渲染为 HTML、xlsx `XLSX.read`/`XLSX.utils.sheet_to_json` 多 sheet 表格（首 sheet 全量 + tab 切换）；新增 `src/utils/highlight.js`（渲染后 DOM 文本流最佳努力匹配，匹配不到不报错）。
  - `deploy/docker-compose.yml` webconsole 镜像 s38→s41（容器内 npm ci + vite build）。
- **自测/回归（S41 自报，本终审抽查其 log 存在性）**：`dev_probe_s41_ui.log` 11/11 + `dev_probe_s41_regression.log` 3/3 + `dev_probe_s41_apifile.log` 3 文档 /file 200 真实二进制。

**S41 主目标独立确认 PASS，可交付；但其所在 CompareView.vue 同时含 BUG-24 缺陷（同一文件在修），故 S41 暂不单独 push，随本轮整轮闭环后一并推送。**

---

## 5. BUG-24 独立确认（源码 grep + 原始 API log，非采信 S42 分析）

- **前端**（本终审独立 grep `frontend/src/views/rag/CompareView.vue`）：L62 `:key="c.chunk_id"` / `:data-cid="c.chunk_id"`、L63 `selectedChunk?.chunk_id === c.chunk_id`（active 判定）、L252 `api.getChunkLocation(kbId, docId, c.chunk_id)`、L287 `c.chunk_id === primary`、L313 `querySelector([data-cid="${c.chunk_id}"])`、L327 `editTarget.value.chunk_id`——**全量读 `c.chunk_id`**。
- **后端**（独立 grep `services/shared/joker_shared/rag/service.py`）：`_chunk_dict`(L579) / `list_chunks`(L597,614) 返回字段为 **`id`**（`dict(row._mapping)` 列名即 `id`），**无 `chunk_id`**。
- **原始 API 铁证**（`dev_probe_s42_api.log`）：location API 正确 id → **200**；`undefined` id（前端实际发送值）→ **500**；chunks 列表 `chunk_id=None`。
- **现象**（S42 真实 UI）：txt/md 点 chunk → 顶部「Internal Server Error」红横幅 + 左栏永不高亮（`dev_probe_s42_verify.log` 两条 FAIL `marks=0`）；active 态 `undefined===undefined` → 所有 chunk 全亮蓝边（截图 cmp_txt_chunk_hl.png / cmp_docx_chunk_hl.png）。
- **定因**：前端 `c.chunk_id` 与 API 字段 `id` 不匹配，**pre-existing（非 S41 引入）**，S39/S41 未测「点 chunk 高亮」故此前未暴露。
- **潜在连带**：txt 521 字符但 `pos.char_end=1021`（越界）、md 623 字符 `char_end=1123`（越界）——疑切分器存**字节偏移**非**字符偏移**；即使修好字段，`t.slice(s,e)` 越界仍可能高亮错误。**待 BUG-24 修复后独立复验**。

---

## 6. push 决策（本终审）

- **本次不 push**。理由：整轮 FAIL（P1 BUG-24 未闭环），QA_STANDARD §三不满足；S41 与 BUG-24 同文件（CompareView.vue）在修，单独 push S41 会将 P1 缺陷与未完成的整轮推上 main，违反「一次 push / 整轮闭环」原则 + 「稳定交付 > 快速交付」。
- **git 现状**：本地 main = `810d390`（S41），**领先 origin/main 1**；origin/main = `760034c425d36c3a502b179bf713ea3f9fc09496`（S40 收口）。**S41 未推远端。**
- **推送时机**：待 **S42b（修 BUG-24）→ S42c（云天明回归复测）→ S44（褚岩终审+push）** 链路完成后，由 **S44** 一次性 push：S41（810d390，前端 docx/xlsx 渲染 + 依赖）+ S42b 修复 + S42c/S44 证据 + 管理回写（**不 push 05-temp**）。

---

## 7. 后续链路（本终审建立，自驱）

| 卡 | 负责人 | 内容 | 依赖 |
|---|---|---|---|
| S42b `t_9cefd314` | 章北海 | 修 BUG-24：`CompareView.vue` 全量 `c.chunk_id`→`c.id`（模板 :key/:data-cid/active 判定/onChunkClick/openEdit/updateChunk）+ 核对 chunk_location 返回 chunk_id 与列表 id 同源；真实 UI 自测 | 已完成（运行中） |
| **S42c** `t_43b3e53a`（本终审创建） | 云天明 | **BUG-24 回归复测**：真实 UI 点 txt/md chunk → 左栏**精确高亮**（黄底 mark）+ 仅被点 chunk active + 无红横幅 + docx 点 chunk 仍正常 + **pos 越界（字节/字符错位）复验** + 7 类型左栏回归不坏；防造假自查 | parent = S42b |
| **S44** `t_e98d3cab`（本终审创建） | 褚岩 | **终审验收 + 一次 push**：不采信自报独立复验 BUG-24 修复 + 回归，PASS → 一次 push（S41 + S42b + S42c/S44 证据 + 回写，不推 05-temp）+ 产出 ACCEPTANCE_S44 + ls-remote 核验 | parent = S42c |
---

## 8. 遗留（不阻塞本轮放行，转 S44 / 后续）

1. **BUG-24（P1）**：待 S42b 修复 + S42c 回归闭环（主阻塞项，S44 放行门槛）。
2. **pos 字符偏移越界（潜在）**：疑切分器存字节偏移非字符偏移；待 BUG-24 修复后 S42c 独立复验，若确认错位需同修切分器 pos 计算。
3. **BUG-25（P3 · 观察，S42 时编号 BUG-22）**：embedding 端点瞬时 ReadError 无重试，批量上传文档落 failed（本轮真实 UI 重试已恢复，非对比页范围，不阻塞）。
4. **BUGS.md 编号冲突（P4 文档治理，S44 已处理）**：BUGS.md 存在两组同编号 BUG——旧 RAG 三缺陷轮 BUG-21/22/23（S38，已关闭，编号保留）vs 新 S42 对比页缺陷。**S44 收口时已将新对比页 BUG 重命名为 BUG-24（P1）/ BUG-25（P3）**，活跃引用同步更新。
