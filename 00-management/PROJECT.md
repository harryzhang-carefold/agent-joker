# PROJECT — agent-joker

> 项目事实源（Source of Truth）。所有角色在此读取项目基本信息。

| 字段 | 值 |
|---|---|
| 项目名称 | agent-joker |
| 项目目标 | 多租户 AI Agent 平台：用户/角色/权限、统一存储（本地/GCS/OSS）、LLM 节点管理、RAG 知识库、MCP Server 注册与调用、Skills、Agent（简易+第三方）创建与对话、BFF 网关（鉴权/流量控制/工具拦截/OpenAI 兼容）、全链路 Trace |
| 项目负责人 | 褚岩（chuyan） |
| 项目状态 | IN_PROGRESS（开发阶段） |
| 创建时间 | 2026-09-22 |
| 当前阶段 | 开发阶段（13 卡线性链 S01→S13，watchdog 实时监控） |
| 最终目标 | docker compose 一键启动 + 9 大模块功能正常（本地验证，不查 CI 不验远端） |

## 项目根目录
`/home/hermes/hermes-workspace/projects/agent-joker`

## 团队分工
- 褚岩（chuyan）— 项目经理/编排者 — `00-management/`
- 罗辑（luoji）— 产品经理 — `01-product/`
- 章北海（zhangbeihai）— 开发工程师 — `02-development/`
- 云天明（yuntianming）— 测试工程师 — `03-testing/`
- 史强（shiqiang）— 系统分析师 — `04-analysis/`、流程图 `01-product/FLOW_DIAGRAMS.md`

## 约束
- 所有输出必须位于本项目目录内。
- 临时文件写入 `05-temp/`，禁止写入 `/tmp` 或 `~/.hermes`。
- 本轮不写业务代码（允许 mermaid 预览 HTML 等辅助产物）。
- 推断内容必须标注"推测"；数据库字段禁止概括省略。
- 交接必须传项目根目录绝对路径 + 任务 ID。
