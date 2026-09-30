# TEST_REPORT_S42c — BUG-24 修复 + 切分器 pos 越界 独立回归复测

> 云天明（yuntianming）| 2026-09-30 | 任务 t_109b04a0
> 范围：章北海 S42b 修复（本地 commit `0f6e6f0`，未 push，待终审）的**独立复测**（不采信自报，防造假）。
> 环境：本地 compose（webconsole:**s42b** / api:**s42b** / bff:s32 / pg / redis 全 healthy），宿主 8080/8000 不变。
> 库：1536 维库 `upload-repro-01`（16 文档 = 7 S42 + 9 S41，测试数据保留未删）。

## 1. 测试结论

**整轮判定：PASS（BUG-24 字段修复 + pos 越界复验 + chunk 编辑 + docx 回归 + 7 类型左栏渲染 全通过；零 5xx；交 S43 终审）**

| 复测项（任务单口径） | 结果 |
|---|---|
| 真实表单登录 acme/admin（仅 /login 入口，零 in-page fetch/localStorage，零 mock） | ✅ |
| BUG-24 字段修复：txt 点 chunk#0 → 左栏精确高亮（黄底 `<mark>`） | ✅ 高亮 span 长度=500（chunk0 原文长度） |
| txt 点 chunk#1 → 高亮 span 长度=71（精确非整篇） | ✅ |
| 仅被点 chunk 显示 active（非全 active） | ✅ active=1 |
| 无「Internal Server Error」横幅 | ✅ |
| pos 越界复验：md 点 chunk#0 → 高亮长度=500（修复前 1123 越界整篇） | ✅ |
| location API 返回 pos 区间不越界（txt char_end≤521、md≤623） | ✅ DB+API 双层核验 |
| 前端不再发送 `chunks/undefined` 请求（字段修复生效） | ✅ undef_reqs=[] |
| chunk 编辑回归：编辑→保存并重嵌入→成功（不再打 undefined） | ✅ |
| docx 点 chunk 高亮仍正常（S41 最佳努力文本匹配，不回退） | ✅ marks≥1 + 仅 #0 active |
| 回归：7 类型左栏渲染不坏（txt/md/pdf/png/jpg/docx/xlsx） | ✅ 7/7 |
| 全程零 5xx（浏览器侧响应） | ✅ 5xx=[] |

## 2. 三层独立证据（均独立实现，未 import 章北海脚本）

### 层 1：容器实码 + DB 终态（防「镜像未烘焙/数据未重算」造假）
- **容器实码**：`docker exec joker-api` 内 `splitter.py` L65 `base = int(pos.get("char_start") or 0)` → `char_start=base+s`、`char_end=base+s+e`（修复在运行的镜像内，非仅本地 git）。
- **前端 bundle**：`joker-webconsole` 内 `CompareView-DEUfTwhn.js` 中 `chunk_id` 计数=**1**（唯一 1 处为正确的响应字段 `primary_chunk_id`）→ 修复前 6 处 `c.chunk_id` 已全部改为 `c.id`。
- **DB 终态**（`rag_chunks.pos` jsonb，4 探针 chunk）：
  | 文档 | chunk | char_start | char_end | content_len | 越界? |
  |---|---|---|---|---|---|
  | s42_txt_probe.txt | #0 | 0 | **500** | 500 | 否（修复前 1021） |
  | s42_txt_probe.txt | #1 | 450 | **521** | 71 | 否（修复前 592） |
  | s42_md_probe.md | #0 | 0 | **500** | 500 | 否（修复前 1123） |
  | s42_md_probe.md | #1 | 450 | **623** | 173 | 否（修复前 796） |
  区间与 content 长度完全匹配，**不再越界**（txt 末=521 全文长、md 末=623 全文长）。

### 层 2：API 层（宿主 urllib 真实 HTTP，真实表单登录，零 mock）
脚本 `api_verify_s42c.py`，日志 `03-testing/dev_probe_s42c_api.log`（10 PASS）：
- 真实登录 200；1536 库定位 dim=1536；txt/md 探针 ready。
- chunks 列表含 `id` 字段、`chunk_id=None`（前端 `c.id` 可取）。
- `/file` 原文 txt=521 字符、md=623 字符。
- **逐 chunk location API：pos 全在 [0,全文长] 内不越界 + `content == 原文[cs:ce]` 逐字匹配**（txt #0[0,500]/#1[450,521]；md #0[0,500]/#1[450,623]）。
- **受控负向测试**：故意用字符串 `"undefined"` 调 `chunks/undefined/location` → **500**（验证端点确实拒绝该值；修复后前端不再发送，见层 3 `undef_reqs=[]`）。

### 层 3：真实 UI（Playwright 真实表单登录 acme/admin，仅 /login 入口，零 in-page fetch/localStorage，零 mock）
脚本 `ui_verify_s42c.py`（独立实现），日志 `03-testing/dev_probe_s42c_ui_ym.log`（**27 PASS / 0 FAIL**），截图 `03-testing/screenshots/s42c_ym/`（20 张）：
- txt 点 chunk#0 → `<mark>=1` + **高亮 span 长度=500**（精确非整篇）+ 仅 1 active + 无错误横幅。
- txt 点 chunk#1 → 高亮 span 长度=71（精确）+ 仅 1 active。
- md 点 chunk#0 → 高亮 span 长度=500（修复前 1123 越界整篇）+ 区间非整篇（500<623）+ 仅 1 active。
- chunk 编辑：txt chunk#0 打开编辑框（回显=DB content，不打 undefined）→ 追加标记 →「保存并重嵌入」成功 + 右栏显示「已编辑」tag（edited_at 留痕）→ 恢复原文。
- docx 点 chunk#0 → 渲染 DOM 有 `<mark>` 高亮（S41 最佳努力匹配不回退）+ 仅 1 active + 无横幅。
- 7 类型左栏渲染回归全 PASS（txt/md/pdf/png/jpg/docx/xlsx）。
- **全程零 5xx（浏览器侧）+ 前端不再发送 `chunks/undefined` 请求**。

### 关键截图独立 vision 复核（非自报采信）
- `03_txt_chunk0_hl.png`：黄色高亮**仅覆盖前 500/521 字符**（最后一段 "Paragraph three: end of file." 仅 "Paragraph" 一词高亮，其余未高亮 → 非整篇）；右栏**仅 #0 蓝色 active 边框**；**无**顶部红色 Internal Server Error 横幅。
- `06_md_chunk0_hl.png`：高亮约 500/623，非整篇全高亮；仅 #0 active；无横幅。
- `11_docx_chunk0_hl.png`：渲染 Word 文档（标题/表格）首段黄色高亮；仅 #0 active；无横幅。

## 3. 附注：存量 pos 越界（历史文档，非本轮范围，如实上报）

独立全库核查发现：**除 2 个 S42 探针外，其他历史文档的 chunk pos 仍存在越界/长度不一致**（`char_end - char_start ≠ content_len`），因 S42b 仅对 2 个 S42 探针做了 resplit 重算，其余 14 文档未重算（任务单已预见此情况）。明细：
- `hello.txt` #0 [0,122] 但 content=61（越界×2，历史文档）
- `t.md` #0 [0,28] content=14；`policy.pdf` #0 [0,58] content=29
- `s41docx_*` / `s42_docx_probe.docx` 多 chunk（docx 块级坐标，ce−cs≠clen）
- `s42_pdf_probe.pdf` #0 [0,488] content=244 等；png/jpg 单块页级坐标
- 无 `inverted`（char_end<char_start）倒挂。

**影响**：这些历史文档若点 chunk 联动高亮，可能因越界区间高亮错误（与 BUG-24 修复前的同类问题）；但**本轮复测对象（2 个 S42 探针 txt/md）已完全修复**。docx/pdf/png/jpg/xlsx 的高亮走 DOM 文本流匹配（txt/md 之外不依赖 char 区间），故本轮回归 7 类型左栏渲染不坏、docx 点 chunk 高亮正常。

**建议（另开任务，非本轮阻塞）**：若需全库 pos 修正，需对全部历史文档逐个 `POST .../resplit` 重算 pos（章北海执行），或评估 docx/pdf 等块级坐标的 char 偏移语义是否本就应为「块内相对偏移」（需与解析器对齐）。**本轮不因历史文档存量问题判 FAIL**（任务单明确：存量越界仅 2 个 S42 文档已重算，其余如需全库修正另开任务给章北海）。

## 4. 并发冲突记录（hotspot，如实上报）

复测期间检测到**同一任务 t_109b04a0 存在第二方并发 worker**：约 20:25:25–20:25:53（CST）另一进程写入了 `03-testing/dev_probe_s42c_ui.log`（含我脚本中不存在的检查项如「editTarget 读 c.id」「ui_len==db_len」）并覆盖了 `screenshots/s42c/` 的 `00_login_*`/`regress_*` 截图。为保证我的交付物独立可验证、不被并发污染，我将独立 UI 复测定向到**不冲突路径**：
- 日志：`03-testing/dev_probe_s42c_ui_ym.log`（27 PASS，时间戳 20:29:xx，全部我的独立运行）
- 截图：`03-testing/screenshots/s42c_ym/`（20 张，时间戳 20:29:xx）
- API 日志：`03-testing/dev_probe_s42c_api.log`（10 PASS）
该并发进程现已退出（`ps` 无 playwright 进程），DB 终态干净（无 probe 串残留，4 探针 chunk 内容/pos 正确）。**本报告所有结论均基于 `_ym` 独立路径证据 + 容器实码 + DB 终态三层交叉**，不受并发进程影响。

## 5. 防造假自查（硬规则遵守）
- **登录真表单**：`page.goto(BASE+'/login')` 唯一入口 + `page.fill` 填 tenant/username/password + 点「登录」，`wait_for_url` 校验离开 /login。仅 /login 入口，其余为站内点击导航（RAG→知识库→文档→对比）。
- **禁止 in-page fetch / localStorage / goto 受保护页**：UI 脚本**零** `page.evaluate(fetch)`、**零** localStorage 注入、**零** goto 受保护页。判定结论基于真实 UI 点击 + 宿主 urllib 原始 API 响应 + 容器实码 + DB psql 四层证据。
- **API 取证走宿主 urllib + 真实登录 token**（非 in-page、非注入）。
- **截图独立 vision 复核**：3 张关键截图（txt/md/docx chunk 高亮）逐项确认「黄色高亮精确区间 + 仅 #0 active + 无红横幅」。
- **不采信章北海自报**：未 import `05-temp/s42b/ui_test_bug21.py`，全部独立实现；容器实码 + DB 终态 + bundle 字段计数交叉核验修复真实落地。

## 6. 交付物
| 文件 | 说明 |
|---|---|
| `03-testing/TEST_REPORT_S42c.md` | 本报告 |
| `03-testing/dev_probe_s42c_api.log` | API 层 10 PASS（宿主 urllib 真实 HTTP） |
| `03-testing/dev_probe_s42c_ui_ym.log` | 真实 UI 27 PASS（Playwright 真实表单，独立路径） |
| `03-testing/screenshots/s42c_ym/` | 20 张截图（txt/md/docx 高亮 + 编辑 + 7 类型回归） |
| `03-testing/BUGS.md` | BUG-24 状态更新为「已修（S42b）+ S42c 独立复测 PASS」 |
| 独立脚本（scratch） | `api_verify_s42c.py` / `ui_verify_s42c.py` / `restore_chunk0.py`（可复跑） |

## 7. 交接
- **S42c 整轮判定：PASS**（BUG-24 字段修复 + pos 越界复验 + chunk 编辑 + docx 回归 + 7 类型左栏渲染全通过，零 5xx，证据三层交叉 + vision 复核）。
- **交褚岩 S43 终审**：commit `0f6e6f0`（本地未 push）可进入终审 push 流程；S42 的 P1（BUG-24）闭环。
- **另开任务给章北海（非本轮阻塞，P3）**：全库历史文档存量 pos 越界需逐个 resplit 重算（或评估 docx/pdf 块级 char 偏移语义），详见第 3 节。
- **BUG-25（P3）**：embedding 瞬时 ReadError 无重试，非本轮范围，S42 已记。
- **测试数据保留**：upload-repro-01 16 文档全保留未删（用户指定）。
