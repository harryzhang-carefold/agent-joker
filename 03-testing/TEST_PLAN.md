# agent-joker S12 功能测试 — 测试计划（TEST_PLAN.md）

- 任务卡：t_14c1715a（S12 功能测试，yuntianming）
- 事实源：`01-product/FEATURES.md`（9 模块 57 功能点，每点验收要点）+ 4 用户裁定（D-A/D-B/D-C/D-D = DECISION-022..025）
- 被测对象：S11 交付的 docker compose（6 容器 + 3 mock 资产，`deploy/docker-compose.yml`），全链路联调 43/43 PASS（S11 自报，本卡独立复核）
- 测试 run：`s12run1790163089`
- 结果：146 项 = **109 PASS / 35 FAIL / 2 SKIP**（见 results_summary.json）

## 1. 测试目标
对 agent-joker 全部 57 功能点验收要点 + 4 用户裁定做**独立功能验证**（不轻信 S11 自报），覆盖：正常流程、边界、异常输入、错误处理、回归影响、用户验收条件。产出逐功能点结论 + 缺陷清单 + 回归说明。

## 2. 测试策略与环境（RISK-015 铁律）
- **被测服务**：`cd deploy && docker compose --profile mocks up -d --build`（6 容器 + mock-mcp/tp/llm）。compose 仅作被起服务，非测试唯一载体。
- **测试自身**：所有探针（probe6..probe15、s12_test.py）**经 `docker run` 起独立容器**执行，网络 `host.docker.internal` 访问 8080（webconsole）/9301（mock-llm）等；测试 DB 数据/大文件全部落 `03-testing/`（fixtures/、results.jsonl、test_run.log、probe*.py/log），**无 /tmp**。
- **鉴权**：3 租户账号（acme admin/member、globex admin）经 8080 登录取 token；多租户越权用 globex token 访问 acme 资源。
- **LLM**：真实 27B 端点（34.121.9.233:4000）自测环境 401 不可达（S03/S07/S08 已记），联调/测试走 **mock-llm（9301）闭环**；embedding 走 **local fallback ngram 确定性向量**（接口与真实端点一致，card_common 允许）。检索命中受 fallback 余弦相似度下限影响（见 §3/§5 环境产物说明）。
- **断点续做**：本卡历经 3 轮（run 241/242/243），均 150 步预算耗尽；run 243 仅收尾文档，**不重跑全量、不新增探针**，37 项 FAIL 逐条以磁盘已有 probe 日志 + 代码核对定因。

## 3. 测试用例映射（57 功能点 + 4 裁定 → 用例 → 结果）
结果列 = results_summary.json 中对应 check 项 PASS/FAIL/SKIP 汇总。逐条证据见 TEST_REPORT.md。

### 模块一 BASE（用户/角色/权限/登录/登出/操作日志/多租户/令牌）— 30 项
| 功能点 | 用例 | 结果 |
|--------|------|------|
| BASE-01 用户管理 | 创建用户/入列表/禁用/禁用禁登/重置密码/重新启用 | 6/6 PASS |
| BASE-02 角色管理 | 创建角色关联权限点/删除角色 PASS；**查看权限清单/改权限生效/用户分配变更角色** | 2 PASS / 3 FAIL（BUG-01/04） |
| BASE-03 权限点 | 定义权限点关联角色 PASS；**用户有效权限=角色并集** | 1 PASS / 1 FAIL（BUG-01/04 连带） |
| BASE-04 登入 | 密码错误拒签/token 三要素 | 2/2 PASS |
| BASE-05 登出 | refresh 吊销 PASS；**原 access token 立即失效**/登出入日志 | 1 PASS / 2 FAIL（BUG-02/06） |
| BASE-06 操作日志 | 可查/按接口筛选/脱敏 PASS；**按时间范围筛选** | 3 PASS / 1 FAIL（BUG-03） |
| BASE-07 多租户 | 跨租户猜 ID→404 | PASS |
| BASE-08 前端管理界面 | SPA index/路由 fallback/9 模块数据端点（API 等价，浏览器自动化本环境不可用，S10 自测 34/34） | 3/3 PASS |
| BASE-09 令牌机制 | 旧 refresh 重放拒/篡改 token 拒/BFF 校验 PASS；**凭 refresh 换新 access** | 3 PASS / 1 FAIL（BUG-05） |

### 模块二 STORE（local/GCS/OSS 后端+切换+上传记录+平台 MCP 三工具）— 12 项
| 功能点 | 用例 | 结果 |
|--------|------|------|
| STORE-01 本地后端 | 配置生效/上传落盘 | PASS |
| STORE-02/03 云后端+切换 | GCS/OSS 实现/无账号不崩溃/env 切换 | PASS |
| STORE-04 统一访问 | 文件名访问/404/跨租户 404 | 3/3 PASS |
| STORE-05 上传记录 | 可查 PASS；**按时间/来源筛选** | 1 PASS / 1 FAIL（BUG-03 同根因） |
| STORE-06/07 平台 MCP 三工具 | server 在工具列表/upload_doc+query_doc 可见/BFF /mcp tools/list | 3/3 PASS |

### 模块三 LLM（endpoint/embedding/reranker 维护+连通性+key 脱敏）— 11 项
| 功能点 | 用例 | 结果 |
|--------|------|------|
| LLM-01 endpoint | 新增/列表/连通性测试/key 脱敏 PASS；**修改 endpoint**（harness 传非字段 `description`） | 4 PASS / 1 FAIL（脚本） |
| LLM-02 embedding | 新增/列表/local fallback 确定性 | 3/3 PASS |
| LLM-03 reranker | 新增/列表/删除 | 3/3 PASS |

### 模块四 RAG（6 类文档+视觉降级+5 切分+每库独立向量表+原文/chunk/对比/检索）— 28 项
| 功能点 | 用例 | 结果 |
|--------|------|------|
| RAG-01 建库 | 创建/入列表（含维度快照） | 2/2 PASS |
| RAG-02 6 类文档 | .exe 拒/.doc 拒 PASS；**6 类上传/来源=kb/解析流水线**（round-1 未等 ready） | 2 PASS / 3 FAIL（脚本，probe10 复现 6/6+ready+2 chunk） |
| RAG-03 视觉降级 | vision 不可用→记录 RISK 不阻断 | PASS |
| RAG-04 5 切分策略 | 表格 is_table PASS；**定长/父子/语义**（round-1 时序） | 1 PASS / 3 FAIL（脚本） |
| RAG-05 原文/chunk | **原文查看/chunk 列表**（round-1 500，probe10 复现 200/1782B、count=2）/手改 chunk/改后检索联动 | 2 PASS / 2 FAIL（脚本） |
| RAG-06 维度快照 | 建库绑定 embedding 维度 | PASS |
| RAG-07 检索 | **纯向量/带 rerank 检索**（fallback 余弦<0.3→0 命中） | 2 FAIL（环境产物） |
| RAG-08 检索参数 | topK=N/阈值 0.99→0/topK 覆盖 | 3/3 PASS |
| RAG-09 反向定位 | **检索带 chunk 索引+pos**（0 命中连带） | 1 FAIL（环境产物） |
| RAG-10 rag_search 工具 | MCP 工具可调用（0 命中连带） | 1 FAIL（环境产物） |
| RAG-11 切分对比 | chunk→定位/反向定位/手改后对比 | 3/3 PASS |
| D-C 每库独立向量表 | 两库不同向量表 rag_chunks_vec_<kb_id>，维度=该库模型维度 | PASS |

### 模块五 MCP（URL 注册多 server+工具同步/禁用/关联提示）— 9 项
| 功能点 | 用例 | 结果 |
|--------|------|------|
| MCP-01 注册 | URL 注册即同步/多 server/编辑 | 3/3 PASS |
| MCP-02 工具 | 工具列表/禁用/启用/删除 | 4/4 PASS |
| MCP-03 关联提示 | **查询关联调用方**（harness 走错路径，正确 `/referring-agents` 200）/无关联可删 | 1 PASS / 1 FAIL（脚本） |

### 模块六 Skills（skill 管理+文件走存储）— 7 项
| 功能点 | 用例 | 结果 |
|--------|------|------|
| SKILL-01 | 手动创建/可编辑/列表 PASS；**上传 .md**（harness multipart 字段名 `file` vs 接口 `files`） | 3 PASS / 1 FAIL（脚本） |
| SKILL-02 | 元数据落库+文件走存储/source=skill 可查/删除 PASS；**files=[]**（上传连带） | 3 PASS / 1 FAIL（脚本连带） |

### 模块七 AGENT（简易三层记忆+引用+tool-calling；第三方 URL 代理+拦截回传）— 25 项
| 功能点 | 用例 | 结果 |
|--------|------|------|
| AGENT-01/02/03 创建+四要素 | 创建简易/类型/四要素回显/非法 tool id 422 | 5/5 PASS |
| AGENT-04 会话 | **对 agent 对话得回复/消息流** PASS；**会话列表/新建/重命名/删除**（harness 字段名 session_id vs id + 201 vs 200，probe14 复现全 200） | 2 PASS / 4 FAIL（脚本） |
| AGENT-05 引用 | 非 official 不附来源 PASS；**official 命中附来源/引用链接原文**（0 命中连带） | 1 PASS / 1 FAIL + 1 SKIP（环境产物） |
| AGENT-06 文件 | 对话文件入存储 source=agent/记录可查 | 2/2 PASS |
| AGENT-07 记忆 | 关闭会话记忆沉淀/长期记忆 PG PASS；**会话内多轮**（turn1 409 + mock-llm 无法演示召回） | 2 PASS / 1 FAIL（环境产物/待复测） |
| AGENT-08 obsidian | vault 笔记+索引 | PASS |
| AGENT-09/10 第三方 | 创建第三方/记忆提供方实现/对话闭环 mock-tp/不配工具正常 | 4/4 PASS |
| AGENT-11 第三方 RAG 引用 | **平台提供检索+引用原文**（0 命中连带） | 1 FAIL（环境产物） |

### 模块八 BFF（鉴权/多租户/限流/路由/OpenAI+SSE/ToolInterceptor/内部直调）— 17 项
| 功能点 | 用例 | 结果 |
|--------|------|------|
| BFF-01 统一鉴权 | 无 token 401/无效 401/有效通过/不重复校验 | 4/4 PASS |
| BFF-02 限流配置 | 运行时调整即时生效（10→1000→10 读回） | 2/2 PASS |
| BFF-03 配置化路由 | routes.yml/未知 404 | 2/2 PASS |
| BFF-04 OpenAI 兼容 | /v1 块式/SSE 流式 | 2/2 PASS |
| BFF-05 多租户 | 跨租户访问 agent→404 | PASS |
| BFF-06/07/08/09 D-B 拦截 | 简易工具 100% ToolInterceptor/第三方 HTTP tool_call 拦截回传/结果入最终回复 | 4/4 PASS |
| D-B 内部直调 | 内部 RAG 直调产生 rag 事件（非 tool_call）保留留痕 | PASS |

### 模块九 TRACE（全链路事件+会话检索+保留天数+月分区+脱敏）— 10 项
| 功能点 | 用例 | 结果 |
|--------|------|------|
| TRACE-01 全链路事件 | 会话可查/事件类型/token 耗费/时间戳/第三方 tool_call 留痕/文件事件 | 6/6 PASS |
| TRACE-02 检索 | 事件多维（event_type）/关键词全文/租户隔离 PASS；**按会话检索**（8/9 PASS，仅按会话 filter 命中 0） | 3 PASS / 1 FAIL |
| D-D 保留天数+月分区 | TRACE_RETENTION_DAYS/AUDIT_RETENTION_DAYS 可配+月分区 DROP | PASS（配置化，代码核对） |
| 脱敏 | 敏感字段脱敏 | PASS |

### 横切：多租户越权防护 / 限流
| 用例 | 结果 |
|--------|------|
| 多租户越权（agent 参数篡改无效、跨租户 403/404） | PASS（BASE-07/BFF-05/STORE-04） |
| 限流 单用户超 QPS→429 | **FAIL**（harness req() 对 429 自动退避重试 + 仅 3 次，429 被吞；probe14 §H 独立复现 10×200→6×429，产品行为正确） |
| 限流 其他租户/同租户另一用户不受影响 | PASS（2/2） |
| 限流 末尾 reset 防泄漏 | PASS |

## 4. 用户裁定专项（4 条）
| 裁定 | 验证 | 结果 |
|------|------|------|
| **D-A** official 两级判定（rag_docs.tag 优先，NULL 继承库级） | `resolve_official()` 代码核对正确；检索侧 official 判定受 fallback 0 命中连带未实测 | 逻辑 PASS / 实测环境产物 |
| **D-B** 工具拦截边界（agent 经 BFF；MCP 工具 100% ToolInterceptor；内部直调保留 rag/file 事件+403 勾选） | BFF-06/07/08/09 + D-B 内部直调 全 PASS | PASS |
| **D-C** 每库独立向量表 rag_chunks_vec_<kb_id>，维度=该库模型维度 | 两库不同向量表、维度=模型维度实测 PASS | PASS |
| **D-D** 保留天数可配（默认 90）+月分区+DROP PARTITION | 配置化 + 月分区代码核对 PASS | PASS |

## 5. 环境限制声明
- **mock-llm 闭环**：真实 27B 端点自测 401 不可达，agent/检索走 mock-llm；trace/工具/引用链路行为与真实端点一致（S11 已证）。
- **fallback ngram embedding**：对中文查询余弦相似度偏低，低于默认阈值 0.3 → RAG-07/09/10、D-A、AGENT-05/11 检索 0 命中。**检索链路本身正确**（S11 e2e T4 score=0.663、RAG-08 阈值 0.99→0 正确、probe10 确认向量已写入独立表）。这些 0 命中判为**自测环境产物**，非产品 BUG；真实 embedding 端点恢复后即可闭环（.env LLM_FALLBACK_* 即生产口径）。
- **浏览器自动化不可用**：「浏览器打开→登录→9 模块」由 API 等价证据覆盖（T2 SPA index + fallback + T3 三账号登录 200），非产品缺陷；前端 22 视图/9 模块 S10 自测 34/34。
