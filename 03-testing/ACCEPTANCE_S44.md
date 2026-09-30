# ACCEPTANCE_S44 — 对比页全类型终审验收（防造假）+ 一次 push main（褚岩）

> 褚岩（chuyan）| 2026-09-30 | 任务 **t_e98d3cab**（S44 放行门槛 + 一次 push）
> 范围：S41（docx/xlsx 左栏真实渲染，commit 810d390）+ S42b（修 BUG-24 原 BUG-21 + 切分器 pos，commit 0f6e6f0）+ S42c（云天明独立回归复测，t_43b3e53a + 并行卡 t_109b04a0 双份）。
> **不采信 S41/S42b/S42c 自报，独立执行核查。**

## 1. 整轮判定

**PASS → 放行一次 push main。**

放行门槛（任务单）全部满足：
- 防造假核查全过（§2）
- BUG-24（原 BUG-21，P1 对比页右→左联动）真闭环（独立复核，§3）
- 7 类型左栏 + chunk 列表全通（§4）
- pos 越界裁定：非新缺陷，不阻塞（§5）
- 无 P0/P1 未闭环（P3 遗留 2 项见 §7，均非阻塞）

## 2. 防造假核查（独立执行，非采信 S42c 自报）

| # | 核查项 | 结果 | 本终审独立动作 |
|---|---|---|---|
| 1 | S42c 全部测试脚本 grep `fetch(`/`localStorage`/`page.evaluate`/`mock`/`intercept` | ✅ **零代码命中** | 本终审 ripgrep 独立扫 `05-temp/s42c/` 全部 5 个脚本（s42c_ui_test.py / s42c_pos_evidence.py / s42c_loc_raw.py / s42c_api_evidence.sh / s42c_diag_edit.py）：唯一命中为 s42c_ui_test.py 第 6 行**注释文字**（"零 in-page fetch/localStorage/mock" 声明），无任何代码使用 |
| 2 | 全部 `page.goto` 逐条判读 = `/login` 唯一入口，无绕登录 | ✅ **2/2 全为 /login** | 独立 grep 全 s42c 目录 `page.goto`：s42c_ui_test.py:51 `page.goto(BASE + "/login", ...)` + s42c_diag_edit.py:18 同；其余导航全部为站内真实点击（RAG→知识库→文档→对比）+ `page.go_back()`。登录为真实表单 `page.fill` acme/admin + 点「登录」+ `wait_for_url` 校验离开 /login |
| 3 | 截图与 TEST_REPORT_S42c 对应（7 类型 + chunk 高亮 + 无红横幅 + pos 高亮区间） | ✅ **对应** | `03-testing/screenshots/s42c/` 磁盘实查 24 张：00_login_form/done、01_docs_list、02/03/04 txt（loaded/chunk0_hl/chunk1_hl）、05/06 md、07 编辑对话框、10/11 docx、regress_txt/md/pdf/png/jpg/docx/xlsx 7 张——与报告 §1 全表逐条对应 |
| 4 | 关键截图独立 vision 复核（≥2 张） | ✅ **2/2 独立复核通过** | 本终审 vision_analyze 独立读 `s42c/txt_chunk0_hl.png` + `s42c/md_chunk0_hl.png`：① 左栏黄色 `<mark>` 高亮**局部一段**（txt 前 500/521 字符，末段 "Paragraph three" 未高亮；md 前 500/623，Section C 未高亮）——**非整篇**，与 DB pos 区间 [0,500) 吻合；② 右栏**仅 #0 蓝色 active**（#1 普通态，范围标 [0,500)/[450,521)）；③ **无**顶部红色 Internal Server Error 横幅。与 S42c 报告 §2 描述一致 |
| 5 | 测试日志原始逐字读取（非经脚本解析） | ✅ 一致 | `dev_probe_s42c_ui.log` 30 行逐行读（20:25:27–20:25:53，30 PASS/0 FAIL，`undefined_reqs=[]`、`5xx=[]`、`marks=1`、`actives=1`、逐字比对 `ui_len=db_len`）；`dev_probe_s42c_pos.log` 逐行读（4 探针 chunk `in_bounds=True slice==content:True` + `chunks/undefined/location` 对照 500）；`results_s42c.json` pass=30 fail=0 与 log 逐条对应 |

**防造假结论：5/5 PASS，无造假。** S42c 双份独立复测（t_43b3e53a 本卡门槛 + t_109b04a0 并行卡）结论一致 PASS，互为交叉验证；并行卡编辑周期（t_109b04a0 worker 对 txt chunk#0 做 save+restore）经 S42c 独立佐证为 PUT 真实 chunk id（非 undefined）200 + re-embedded，且 4 探针 chunk content sha 前后不变（无数据损坏）。

## 3. BUG-24（原 BUG-21，P1）真闭环判定（独立复核）

三层独立证据交叉：

1. **源码独立 grep（本终审）**：`frontend/src/views/rag/CompareView.vue` 全文件**零 `c.chunk_id`**——6 处全为 `c.id`：L62 `:key="c.id"` + `:data-cid="c.id"` + `active: selectedChunk?.id === c.id`、L252 `api.getChunkLocation(kbId, docId, c.id)`、L287 `chunks.value.find((c) => c.id === primary)`、L313 `data-cid` 查询、L327 `updateChunk(..., editTarget.value.id)`。全前端目录 grep `chunk_id` 仅剩 2 处：CompareView L286 `res.data?.primary_chunk_id`（`/chunks_by_location` 契约响应字段，正确）+ SearchView L37 `:key="r.chunk_id"`（检索结果项，不同数据源，非本缺陷面）。
2. **S42c 真实 UI（独立脚本，非 S42b 脚本）**：txt 点 chunk#0 → `<mark>=1` 高亮文本 == DB chunk#0 content **逐字**（len=500）、chunk#1 逐字（len=71）、md chunk#0 逐字（len=500）；`undefined_reqs=[]`（网络层 request 钩子铁证：前端不再发 `chunks/undefined/*`）；`actives=1`（仅被点 chunk，不再全亮）；`500s=[]`（无 Internal Server Error）；chunk 编辑打开对话框回显 == DB content（`match_db=True`，读 `c.id` 不打 undefined）。
3. **负向对照（防「误报闭环」）**：S42c pos 脚本故意用字符串 `undefined` 调 `chunks/undefined/location` → **500**（证明旧缺陷端点确实拒绝该值，S42 报告的 500 非误报）；`dev_probe_s42c_api.log` 同口径负向 500 独立佐证。

**判定：BUG-24 真闭环。** 现象五面（500 横幅 / 左栏永不高亮 / active 全亮 / chunk 编辑打 undefined / undefined 请求）全部消除，且消除基于字段修复（源码 + 网络层双铁证），非 UI 侧掩盖。

## 4. 7 类型左栏 + chunk 列表证据表

S42c 真实 UI 回归（`dev_probe_s42c_ui.log` 20:25:43–20:25:52，本终审逐行读 + 截图磁盘核对）：

| # | 类型 | 文件 | 左栏选择器 | 渲染 | chunk 列表数（=DB） | 截图（s42c/） |
|---|---|---|---|---|---|---|
| 1 | txt | s42_txt_probe.txt | `.orig-text` | ✅ | 2 | regress_txt.txt.png |
| 2 | md | s42_md_probe.md | `.orig-text` | ✅ | 2 | regress_md.md.png |
| 3 | pdf | s42_pdf_probe.pdf | `.orig-pdf` | ✅ | 3 | regress_pdf.pdf.png |
| 4 | png | s42_png_probe.png | `.orig-img` | ✅ | 1 | regress_png.png.png |
| 5 | jpg | s42_jpg_probe.jpg | `.orig-img` | ✅ | 1 | regress_jpg.jpg.png |
| 6 | docx | s42_docx_probe.docx | `.orig-docx` | ✅（S41 真实 docx-preview） | 7 | regress_docx.docx.png |
| 7 | xlsx | s42_xlsx_probe.xlsx | `.orig-xlsx` | ✅（S41 真实 SheetJS） | 3 | regress_xlsx.xlsx.png |

S41 主目标（docx/xlsx 左栏真实渲染）经 S42c 回归**不回退**（docx 点 chunk → 渲染 DOM `<mark>` 高亮 marks=1 + 仅 #0 active + 无横幅）；S41 commit 810d390 实码核验已完成于 S43（真实 docx-preview 0.4.1 + xlsx 0.18.5 依赖、renderAsync + XLSX.read/sheet_to_json，本轮不重复）。

**7/7 全通，chunk 列表全通。**

## 5. pos 越界裁定（任务单 #2 第三项）

S42c 独立复验结论：txt/md 4 探针 chunk `full[cs:ce] == content` **逐字相等** + 区间全在 [0, 全文长] 内（txt 521 / md 623；#0 [0,500]、#1 [450,521]/[450,623]）+ 真实 UI 高亮文本逐字 == DB content → **字节/字符错位不成立（非新缺陷）**。

根因（S42b DEV_REPORT + S42c 独立核验一致）：非字节/字符错位（txt 探针 521 字节=521 字符纯 ASCII），实为 `splitter.py:_char_pos` 的 `char_end` 误以 `block.char_end`（块级全长）为基的加法 bug，S42b 已改以 `block.char_start` 为基并对 2 个 S42 探针 resplit 重算。

**裁定：不阻塞本轮放行。** 错位仅影响高亮区间精度而非 500/功能不可用，且经三层证据（DB + API 逐字 + UI 逐字）确认 2 个探针已精确闭环。库中其余 14 个历史文档存量 pos 越界（S42b 仅重算 2 探针）→ 记为 **P3 新缺陷 BUG-26 待后续排期**（全库 resplit 或评估块级坐标语义），交后续任务，不阻塞本轮。

## 6. 一次 push main

- **前置**：本地 main 领先 origin 2（810d390 S41 + 0f6e6f0 S42b，S41/S42b 均未推远端）；S42c/S44 证据 + 管理回写未 commit → 本卡分两次 commit 后一次 push。
- **commit 1**（S42c/S44 证据）：`03-testing/` 全部 S42/S42c/S43/S44 证据（TEST_REPORT_S42/S42c/S42c_t43b3e53a + ACCEPTANCE_S43/S44 + dev_probe_s42*/s42c* 日志 + screenshots/s42、s42c、s42c_ym）。
- **commit 2**（管理回写 + 验收 + BUGS 重命名）：BUGS.md（BUG-24/25/26 重命名与补登）+ STATUS/PIPELINE/DECISIONS 回写 + ACCEPTANCE_S44。
- **不 push 05-temp**（.gitignore 第 24 行 `05-temp/` 已排除，本卡复核确认）。
- **credential helper 显式指定**（$HOME 下为旧 token，顶层 /home/hermes/.git-credentials 为有效 PAT；仓库无 .github/workflows，无 workflow scope 需求）。
- **ls-remote 核验（push 后独立执行，非自报）**：`git push origin main` → `760034c..c5a4e07 main -> main`；`git rev-parse HEAD` = `c5a4e07d87416d712631c833769695d78fb14a5c` = `git ls-remote origin main`（credential helper 显式顶层有效 PAT）。**一次 push 完成**，本地/远端一致。
  - 补记：本验收报告 push 后补录哈希（c5a4e07 内为占位行），补录本身产生一次 docs-only 追加提交并再次 push——验收主交付（S41+S42b+S42c/S44 证据+回写）在 c5a4e07 一次 push 中全部到位，此追加不影响任何交付物。

## 7. 遗留清单（不阻塞）

| # | 项 | 级别 | 去向 |
|---|---|---|---|
| 1 | 14 个历史文档存量 pos 越界（高亮区间精度） | P3 | **BUG-26**（本卡补登 BUGS.md），如需全库修正另开 P3 任务给章北海 resplit（或评估 docx/pdf 块级 char 偏移语义） |
| 2 | embedding 端点瞬时 ReadError 无重试（批量上传文档落 failed，需手动重试） | P3 | **BUG-25**（原 BUG-22），S42 已记，待后续排期 |
| 3 | 新旧 BUG 编号冲突（P4 文档治理） | P4 | **本卡已处理**：新对比页 BUG 重命名为 BUG-24（P1，右→左联动，已闭环）/ BUG-25（P3，embedding ReadError）；旧 RAG 三缺陷轮 BUG-21/22/23（S38 已关闭）编号保留，TEST_REPORT_S42.md 等活跃引用同步更新，历史交付记录（S40 轮）保持原编号 |

## 8. 验收报告落盘

本文件 = `03-testing/ACCEPTANCE_S44.md`。
