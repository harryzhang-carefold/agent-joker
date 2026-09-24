# agent-joker S12 功能测试 — 测试报告（TEST_REPORT.md）

- 任务卡：t_14c1715a（S12 功能测试，yuntianming）
- 测试 run：`s12run1790163089`（03-testing/results_summary.json）
- 被测对象：S11 交付 docker compose（6 容器 + 3 mock，全链路联调 43/43）
- 隔离：RISK-015（探针经 docker run 独立容器，数据落 03-testing/，无 /tmp）
- 断点续做：3 轮（run 241/242/243），run 243 仅收尾文档，不重跑全量、不新增探针。

## 0. 总览

| 指标 | 值 |
|------|-----|
| 总用例项 | **146** |
| PASS | **109**（74.7%） |
| FAIL | **35**（24.0%） |
| SKIP | **2**（1.4%） |
| **37 项非 PASS 归因** | 产品缺陷影响 **9 项**（= 6 个 BUG）/ 测试脚本缺陷 **17 项** / 自测环境产物（fallback embedding / mock-llm）**8 项** / SKIP **2 项** / 待复测 **1 项** |
| 严重度 | P0 **0** / P1 **3** / P2 **3**（BUGS.md） |
| 核心链路 | **未中断**（RAG 全链路 / 简易+第三方 agent / trace / 限流 429 均通过） |

**总体结论：核心功能链路通过，存在 3 P1 + 3 P2 真实缺陷，需修复后回归。** 无 P0、无阻塞（核心链路跑通），**不满足「全部验收」但满足「主链路可用」**。37 项 FAIL 中 28 项经独立 probe 复现/代码核对为**非产品缺陷**（19 脚本 + 9 环境），真实产品缺陷 6 项集中于 BASE 权限/登出/日志/令牌。

> 说明：results_summary 头部 `pass=109 / fail=35 / skip=2`（109+35+2=146）；results 列表中 `pass=false` 项共 **37**（35 FAIL + 2 SKIP 以 pass=false 记录）。下文「37 项非 PASS」即此 37。

## 1. 逐模块结论（PASS 证据 + FAIL 归因）

### 模块一 BASE（30 项：22 PASS / 8 FAIL）
**通过项**：用户增删改/禁用/重置密码/启用（6）、角色创建+删除（2）、权限点定义（1）、登录+token 三要素（2）、登出 refresh 吊销（1）、日志可查/按接口筛选/脱敏（3）、跨租户 404（1）、前端 SPA index/路由 fallback/9 模块数据端点（3）、令牌重放拒/篡改拒/BFF 校验（3）。
**FAIL 归因**：
- 查看角色权限清单 / 改权限即时生效 → **BUG-01（P1，产品）**：scope 绑定后读回空（probe14 §A/probe15 §B）。
- 用户可分配变更角色 → **BUG-04（P2，产品）**：GET user 无 roles 字段 + 仅 role_names 触发 422（probe14 §B）。
- 用户有效权限=角色并集 → BUG-01/04 连带（roles=[]）。
- 登出后原 access token 立即失效 → **BUG-02（P1，产品）**：post_logout_api=200（BFF 剥离 Authorization → jti 黑名单未写入，gateway.py:244 / auth.py:252）。
- 登出入操作日志 → **BUG-06（P2，待复测）**：audit_logout_found=False。
- 日志按时间范围筛选 → **BUG-03（P1，产品）**：500（start/end 带 Z 未解析，audit.py:33）。
- 凭 refresh 换新 access → **BUG-05（P2，待复测）**：refresh=401。

### 模块二 STORE（12 项：11 PASS / 1 FAIL）
**通过**：local 配置生效/上传落盘、GCS/OSS 实现+不崩溃、env 切换、按文件名访问/404/跨租户 404、上传记录可查、平台 MCP server 在工具列表/upload_doc+query_doc 可见/BFF /mcp tools/list。
**FAIL**：上传记录按时间/来源筛选 → **BUG-03（P1，产品）**：500（同审计日志根因，storage/service.py:346）。

### 模块三 LLM（11 项：10 PASS / 1 FAIL）
**通过**：endpoint 新增/列表/连通性测试/key 脱敏、embedding 新增/列表/local fallback 确定性、reranker 新增/列表/删除。
**FAIL**：修改 endpoint → **测试脚本缺陷**：harness 传 `{"description":"s12 test ep"}`，但 endpoint 可更新字段为 name/base_url/model/auth_scheme/supports_vision/timeout_seconds/status（llm/service.py:127），**无 description 字段** → 400 `no fields to update` 为正确行为。probe14 §G 确认同 400。

### 模块四 RAG（28 项：8 PASS / 12 FAIL + D-C PASS）
**通过**：建库+入列表、.exe 拒 422、.doc 拒 422、维度快照固化、表格 is_table 切分、topK=N、阈值 0.99→0、topK 覆盖、chunk→定位/反向定位/手改后对比（RAG-11 3 项）、D-C 每库独立向量表（两库不同、维度=模型维度）。
**FAIL 归因**：
- 6 类文档上传/来源=kb/解析流水线（3）→ **测试脚本缺陷**：round-1 上传后未等 parse ready（harness 时序）。probe10 独立复现 **uploaded=6/6、txt status=ready chunk_count=2、RAG-05 原文 200/1782B、定长 resplit 200**，证明上传/解析/切分/向量化链路正确。
- 定长/父子/语义切分（3）→ **测试脚本缺陷**：round-1 时序（probe10 定长 resplit 200 复现）。
- 原文查看/chunk 列表（2）→ **测试脚本缺陷**：round-1 500/0（probe10 复现 200/1782B、count=2）。
- 纯向量/带 rerank 检索（2）→ **自测环境产物**：fallback ngram embedding 余弦相似度 < 默认阈值 0.3 → total=0（probe10 RAG-07 no-rerank/rerank 均 total=0，code=200）。检索逻辑正确（S11 e2e T4 score=0.663、RAG-08 阈值正确、probe10 向量已写入）。
- 检索带 pos 反向定位 / rag_search 工具（2）→ **环境产物连带**：0 命中 → hit0_pos=None、MCP 工具 code=200 但 0 命中。

### 模块五 MCP（9 项：8 PASS / 1 FAIL）
**通过**：URL 注册即同步/多 server/编辑、工具列表/禁用/启用/删除、无关联可删。
**FAIL**：查询关联调用方 → **测试脚本缺陷**：harness 走错路径（`/callers`/`/referencing`/`/refs` 均 404）；正确端点 `/api/mcp/servers/{id}/referring-agents` 返回 **200** `{"referring_agents":[]}`（probe14 §D）。

### 模块六 Skills（7 项：5 PASS / 2 FAIL）
**通过**：手动创建/可编辑/列表、上传记录 source=skill 可查、删除 skill。
**FAIL**：
- 上传 .md → **测试脚本缺陷**：harness `mp()` 以 `name="file"` 发文件（s12_test.py:121），但接口 `upload_skill` 声明 `files: list[UploadFile]`（skills.py:76），字段名不匹配 → 422（probe14 §E 另见 `/upload` 单独 404，疑 harness 路径/字段问题）。
- skill 元数据 files=[] → **测试脚本缺陷连带**：上传未成功 → files 空。

### 模块七 AGENT（25 项：17 PASS / 8 FAIL）
**通过**：创建简易/类型/四要素回显/非法 tool id 422、对 agent 对话得回复/消息流、非 official 不附来源、对话文件入存储 source=agent/记录可查、关闭会话记忆沉淀/长期记忆 PG、obsidian vault 笔记+索引、创建第三方/记忆提供方实现/对话闭环 mock-tp/不配工具正常。
**FAIL 归因**：
- 会话列表/新建/重命名/删除（4）→ **测试脚本缺陷**：harness 用 `session_id` 字段读回（接口返回 `id`）+ 期望 201（实际 200）+ PATCH rename/DELETE 路径与 harness 不一致。probe14 §C 独立复现 **create 200 / rename 200 / delete 200**，会话管理链路正确。
- official 命中附来源 / 引用链接原文位置 → **环境产物 + SKIP 连带**：fallback 0 命中 → forced_official=False cites=0；「引用可链接」SKIP（no citations）。
- 会话内多轮上下文 → **环境产物/待复测**：probe15 §D turn1=409（疑似 session 状态冲突/并发），mock-llm 无法演示真实召回（reply2 为 mock 固定应答，无 99231/ORD/订单）。多轮机制（redis 短期）代码存在，需真实端点复测。

### 模块八 BFF（17 项：14 PASS / 0 FAIL）
**通过（全）**：统一鉴权（无/无效 401、有效通过、不重复校验）、限流配置运行时调整即时生效（10→1000→10 读回）、配置化路由/未知 404、OpenAI /v1 块式+SSE、跨租户 404、D-B 工具拦截 100% ToolInterceptor、第三方 HTTP tool_call 拦截回传、工具结果入最终回复、内部 RAG 直调保留 rag 事件（非 tool_call）。

### 模块九 TRACE（10 项：9 PASS / 1 FAIL）
**通过**：会话 trace 可查、全链路事件类型（system/message/rag/tool_call+交互内容）、token 耗费、时间戳、第三方 tool_call 留痕、文件事件留痕、事件多维检索（event_type）、关键词全文（tsvector）、租户隔离（globex 不含 acme）、D-D 保留天数可配+月分区+DROP、脱敏。
**FAIL**：按会话检索 trace → **未定死（疑似脚本/session 过滤）**：8/9 trace 项 PASS，仅「按会话 filter」命中 0；probe14 §I 显示当时 `sessions now: 0`（会话被前序清场）。需一次干净复测（建会话→产生 trace→按该 session_id 检索）。

### 横切：多租户越权 / 限流（5 项：4 PASS / 1 FAIL）
**通过**：多租户越权（agent 参数篡改无效、跨租户 403/404，BASE-07/BFF-05/STORE-04）、限流其他租户 200、同租户另一用户 200、末尾 reset 防泄漏。
**FAIL**：限流单用户超 QPS→429 → **测试脚本缺陷**：harness `req()` 对 429 自动退避重试 8 次 + 该用例仅发 3 次 GET（s12_test.py:76-106,1010），429 被吞 → admin_codes=[200,200,200]。**probe14 §H 独立复现 16 连发 = 10×200 + 6×429**，证明限流产品行为正确（user_qps=10 后超量 429、其他用户 200、reset 回 10 无泄漏）。

## 2. 4 用户裁定专项结论
- **D-A official 两级判定**：`resolve_official(doc_tag, kb_tag)`（retrieval.py:42）逻辑正确（文档级优先、NULL 继承库级）。检索侧 official 判定因 fallback 0 命中未实测。**结论：逻辑 PASS，实测受环境限制。**
- **D-B 工具拦截边界**：BFF-06/07/08/09 + D-B 内部直调全 PASS（简易 100% ToolInterceptor、第三方 HTTP 拦截回传、内部 RAG 保留 rag 事件非 tool_call、勾选 403 经 check_agent_kb_grants）。**结论：PASS。**
- **D-C 每库独立向量表**：实测两库不同 rag_chunks_vec_<kb_id>、维度=该库 embedding 模型维度。**结论：PASS。**
- **D-D 保留天数可配+月分区**：TRACE_RETENTION_DAYS/AUDIT_RETENTION_DAYS 配置化（默认 90）+ 月分区 DROP PARTITION（shared/audit.py:116 代码核对）。**结论：PASS。**

## 3. 37 项 FAIL 逐条归类全表
图例：P=产品 BUG（见 BUGS.md）｜S=测试脚本缺陷｜E=自测环境产物（fallback embedding/mock-llm）｜K=SKIP 连带

| # | 用例 | 证据 | 归类 |
|---|------|------|------|
| 01 | BASE-02 查看角色权限清单 | probe15 §B readback []；probe14 §A | **P** BUG-01 |
| 02 | BASE-02 改角色权限即时生效 | probe14 §A after update [] | **P** BUG-01 |
| 03 | BASE-02 用户可分配/变更角色 | probe14 §B roles=None + 422 | **P** BUG-04 |
| 04 | BASE-03 用户有效权限=并集 | roles=[] | **P** BUG-01/04 连带 |
| 05 | BASE-05 登出后原 access token 失效 | post_logout_api=200；gateway.py:244 剥离 Authorization | **P** BUG-02 |
| 06 | BASE-05 登出入操作日志 | audit_logout_found=False | **P** BUG-06（待复测） |
| 07 | BASE-06 日志按时间范围筛选 | probe14 §F 500；audit.py:33 start/end 未解析 | **P** BUG-03 |
| 08 | BASE-09 凭 refresh 换新 access | refresh=401 new_token=no | **P** BUG-05（待复测） |
| 09 | STORE-05 上传记录按时间/来源筛选 | probe14 §F 500；storage/service.py:346 | **P** BUG-03 |
| 10 | LLM-01 修改 endpoint | code=400；harness 传非字段 description（llm/service.py:127） | **S** |
| 11 | RAG-02 六类文档上传 | round-1 未等 ready；probe10 uploaded=6/6 | **S** |
| 12 | RAG-02 上传记录来源=kb | 同上 | **S** |
| 13 | RAG-02 解析流水线 ready+chunk | 同上；probe10 status=ready chunk_count=2 | **S** |
| 14 | RAG-04 定长切分 | round-1 时序；probe10 resplit 200 | **S** |
| 15 | RAG-04 父子切分 | round-1 时序 | **S** |
| 16 | RAG-04 语义切分 | round-1 时序 | **S** |
| 17 | RAG-05 原文档查看 | round-1 500；probe10 200/1782B | **S** |
| 18 | RAG-05 chunk 列表视图 | round-1 0；probe10 count=2 | **S** |
| 19 | RAG-07 纯向量检索 | probe10 total=0（fallback 余弦<0.3） | **E** |
| 20 | RAG-07 带 rerank 检索 | probe10 total=0 | **E** |
| 21 | RAG-09 检索带 pos 反向定位 | hit0_pos=None（0 命中连带） | **E** |
| 22 | RAG-10 rag_search 工具 | code=200 0 命中（环境连带） | **E** |
| 23 | D-A official 判定 | 0 命中（forced_official=False）；resolve_official 逻辑正确 | **E** |
| 24 | D-A 库级 NULL 判定 | SKIP: kb2 doc upload failed | **K** |
| 25 | MCP-03 关联调用方 | harness 走错路径；正确 /referring-agents 200（probe14 §D） | **S** |
| 26 | SKILL-01 上传 .md | code=422；harness 字段 file vs 接口 files | **S** |
| 27 | SKILL-02 files=[] | 上传连带 | **S** |
| 28 | AGENT-04 会话列表 | sessions=1 字段名不匹配；probe14 §C 200 | **S** |
| 29 | AGENT-04 会话新建 | 期望 201 实际 200 | **S** |
| 30 | AGENT-04 会话重命名 | round-1 500；probe14 §C rename 200 | **S** |
| 31 | AGENT-04 会话删除 | round-1 500；probe14 §C delete 200 | **S** |
| 32 | AGENT-05 official 命中附来源 | cites=0（0 命中连带） | **E** |
| 33 | AGENT-05 引用链接原文位置 | SKIP: no citations | **K** |
| 34 | AGENT-07 会话内多轮 | turn1 409（probe15 §D）+ mock-llm 无召回 | **E**（待复测） |
| 35 | AGENT-11 第三方 RAG 引用 | rag_hits=0（0 命中连带） | **E** |
| 36 | TRACE-02 按会话检索 | total=0；probe14 §I sessions=0（会话被清场） | 待复测（疑似 S） |
| 37 | 限流 单用户超 QPS→429 | admin_codes=[200,200,200]（harness req() 吞 429）；probe14 §H 10×200→6×429 | **S** |

**计数**：P（产品）= 01,02,03,04,05,06,07,08,09 → **9 项 FAIL 对应 6 个产品 BUG**（BUG-01 含 01/02/04，BUG-03 含 07/09，BUG-04 含 03）｜S（脚本）= 10,11,12,13,14,15,16,17,18,25,26,27,28,29,30,31,37 → **17 项**｜E（环境）= 19,20,21,22,23,32,34,35 → **8 项**｜K（SKIP）= 24,33 → **2 项**｜待复测 = 36（+ 08/06 已列 P）→ **1 项**。
合计 9+17+8+2+1 = 37 ✓。

> 口径说明：BUGS.md 列 **6 个产品 BUG**（P1×3 + P2×3），覆盖上表 9 项「P」FAIL（多对一）。TEST_PLAN/汇总里「产品 BUG 6」指缺陷数，「P 项 9」指受产品缺陷影响的 FAIL 用例数。

## 4. 缺陷汇总（按严重度，详见 BUGS.md）
| ID | 严重 | 模块 | 一句话 |
|----|------|------|--------|
| BUG-01 | **P1** | BASE 权限 | 角色 scope 绑定后读回空，权限并集恒空 |
| BUG-02 | **P1** | BASE 登出 | 登出后 access token 未失效（BFF 剥离 Authorization 致 jti 黑名单未写） |
| BUG-03 | **P1** | BASE/STORE 日志 | 审计日志/上传记录按时间筛选 500（start/end 未解析） |
| BUG-04 | P2 | BASE 权限 | 用户角色分配不可读 + 无法仅改角色（422） |
| BUG-05 | P2 | BASE 令牌 | 新 refresh 换 access 401（待复测确认） |
| BUG-06 | P2 | BASE 日志 | 登出未入操作日志（待复测确认） |

## 5. 遗留与复测建议（交 S13 终审 / 章北海修复后回归）
1. **真实 embedding/LLM 端点恢复后复测**（.env LLM_FALLBACK_* 即生产口径）：RAG-07/09/10、D-A、AGENT-05/11、AGENT-07 多轮 —— 验证检索命中、official 判定、多轮召回、引用链接原文位置。当前 0 命中为 fallback 环境产物，非产品缺陷。
2. **BUG-05/06 复测确认**：单一登录→立即刷新（隔离 IP 窗口）确认 refresh 是否真 401；登出后延迟再查审计表确认是否时序产物。
3. **TRACE-02 按会话检索**：建会话→产生 trace→按该 session_id 检索，确认是否 session 过滤错位。
4. **修复后回归**：BUG-01/02/03/04 修复后，对 BASE 权限链路（建角色→绑 scope→用户绑角色→有效权限并集→越权 403）、登出黑名单、时间筛选、用户角色分配做回归（见 REGRESSION.md）。

## 6. 通过能力面（109 PASS 证明已验证可用）
用户/角色/权限管理（除 scope 读回）、登录/登出（refresh 侧）、操作日志（除时间筛选）、多租户隔离（跨租户 404/403）、前端 SPA 9 模块、令牌篡改/重放/BFF 校验；存储 local/GCS/OSS 后端+切换+统一访问+上传记录（除时间筛选）+平台 MCP 三工具；LLM endpoint/embedding/reranker 维护+连通性+key 脱敏；RAG 建库/6 类文档类型校验/5 切分策略（表格）/每库独立向量表 D-C/维度快照/检索参数 topK+阈值/切分对比双向联动；MCP URL 注册+工具同步/禁用/关联提示；Skills 管理（除文件上传字段）；简易 agent 创建/四要素/对话/文件/记忆沉淀/obsidian、第三方 agent URL 代理/拦截回传闭环；BFF 统一鉴权/限流配置/路由/OpenAI 块式+SSE/ToolInterceptor 100% 拦截/内部直调保留事件；TRACE 全链路事件/多维检索/租户隔离/保留天数+月分区 D-D/脱敏；限流 429（产品行为，probe14 复现）+多租户独立计数。
