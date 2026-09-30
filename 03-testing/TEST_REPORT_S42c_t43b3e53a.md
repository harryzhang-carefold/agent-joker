# TEST_REPORT_S42c（t_43b3e53a）— BUG-24 修复独立回归复测（第二份独立复测）

> 云天明（yuntianming）| 2026-09-30 | 任务 **t_43b3e53a**（S44 放行门槛复测卡）
> **独立复测，不采信 S42b 自报**，也不复用/采信 S42b 脚本或同一任务另一张并行卡 t_109b04a0 的结论。
> 环境：本地 compose（webconsole:**s42b** / api:**s42b** / bff:s32 / pg / redis 全 healthy），宿主 8080→bff→api→pg。
> 库：1536 维库 `upload-repro-01`（16 文档 = 7 S42 + 9 S41，测试数据保留未删，用户指定）。
> 登录：真实表单 acme / admin / 123456，**仅** `page.goto(BASE + '/login')` 唯一入口，其余为站内真实点击导航（RAG→知识库→文档→对比）。

## 0. 与并行卡 t_109b04a0 的关系（如实说明，避免交付物混淆）

本任务（BUG-24 修复回归复测）存在**两张并行卡**，同分配给 yuntianming：
- **t_109b04a0**（S42b 章北海创建）：已产出 `03-testing/TEST_REPORT_S42c.md` + 更新 BUGS.md（BUG-24 关闭）。
- **t_43b3e53a**（本卡，S43 褚岩创建的 S44 放行门槛卡）：本卡为**独立第二份复测**。

为不覆盖 t_109b04a0 的交付物，本卡报告落**独立路径**（本报告），UI 截图落 `03-testing/screenshots/s42c/`（非 `_ym` 后缀），API/pos 取证日志落 `dev_probe_s42c_pos.log`（本卡独立生成，与 t_109b04a0 的 `dev_probe_s42c_ui_ym.log`/`api.log` 相互独立）。**两份复测结论一致（均 PASS）**，互为交叉验证。本卡**未修改** `TEST_REPORT_S42c.md` 与 `BUGS.md`（已由 t_109b04a0 正确闭环，避免重复写入造成冲突）。

## 1. 测试结论

**整轮判定：PASS（BUG-24 闭环 + pos 越界未成新缺陷 + chunk 编辑同源 + docx 回归 + 7 类型回归全通过；零 5xx）。满足 S44 放行门槛（BUG-24 闭环 + 7 类型回归不坏）。**

| 复测项（任务单口径） | 结果 | 证据 |
|---|---|---|
| 真实表单登录 acme/admin（仅 /login 入口，零 in-page fetch/localStorage/mock） | ✅ | `dev_probe_s42c_ui.log` 20:25:27 |
| **BUG-24 主修复**：txt 点 chunk#0 → 左栏精确高亮（黄底 `<mark>`） | ✅ `<mark>=1`，高亮文本 == DB chunk#0 content **逐字**（len=500） | UI + DB 逐字比对 |
| txt 点 chunk#1 → 精确高亮 | ✅ 高亮文本 == DB chunk#1 content 逐字（len=71） | UI |
| **前端不再发 `chunks/undefined/*` 请求**（字段修复生效，铁证） | ✅ `undefined_reqs=[]`（网络层监听） | UI request 钩子 |
| 仅被点 chunk 显示 active（不再全亮） | ✅ `actives=1` | UI |
| 无「Internal Server Error」红横幅 | ✅ `500s=[]` | UI |
| md 点 chunk#0 → 精确高亮（逐字 == DB，len=500）+ 仅 #0 active + 无横幅 | ✅ | UI + vision 复核 |
| **pos 越界复验**：txt/md 全部 chunk `full[cs:ce] == content` 逐字 + 区间在 [0,全文长] 内 | ✅ **未成新缺陷**（详见 §3） | `dev_probe_s42c_pos.log` |
| **chunk 编辑同源**：打开编辑框读 `c.id`，回显 == DB content（不打 undefined） | ✅ `val_len=500 match_db=True` | UI |
| **docx 回归**：点 chunk → 渲染 DOM 高亮（最佳努力，不调 location API）+ 仅 #0 active | ✅ `marks=1` | UI |
| **7 类型回归不坏**：txt/md/pdf/png/jpg/docx/xlsx 左栏渲染 + 右栏 chunk 列表 | ✅ 7/7（chunk 数 2/2/3/1/1/7/3 全对） | UI |
| 全程零 5xx 服务器错误 | ✅ `5xx=[]` | UI response 钩子 |

**判定依据**：BUG-24（P1，对比页右→左联动 txt/md 点 chunk 500 / 左栏永不高亮 / 顶部红横幅 / active 全亮 / chunk 编辑同源）经**独立三层证据**（真实 UI 点击 + 宿主原始 API 响应 + DB psql + 容器实码 + 前端 bundle 字段计数）**闭环确认**；pos 越界经逐字比对**未成新缺陷**；7 类型回归不坏。满足 S44 放行门槛。

## 2. 独立三层证据（均本卡独立实现，未 import S42b / 未 import 并行卡脚本）

### 层 1：部署态 + 容器实码 + DB 终态（防「镜像未烘焙 / 数据未重算 / 源码改了但没部署」造假）
- **部署镜像**（`docker inspect`）：`joker-api` = `agent-joker-api:s42b`、`joker-webconsole` = `agent-joker-webconsole:s42b`（两容器均 healthy）——非 S42b 自报，本卡独立读取。
- **API 容器实码**（`docker exec joker-api`）：`splitter.py` L65 `base = int(pos.get("char_start") or 0)` → `char_start=base+s`、`char_end=base+s+e`（修复**在运行的镜像内**，非仅本地 git）。
- **前端 bundle 字段计数**（`joker-webconsole` 内 `CompareView-DEUfTwhn.js`）：`chunk_id` 计数 = **1**（唯一 1 处为正确的响应字段 `primary_chunk_id`）→ 修复前 6 处 `c.chunk_id` 已全部改 `c.id`。源码 `CompareView.vue` 独立 grep：`:key="c.id"`/`:data-cid="c.id"`/`selectedChunk?.id===c.id`/`getChunkLocation(...,c.id)`/`find(c=>c.id===primary)`/`updateChunk(...,editTarget.value.id)` 全部 `c.id`，**零 `c.chunk_id`**（唯一保留 `primary_chunk_id` 为 `/chunks_by_location` 契约响应字段）。
- **DB 终态**（`psql rag_chunks.pos`，4 个 S42 探针 chunk）：

  | 文档 | chunk | char_start | char_end | content_len | span=ce−cs | 越界? |
  |---|---|---|---|---|---|---|
  | s42_txt_probe.txt (521 字符) | #0 | 0 | **500** | 500 | 500 | 否（S42 修复前 1021） |
  | s42_txt_probe.txt | #1 | 450 | **521** | 71 | 71 | 否（S42 修复前 592） |
  | s42_md_probe.md (623 字符) | #0 | 0 | **500** | 500 | 500 | 否（S42 修复前 1123） |
  | s42_md_probe.md | #1 | 450 | **623** | 173 | 173 | 否（S42 修复前 796） |

  `span == content_len` 全部成立，区间全部落在 [0, 全文长] 内。

### 层 2：API 层（宿主 urllib + 真实登录 token，非 in-page；本卡独立脚本 `05-temp/s42c/s42c_pos_evidence.py`）
日志 `03-testing/dev_probe_s42c_pos.log`（本卡独立生成）：
- 真实登录 200（token_len=3927）。
- `/file` 原文：txt=**521** 字符、md=**623** 字符。
- chunks 列表含 `id` 字段、`chunk_id=None`（前端 `c.id` 可取）。
- **逐 chunk location API**（响应结构 `{pos:{char_start,char_end}, chunk_id}`）：
  - txt #0 `pos.cs=0 pos.ce=500` in_bounds=True **`full[0:500] == content`:True**
  - txt #1 `pos.cs=450 pos.ce=521` in_bounds=True **`full[450:521] == content`:True**
  - md #0 `pos.cs=0 pos.ce=500` in_bounds=True **`full[0:500] == content`:True**
  - md #1 `pos.cs=450 pos.ce=623` in_bounds=True **`full[450:623] == content`:True**
  - 结论：**txt/md 精确高亮区间 PASS（逐字）**。
- **受控负向对照**：故意用字符串 `undefined` 调 `chunks/undefined/location` → **500**（证明 S42 报告的旧缺陷端点确实会拒绝该值；修复后前端不再发送，见层 3 `undefined_reqs=[]`）。

### 层 3：真实 UI（Playwright 真实表单 acme/admin，仅 /login 入口，零 in-page fetch/localStorage/mock；本卡独立脚本 `05-temp/s42c/s42c_ui_test.py`）
日志 `03-testing/dev_probe_s42c_ui.log`（**30 PASS / 0 FAIL**），截图 `03-testing/screenshots/s42c/`（16 张，非 `_ym` 后缀，本卡独立生成）：
- **网络层铁证**：注册 `request` 钩子，点 txt/md chunk#0/#1 后监听所有请求 URL，**`undefined_reqs=[]`**（前端不再发 `chunks/undefined/*`）——比「只看截图无红横幅」更硬的证据。
- **逐字比对**（比 S42b 只量「长度」更严）：`.orig-text mark.hl` 的 `inner_text` 与 **DB chunk content 逐字相等**（txt#0=500 / txt#1=71 / md#0=500，均 `match_db`/逐字相等），非仅长度相等——直接证伪「高亮区间错位/字节字符错」假说。
- **active 唯一**：`.chunk-item.active` = 1（非全亮）。
- **无 5xx**：`response` 钩子全程 `5xx=[]`。
- **chunk 编辑同源**：点「编辑」打开对话框，`textarea` 回显 == DB chunk#0 content（`val_len=500 match_db=True`），**不打 undefined、无 500**；**仅打开验证后取消，不保存**（保留测试数据）。
- **docx 回归**：点 chunk → 渲染 DOM 有 `<mark>` 高亮（走 `highlightQuery` 文本流匹配，不调 location API）+ 仅 #0 active + 无横幅。
- **7 类型回归**：txt/md/pdf/png/jpg/docx/xlsx 左栏渲染（`.orig-text`/`.orig-pdf`/`.orig-img`/`.orig-docx`/`.orig-xlsx`）+ 右栏 chunk 列表数（2/2/3/1/1/7/3）全对。

### 关键截图独立 vision 复核（非自报采信，本卡 vision_analyze）
- `03-testing/screenshots/s42c/txt_chunk0_hl.png`：左栏**黄色 `<mark>` 高亮**（覆盖标题/分隔线/首段，非整篇）；右栏**仅 #0 蓝色 active 边框**（#1 灰边，范围标 `[0,500)`/`[450,521)`）；**无**顶部红色 Internal Server Error 横幅。
- `03-testing/screenshots/s42c/md_chunk0_hl.png`：左栏**黄色高亮**（约 500/623，非整篇全高亮）；**仅 #0 active**；**无横幅**。

## 3. pos 越界复验结论（任务单 #4，独立判定）

S42 曾疑「txt 521 字符但 `pos.char_end=1021`、md 623 字符 `char_end=1123`（越界），疑切分器存字节偏移非字符偏移」。**本卡独立复验结论：该潜在缺陷【未成新缺陷】，不新增 BUG 条目。**

依据（三层一致）：
1. **DB**：4 个 S42 探针 chunk `char_end` 全部 ≤ 全文长（txt 521 / md 623），`span==content_len`。
2. **API**：`full[cs:ce] == content` 逐字相等（§2 层 2），即**高亮区间精确**、无字节/字符错位。
3. **真实 UI**：高亮 `<mark>` 文本与 DB content 逐字相等（§2 层 3），用户所见高亮即 chunk 原文。

根因澄清（与 S42b DEV_REPORT 一致，本卡独立核验源码确认）：S42 的越界**不是字节/字符错位**（txt 探针 521 字节 = 521 字符纯 ASCII），而是 `splitter.py:_char_pos` 的 `char_end` 误以 `block.char_end`（块级全长）为基的加法 bug；S42b 已改为以 `block.char_start` 为基，并对 2 个 S42 探针 resplit 重算存量 pos。**修复后 txt/md 高亮精确，BUG-24 与 pos 越界均已闭环。**

> 说明：S42b 已对 2 个 S42 探针 resplit；**库中其余历史文档（14 个）存量 pos 仍可能越界**（S42b 未全库重算，任务单已预见）。此为**存量数据问题**，非本轮复测对象（2 个 S42 探针）范围，且**不影响 BUG-24 闭环判定**（本轮 txt/md 探针已精确）。是否需全库 resplit 由 S44 终审裁定（并行卡 t_109b04a0 已在其报告 §3 建议另开 P3 任务给章北海）。本卡不据此判 FAIL。

## 4. 数据完整性核验（防测试破坏保留数据）
- 测试**前后**（含并发编辑 save+restore 周期后）4 个 S42 探针 chunk **content 逐字不变**（`sha256` 不变：txt#0 `1cbdb7d2…`、txt#1 `59582d4b…`、md#0 `d939b64b…`、md#1 `aa127460…`），原文 marker（`s42txt_/s42md_meridian_cobalt_marker_7f2a`）仍在。
- 本卡 UI 脚本 chunk 编辑**仅打开对话框验证回显后取消，未点保存**（保留测试数据，用户指定）。
- **如实记录**：复测窗口内（20:22–20:29 CST）检测到**并行卡 t_109b04a0 的 worker** 对 txt chunk#0 做了「保存+恢复」编辑周期（api 日志 5 次 `PUT /chunks/9c96525e…` 200 OK + re-embedded，截图 `s42c_ym/08_edit_saved`/`09_edit_restored`），致该 chunk `edited_at` 留痕（`已编辑` tag）。该 PUT **target 为真实 chunk id（非 undefined）且 200 + re-embedded**，**独立佐证本卡范围 #2（chunk 编辑读 c.id 正常）**；最终 content 逐字不变（§4），无数据损坏。

## 5. 防造假自查（硬规则遵守）
- **真实表单登录**：`page.goto(BASE + '/login')` 唯一入口 + `page.fill` tenant/username/password + 点「登录」+ `wait_for_url` 校验离开 /login。仅 /login 入口，其余站内真实点击导航。
- **零 in-page fetch / 零 localStorage 注入 / 零 goto 受保护页 / 零 mock**：本卡 UI 脚本（`s42c_ui_test.py`）仅 `chromium` + `page.goto('/login')` + 站内点击；API 取证走**宿主 urllib + 真实登录 token**（非 in-page、非注入）。
- **判定只基于真实 UI 点击 + 宿主原始 API 响应 + DB psql + 容器实码 + bundle 字段计数 + 网络层请求监听 + 截图独立 vision 复核**（比 S42b 多「逐字 content 比对 + 网络层 undefined 监听」两层硬度）。
- **不采信自报**：未 import S42b `ui_test_bug21.py`、未 import 并行卡 t_109b04a0 脚本，全部本卡独立实现；容器实码 + DB 终态 + bundle 计数交叉核验修复真实落地。

## 6. 交付物
| 文件 | 说明 |
|---|---|
| `03-testing/TEST_REPORT_S42c_t43b3e53a.md` | 本卡报告（独立于 t_109b04a0 的 `TEST_REPORT_S42c.md`） |
| `03-testing/dev_probe_s42c_pos.log` | 本卡 API 层 pos 越界逐字复验（txt/md 精确区间 PASS + undefined 500 对照） |
| `03-testing/dev_probe_s42c_ui.log` | 本卡真实 UI 30 PASS（Playwright 真实表单，非 `_ym`） |
| `03-testing/screenshots/s42c/`（非 `_ym` 后缀 16 张） | 本卡 UI 截图（txt/md/docx 高亮 + 编辑对话框 + 7 类型回归） |
| `05-temp/s42c/`（scratch） | 本卡独立脚本 `s42c_ui_test.py`/`s42c_pos_evidence.py`/`s42c_diag_edit.py`/`verify_no_change.py`（可复跑） |

> 注：`TEST_REPORT_S42c.md`、`BUGS.md`（BUG-24 闭环状态）已由并行卡 t_109b04a0 产出并更新，本卡**未重复写入**，避免文件冲突；两份报告结论一致（PASS），互为独立交叉验证。

## 7. 交接（交 S44 t_e98d3cab，褚岩终审+push）
- **S42c 整轮判定：PASS**。BUG-24（P1）闭环；pos 越界**未成新缺陷**（精确高亮已证实）；7 类型回归不坏；零 5xx。满足 S44 放行门槛。
- **放行条件达成**（BUG-24 闭环 + 7 类型回归不坏）→ 可放行 S44 push。
- **并行卡说明**：本卡（t_43b3e53a）与 t_109b04a0 为同一复测任务的两张卡，结论一致 PASS；建议 S44 终审时两份报告交叉参照，交付物路径已按卡区分（避免覆盖）。
- **遗留（非本轮阻塞，交 S44 裁定）**：
  1. 库中其余 14 个历史文档存量 pos 越界（S42b 仅重算 2 个 S42 探针）→ 如需全库修正，另开 P3 任务给章北海 resplit（或评估 docx/pdf 块级 char 偏移语义）。
  2. BUG-25（P3）embedding 瞬时 ReadError 无重试，S42 已记，非本轮范围。
- **测试数据保留**：upload-repro-01 16 文档全保留未删（用户指定）；chunk content 逐字未变（§4）。
