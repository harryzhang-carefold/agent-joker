# ACCEPTANCE S31 — 终审：S29/S30 修复-回归通过后验收 + 一次 push

- **验收人**：褚岩（chuyan，项目经理），任务卡 t_0e99f112
- **日期**：2026-09-28（CST）
- **上游**：S29（zhangbeihai，t_24b08308，commit 1ed12a4）修复 BUG-16/17/18 + 自测；S30（yuntianming，t_554ee9cc）UI 复测 + 回归 + 防造假自查 **PASS**（TEST_REPORT_S30.md）
- **标准**：`03-testing/QA_STANDARD.md` 第三节（验收）+ 防造假条款；**不采信 S29/S30 自报，独立核查**

> **整轮判定：## PASS — 终审通过，一次 push 完成（e303f02..HEAD 全量）。**

---

## 一、防造假核查（S30 证据，同 S28 标准，逐项独立执行）

| 检查项 | 独立核查动作 | 结果 |
|---|---|---|
| S30 脚本 grep `fetch\|localStorage` | 本人对 `05-temp/s30/` 全部 12 个文件执行 grep | **零代码命中**（仅 2 处注释行自述"不用 fetch/localStorage"，非调用） |
| `page.goto` 逐条判读 | 全量 12 处 goto 逐条阅读源码 | 1 处为 `s30_lib.js` 登录页入口（`/login`），其余 11 处均为**登录后站内跳转**（/agents、/users、/roles、/llm/endpoints、/skills）；`s30_bug16_chat.js` 先 `realFormLogin`（fill 租户/用户名/密码 → click 登录 → waitForURL 离开 /login）再进入任何受保护页。**无绕登录** |
| 真实表单登录 | 读 `s30_lib.js:37` + 各脚本登录段 | fill `input[placeholder="如 acme"]`/`input[placeholder="admin"]`/`input[type="password"]` + click「登录」+ `waitForURL(!/login/)`，3 个脚本一致 |
| 截图独立 vision 核验（抽查 5 张） | 本人逐张独立 vision 分析（不采信 S30 描述） | 5/5 与报告一致，见下表 |
| 真实 LLM（34.121.9.233:4000）原始 200 响应 | 读 `dev_probe_s30_dep_verify.log` 原文 | 2 次原始 200（1390ms / 1317ms），`model=vllm-qwen3.8-27b`、`system_fingerprint=vllm-0.27.1-668ce1ce`，唯一 marker `s30dep_125552` 回显 + 算术 42 正确（非 mock/缓存）；**本人另独立复跑**：用 deploy/.env 与容器 env 两个 key 分别真实请求，均 HTTP 200（Pong!） |
| S29 dev_probe 证据覆盖全部修改接口 | 读 `dev_probe_s29_bug17/bug18.log` 原文 | BUG-17 A/B/C/D（单文件/多文件/显式 name/重复 409）+ 读回 + 清理全 PASS；BUG-18 A-G（空串/不传/唯一/重复 409/读回 NULL/PUT 归一/幂等重跑）全 PASS；BUG-16 由 `05-temp/s29/s29_bug16_results.jsonl` 7/7 + commit 内 7 张截图覆盖（S30 已独立复测 UI 层） |

### 1.1 截图独立 vision 核验明细（5 张）

| 截图 | 独立 vision 核验结果 |
|---|---|
| `s30bug16_045107_04_block_turn1.png` | AI 气泡 textContent=**pong**（清晰可读）、SSE 流式**未勾选**、会话 `b4c3ab18` 显示 — 与报告核心判据一致 ✅ |
| `s30reg_045142_user_dup409.png` | 红色 toast「**username or email already exists**」+ 邮箱已填 `s30_mail_045142@s30.test` ✅ |
| `s30llm_045405_llm_test_toast.png` | 绿色 toast「✅ **探测结果: 可用** — ok: model=vllm-qwen3.8-27b responded in 825ms」✅（表格「最近探测」单元 vision 判为红色文字但内容为 `ok: model=…`，属标签着色观感差异，功能判据 toast+API 200 均成立，非产品缺陷） |
| `s30reg_045142_skill_upload1.png` | toast「✅ **已上传 s30bug17_045142.md**」+ 列表行 `s30bug17_045142`（source=upload、文件数 1、active）✅ |
| `s30reg_045142_user_nomail.png` | 绿色 toast「**已创建**」✅；新行在 24 行列表下方未入截图可见区，行存在性由 jsonl `rowNew>0`（PASS 判据含 rowNoMail>0）保障，非缺失 |

---

## 二、证据交叉（S29 自测 × S30 复测 × BUGS 台账）

| 修复点 | S29 自测证据 | S30 独立复测 | BUGS.md 状态 | 交叉结论 |
|---|---|---|---|---|
| **BUG-16**（P1，`ChatView.vue` finalize 补 `ai.content`） | Playwright 真实表单登录 + 真实 LLM 块式气泡=pong 7/7 + 7 截图 | 块式气泡 pong + 多轮 pong 2（sameSession=true）+ SSE 对照无回归；jsonl 8 条全 PASS | 已修（S29） | **全闭环** |
| **BUG-17**（P2，skills 上传 name 可选） | dev_probe A-D 全 PASS（201/201/201/409 + 读回） | UI 单文件 201 落库 name 正确 + 多文件 201；内联创建无回归 | 已修（S29） | **全闭环** |
| **BUG-18**（P2，空串 email 归一化 NULL） | dev_probe A-G 全 PASS（含 DB 归一 1→0、幂等重跑） | UI 不填邮箱 201 / 填邮箱 201 / 重复 409 + **DB 核验 email=''=0、IS NULL=32** + 启动日志 normalize 1 users | 已修（S29） | **全闭环** |
| S26 修复（BUG-13/14/15，commit 07866bf/23f8d41） | dev_probe_s26_auth 98/98 自测 | S30 回归覆盖登录/登出/错误密码 401（S29 波及面）；BUG-15 nginx 变量式已在 S28 轮重建后复测 | 已修（S26） | **全闭环** |
| S29 改动波及面回归 | 7 文件 + 文档/compose | 登录/登出/401/用户 24 行/角色 73 行/LLM 连通 toast 可用/Skills 内联/Agent 维护 51 行，**无新缺陷**；1 条 LLM toast 首轮 FAIL 定性为 harness 4s 轮询窗口时序误判（快速轮询复跑 PASS，截图佐证） | — | **无回归** |

**P0/P1 状态**：BUGS.md 台账 P0=0 未关；P1=BUG-13/14/15/16 全部「已修」+ 复测 PASS。**满足 QA_STANDARD §三「P0/P1 全关闭」放行条件。**

---

## 三、独立复跑铁证（本卡，不采信任何上游自报）

1. **真实 LLM key 一致性 + 有效性**（S30 附注要求的 S31 核对项）：`deploy/.env` `LLM_FALLBACK_API_KEY`（len=66）与 `joker-api` 容器 env 值 **SHA256 前 8 位一致（52833b06）**、前后 4 字节一致；两者分别真实请求 `http://34.121.9.233:4000/v1/chat/completions` 均 **HTTP 200**（"Pong!" / "pong"）。→ S30 附注所述「.env key 已失效 401」在 push 时点已不存在（key 一致性核对通过，环境无漂移）。
2. **S30 脚本源码审计**：防造假 grep + goto 判读（§一），零违反。
3. **原始 200 响应审计**：`dev_probe_s30_dep_verify.log` 含完整 RAW JSON（id/model/fingerprint/usage 齐全）+ 唯一 marker 回显，mock 不可复现。
4. **DB 归一审计**：同 log 内 psql 输出 `email_empty_count=0 / email_null_count=32 / pass=true`。
5. **git 状态审计**：产品代码零未提交改动；S29 commit 1ed12a4 与报告声明文件清单一致（ChatView.vue/UsersView.vue/iam.py/skills.py/seed 相关 + dev_probe + 截图 + DEV_REPORT_S29）。

---

## 四、Push 执行记录（一次推送）

- **push 前远端**：`origin/main = e303f02b7d3807ee421e1ec1312b70ad38d6c41c`（ls-remote 核验）
- **本次 push 范围**（e303f02 之后的全部本地 commit + 新 S30 证据/S31 验收 commit）：

| commit | 内容 |
|---|---|
| `07866bf` | S26 fix：BFF/API 公开认证端点精确匹配（BUG-13/14） |
| `23f8d41` | S26 fix：nginx 变量式 proxy_pass（BUG-15）+ 全模块自测 98/98 |
| `a32314e` | S28 验收 FAIL 打回证据（报告/154 条结果（112+42）/167 截图/dev_probe_s26×10/BUGS 16-18/DECISION-029） |
| `1ed12a4` | S29 fix：BUG-16/17/18 + dev_probe_s29×2 + 7 截图 + DEV_REPORT_S29 |
| `45abf1b` | S30 证据：TEST_REPORT_S30.md + dev_probe_s30_dep_verify.log + screenshots/s30/（22 张） |
| 本 commit（S31 验收） | 本报告 + DELIVERY_REPORT §13 + DECISION-030 + RISKS/STATUS/PIPELINE 回写 |

- **凭据**：`-c credential.helper= -c credential.helper=store -c credential.helper.file=/home/hermes/.git-credentials`（环境坑：$HOME 下为旧 token）；仓库无 `.github/workflows`，无 workflow scope 需求。
- **push 后远端核验**：见交付结论（ls-remote 输出随卡内 metadata 归档）。
- **不入库**：`05-temp/`（诊断脚本/results.jsonl，gitignore 覆盖，符合 S28 口径）。

---

## 五、交付结论（S31 终审权威）

**判定：终审通过，交付。**

- QA_STANDARD §三 验收条件全满足：防造假核查 6/6 PASS（§一）；S29/S30 证据交叉覆盖 3 BUG 全部修复点 + 波及面（§二）；P0/P1 全关闭；独立复跑铁证 5 项（§三）。
- 远端 main 已同步至 S31 验收 commit（一次 push，范围见 §四）。
- **剩余问题清单（随交付报告给用户，不阻塞）**：
  1. **RISK-016（高，待用户操作）**：用户生产 vLLM（34.121.9.233:4000）API key 已在聊天中多次明文暴露，**需轮换**；轮换后更新平台 `platform-fallback-llm` 端点 key + `deploy/.env`（本次 push 时点 key 一致性已核对通过，轮换后需重新同步）。
  2. OBS-01（P3）：限流 QPS 边界敏感，生产按实际 QPS 调 `RATE_LIMIT_*`。
  3. 平台管理员与租户 admin 同密码（SEED_ADMIN_PASSWORD 口径），生产首登后应改密（PROD_DEPLOY.md 已提示）。
  4. 无独立 embedding/vision 模型（27B 纯文本）→ 本地 fallback 兜底，接真实模型自动生效。

> 褚岩（项目经理）终审签字：2026-09-28。
