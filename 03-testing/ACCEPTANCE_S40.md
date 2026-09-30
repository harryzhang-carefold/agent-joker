# ACCEPTANCE S40 — agent-joker RAG 三缺陷轮终审验收（S38 修复 + S39 复测）

- **验收人**：褚岩（chuyan），任务卡 t_a48b7d7f
- **日期**：2026-09-30（CST）
- **范围**：S38（t_bda82f31，zhangbeihai，commit ac49755）+ S39（t_d5ad526f，yuntianming，TEST_REPORT_S39）
- **原则**：不采信 S38/S39 自报，全部独立核查（防造假 grep + 原始 API 响应逐字读 + 容器实码 + 容器日志 + psql 终态 + 关键截图独立 vision 复核）
- **判定**：**PASS** — 三缺陷修复全部独立核验成立，防造假核查 6/6 通过，无产品代码缺陷，交付放行 + 一次 push

## 一、整轮判定

| 缺陷 | S38 修复 | S39 复测 | 本终审独立核验 | 判定 |
|---|---|---|---|---|
| ① md 不支持（上传 .md → 422） | parser 加 md/.markdown，走 _parse_txt | 1536 库上传 .md → 201(doc_type=md, parse=text) → ready → 检索 top1 0.449167 命中唯一 marker → 对比按钮 enabled → 对比页渲染 | 容器实码 SUPPORTED_TYPES 含 md + router text/markdown；S38 probe 06/07（201 + 0.53712）与 S39 raw_036-045 双侧一致；截图 10b/12b vision 复核一致 | **PASS** |
| ② reindex 后 failed 文档不刷新（对比按钮永久 disabled） | service 新增 _requeue_failed_docs（reindex 切 active 后 failed 文档自动重入队） | 256 坏端点库 txt→failed(ReadTimeout) → reindex 换 1536 → 库 active(1536) → failed 文档【自动】重算 ready（零手动 retry）→ 检索 top1 0.696454 | 容器实码 _requeue_failed_docs L1080/L1097；**独立 grep joker-api 日志** 005640e3 全时序铁证（09:02:17 uploaded → 09:02:43 reindex done dim=1536 → 09:02:43 `requeued 1 failed docs` → 09:02:45 `doc ready 1 chunks`，零 retry 请求）；截图 04a(failed ReadTimeout)/07a(ready 无错误) vision 复核；psql 文档 txt ready chunk=1 | **PASS** |
| ③ 检索首次 500 裸 ASGI traceback | retrieval 新增 _embed_query_with_retry（1 次重试 2s 退避，4xx 不重试，仍失败 → 502 可读中文） | 不可达 1536 端点库检索 → 502（非裸 500）可读中文 detail 无 traceback → 前端 toast 同文可读 → 好库连续 5 次查询全 200 无 500 | 容器实码 _embed_query_with_retry L119/L226；raw_053 逐字读（502 + detail「embedding 服务暂时不可用（已自动重试 1 次仍失败）…（ReadTimeout）」，无 Traceback/httpcore/asyncpg 泄露）；raw_054-058 逐份核验全 200；api_raw 58 份 grep 4xx/5xx 仅 raw_047(409 脚本重复合并)+raw_053(502) 两份，**全 58 份零 500**；截图 14c vision 复核 toast 同文 | **PASS** |

## 二、防造假核查（6/6 PASS）

| # | 核查项 | 方法 | 结果 |
|---|---|---|---|
| 1 | S39 脚本无 in-page fetch | grep `fetch(` 于 s39_ui_test.js + 3 个 cleanup 脚本 | **零命中** |
| 2 | S39 脚本无 localStorage 注入 | grep `localStorage` | 仅 1 处注释（防造假声明行 2），零代码命中 |
| 3 | S39 脚本无 goto 受保护页绕登录 | grep `page.goto` | 主脚本 1 处 = `/login` 登录入口；3 个 cleanup 各 1 处 = `/login`，共 4 处全为登录入口，其余全部站内 click 导航 |
| 4 | 截图与报告对应 | 03-testing/screenshots/s39/ 实数 **32 张** = 报告声明 32 张；关键 5 张（00_login_ok / 04a_txt_failed / 07a_txt_auto_ready / 10b_md_ready / 12b_compare_page / 14c_search_502）逐张独立 vision 复核 | 6/6 与报告逐字一致（login 成功页 / failed+ReadTimeout / ready 无错误 / md+ready+parse=text / 对比页左栏 md 原文完整+右栏 chunk+顶部 md/ready tag / 红色 toast 可读中文同文） |
| 5 | 原始 API 响应与报告逐字一致 | 直接读 raw_027 / raw_045 / raw_053 / raw_054-058（非经脚本解析） | 0.696454 / 0.449167 / 502 可读 detail / 5×200 全部逐字吻合；58 份零 500 |
| 6 | 环境铁证独立复核 | docker exec 容器实码 + docker logs + psql | 见 §三 |

## 三、环境铁证（独立复核，非自报）

**容器实码（joker-api:s38 活体 grep）**：
- `parser.py:37 SUPPORTED_TYPES = ("txt","md","docx","xlsx","pdf","png","jpg")`（含 md）
- `service.py:1080` reindex 成功路径调用 `_requeue_failed_docs` + `:1097` 函数定义
- `retrieval.py:119` `_embed_query_with_retry` 定义 + `:226` search_kbs 查询向量化调用
- `routers/rag.py:281 "md": "text/markdown; charset=utf-8"`

**容器日志铁证（joker-api，RUN s39929677 KB_A 005640e3-9ba9-4f64-9da1-0be4fde94bc5）**：
```
09:02:17,404 doc uploaded s39txt_929677.txt → kb 005640e3… (fb644cb1…)
09:02:43,715 reindex done kb=005640e3…: shadow …_reindex → … (dim=1536)
09:02:43,717 reindex: requeued 1 failed docs for kb=005640e3…: ['fb644cb1…']   ← _requeue_failed_docs 生效
09:02:45,319 doc ready fb644cb1…: 1 chunks (strategy=fixed, dim=1536)            ← 自动重算，全程零手动 retry
```
（S38 自测 RUN 56876618/11eac4c7 同样有 `requeued 1 failed docs` 日志，两轮互相印证）

**psql 终态复核（joker-pg，独立查询）**：
- s39 测试库 5 行全部软删（`deleted_at` 非空，`deleted_at IS NULL` 计数 = **0**）；级联软删文档 3 行（s39txt/s39md/s39_probe 均 deleted）——与 S39 报告「0 个 active s39 库」一致（报告按活跃库口径；软删行留存为正常软删机制，API 日志 `kb deleted …; vec table dropped` 5 条与 5 行 deleted_at 一一对应）
- 9 个 s39 测试 embedding 模型全部 `disabled`
- 删库日志时序（09:10:35/09:10:37 kb-b/kb-c + 09:16:21-25 kb-a×3）与 cleanup1/cleanup3 日志自洽

**清理声明核验**：S39 报告声明的清理（3 库+9 模型）经 psql + API 日志双侧独立复核成立。

## 四、S38 × S39 证据交叉

| 修复点 | S38 自测（dev_probe_s38_01..17，真实 HTTP） | S39 复测（真实 UI + 原始响应） | 交叉结论 |
|---|---|---|---|
| md 支持 | 06: 上传 s38_md_56871.md → 201 doc_type=md；07: 检索 200 top1 **0.53712** 命中唯一 marker | raw_045: 检索 200 top1 **0.449167** 命中唯一 marker + 对比页渲染 | 双侧独立命中，分数差异=查询文本/文档不同（各自唯一 marker），链路一致 ✓ |
| reindex 自动重算 | 10: reindex 200 reindexing；11: 库 active dim=1536；14: 检索 200 top1 **0.80363** | API 日志 `requeued 1 failed docs`→`doc ready`（零手动 retry）+ raw_027 检索 **0.696454** | 双侧日志/响应一致 ✓ |
| 检索 502 容错 | 13: 502 detail 可读中文（ConnectError 变体）无 traceback | raw_053: 502 detail 可读中文（ReadTimeout 变体）+ 5×200 无 500 | 双侧 502 语义一致，S39 额外验证前端 toast + 连续查询无回归 ✓ |

> S39 报告 §五 披露的 3 个脚本 FAIL（09a/14b 取 `body.data.items` 实际 `body.items`；Phase C 复用已存在模型二次创建 409）均为**测试脚本 JSON 解析缺陷**，已逐条对照原始响应核实（raw_027/raw_045 确为 `body.items` 且 200 命中；raw_047 409 后 KB_C 建库 201 正常），非产品缺陷，不影响 PASS 判定。

## 五、遗留（不阻塞）

- **md 纯文本解析边界**（P3，S38 已声明）：md 按纯文本解析、不做 markdown 语义切分 → 长 md 文档检索精度受切分粒度影响；本轮短文档 top1 0.449 命中正常但余量小（阈值 0.3）。后续可排期 md 语义切分。
- **502 重试策略**（P3，最小语义）：仅 1 次重试 + 2s 退避，4xx 不重试（保留 404/409 业务语义），按任务要求的最小实现，生产可按端点稳定性调参。
- **RISK-019**（既有，端点侧环境态）：外部 3584 维端点仍漂移（服务 1536 维），3584 维真实端点链路待端点方恢复后补测——非本轮范围、非代码缺陷。
- **BUG-20**（P3 观察，既有）：KB 列表 reindex 状态无自动刷新，待后续排期。

## 六、交付与 push

- **判定：PASS，交付放行**（三缺陷闭环，防造假 6/6，证据交叉无缺口，无阻塞项，无新发现产品 BUG）。
- **一次 push main**（本终审执行）：
  - ac49755（S38 修复代码）
  - a7e3cbd（S38 PIPELINE 补记）
  - S39 测试证据：TEST_REPORT_S39.md + screenshots/s39/（32 张）
  - 本终审：ACCEPTANCE_S40.md + BUGS.md（BUG-21/22/23 补登）+ PIPELINE/STATUS 回写
  - 不 push 05-temp/
- **commit hash**：`44a3500`（S40 终审交付 commit，含 S38 代码 ac49755 + S39 证据 + 本验收/回写）
- **ls-remote 核验**：`git ls-remote origin main` = `44a3500b9f5cadd33579a50450e50590a0d0674a` = 本地 `git rev-parse HEAD`，**远端 main 与本地一致**（push 输出 `3c53bc9...44a3500 main -> main`）。
- **收口补记**：本行随 S40 收口 commit 落盘（记录上述 ls-remote 核验终值），一次 push 完成。
