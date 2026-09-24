# agent-joker 项目简报（BRIEF）

> 本文件是全队单一事实源。所有 profile 行动前必读本文件 + 05-temp/assets/ 原始需求。
> 本轮范围：**设计阶段**——功能流程图、架构设计、数据库设计。不写代码。

## 1. 系统定位

agent-joker 是一个多租户 AI Agent 平台：提供用户/角色/权限体系、统一存储模块、LLM 节点管理、RAG 知识库、MCP Server 注册与调用、Skills 管理、Agent（简易 + 第三方）创建与对话，外加一个 BFF 网关负责统一鉴权、流量控制、工具调用拦截与协议转换（OpenAI 兼容），并全链路 trace 记录。

## 2. 原始需求（用户原话逐条，2026-09-22）

### 基础功能
- 用户管理、角色管理、权限管理、登入登出、接口操作日志

### 存储模块
- 保存文件：支持配置本地存储路径或云存储（Google Cloud Storage、阿里云 OSS），配置文件可配置
- 访问文件：本地目录存储时需开发统一接口，可根据文件名称访问
- 保存文件上传记录
- 上传和访问文件接口都可注册为 MCP 工具

### LLM 节点
- LLM endpoint 信息维护
- embedding 模型信息维护
- reranker 模型信息维护

### RAG
- 创建知识库
- 上传文档类型：txt、word、excel、pdf、png、jpg
- 图片、扫描版 PDF 及普通文档中的部分图片，需通过 LLM 视觉能力提供文档内容（主要是论文公式、图表）
- 上传文档（调用存储模块 API）
- 切分策略：定长、父子、语义、结构化/文档树、表格
- 支持原文档查看，支持手动修改切分后的 chunk 内容
- 支持选择 embedding 模型、rerank 模型（可选）
- 支持设置 topK、阈值
- 支持检索返回 chunk 索引及所在原文档位置，用于反向定位内容位置
- 支持 MCP server，可将知识库相关查询接口做成 MCP 工具

### MCP
- 支持通过 URL 注册 MCP server，支持注册多个
- 支持显示每个 MCP server 的工具列表，支持禁用、启用、删除等操作
- 删除、禁用等操作需提示可能存在关联的调用方

### Skills
- 支持手动添加、上传 skill，维护 skill 名称、内容等信息
- skill 元数据保存到数据库，skill 相关文件调用存储模块 API

### Agent
- 支持创建、维护 agent 信息
- agent 类型可选「简易 agent」（本地通过 langchain 实现）、「第三方 agent」（通过 URL 创建、维护、交互）
- 支持配置 agent 相关信息：LLM endpoint、指定的 RAG 库、MCP 工具、skills，都从已存在的列表中勾选
- 支持 agent 对话交互、会话列表、对话详情

### 简易 agent
- agent 记忆采用 redis（短期记忆）、pgsql（长期记忆）、obsidian（知识沉淀）
- agent 交互中涉及到文件，需将文件上传到存储模块
- 交互中涉及 RAG 知识检索，如果知识文档 tag 是 `official` 或用户有明确要求显示引用来源，agent 回复结果最后位置附上 RAG 知识来源，且可链接到原始文档的对应位置

### 第三方 agent
- 记忆由 agent 提供方实现
- 交互中涉及文件，需通过存储模块的 MCP 工具将文件上传到存储模块（平台提供上传文档和查询文档的 MCP 工具，agent 提供方决定是否调用）
- 交互中涉及 RAG 知识检索，同上：知识文档 tag 是 `official` 或用户明确要求显示引用来源时，回复末尾附 RAG 来源并可链接原文档对应位置（平台提供知识检索结果及引用原文档信息，agent 提供方决定是否显示）

### BFF 网关
- 负责统一鉴权（Access Token）、流量控制、API 路由、协议转换（将各引擎响应统一为 OpenAI 兼容格式）
- 统一鉴权与多租户隔离：agent 的 chat 接口接收请求头 Access Token，提取 tenant_id、user_id 和 scopes；校验用户是否有权限访问目标 Agent（如普通员工只能用客服 Agent，管理员能用数据分析 Agent）
- 统一工具执行拦截（Tool Call Interceptor）：Agent 工具调用必须经过 BFF 统一拦截
  - 简易 Agent：BFF 在代码层面拦截 LangChain 的 Tool 执行回调
  - 第三方 Agent：agent 返回 Tool Call 意图后，BFF 拦截该 HTTP 响应
  - 拦截动作：校验 Scope 权限；强制覆写参数（将 Access Token 强制注入工具参数，防止数据越权——mcp 工具或接口会统一校验 access token 的权限，这是业务系统本身的权限校验机制）；代理执行（BFF 使用自己的机器凭证调用真实的 MCP Server 或业务 API，再将结果返回 Agent）

### Trace
- 记录 agent 每个会话的交互内容（包含上传文件、生成的文件等）、工具调用、RAG 调用、时间点、耗费 token 等
- 检索功能（对 trace 数据的检索）

## 3. 模块范围

| 模块 | 设计深度 | 备注 |
|---|---|---|
| 基础功能（用户/角色/权限/登录/操作日志） | 完整设计 | 明确 |
| 存储模块（本地/GCS/OSS + 上传记录 + MCP 化） | 完整设计 | 明确 |
| LLM 节点（endpoint/embedding/reranker） | 完整设计 | 明确 |
| RAG（上传/视觉解析/5种切分/检索/原文定位/MCP化） | 完整设计 | 核心模块，重点 |
| MCP 注册与管理 | 完整设计 | 明确 |
| Skills | 完整设计 | 明确 |
| Agent（简易/第三方）+ 记忆（redis/pgsql/obsidian） | 完整设计 | 重点 |
| BFF 网关（鉴权/租户/工具拦截/OpenAI 兼容） | 完整设计 | 重点 |
| Trace + 检索 | 完整设计 | 明确 |

## 4. 推测范围（用户未明确，团队提出方案并标注"推测"）

以下为用户未指定、由团队在设计中提出并需标注"推测"的部分，闭环可演示即可，不过度设计：

1. **前端管理界面**：用户/角色/权限管理、知识库管理（原文查看、chunk 编辑）、MCP/Skills/Agent 管理、会话列表与对话详情，均暗示需要一个 Web 管理控制台。推测技术栈：Vue3 或 React（团队选型并记录 DECISIONS）。
2. **认证方案**：用户提到 Access Token（JWT 倾向），登入登出方式（密码登录 + JWT 访问/刷新令牌）由团队确定。
3. **多租户模型**：BFF 提到 tenant_id，推测所有业务表带 tenant_id 做行级隔离，登录账号属某租户。
4. **向量库选型**：RAG 需要向量检索，推测用 pgvector（与 pgsql 同库）或独立向量库，团队选型。
5. **RAG 解析流水线**：OCR/版面分析/视觉 LLM 的具体实现方式（如解析库选型）由团队设计。
6. **Obsidian 知识沉淀**：推测为本地/容器内 vault 目录 + 结构化笔记写入，具体格式由团队设计。
7. **简易 agent 的 langchain 编排方式**（ReAct / tool-calling loop）由团队设计。

## 5. 技术栈约束

- 后端：Python（LangChain 为硬性要求），框架团队选型（推测 FastAPI）
- 数据库：PostgreSQL（硬性要求，长期记忆/元数据）+ Redis（短期记忆/缓存）
- 存储：本地目录 / GCS / 阿里云 OSS，配置文件切换
- 部署：Docker Compose 本地可启动（团队自测用）
- 其他依赖（向量库、解析库、前端框架）团队选型，全部记录到 DECISIONS.md

## 6. 本轮（设计阶段）交付物与验收标准

| 交付物 | 路径 | 负责 | 验收标准 |
|---|---|---|---|
| 功能流程图 | `01-product/FLOW_DIAGRAMS.md`（mermaid 为主，可附 HTML 预览） | luoji/shiqiang | 覆盖全部 9 大模块；核心流程（登录鉴权、文档上传→解析→切分→检索、agent 对话含工具拦截、第三方 agent 对话）为时序图/流程图，关键分支（official tag 引用、工具 scope 校验失败、本地 vs 云存储）必须画出 |
| 架构设计 | `02-development/ARCHITECTURE.md` | zhangbeihai | 服务划分、组件交互、关键时序（BFF 工具拦截、RAG 流水线、agent 对话）、MCP server 设计、BFF 设计、部署拓扑；选型理由；与 BRIEF 逐条对照无遗漏 |
| 数据库设计 | `02-development/DB_DESIGN.md` | zhangbeihai | **按业务功能分章；每张表全部字段逐行列出（字段名/类型/描述/业务逻辑/关联），禁止概括省略**；覆盖全部 9 模块的表 + Redis key 设计 + obsidian 目录结构；ER 关系图（mermaid）；多租户隔离与索引策略说明 |
| 设计评审与整合 | `00-management/DESIGN_REVIEW.md` | chuyan | 三文档交叉检查（流程↔架构↔表 一致性）、与 BRIEF 需求逐条对照表、遗留问题清单 |

质量要求（用户标准）：**全面、仔细、准确**。推断内容必须标注"推测"。数据库字段定义必须能支撑流程图和架构中的每一个功能点。

## 7. 约束

- 本轮不写业务代码（允许生成 mermaid 预览 HTML 等辅助产物）
- 项目状态一律落文件（PROJECT/PLAN/STATUS/RISKS/DECISIONS），不依赖 profile 记忆
- 交接必须传项目根目录绝对路径 + 任务 ID
- 临时文件一律放 `05-temp/`，禁止 /tmp
- 团队：chuyan(PM) luoji(产品) zhangbeihai(开发) yuntianming(测试) shiqiang(系统分析)——注意是"章北海"
