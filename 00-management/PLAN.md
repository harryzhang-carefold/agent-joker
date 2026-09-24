# PLAN — agent-joker

> 任务计划。褚岩维护，所有人读取。

## 阶段一：设计（已完成 100%）

| 任务ID | 任务 | 负责人 | 依赖 | 优先级 | 状态 |
|---|---|---|---|---|---|
| TASK-D01 | 功能流程图 FLOW_DIAGRAMS.md | 史强 | — | P0 | DONE |
| TASK-D02 | 功能点清单 FEATURES.md | 罗辑 | — | P0 | DONE |
| TASK-D03 | ARCHITECTURE.md + DB_DESIGN.md | 章北海 | D01,D02 | P0 | DONE |
| TASK-D04 | 设计终审 DESIGN_REVIEW.md | 褚岩 | D03 | P0 | DONE |
| TASK-D05~D09 | v2 修订 + 复核 + 收口 | 史强/罗辑/章北海/云天明/褚岩 | — | P0 | DONE |

## 阶段二：开发（进行中，2026-09-22 立项）

> 立项依据：用户 2026-09-22 拍板技术基线（Vue3 + FastAPI + PG16/pgvector + Redis7 + docker compose 一键启动）+ 设计事实源（FEATURES 57 功能点 / ARCHITECTURE / DB_DESIGN 34 表 / DECISIONS 001..025 / 4 条用户裁定 D-A/D-B/D-C/D-D = DECISION-022..025）。
> 切片原则：每任务一个领域切片，严格线性串行（同一代码库禁止并发，共享文件 init_schema.sql / API_NOTES.md / .env.example 避免冲突）。执行顺序 S01→S02→...→S13。
> 每张卡交付 02-development/DEV_REPORT_Sxx.md + 自测证据；API 面同步 API_NOTES.md；未完成时写 PROGRESS 断点供 monitor 续做。

| seq | 卡ID | 任务 | 负责人 | 前置 | 优先级 | 状态 |
|---|---|---|---|---|---|---|
| 1 | S01 (t_a884eff3) | 后端骨架（FastAPI+PG/Redis+租户中间件+IAM+登录+审计+34 表 schema） | 章北海 | — | P0 | IN_PROGRESS |
| 2 | S02 (t_36f66f56) | 存储模块（local/GCS/OSS+上传记录+平台 MCP 三工具） | 章北海 | S01 | P0 | TODO |
| 3 | S03 (t_f256d037) | LLM 节点（endpoint/embedding/reranker+连通性探测+本地 fallback embedding） | 章北海 | S02 | P0 | TODO |
| 4 | S04 (t_8c8f30e0) | RAG 解析+切分（6 类文档+视觉 LLM+5 策略+每库独立向量表[D-C]+原文查看+chunk 编辑+切分对比） | 章北海 | S03 | P0 | TODO |
| 5 | S05 (t_1a9e41b6) | RAG 检索+MCP 化（topK/阈值/rerank 可选+pos 反向定位+official 两级判定[D-A]+rag_search） | 章北海 | S04 | P0 | TODO |
| 6 | S06 (t_d2e1eaf0) | MCP 注册管理 + Skills | 章北海 | S05 | P0 | TODO |
| 7 | S07 (t_df563f72) | 简易 agent（langchain+三层记忆+引用）+ 第三方 agent（DECISION-008 协议+mock server） | 章北海 | S06 | P0 | TODO |
| 8 | S08 (t_f9b3989d) | BFF 网关（统一鉴权/多租户/ToolInterceptor[D-B]/OpenAI 兼容/限流） | 章北海 | S07 | P0 | TODO |
| 9 | S09 (t_075d0bf0) | trace + 检索（保留天数可配置[D-D]+月分区+脱敏） | 章北海 | S08 | P0 | TODO |
| 10 | S10 (t_08562193) | 前端管理台（Vue3，9 模块页面 + 对话交互 + 切分对比查看） | 章北海 | S09 | P0 | TODO |
| 11 | S11 (t_2d755ae8) | docker compose 集成 + 联调（6 容器+mock MCP/agent+全链路闭环） | 章北海 | S10 | P0 | TODO |
| 12 | S12 (t_14c1715a) | 功能测试（按 FEATURES 验收要点 + mock 第三方资产，RISK-015 docker run 隔离） | 云天明 | S11 | P0 | TODO |
| 13 | S13 (t_9ec0b5c6) | 终审验收 + 交付报告（独立 compose 抽验 + 4 用户裁定核对 + DELIVERY_REPORT） | 褚岩 | S12 | P0 | TODO |

状态枚举：TODO / IN_PROGRESS / DONE / BLOCKED

> 依赖图为严格线性链（每卡最近未完成父 = 前序卡），保证 zhangbeihai 无并发（共享代码库安全）。S13 为交付收口，完成后 monitor cron 发交付报告给主 agent 并自删。
