# STATUS — agent-joker

> 当前状态快照。每次任务完成后由褚岩更新。

- **项目阶段**：**全量重测轮验收 FAIL 打回（2026-09-26 用户下令重测：S26 自测 98/98 + S27 浏览器测试 45PASS/4FAIL → S28 终审防造假核查通过但发现 3 个真实产品 BUG 未修 → 建 S29 修复 / S30 回归）**
- **总体进度**：设计 100%；开发 100%（S01..S11 + S14 + S17 + S20 + S23a + S25a）；测试 100%（S12 146 项 + S15 40 项 + S18 41 项 + S21 浏览器全功能 + S23 回归 + S25b 回归 PASS）；终审 100%（S13 首轮 + S16 迭代 + S19 实测 + S22 打回 + S24 终审通过）
- **产品**：100%（FEATURES 57 功能点 + FLOW_DIAGRAMS 21 图，定稿）
- **技术设计**：100%（ARCHITECTURE 9 章 + DB_DESIGN 34 表 + DECISIONS 001..028）
- **开发**：S01..S11 全 DONE + S14 迭代修复 6 个 BASE 缺陷 DONE + S17 BUG-07 DONE + S20 BUG-08 排查/前端修复 DONE + S23a BUG-11/10/09/12 修复 DONE + S25a BUG-11 探测链路 bearer 前缀修复 DONE
- **测试**：S12（146 项）+ S15（40 项）+ S18（41 项）+ S21（浏览器全功能）+ S23 回归（FAIL，定位探测链路掩码值缺陷）+ **S25b 回归 PASS**（独立严格伪鉴权 A/B/C/D + 9 模块冒烟 14/14 + 真实端点）
- **终审**：S13 首轮 + S16 迭代 + S19 实测 + **S22 按新 QA 标准打回** + **S24 终审通过（6/6 核对 + 独立复跑铁证，交付）**

## 当前阻塞
- **BUG-19 轮进行中（2026-09-28，用户真实 UI 报「新增知识库保存报错」）**：主 agent 本地复现定因——3584 维 embedding 模型建库恒 500（pgvector HNSW 索引 2000 维硬上限，`s26-gte-qwen2-real` 3584 维超限）。S32（t_892ebfc3，zhangbeihai 修复）已完成：>2000 维降级顺序扫描 + 可读 500，自测 12/12 PASS + 顺序扫描 EXPLAIN 铁证（`02-development/DEV_REPORT_S32.md`、`03-testing/dev_probe_s32_bug19*.log`）；S33（t_28d8f1f7，yuntianming 复测+回归）todo 等待中；S34（t_801fcd7e，chuyan 终审+push）按链等待。
- **RISK-019（端点侧环境态，S32 登记）**：外部 3584 维端点 `34.64.61.208:4000` 模型漂移（现服务 1536 维 `gte-Qwen2-1.5B-instruct`，DB 行仍指 3584 维 `gte-qwen2`）——非平台代码缺陷，3584 维文档链路已用 local provider 闭环验证，真实端点链路待 S33 复测时确认。
- **RISK-016（用户操作项）**：生产 vLLM API key 已在聊天多次暴露，需轮换 34.121.9.233:4000 key 并同步平台端点配置。
- **S29/S30 轮已收口**：BUG-16/17/18 已修 + S30 复测全 PASS + S31 终审 PASS（代码已 push 远端 6bef164）。

## 交付结论（2026-09-24，S24 终审，权威）
- **QA_STANDARD §三 6 项逐项核对 6/6 PASS**；S24 独立复跑铁证（SHA256 重算 + 容器实码 + 全新 key 严格伪鉴权端到端）全通过。
- **缺陷台账 12 个全部闭环**（6 BASE + BUG-07 + BUG-08/09/10/11 + BUG-12），无 P0/P1/P2 未修复项。
- **核心修复**：BUG-11 凭据发送（探测链路 + agent 运行时均发 `Authorization: Bearer <key>`，字节级铁证）；BUG-12 BFF FERNET_KEY；BUG-10 nginx 路由收窄；BUG-09 上传白名单。
- **OBS-02 已缓解**：真实 LLM 端点 34.121.9.233:4000 真实 key 探测 ok=true（S25b 验证）；若端点侧再抖动属端点 worker key 配置（环境态），平台侧 401 判定路径 + fallback 闭环，无需改代码。
- 部署：8 容器全 healthy（s25 镜像）；启动 `cd deploy && docker compose up -d --build`。
- 代码已提交并推送远端 origin（S24 本卡执行）。
- 详见 00-management/DELIVERY_REPORT.md §12（QA 证据清单 §12.5 供用户抽查）。

> 历史里程碑：首轮 S13 交付（2026-09-23）→ 迭代 S14..S16 → 实测修复 S17..S19 → 新 QA 标准 S22..S24（本轮）。

## 编排机制
- 首轮 13 卡严格线性链（zhangbeihai 9 / yuntianming 1 / chuyan 1）已完成。
- 迭代 3 卡链 S14(t_437c008e zhangbeihai 修复) → S15(t_dfb336b3 yuntianming 回归) → S16(t_4a73489d chuyan 终审) 已全部完成。
- 用户实测修复轮 3 卡链 S17(t_dcd84e35 zhangbeihai BUG-07 修复) → S18(t_d939b9e2 yuntianming 回归) → S19(t_cb525a29 chuyan 终审+推远端) 已全部完成。
- 新 QA 标准轮：S22(t_0bef5b8e chuyan 终审打回) → S23a(zhangbeihai 修复) → S23(t_19433d9a yuntianming 回归 FAIL) → S25a(t_342e0950 zhangbeihai 修复) → S25b(t_5a90dc0b yuntianming 回归 PASS) → **S24(t_ff562cb9 chuyan 终审通过，本卡)** 全部完成。
- watchdog cron 已收口自删。

## 当前风险（交付后跟踪，不阻塞）
- **RISK-016 用户生产 vLLM（34.121.9.233:4000）key 已多次明文暴露（高）**：**用户操作**——轮换 vLLM 服务端 `--api-key`，轮换后同步平台 `platform-fallback-llm` 端点 key（UI 编辑，Fernet 加密）+ `deploy/.env`，复跑连通性（S31 push 时点一致性已核对通过，无漂移）。
- **RISK-018（新增，中）**：key 轮换后 `.env` 与平台端点 key 可能再次失配 → 按 RISK-016 同步 + 复跑连通性。
- **OBS-01 限流 QPS 敏感（P3）**：多登录/高并发下 refresh 轮换与 429 边界敏感；生产按实际 QPS 调 `RATE_LIMIT_*`。
- **OBS-02 真实 LLM 端点 34.121.9.233:4000 key 401（环境态，已缓解）**：S21/S23 持续 401 → S25 真实 key 探测 ok=true 已恢复；S31 时点双 key（.env/容器 env）真实请求均 200；若再抖动需用户端点侧核查 worker `--api-key` 一致性；平台侧无需改代码（401 结构化判定 + mock/本地 fallback 兜底）。
- 无独立 embedding/vision 模型（27B 纯文本）→ 本地 fallback embedding 兜底；接真实模型自动生效。
- 平台管理员密码=SEED_ADMIN_PASSWORD（与租户 admin 同密码，任务要求口径），生产首登后应改密（PROD_DEPLOY.md 已提示）。
- RISK-003（BRIEF 两处歧义，已按双通道裁定实现）待用户最终确认（不阻断）。

## 最近更新
- 2026-09-28：**S31 终审通过，交付 + 一次 push（本卡 t_0e99f112）**。S30 PASS 后独立终审（不采信自报）：防造假核查 6/6 PASS（S30 12 脚本 grep fetch/localStorage 零代码命中、12 处 goto 逐条判读全为登录后站内跳转、5 张截图独立 vision 核验与报告一致、真实 LLM 34.121.9.233 原始 200 + 唯一 marker s30dep_125552、S29 dev_probe 覆盖全部修改接口）；S29/S30 证据交叉覆盖 BUG-16/17/18 全部修复点 + 波及面回归无新缺陷；P0/P1 全关；key 一致性独立复核（.env 与容器 env SHA256 一致 + 双 key 真实 200）。**一次 push main**：e303f02 之后全部 commit（07866bf S26/BUG-13-14 → 23f8d41 S26/BUG-15 → a32314e S28 证据 → 1ed12a4 S29 修复 → S30 证据 → S31 验收），ls-remote 核验同步。验收报告 `03-testing/ACCEPTANCE_S31.md` + DELIVERY_REPORT §13 + DECISION-030 + RISK-017 关闭/新增 RISK-018。遗留（不阻塞）：RISK-016 用户轮换 vLLM key、OBS-01/02、管理员同密码、无独立 embedding/vision。
- 2026-09-28：S29 修复（zhangbeihai，commit 1ed12a4）：BUG-16 ChatView finalize 补 ai.content + BUG-17 skills 上传 name 可选（默认首文件名）+ BUG-18 空串 email 归一化 NULL（后端 create/update + 启动幂等迁移 + 前端空邮箱不传）；dev_probe_s29_bug17/18 全 PASS + BUG-16 Playwright 真实表单登录+真实 LLM 块式气泡=pong 7/7。
- 2026-09-28：S30 UI 复测 + 回归（yuntianming）整轮 **PASS**：3 BUG 独立复测全过（块式气泡 pong 非 API 200 / 单多文件上传 201 落库 name 正确 / 不填邮箱 201 + 重复 409 + DB email=''=0 归一）+ S29 波及面回归无新缺陷 + 防造假 7/7；真实 LLM 原始 200 + 唯一 marker s30dep_125552；截图 22 张 + results.jsonl 25 条（1 条 harness 时序误判已复跑 PASS）。
- 2026-09-28：**S28 全量重测验收 FAIL 打回（本卡 t_4b6efa6d）**。防造假核查 3/3 PASS（grep 28 个 S27 脚本 fetch/localStorage 零命中；goto 24 处逐条判读全部登录后站内跳转；5 张截图独立 vision 核验与报告步骤一致；S26 真实端点 34.121.9.233/34.64.61.208 原始 200 响应无 mock 冒充）；S27 发现 3 个真实产品 BUG（BUG-16 P1 / 17 P2 / 18 P2）源码定因独立复核全部成立 → QA_STANDARD §三「P0/P1 全关」不满足，不 push。建 S29（zhangbeihai 修复）/ S30（yuntianming 回归）。验收报告 `03-testing/ACCEPTANCE_S28.md` + DECISION-029 + RISK-016/017。遗留：用户需轮换 vLLM key（已多次暴露）。
- 2026-09-24：**S24 终审通过，项目交付**。QA_STANDARD §三 6/6 PASS + 独立复跑铁证（SHA256 重算 / 容器实码 Bearer×1 掩码×0 / 全新 key 严格伪鉴权 A ok=true wire 逐字节 CORRECT_BEARER + B NO_HEADER）；DELIVERY_REPORT §12（含 QA 证据清单）+ DECISION-028（新 QA 标准）落盘；代码推送远端 origin。
- 2026-09-24：S25b 回归 **PASS**（yuntianming 独立复验，测试自定 key）：BUG-11 A/B/C/D 全 PASS（A 探测 ok=true + wire sha256("Bearer "+key) 逐字节；B 无 key NO_HEADER/ok=false；C agent 运行时 200+pong；D 真实端点 ok=true）+ BUG-10/09 无回归 + 9 模块冒烟 14/14 + DEP_VERIFICATION 刷新 + BUGS.md BUG-11 关闭。
- 2026-09-24：S25a 修复（zhangbeihai，commit 9fd0a93）：`_auth_header` bearer 前缀 `***` → `Bearer `（仅 bearer 分支）+ s25 镜像重建 + 字节级自测 3 张 dev_probe。
- 2026-09-24：S23 回归 **FAIL**（yuntianming 独立复验）：agent 运行时已修，但探测链路仍发 `***<key>` 掩码值（SHA256 铁证），开发自测 has_auth 子串判定为误报 → 打回 S25a。
- 2026-09-24：S23a 修复（zhangbeihai，commit 5dcaea8 + 6626472）：BUG-11 内部取 key 通道 + BUG-10 nginx 收窄 + BUG-09 上传 allowlist + BUG-12 BFF FERNET_KEY。
- 2026-09-24：S22 终审按新 QA 标准 **打回**（开发自测证据缺失 / BUG-08 伪鉴权 FAIL / 浏览器截图不全）；用户拍板新 QA 标准（QA_STANDARD.md，DECISION-028）。
- 2026-09-24：S19 用户实测修复轮终审完成（S17 BUG-07 修复 + S18 回归 41/41 + S19 独立抽验 11/11，累计 7 缺陷全闭环）。
- 2026-09-24：S14..S16 迭代完成（6 BASE 缺陷全闭环）。
- 2026-09-23：S12/S13 首轮完成。
- 2026-09-22：开发阶段立项。
