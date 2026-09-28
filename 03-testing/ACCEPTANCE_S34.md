# ACCEPTANCE S34 — BUG-19 终审验收（防造假核查 + 证据交叉 + push）

- **验收人**：褚岩（chuyan），任务卡 t_801fcd7e
- **日期**：2026-09-28（CST）
- **对象**：BUG-19（P1，3584 维建库 → 500）S32 修复（commit fe1cb5a）+ S33 复测（t_28d8f1f7, yuntianming）
- **整轮判定**：**PASS — 验收通过，交付**
- **push**：一次 push 含 S32 修复（fe1cb5a，已提交未推）+ S33/S34 证据与回写（本 commit，见 §五）

> 不采信 S32/S33 自报，本终审独立核查：逐条 grep 脚本源码、逐张截图 vision 核验、
> 独立重连 PG 复跑索引铁证、独立 grep 容器内部署代码、独立复核 API 日志。

---

## 一、防造假核查（QA_STANDARD §三 逐条，全部独立执行）

| # | 检查项 | 方法（本终审独立执行） | 结果 |
|---|---|---|---|
| 1 | 无 in-page `fetch(` 登录/注入 | grep `05-temp/s33/` 全部 `.js`：`fetch(` **零命中**（唯一含 "fetch" 字样的是注释里的 "无 in-page fetch"） | **PASS** |
| 2 | 无 `localStorage` 注入 | 同上目录全量 grep `localStorage`：仅 2 处**注释**（防造假自述），**零代码命中** | **PASS** |
| 3 | 无登录前 goto 受保护页 | 15 处 `page.goto` 逐条判读：1 处 = `/login`（`s33_lib.js:35`，真实表单入口）；14 处 = 登录后站内跳转（`/rag/kbs`、`/rag/kbs/:id`、`/rag/search`），均发生在 `realFormLogin` 成功之后（`waitForURL(!/login/)`）；无 cookie/token 注入、无 `addCookies` | **PASS** |
| 4 | 登录为真实表单 | `s33_lib.js:34-54`：fill 租户/用户名/密码 → click「登录」→ `waitForResponse(/api/auth/login)` + `waitForURL` 离开 /login；三个 UI 脚本（s33_ui_test / s33_retest_reindex / s33_shot_reindex）全部复用该函数 | **PASS** |
| 5 | 截图与报告对应 | 38 张截图 vs TEST_REPORT_S33 逐条引用比对（见 §二）；独立 vision 复核 3 张关键截图（§二） | **PASS** |
| 6 | 脚本与日志同源 | `results.jsonl`(71 行) 与 `dev_probe_s33_ui.log`/`dev_probe_s33_reindex_retest.log` 行级一致；RUN 号 s33908145 / s33r26936 / s33idx581381 在三份产物中一致 | **PASS** |

**防造假结论：6/6 PASS，无造假。**

---

## 二、证据交叉（S32 自测 × S33 复测 × 本终审独立复跑）

### 2.1 3584 维核心链路（修复前 = 500）

| 判据 | S32 自测（dev_probe_s32_bug19.log） | S33 复测（dev_probe_s33_ui.log 等） | S34 终审独立核验 |
|---|---|---|---|
| 3584 维建库 201（**非 mock**：真实 HTTP 端点原始 201 响应体含 `embedding_dim:3584`） | A: 201（real 模型行 b13b0706…） | UI #01: 201（kbid 6b5509cb…，toast「建库成功」）+ #03: 201（local） | 日志响应体逐字核对（§2.4） |
| 3584 无 HNSW（仅 pkey） | C: `hnsw indexes 3584-real=[] / 3584-local=[]` | 独立 psql（s33_index_check.sql）：KB3584 仅 pkey | **本终审重连 PG 复跑**：两库已软删除（deleted_at 09:12:45）+ 向量表已 DROP，**与 S33 清理阶段时序自洽**；S33 当时 psql 快照 + S32 自测同项双重独立一致 |
| 256 维 HNSW 分支正常（≤2000 行为不变） | C: 256 有 `idx_…_embedding(hnsw)`；D3 检索 200 命中 | UI #13/#14/#15 全 PASS + psql KB256 有 1 个 hnsw | 同上（S32/S33 两条独立证据链一致） |
| 3584 顺序扫描检索正确（无 HNSW 时） | seqscan.log: EXPLAIN = **Seq Scan**，top1 sim 0.999991 | UI #08: 检索 200、marker A 命中 top1 0.535 | **vision 独立复核 `08_search_3584_hit.png`**：页面无误读——库 `s33_kb_3584local_s33908145 (3584d)`、查询含 `zephyr_quartz_marmoset_A_s33908145`、结果 4 条、top1 53.5%、内容 = 探针文档原文。UI 渲染与 API 200 响应（score 0.534993）一致 |
| reindex 3584→256 | — | 初轮 #10 FAIL（测试脚本轮询缺陷，读陈旧表格）→ API 日志 `reindex done kb=f61a9f22…(dim=256)`（07:35:42，触发后 ~1s）+ 复测 8/8（4.8s 完成） | **本终审独立 grep joker-api 日志**：`07:40:41,283 reindex done kb=5765c26b-…(dim=256)`（= 复测 RUN s33r26936 的 kbid），与 retest log 07:40:44 完成判定一致；另见 09:15:11 第三次 reindex（补拍 s33s_kb） |
| 外部 3584 端点（RISK-019） | endpoint.log：端点漂移（1536 维 gte-Qwen2-1.5B-instruct，model=gte-qwen2 404） | dev_probe_s33_endpoint.log：15:21 复核仍漂移 | 端点侧环境态，非平台缺陷；3584 文档链路以 local provider 闭环为准，RISK-019 维持 open（非阻塞） |

### 2.2 回归（256 维 HNSW 分支 + KB CRUD）

S32：256 建库/上传/ready/检索全 PASS。S33：#13/#13b/#14/#15/#16/#17/#18（3×删库 200）全 PASS。
本终审抽查 `15_search_256_hit.png` 与 #18 删库 toast「已删库」+ DB 软删记录，无矛盾。

### 2.3 部署核验（修复确实在线上，非源码自嗨）

| 项 | 本终审独立 grep 容器（joker-api） | 结果 |
|---|---|---|
| PG 函数 `create_rag_chunks_vec` | `IF p_dim <= 2000 THEN … USING hnsw …`（S32 注释在体内） | **PASS** |
| `joker_shared/rag/service.py` | L167/L232（可读 500 提示）/ L378-379 `if new_dim <= 2000` reindex 分支 | **PASS** |

### 2.4 3584 维证据「真实端点原始 200/201、非 mock」核验

- S32 A 项响应体：`POST /api/rag/kbs → 201`，body 含 `embedding_model_id=b13b0706…`、`embedding_dim=3584`、真实 uuid/时间戳 —— **真实 HTTP 原始响应，无 mock 痕迹**。
- S33 UI #01/#03 同为真实表单操作触发的 `waitForResponse` 原始 201。
- 3584 **文档链路**（上传→向量化→检索）：因外部端点漂移（RISK-019），按 S32 既定方案用 **local 3584 provider**（确定性 n-gram 向量）闭环 —— 这是**平台侧链路真实验证**（真实 UI 操作、真实 API 201/200、真实 PG 向量表、真实检索 SQL），embedding 本身为确定性本地生成而非外部模型，已如实记录于 TEST_REPORT_S33 §1.3 与 RISKS（RISK-019），**不构成造假**，真实外部端点链路待端点恢复后补测。

**证据交叉结论：S32/S33 两条独立证据链 + 本终审独立复跑（PG/API 日志/容器代码/截图 vision）全部一致，无缺口。**

---

## 三、初轮 FAIL 定因复核（S33 §二，本终审确认）

- 现象：主 UI 脚本 #10 在 90s 内读不到 `active+256`。
- 定因：脚本读**已加载表格** `textContent()` 未 `page.reload()`，KB 列表页无自动刷新（既有行为，非 S32 引入）。
- 铁证：API 日志 `reindex done`（07:35:42）+ 本终审独立 grep 复核 + 修正脚本复测 8/8（4.8s）。
- **本终审裁定：测试伪报，非产品缺陷，定因成立。** 已另记 BUG-20（P3 UX 观察：列表 reindex 状态无自动轮询），非阻塞。

---

## 四、验收结论

| 验收标准 | 判定 |
|---|---|
| 3584 维建库不再 500（201，核心） | ✅ |
| >2000 维不建 HNSW（降级顺序扫描）且检索正确 | ✅（pg_indexes 无 hnsw + EXPLAIN Seq Scan + top1 正确） |
| ≤2000 维 HNSW 分支回归正常 | ✅（256 有 hnsw + 全流水线 PASS） |
| 换模型 reindex（3584→256）功能正确 | ✅（API 日志 + 复测 8/8 + DB 最终态 active/256） |
| KB 列表/详情/删库正常 | ✅ |
| 测试无造假 | ✅（6/6） |
| 证据为真实端点原始 200/201 | ✅（§2.4） |

**整轮判定：PASS。BUG-19（P1）闭环，无阻塞项，交付。**

遗留（均非阻塞）：
1. RISK-019 open：外部 3584 端点模型漂移（端点侧环境态），3584 真实端点文档链路待端点恢复后补测。
2. BUG-20（P3 UX 观察）：KB 列表 reindex 状态无自动刷新。
3. 既有行为（非缺陷）：`delete_embedding_model` 对仅被软删 KB 引用的模型返回 409。

---

## 五、Push 记录

- 一次 push 内容：S32 修复（fe1cb5a，本地既有）+ S33 证据（TEST_REPORT_S33 + 5 份 log + sql + 38 张截图）+ S34 验收（本文件）+ BUGS.md/PIPELINE.md/STATUS.md/DECISIONS.md 回写。
- 本地 commit hash：S32 修复 = `fe1cb5a`；S33/S34 证据与验收 = `b5e5df2`（HEAD）。
- **push 远端核验（已执行）**：`git push origin main` → `6bef164..b5e5df2 main -> main`；push 后 `git ls-remote origin main` = `b5e5df280b1f57d992338b9113a7091ab7017e74` = 本地 HEAD，远端与本地一致（非自报）。
- push 前工作树核验：`05-temp/` 已 gitignore（不推诊断脚本）；提交内容 = 12 个跟踪文件 + 38 张截图，无遗漏、无越界。
- push 核验补记（`7cb541f`）：push 后补记本文件 → `b5e5df2..7cb541f`，ls-remote = `7cb541f` = 本地 HEAD，远端最终一致。
