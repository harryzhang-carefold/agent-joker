# DEV_REPORT_S42b — 修复 BUG-21 对比页右→左联动 txt/md 点 chunk 500 + 切分器 pos 越界

> 章北海（zhangbeihai）| 2026-09-30 | 任务 t_9cefd314（父 t_2e466e41 S42）
> 修复对象：S42 独立复测发现的 P1 真实产品 BUG-21（pre-existing，非 S41 引入）。

## 1. 问题与根因（含任务单未预判的第二缺陷）

### 1.1 缺陷 A（BUG-21 主体，前端字段不匹配）
对比页 `frontend/src/views/rag/CompareView.vue` 全量读 `c.chunk_id`，但右栏 chunk 列表
API（`list_chunks` → `_chunk_dict`）返回字段是 **`id`**（无 `chunk_id`）：
- `c.chunk_id === undefined` → 请求打到 `.../chunks/undefined/location` → **500**
- 前端 `catch` 吞错 → 左栏 txt/md **永不高亮** + 顶部「Internal Server Error」红横幅
- active 态视觉 BUG：`undefined === undefined` → **所有 chunk 都显示 active 蓝边框**
- chunk 编辑（`openEdit`/`updateChunk`）同样读 `c.chunk_id` → 大概率也打 undefined

DB 铁证（`03-testing/dev_probe_s42_api.log`）：
- 正确 id → location 200；`undefined` → 500
- chunks 列表 keys 含 `id`，`chunk_id=None`

### 1.2 缺陷 B（任务单标为「潜在」，实为必须修的越界缺陷）
任务单疑「切分器存字节偏移非字符偏移」。**实测非字节/字符错位**（S42 的 txt 探针 521 字节
= 521 字符，纯 ASCII），真正根因在 `services/shared/joker_shared/rag/splitter.py:_char_pos`：

```python
# 修复前（bug）
pos["char_end"] = int(pos["char_end"] ...) + e   # 以 block.pos.char_end（块级全长）为基
```

`_char_pos(block, s, e)` 的入参语义是「块内起始 s、长度 e」，`char_start` 正确以
`block.char_start` 为基，但 `char_end` 误以 **`block.char_end`（块级全长）** 为基 → 越界：

| 文档 | chunk | content（正确） | 修复前 pos | 修复后 pos |
|---|---|---|---|---|
| txt 521 字符 | #0 | text[0:500] | char_end=**1021** | char_end=**500** |
| txt 521 字符 | #1 | text[450:521](71) | char_end=**592** | char_end=**521** |
| md 623 字符 | #0 | text[0:500] | char_end=**1123** | char_end=**500** |
| md 623 字符 | #1 | text[450:623](173) | char_end=**796** | char_end=**623** |

content 本身一直正确（`chunk0 == text[:500]`、`chunk1 == text[450:]` 已验证），**只有
char_end 越界**。后果：前端 `t.slice(0, 1021)` 用越界区间 → **整篇原文被高亮**（高亮错误，
违反 R06/R09「精确高亮」验收）。docx 用文本匹配高亮不读 char 区间，故 S41 未发现；
txt/md 读 char 区间，故越界缺陷在 BUG-21 字段修复后必暴露——**必须同轮修**，否则
「点 chunk → 左栏精确高亮」无法闭环。

## 2. 修复改动

### 2.1 前端 `frontend/src/views/rag/CompareView.vue`（6 处 `c.chunk_id` → `c.id`）
- 模板 `:key="c.chunk_id"` → `:key="c.id"`、`:data-cid="c.chunk_id"` → `:data-cid="c.id"`
- active 判定 `selectedChunk?.chunk_id === c.chunk_id` → `selectedChunk?.id === c.id`
- `onChunkClick`：`api.getChunkLocation(kbId, docId, c.chunk_id)` → `c.id`
- `onLeftClickSeg`：`chunks.find(c => c.chunk_id === primary)` → `c.id === primary`
  （`primary_chunk_id` 来自 `chunks_by_location`，返回 `str(r[0])` = chunk `id`，同字段）
- `scrollChunkTo`：`[data-cid="${c.chunk_id}"]` → `${c.id}`
- `onEditConfirm`：`api.updateChunk(kbId, docId, editTarget.value.chunk_id, ...)` → `.id`
- 保留 `primary_chunk_id`（响应字段名，非 chunk 数据字段）——`chunks_by_location` 契约如此。
- `SearchView.vue` 的 `r.chunk_id` **不改**：它来自 `/api/rag/search`（`retrieval.py` 返回
  `chunk_id`），与 chunk 列表 API 是不同契约，本来就正确。

### 2.2 后端 `services/shared/joker_shared/rag/splitter.py:_char_pos`（char_end 改以 char_start 为基）
```python
base = int(pos.get("char_start") or 0)
pos["char_start"] = base + s
pos["char_end"]   = base + s + e
```
所有 6 处调用点入参均为 (块内起始 s, 长度 e)，与 char_start 同基；docx 多节块（char_start
非 0）、parent_child 父块聚合、semantic 句子区间、structured_tree 子块均覆盖，单测 5 策略
全过、无越界。

## 3. 数据修复（存量越界 pos 重算）
splitter 修复只影响**新切分**；库中 S42 的 txt/md chunk 仍存越界 pos。经
`POST /api/rag/kbs/{kb}/docs/{doc}/resplit`（复用现有重切分：删旧 chunk + 重建向量）对
`upload-repro-01` 的 `s42_txt_probe.txt` / `s42_md_probe.md` 重算 → pos 修正
（txt 500/521、md 500/623）。**仅重切这 2 个 S42 探针文档**，未动其余 14 个文档
（S41 历史 + 其它类型，用户指定保留）。

## 4. 部署
镜像重建 + 平滑替换（compose project=agent-joker，8080/8000 端口/卷/网络不变，无数据丢失）：
- `agent-joker-api:s38` → **`agent-joker-api:s42b`**（烘焙 splitter 修复；容器实码 grep
  `base = int(pos.get(` 在 `/app/joker_shared/rag/splitter.py:65` 命中）
- `agent-joker-webconsole:s41` → **`agent-joker-webconsole:s42b`**（node22 重建 dist；bundle
  `CompareView-*.js` 内 `chunk_id` 计数 6→1，余 1 处为正确响应字段 `primary_chunk_id`）
- 部署后 `docker ps`：joker-api / joker-webconsole 均 **healthy**；joker-pg/redis/bff 未动。

## 5. 自测证据（三层，防造假）

### 5.1 切分器单元自测（26/26 PASS）
`05-temp/s42b/test_splitter_bug21.py`：导入真实 parser/splitter（仅 stub 重量级依赖），
用 S42 真实 txt/md 探针文件复现：txt chunk0 char_end=500（修复前 1021）、chunk1=521
（修复前 592）；md 500/623（修复前 1123/796）；高亮 slice == content；5 策略全过无越界。

### 5.2 API 层 resplit + location 复验（25/25 PASS）
`05-temp/s42b/resplit_verify.py`：真实 HTTP 经 webconsole:8080→bff→api→pg，acme/admin 登录，
resplit txt/md → ready → 逐 chunk location 接口 pos 全在 [0, 全文长] 内不越界、chunk 含 `id`
字段（`chunk_id=None`）、chunk0 char_end=500 / 末 chunk char_end=全文长、content == 原文 slice。

### 5.3 真实 UI Playwright 自测（26/26 PASS，真实表单登录，零 mock）
`05-temp/s42b/ui_test_bug21.py`（真实表单 acme/admin，仅 /login 入口，站内导航点击，零
in-page fetch/localStorage）：
- txt 点 chunk#0 → 左栏 1 个 `<mark>`、高亮 span **长度=500**（精确，非越界全文）、**仅 1
  个 chunk active**、无 Internal Server Error、全程零 5xx
- txt 点 chunk#1 → 高亮长度=71（精确）
- md 点 chunk#0 → 1 个 `<mark>`、长度=500、仅 1 active、无错误
- docx 点 chunk → 渲染 DOM 有 mark（S41 回归仍正常）、仅 1 active、无错误
- 7 类型左栏渲染回归全 PASS（txt/md/pdf/png/jpg/docx/xlsx）
- 证据：`03-testing/dev_probe_s42b_ui.log` + `03-testing/screenshots/s42b/`（16 张）
- 关键截图独立 vision 复核：`txt_chunk0_hl.png`（黄色高亮 + 仅 #0 active + 无红横幅）、
  `md_chunk0_hl.png`（黄色高亮 + 仅 #0 active + 无红横幅）。

## 6. 已知问题 / 边界
- **BUG-22（P3，非本卡）**：embedding 端点瞬时 ReadError 无自动重试——S42 已记，待后续排期，
  不阻塞本轮。
- md 按纯文本解析不做 markdown 语义切分（S38 既定边界，P3）。
- 本次仅重切 2 个 S42 探针文档；**其余历史文档若存过越界 pos，需各自 resplit 才修正**——
  本轮范围仅 S42 复测数据，未全库重切（如需全库修正请另开任务，注意重切会重算向量）。

## 7. 交测试
交云天明 S42 回归复测：BUG-21 字段修复（无 500/无全 active/高亮）+ pos 越界复验
（txt/md 点 chunk 精确高亮）+ 7 类型回归。测试数据保留在库（用户指定）。

## 变更文件
- `frontend/src/views/rag/CompareView.vue`（6 处字段对齐）
- `services/shared/joker_shared/rag/splitter.py`（_char_pos char_end 基修正）
- `deploy/docker-compose.yml`（api/webconsole 镜像 tag s38/s41 → s42b）
- `05-temp/s42b/`（自测脚本 + 证据，3 份 .py）
- `03-testing/dev_probe_s42b_ui.log` + `03-testing/screenshots/s42b/`（测试证据，非开发产物）
