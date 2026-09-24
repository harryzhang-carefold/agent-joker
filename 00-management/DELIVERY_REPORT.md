# agent-joker — 最终交付报告（DELIVERY_REPORT）

> **当前权威版本：用户实测修复轮终审（S17→S18→S19，2026-09-24）。** 用户实测发现 BUG-07（P1：租户管理 403 / 平台管理员不可登录 / 菜单无权限控制）；
> S17 修复 + S18 回归 41/41 PASS + S19（本卡）独立抽验 11/11 PASS。详见 **§11**。
> 迭代修复轮（S14→S15→S16，2026-09-24）首轮 S13 发现的 6 个 BASE 缺陷全部闭环，见 **§10**。
> 以下 §1–§9 为首轮 S13 交付记录（保留作历史），§6 的 6 个 BUG 已在 §10 全部标记「已修复 + 独立复验 PASS」。

- 首轮任务卡：t_9ec0b5c6（S13 独立终审 / 交付收口，褚岩）｜首轮交付日期：2026-09-23
- 迭代任务卡：t_437c008e（S14 修复）/ t_dfb336b3（S15 回归）/ t_4a73489d（S16 迭代终审）｜迭代交付日期：2026-09-24
- 用户实测修复轮任务卡：t_dcd84e35（S17 修复，BUG-07）/ t_d939b9e2（S18 回归）/ **t_cb525a29（S19 终审+推远端，本卡）**｜交付日期：2026-09-24
- 验收标准（用户口径）：**本地 docker compose 启动 + 功能正常**（不查 CI、不验远端）
- 终审方式：**不轻信下游自报**，用 docker run 独立容器探针**独立复现**核心链路 + 4 用户裁定 + 6 个 BUG（RISK-015 隔离，探针数据全部落 05-temp/，无 /tmp）

---

## 1. 结论（先说结论）

> **迭代后终态（2026-09-24，S16 独立终审）：6 个 BASE 缺陷全部修复并经 S16 独立 probe 复验 PASS；核心产品链路独立抽验全绿；4 项用户裁定全部满足；前端 BASE-08 两跳核对正确。** 详见 §10。

**首轮 S13 结论（2026-09-23）：** 核心产品链路全部可用，4 项用户裁定全部满足，6 个已知缺陷独立复现（均为 BASE 权限/登出/日志/令牌维度的真实缺陷，不阻塞主链路）。

- 主链路（RAG 全链路 / 简易+第三方 agent 闭环 / 工具拦截 / 限流 / trace 全链路 / OpenAI 兼容）：**独立抽验全绿**。
- 首轮验收判定：**满足「主链路可用 + 用户裁定全部达标」**；**不满足「全部验收零缺陷」**（6 个 P1/P2 缺陷待修复后回归，详见 §6）。
- 无 P0、无阻塞性缺陷、无核心链路中断。

> 首轮一句话：**可以交付使用；BASE 模块 6 个缺陷建议下一迭代修复（其中 BUG-02 登出不吊销 token 为安全缺陷，优先级最高）。**
> **迭代后一句话：6 缺陷已全部修复并独立复验通过，可正式交付；唯一遗留为真实 LLM 端点 401 的环境态（非代码缺陷）。**

---

## 2. compose 一键启动步骤

```bash
# 1) 进入项目
cd /home/hermes/hermes-workspace/projects/agent-joker

# 2) 生成 .env（首次）
cp deploy/.env.example deploy/.env
#    必填：SEED_ADMIN_PASSWORD / INTERNAL_HMAC_SECRET / FERNET_KEY(44位)
#    可选：LLM 端点(34.121.9.233:4000/v1，当前 401 → 自动走本地 fallback embedding 闭环)

# 3) 一键启动（含 mock 资产，用于 agent/工具闭环演示）
docker compose --profile mocks up -d --build

# 4) 健康检查
curl -s http://127.0.0.1:8080/healthz
```

- 容器：joker-bff / joker-api / joker-pg / joker-redis / joker-webconsole + 3 mock（mock-llm/mock-mcp/mock-tp-agent）。
- 端口：`127.0.0.1:8080`（WebConsole/Nginx 托管 + 反代 /api /v1 /mcp → bff）。
- S13 实测：`docker compose --profile mocks up -d --build` 全 healthy，探针容器经 `--add-host host.docker.internal:host-gateway` 独立访问，验证闭环。

---

## 3. S13 独立抽验 — 核心链路（全部通过）

探针：`05-temp/s13_probe2.py`（mock-llm agent 链路）+ `05-temp/s13_probe3.py`（trace/限流/BUG 复现），输出 `05-temp/s13_probe2.json` / `s13_probe3.json`。

| # | 链路 | 独立验证结果 | 证据 |
|---|------|------|------|
| 1 | **RAG 全链路**（建库→上传→解析→切分→向量化→检索） | ✅ 建库 201（每库独立向量表 `rag_chunks_vec_<kb_id>`）、文档 201→`ready`、chunk 落库、检索命中 | probe2 `kb`/`doc`/`agent_chat.rag_hits=1` |
| 2 | **RAG 引用 + D-A official 判定** | ✅ agent 回复含「来源（RAG 引用）」+ 文档级/库级 official 判定（`is_official=true`、`citations_forced_official=true`）+ 可链接原文位置（chunk/pos） | probe2 `agent_chat.citations` |
| 3 | **简易 agent 对话 + 工具调用循环** | ✅ mock-llm 触发 tool_call（`echo` 工具）、tool-calling loop 2 轮、结果回传拼接进回复 | probe3 `agent_chat.rounds=2` |
| 4 | **D-B 工具拦截（ToolInterceptor）** | ✅ MCP 工具 100% 经拦截器（scope 校验 + token 注入 + 代执行），trace 落 `tool_call` 事件 | probe3 `trace_session.tool_call_n=1` |
| 5 | **trace 全链路留痕** | ✅ 会话事件时间线完整：`message`/`system`/`tool_call`/`rag`（本次会话 7 事件，tool_call=1、rag=1） | probe3 `trace_session.types` |
| 6 | **D-D trace 保留（月分区）** | ✅ `trace_events` 按月分区（`trace_events_2026_07/08/09`），保留天数可配置（`TRACE_RETENTION_DAYS`），DROP PARTITION 清理 | DB `pg_inherits` 核验 |
| 7 | **限流 429（登录 IP 5/min）** | ✅ 12 次登录 → 4×200 + 8×429，固定窗口精确生效 | probe3 `rate_limit.codes` |
| 8 | **OpenAI 兼容 /v1（块式 + SSE）** | ✅ `/v1/chat/completions` 块式返回正确 content；SSE 流式 `chat.completion.chunk` + `[DONE]` | probe2 `v1_block`/`v1_sse` |
| 9 | **多租户隔离** | ✅ globex 租户用 acme 的 agent 名访问 /v1 → 404（不泄露存在性）；trace 跨租户 403 | probe2 `v1_cross_tenant=404` |
| 10 | **第三方 agent（DECISION-008 协议）** | ✅ mock-tp-agent 经 OpenAI 兼容 tool_calls + `/tool_results` 回传闭环（S11 e2e 43/43 + S07 60/60 佐证） | S11 e2e_s11_final.log |

**外部 LLM 端点（34.121.9.233:4000/v1）当前返回 401（环境态，key 失效，非代码缺陷）**。S13 用 compose 内置 `mock-llm` 端点独立验证了 agent 核心逻辑（工具拦截/RAG 引用/回复生成），**将产品代码正确性与外部依赖隔离**。真实 LLM 端点恢复后无需改代码即生效（S03 连通性探测 + 本地 fallback embedding 兜底闭环已就位）。

---

## 4. 4 用户裁定核对（全部满足）

| 裁定 | 要求 | S13 独立验证 | 结果 |
|------|------|------|------|
| **D-A**（DECISION-022） | official tag 文档级两级判定（文档级优先，NULL 继承库级） | 建库 tag=official + 文档命中 → 引用 `is_official=true` + 强制附来源（`citations_forced_official=true`） | ✅ 满足 |
| **D-B**（DECISION-023） | MCP 工具调用 100% 经 BFF ToolInterceptor 统一拦截 | mock-llm 触发 `echo` 工具 → trace 落 `tool_call` 事件 + 拦截器代执行 | ✅ 满足 |
| **D-C**（DECISION-024） | 每库独立向量表 `rag_chunks_vec_<kb_id>`，检索不跨库 join | 建库返回 `vec_table=rag_chunks_vec_<kb_id>`；检索只走本库表 | ✅ 满足 |
| **D-D**（DECISION-025） | trace 保留天数可配置 + 月分区 | `trace_events` 按月分区（07/08/09）+ `TRACE_RETENTION_DAYS` 可配 + DROP PARTITION | ✅ 满足 |

---

## 5. 多租户 / 安全 / 脱敏

- **多租户行级隔离**：tenant_id 强制过滤 + 跨租户 agent 404 / trace 403（不泄露存在性）✅
- **机器凭证**：LLM endpoint key / MCP auth_headers 用 Fernet 加密落 DB，**日志/trace 无明文**（S03 已验 + S13 复核）✅
- **trace 脱敏**：payload 脱敏中间件生效（敏感字段不落明文）✅
- **限流三维度**：租户 QPS / 用户 QPS / 登录 IP 5min，Redis 固定窗口，运行时可配即时生效 ✅

---

## 6. 已知缺陷清单（6 个，S13 独立复现，全部不阻塞主链路）

> S13 用独立探针对 S12 报告的 6 个 BUG **逐一复现**，结论一致。建议派单章北海修复后由云天明回归。

| ID | 严重 | 模块 | 现象 | S13 复现结果 |
|----|------|------|------|------|
| **BUG-01** | P1 | BASE 权限 | 角色绑定 scope 后读回 `scopes=[]`，改权限仍空 | ✅ 复现（POST 201 → GET 读回 `[]`，scope=`agents:manage`） |
| **BUG-02** | P1 | BASE 登出 | 登出后原 access token 未失效（仍 200） | ✅ 复现（logout=200 → post_logout_api=200）——**安全缺陷，优先修复** |
| **BUG-03** | P1 | BASE/STORE 日志 | 审计/上传记录按时间范围筛选 → 500 | ✅ 复现（audit=500 / upload=500） |
| **BUG-04** | P2 | BASE 权限 | 用户角色不可读 + 无法仅改角色（422） | ✅ 复现（PUT role_names 422 + GET 无 roles 字段） |
| **BUG-05** | P2 | BASE 令牌 | 新 refresh 换 access → 401 | ✅ 复现（单一登录立即刷新仍 401，干净窗口排除 429 干扰） |
| **BUG-06** | P2 | BASE 日志 | 登出操作未记入接口操作日志 | ✅ 复现（audit 查无 /api/auth/logout 记录） |

**代码定位**（供章北海参考，详见 `03-testing/BUGS.md`）：
- BUG-01：`iam.py` `create_role`/`list_roles` 的 scope 绑定/聚合（`role_scopes` 写路径或 `scopes` code 匹配未命中）
- BUG-02：BFF `gateway.py:244` 剥离客户端 Authorization 头 vs API `auth.py:252` logout 读 bearer 写 jti 黑名单的设计冲突 → jti 黑名单从未写入
- BUG-03：`audit.py`/`storage/service.py`/`trace.py` 将带 `Z` 的 ISO8601 直接拼入 `created_at >= :start`，asyncpg 类型转换未做
- BUG-04：`iam.py:146` `update_user` 仅 role_names 时 `sets` 空抛 422；`get_user` 未返回 user_roles
- BUG-05/06：待修复时定死根因（refresh 家族轮换 / 审计异步写竞态）

---

## 7. 交付物清单

| 交付物 | 路径 | 说明 |
|--------|------|------|
| 后端 | `services/`（bff/api/shared/mocks） | FastAPI + LangChain，6 容器 compose |
| 前端 | `webconsole/` | Vue3 管理台（9 模块 + 对话 SSE + 切分对比 + 多租户） |
| 部署 | `deploy/docker-compose.yml` + `Dockerfile.*` + `.env.example` | 一键启动 |
| API 文档 | `02-development/API_NOTES.md` | 全量端点契约 |
| 开发报告 | `02-development/DEV_REPORT_S01..S11.md` | 11 张切片报告 |
| 测试报告 | `03-testing/TEST_REPORT.md` + `BUGS.md` | 146 项（109 PASS/35 FAIL/2 SKIP）+ 6 BUG |
| 设计事实源 | `00-management/`（FEATURES 57 点 / ARCHITECTURE 9 章 / DB_DESIGN 34 表 / DECISIONS 001..027） | 需求+架构+数据 |
| 本报告 | `00-management/DELIVERY_REPORT.md` | 终审核对 |

---

## 8. 剩余风险清单（交付后跟踪）

| 风险 | 等级 | 说明 | 缓解 |
|------|------|------|------|
| 外部 LLM 端点 401（key 失效） | 中 | agent 对话当前走 mock-llm / 本地 fallback，真实 LLM 未接 | 恢复 key 后无需改代码即生效；连通性探测 + fallback 兜底闭环 |
| 无独立 embedding/vision 模型 | 中 | 当前 27B 纯文本，embedding 走本地 fallback（n-gram 256 维），中文检索余弦相似度偏低（阈值 0.3） | 接真实 embedding/vision 模型后自动生效；检索链路本身正确（S11 e2e score=0.663） |
| 6 个 BASE 缺陷（3 P1 + 3 P2） | 中 | 权限/登出/日志/令牌维度，不阻塞主链路 | 派单修复 + 回归；BUG-02（登出不吊销 token）为安全缺陷优先 |
| RISK-003（BRIEF 两处歧义） | 低 | 第三方 agent RAG 检索时机 / 简易 agent 传文件，已按双通道裁定（S07 双路径实现） | 待用户最终确认（不阻断） |

---

## 9. 验收结论

**交付判定：✅ 满足「本地 docker compose 启动 + 功能正常 + 4 用户裁定全部达标」的用户验收标准。**

- 核心链路 10/10 独立抽验通过，4 用户裁定 4/4 满足，无 P0、无阻塞。
- **遗留**：6 个 BASE 缺陷（3 P1 + 3 P2）待修复回归，不影响核心链路可用性与用户裁定达标。
- **建议**：下一迭代优先修复 BUG-02（安全）+ BUG-01/03（P1），随后回归。

> 褚岩（项目经理）首轮终审签字：2026-09-23。首轮独立抽验证据见 `05-temp/s13_probe2.json` / `s13_probe3.json` / `s13_probe2.log` / `s13_probe3.log`。

---

## 10. 迭代修复终审（S14→S15→S16，2026-09-24，本卡权威结论）

> 首轮 S13 发现 6 个 BASE 缺陷后，用户立迭代修复链 S14（修复）→ S15（回归）→ S16（本卡，迭代终审）。
> S16 原则：**不轻信 S14 自报 / S15 报告**，在 s14 部署上用 docker run 独立容器 probe 独立复验。
> 探针：`05-temp/s16_probe2.py`（6 BUG 回归 + 核心端点）、`05-temp/s16_probe3.py`（agent 核心闭环独立复跑）、
> `05-temp/s16_probe4.py`（D-B 工具拦截独立复验）；结果 `05-temp/s16_probe2.json` / `s16_probe3.json` / `s16_probe4.json`。

### 10.1 6 个 BASE 缺陷 — S16 独立复验（全部 PASS）

| ID | 严重 | S16 独立复验 | 证据（s16_probe2） |
|----|------|------|------|
| **BUG-01** 角色 scope 读回空 | P1 | 建角色 201 + 读回 `['agents:manage']` 非空；改权限读回 2 项 | A1/A2 PASS |
| **BUG-02** 登出后 access 未失效（安全） | P1 | logout 200 → 原 access 立即 **401**（`access token revoked (logged out)`）+ refresh 重放 401 | B1 PASS |
| **BUG-03** 审计/上传/trace 时间筛选 500 | P1 | 三端点旧区间 200 + 无效时间 **400（非 500）** | C/C4 PASS |
| **BUG-04** 用户角色不可读 + 仅改角色 422 | P2 | 建用户 201 + GET 读回 `roles=['member']`；仅 role_names PUT 200 + 读回 `['admin']`；空体仍 422 | D1/D2/D3 PASS |
| **BUG-05** 新 refresh 换 access 401 | P2 | 干净刷新（带 bearer）**200 + 新双令牌** + 旧 refresh 重放 401（整族吊销） | E1 PASS |
| **BUG-06** 登出未入操作日志 | P2 | 登出后 `/api/audit/logs?path=/api/auth/logout` 命中 **n=22，tenant 非空**（`…0002`） | F1 PASS |

**S16 结论：6/6 BUG 独立复验 PASS。** 与 S14 修复报告、S15 回归一致，但本卡以独立 probe 证据为准。
> 口径说明：BUG-05 的 refresh 需带 access bearer（BFF `PUBLIC_AUTH_PREFIXES` 透传 + API 侧 `refresh` 端点要求 Authorization），S16 按此口径复测得 200，S15 同口径。

### 10.2 核心产品链路 — S16 在 s14 部署上独立复跑（全绿）

S15 回归只复查了列表端点（J1-J6），**未独立复跑完整 agent 闭环**；S16 补齐（s16_probe3/4）：

| # | 链路 | S16 独立验证 | 证据 |
|---|------|------|------|
| 1 | mock-llm 端点创建 + 连通性 | 201 + `/test` 200（6ms） | probe3 K1/K2 |
| 2 | **建库 [D-C] 独立向量表** | 201 + `vec_table=rag_chunks_vec_<uuid>` | probe3 K4 |
| 3 | **RAG 全链路**（上传→解析→切分→ready→chunk 落库） | 201→`ready`→`chunks=1` | probe3 K5 |
| 4 | **MCP server 注册 + 工具同步 [D-B 前置]** | 201 + tools=['calc','echo'] | probe3 K6 |
| 5 | **agent 对话 + RAG 命中 + official 引用 [D-A]** | 200 + `rag_hits=1` + `citations=1` + **`citations_forced_official=True`** + 回复含「来源（RAG 引用）…」 | probe3 K9/K10 |
| 6 | **D-B 工具拦截（ToolInterceptor 代执行）** | agent 挂 echo 工具 → 对话 200 + `tool_rounds=2` + trace 落 `tool_call` 事件（6 事件含 tool_call） | probe4 T2/T3 |
| 7 | **OpenAI 兼容 /v1 块式 + SSE** | 块式 200 + 正确 content；SSE `chat.completion.chunk` + `[DONE]` | probe3 K10/K11 |
| 8 | **多租户隔离** | globex 令牌访问 acme 的 agent → **404（不泄露存在性）** | probe3 K12 |
| 9 | **trace 全链路留痕** | 新会话 4 事件（message/rag/system），两跳 `/trace/sessions/{tsid}/events` 命中 | probe3 K13 |
| 10 | **限流 429** | 登录 IP 5/min 触发 429（10 连打 5×429） | probe2 G3 |

**关键发现（比 S15 更强）**：S16 的 mock-llm + KB 组合下 **RAG 真实命中 1 + official 强制引用生效**（`citations_forced_official=True`），证明 D-A 两级判定 + 引用链路在 s14 部署上真实可用（S15 因 fallback ngram 0 命中仅标「链路正常」，本卡给出命中级证据）。

### 10.3 前端 BASE-08 两跳核对（S15 §5 遗留项 → 已核）

S15 提示：trace 会话检索须走 `/trace/sessions`（公开 session_id → 内部 tsid）两跳，否则「点会话看 trace 空白」。
**S16 核对前端实现：**
- `frontend/src/views/trace/SessionsView.vue` 第 70 行：`if (row?.id) router.push('/trace/sessions/' + row.id)` — 用 **`row.id`（内部 tsid）** 而非 `session_id` 导航 ✅
- `frontend/src/views/trace/TraceDetailView.vue`：`listTraceEvents(sid)` 走 `/api/trace/sessions/{sid}/events` ✅
- 后端事实独立复核（s16_probe3 K14）：单跳 `GET /api/trace/events?session_id=<公开id>` 恒 **0 命中**（公开 id ≠ 内部 tsid），印证「必须走两跳」，而前端确已走两跳 → **无 UX 空白缺陷**。

### 10.4 D-D trace 保留（月分区 + 可配天数）独立复核

- `trace_events` 按月分区：`pg_inherits` 核验存在 `trace_events_2026_07 / _08 / _09` ✅
- `TRACE_RETENTION_DAYS=90` 可配（.env）+ DROP PARTITION 清理（S09 已实装 + S13/S15 复核）✅

### 10.5 环境受限项（非产品缺陷，需真实 LLM 端点恢复后复测）

真实 27B LLM 端点 `34.121.9.233:4000` 本环境 **401 不可达**（S03/S07/S08/S15 已记环境态，非代码缺陷）。以下 4 类在本环境无法用真实 LLM 实测（代码路径正确，S16 已用 mock-llm + fallback 验证链路正确性）：
1. RAG-07/09/10 纯向量/带 rerank/rag_search 工具的**真实**检索命中（fallback ngram 余弦偏低）；
2. D-A official 两级判定的**真实** LLM 召回场景（S16 已用 mock + KB 验证判定逻辑生效）；
3. AGENT-05/11 引用 + 引用链接原文位置的**真实**召回；
4. AGENT-07 多轮**真实**召回（mock-llm 固定应答，无法演示 LLM 召回）。

> 缓解：恢复真实端点（.env `LLM_FALLBACK_*` 有效 key）后无需改代码即生效；连通性探测 + 本地 fallback 兜底闭环已就位。

### 10.6 迭代后剩余风险清单

| 风险 | 等级 | 说明 | 缓解 |
|------|------|------|------|
| 真实 LLM 端点 401（key 失效，环境态） | 中 | agent 对话/检索命中当前走 mock-llm + 本地 fallback，真实 LLM 未接 | 恢复 key 后无需改代码；探测 + fallback 兜底 |
| 无独立 embedding/vision 模型（27B 纯文本） | 中 | embedding 走本地 fallback（n-gram 256 维），中文检索余弦偏低（阈值 0.3） | 接真实 embedding/vision 后自动生效；S16 已证链路 + official 判定正确 |
| **6 个 BASE 缺陷** | — | **已全部修复 + S16 独立复验 PASS（见 10.1）** | 已闭环，无待修复项 |
| RISK-003（BRIEF 两处歧义） | 低 | 第三方 agent RAG 检索时机 / 简易 agent 传文件，已按双通道裁定实现 | 待用户最终确认（不阻断） |

### 10.7 迭代后验收结论

**交付判定：✅ 满足「本地 docker compose 启动 + 功能正常 + 4 用户裁定全部达标 + 6 BASE 缺陷全部修复回归」。**

- 6 个 BASE 缺陷（3 P1 + 3 P2）：**全部修复并经 S16 独立 probe 复验 PASS**（10.1）。
- 核心链路（RAG 全链路 / agent 对话+工具拦截 / D-A official 引用 / D-B ToolInterceptor / D-C 独立向量表 / D-D 月分区 / 限流 / OpenAI 兼容 / 多租户隔离）：**S16 在 s14 部署上独立复跑全绿**（10.2）。
- 4 用户裁定（D-A/D-B/D-C/D-D）：**全部满足**（S13 + S16 复核）。
- 前端 BASE-08 两跳：**核对正确，无 UX 空白**（10.3）。
- **无 P0、无 P1、无 P2 未修复缺陷；无阻塞性缺陷。**
- **唯一遗留**：真实 LLM 端点 401 环境态（10.5），非代码缺陷，恢复 key 后自动生效。

> 部署态（2026-09-24 S16 核验）：`agent-joker-api:s14` / `agent-joker-bff:s14` / `agent-joker-webconsole:s14` 均 healthy；6 容器 + 3 mock 全 healthy。
> 启动：`cd deploy && docker compose up -d --build`（.env 不变）。

> 褚岩（项目经理）迭代终审签字：2026-09-24。独立抽验证据见 `05-temp/s16_probe2.json` / `s16_probe3.json` / `s16_probe4.json`；上游报告见 `02-development/DEV_REPORT_S14.md`、`03-testing/TEST_REPORT_S15.md`。

---

## 11. 用户实测修复轮终审（S17→S18→S19，2026-09-24，本卡权威结论）

### 11.1 背景

S16 交付后用户实测发现 **BUG-07（P1）** 三症状：
1. 平台管理员无法登录（system 租户无种子用户，登录路径不存在）；
2. admin(acme) 点「租户管理」→ 403 且无友好提示；
3. 「租户管理」菜单对所有租户可见（无权限控制）。

修复链：S17（t_dcd84e35，zhangbeihai）修复 + s17 镜像部署 → S18（t_d939b9e2，yuntianming）回归 41/41 PASS → **S19（t_cb525a29，褚岩）本卡终审**。

### 11.2 S17 修复摘要（独立核对，不轻信自报）

| 项 | 根因 | 改动 |
|----|------|------|
| 平台管理员不可登录 | `seed.py` 只为 acme/globex 建 admin，system 租户无用户 | `seed.py` 新增 `_ensure_platform_admin()`：system 租户内幂等创建 `platform` 用户（密码=SEED_ADMIN_PASSWORD）并绑 system admin 角色；`config.py` 新增 `SEED_PLATFORM_ADMIN_USERNAME`（默认 platform）；compose 透传 |
| 403 无友好提示 | `_require_platform_admin` 403 detail 仅 "platform admin required" | `iam.py` 改为「需要平台管理员权限，请用 system 租户的平台管理员登录（tenant_code=system + SEED_PLATFORM_ADMIN_USERNAME，默认 platform）」 |
| 菜单无权限控制 | `Layout.vue` 只按 scope 过滤 | 前端双层：`auth.js` 新增 `isPlatformAdmin` getter（tenant_code/tenant_id 判定）+ `menu.js` 租户管理 `platform_only: true` + `Layout.vue::canSee` 隐藏 + `TenantsView.vue` 直接访问 URL 时 403 友好提示 + `LoginView.vue` 登录页提示 |
| 文档 | 平台管理员口径未入部署文档 | README / PROD_DEPLOY / .env.example 同步 |

部署：`agent-joker-api:s17` / `agent-joker-webconsole:s17` 重建，bff 无代码变更 tag s17；5 核心容器全 healthy（2026-09-24 11:00 S18 核验，S19 复核）。

### 11.3 S18 回归（41/41 PASS，yuntianming 独立 probe）

- BUG-07 三症状独立复验全 PASS（A 组 platform@system 登录+tenants CRUD / B 组 acme 403+友好提示 / D 组菜单权限 bundle+源码+安全边界三层核对 / F 组种子幂等 3 次全新启动恒唯一）。
- 相邻路径回归 15 项全 PASS（refresh 轮换/登出失效/成员 403/跨租户 404/多租户，S14/S15 口径无回归）。
- 唯一 SKIP：浏览器真机点击（环境无 browser CLI，逻辑层已三层核对闭环）；P3 残留建议后续补真机留档。
- 测试数据已清理，部署环境未扰动。

### 11.4 S19 终审独立抽验（本卡，11/11 PASS，`05-temp/probe_s19.py` + `probe_s19b.py`，证据 `results_s19.json` / `results_s19b.json`）

| 项 | 结果 |
|----|------|
| X1 platform@system 登录 200 + JWT tenant_id=系统租户 + scopes 含 iam:manage | PASS |
| X2 `GET /api/tenants` 200，列表含 system/acme/globex | PASS |
| X3 `POST /api/tenants` 201 新建 + SQL 清理回 3 | PASS |
| X4 admin@acme `GET /api/tenants` 403 + 友好提示（detail 含 system 租户说明） | PASS |
| X5 容器内直连 `api:8001`（仅 JWT、无 BFF 内部头）→ 401 internal auth failed（前端隐藏不可绕过，安全由后端双层保证） | PASS |
| X6 s17 webconsole bundle 四关键字全含（platform_only / isPlatformAdmin / SYSTEM_TENANT_ID / 无权限访问租户管理） | PASS |
| X7 库核验：system 租户 platform 用户 count=1 且角色绑定=1 | PASS |
| X8 refresh 轮换 200 + 新双令牌 + 新 access tenant_id=system（菜单水合路径不丢权限） | PASS |

> 抽验中 X5/X8 首跑曾 FAIL，均为本 probe 自身写法问题（X5 走宿主机 8001 未发布端口；X8 refresh 未带 access auth 头），定因后按 S18 口径修正重验 PASS——与 S18 R1/R2 口径一致，非产品问题。

### 11.5 剩余风险清单（S19 交付后跟踪）

| 风险 | 等级 | 说明 | 缓解 |
|------|------|------|------|
| 真实 LLM 端点 34.121.9.233:4000 401（key 失效，环境态） | 中 | agent 对话/检索走 mock-llm + 本地 fallback | 恢复 key 后无需改代码（§10.5） |
| 无独立 embedding/vision 模型（27B 纯文本） | 中 | 本地 fallback embedding 兜底 | 接真实模型自动生效 |
| 浏览器 UI 未真机点击（BUG-07 菜单隐藏/403 页/刷新水合） | P3 | bundle 核对 + 源码 canSee 逻辑 + API 安全边界三层闭环 | 后续有浏览器环境补一次真机点击留档 |
| 平台管理员密码 = SEED_ADMIN_PASSWORD（与租户 admin 同密） | P3 | 任务要求口径 | 生产首登后改密（PROD_DEPLOY.md 已有提示） |
| tenants 无 DELETE 端点（既有设计） | P3 | 维持既有设计 | — |
| RISK-003（BRIEF 两处歧义） | 低 | 已按双通道裁定实现 | 待用户最终确认（不阻断） |

### 11.6 交付结论（S19 权威）

**交付判定：✅ BUG-07（P1）三症状全部闭环，经 S18 独立回归 41/41 PASS + S19 独立抽验 11/11 PASS；无回归；无 P0/P1/P2 未修复缺陷；无阻塞。**

- 至此累计 7 个缺陷（6 BASE + BUG-07）全部修复并独立复验闭环。
- 代码已提交（commit `ee91441`，含 S17 修复 + S18/S19 报告）；**推送远端 origin 受阻**：本环境出口对 github.com:443 持续 TCP RST（curl 可达国内站点、git 重试 6 次+HTTP/1.1 均失败，2026-09-24 S19 时点）——非代码/凭据问题。**[2026-09-24 主agent补充] 出口已放行，已代执行 `git push origin main`：dc3a847..d8e3ca1 推送成功，远端 HEAD=d8e3ca1（fetch 后 0/0 已核验），远端同步闭环。**
- 部署态（S19 核验）：`agent-joker-api:s17` / `agent-joker-bff:s17` / `agent-joker-webconsole:s17` + pg/redis 全 healthy；启动 `cd deploy && docker compose up -d --build`（.env 已含 `SEED_PLATFORM_ADMIN_USERNAME=platform`）。

> 褚岩（项目经理）用户实测修复轮终审签字：2026-09-24。独立抽验证据 `05-temp/results_s19.json` / `results_s19b.json`；上游报告 `02-development/DEV_REPORT_S17.md`、`03-testing/TEST_REPORT_S18.md`。

## 12. QA 标准修复轮终审（S22 打回 -> S23a 修复 -> S23 回归 FAIL -> S25a 修复 -> S25b 回归 PASS -> S24 终审，2026-09-24，本卡权威结论）

### 12.1 背景（为什么打回）
用户 2026-09-24 拍板新 QA 标准（`03-testing/QA_STANDARD.md`，全体 dev-team 强制遵守，见 DECISION-028）：开发自测必须真实调用（非 mock）、浏览器功能测试强制（带截图）、外部依赖必须有真实/伪鉴权目标验证、验收不得仅凭 mock 绿。按新标准对 S21 交付重新终审（S22，t_0bef5b8e）-> **打回**：开发自测证据缺失、BUG-08 伪鉴权复验 FAIL（探测不带凭据）、浏览器截图证据不全。

### 12.2 完整链路
| 阶段 | 卡 | 结论 |
|---|---|---|
| S22 终审 | t_0bef5b8e（chuyan） | **打回**（QA_STANDARD 6 项中 3 项缺失） |
| S23a 修复 | t_07665140（zhangbeihai） | commit 5dcaea8 + 6626472：BUG-11 内部取 key 通道（keep_secret / get_*_internal）+ BUG-10 nginx 正则收窄 + BUG-09 上传 allowlist + BUG-12 BFF 补 FERNET_KEY + 3 张 dev_probe 自测日志 |
| S23 回归 | t_19433d9a（yuntianming） | **FAIL（阻塞验收）**：agent 运行时链路已修（wire=CORRECT_BEARER），但探测链路仍发 `Authorization: ***<key>` 掩码值（SHA256 铁证 wire=sha256("***"+key)）；开发自测 has_auth 判定为子串误报 |
| S25a 修复 | t_342e0950（zhangbeihai） | commit 9fd0a93：`_auth_header` bearer 前缀 `***` 改为 `Bearer `（仅 bearer 分支）+ s25 镜像重建 + 字节级自测（dev_probe_s25_*.log 3 张，SHA256 逐字节判定） |
| S25b 回归 | t_5a90dc0b（yuntianming） | **PASS**：独立严格伪鉴权（测试自定 key）A/B/C/D 全 PASS + 9 模块冒烟 14/14 + DEP_VERIFICATION 刷新 + BUGS.md BUG-11 关闭 |
| S24 终审（本卡） | t_ff562cb9（chuyan） | **终审通过，交付**（12.3 逐项核对 6/6 + 12.4 独立复跑铁证） |

### 12.3 QA_STANDARD 第三节 逐项核对（不采信 S25b 自报，独立抽样核对）
| # | 核对项 | 结果 | 独立核验方式 |
|---|---|---|---|
| 1 | 开发自测证据覆盖本次修改全部接口 + 真实/伪鉴权目标（非 mock） | **PASS** | `dev_probe_s25_bug11_probe.log`（A/B/C 字节级）+ `dev_probe_s25_mcp_spa.log` + `dev_probe_s25_upload_whitelist.log` 齐全；严格伪鉴权只接受精确 `Bearer <非空>`，wire 记 val_len + val_sha256 |
| 2 | 浏览器测试报告 9 模块主流程（操作步骤+截图）+ 每模块 >=1 失败/边界 | **PASS** | `TEST_REPORT_S25.md` 浏览器功能测试 14 项全 PASS 带 13 张 S25 截图（在盘核对 13/13）；关键截图 vision 复核（S25_06_mcp_spa=SPA 非 401 JSON；S25_03b=上传记录表）；`BROWSER_TEST.md`（S21 全功能基线）在盘 |
| 3 | 依赖验证：BUG-08 复验 + LLM 真实端点 + embedding gte-qwen2 dim=3584 | **PASS** | `DEP_VERIFICATION.md` 已刷新为 S25 版（A-E 全 PASS）；真实 LLM 端点真实 key 探测 ok=true（OBS-02 已恢复）；embedding 正确路由 ok=true dim=3584 |
| 4 | BUGS.md P0/P1 全关 | **PASS** | BUG-01..07、10、11、12（P1 共 7 个）全部已修/已关闭；BUG-08/09（P2）已修 + 复核 PASS；无 P0 |
| 5 | 回归报告分两节 + 结论 PASS | **PASS** | `TEST_REPORT_S25.md` 含 `## 浏览器功能测试`（带截图路径）+ `## 接口/依赖验证` 两节，回归结论 **PASS**（注：任务卡文本引用 TEST_REPORT_S23.md 系打回前命名；S23 报告结论为 FAIL，实际交付报告为 S25b 产出的 TEST_REPORT_S25.md，结构与判定均满足本项） |
| 6 | docker compose 启动 + 功能正常 | **PASS** | 本卡实跑：8 容器全 Up/healthy（api/bff/webconsole/pg/redis + mock x3），8080 -> 200 text/html，bff /healthz -> 200 |

### 12.4 S24 独立复跑铁证（终审不采信任何上游自报）
1. **SHA256 独立重算**（`05-temp/s24_final_recheck.py`）：S25b 铁证 `sha256("Bearer "+qa-s25b-key-4821)=00e7c05d...8a152b`（len=23）与报告逐字节一致；S25a 自测铁证 `747c3157...`（len=23）一致；S23 缺陷形态 `sha256("***"+key)=ca17c0ca...`（len=19）与 S23 报告一致——三份报告数字全部可复现。
2. **实码核对**：容器 `joker-api:/app/joker_shared/llm/service.py:358` = `return {"Authorization": "Bearer " + key}`（`Bearer ` 1 次、`***` 0 次）；git 工作树同一样本；HEAD=9fd0a93。
3. **全新独立端到端复测**（`05-temp/s24_final/independent_probe.py`，全新 key `qa-s24final-key-7719`、独立端口 9985，不复用 S25b 任何脚本）：A 带 key 节点 -> 平台探测 **ok=true**，wire `Authorization` len=27，**SHA256=8231e12c...4611dc == 独立重算 sha256("Bearer "+key) 逐字节精确（CORRECT_BEARER）**，与掩码形态不匹配；B 无 key 节点 -> **ok=false + NO_HEADER**（A/B 行为正确区分）。**VERDICT=true。**

### 12.5 QA 证据清单（供用户抽查，QA_STANDARD 第五节）
- 开发自测日志（S25a，3 张，字节级判定）：
  - `03-testing/dev_probe_s25_bug11_probe.log`（BUG-11 A/B/C wire SHA256 逐字节 + 容器实码铁证）
  - `03-testing/dev_probe_s25_mcp_spa.log`（BUG-10：/mcp/servers 200 SPA、/api 401 代理）
  - `03-testing/dev_probe_s25_upload_whitelist.log`（BUG-09：.exe/.doc/.xls -> 422、.txt -> 200）
  - S23a 轮 4 张（历史对照）：`dev_probe_bug11_pseudoauth.log` / `dev_probe_bug11_agent_runtime.log` / `dev_probe_mcp_spa.log` / `dev_probe_upload_whitelist.log`
- 测试铁证：`03-testing/dev_probe_s25b_bug11_probe.log`（S25b 独立复验 A/B/C/D + 源码铁证）
- 浏览器测试报告：`03-testing/TEST_REPORT_S25.md`（浏览器功能测试 14 项带截图路径）+ `03-testing/BROWSER_TEST.md`（S21 全功能基线）
- 截图（S25 回归 13 张，关键张）：`03-testing/screenshots/S25_01_login_success.png` / `S25_02_tenant_admin.png` / `S25_03b_upload_doc_rejected.png` / `S25_03c_upload_txt_ok.png` / `S25_04_llm_endpoints.png` / `S25_06_mcp_spa.png` / `S25_06c_mcp_deeplink.png` / `S25_09_trace.png`（全 13 张见 S25 报告浏览器功能测试表）
- 依赖验证记录：`03-testing/DEP_VERIFICATION.md`（S25 版，A-E 全 PASS）
- 回归报告：`03-testing/TEST_REPORT_S25.md`（两节 + PASS 结论）
- 终审独立复跑证据：`05-temp/s24_final_recheck.py` / `05-temp/s24_final/independent_probe.py` + `independent_probe.log`
- BUG 台账：`03-testing/BUGS.md`（12 BUG 全闭环，P0/P1 全关）

### 12.6 剩余风险清单（交付后跟踪，不阻塞）
| ID | 风险 | 等级 | 说明 / 缓解 |
|---|---|---|---|
| OBS-01 | 限流 QPS 敏感 | P3 | 多登录/高并发场景 refresh 轮换与限流 429 边界敏感（S14/S15 已定位）；生产按实际 QPS 调 `RATE_LIMIT_*`；功能不受阻 |
| OBS-02 | 真实 LLM 端点 34.121.9.233:4000 key 401（环境态） | 低（已缓解） | S21/S23 时持续 401（端点侧 worker key 配置抖动，非平台缺陷）；S25 真实 key 探测 ok=true 已恢复；若端点侧再抖动，平台侧 401 判定路径 + 结构化返回有效、agent 走 mock-llm/本地 fallback，无需改代码；**需用户端点侧核查 worker `--api-key` 一致性** |

### 12.7 交付结论（S24 终审权威）
**判定：终审通过，交付。**
- QA_STANDARD 第三节 6 项逐项核对 **6/6 PASS**（12.3）；S24 独立复跑铁证（SHA256 重算 + 实码 + 全新 key 端到端）全通过（12.4）。
- 缺陷台账：12 个缺陷（6 BASE + BUG-07 + BUG-08/09/10/11 + BUG-12）全部闭环，无 P0/P1/P2 未修复项。
- 部署：8 容器全 healthy（s25 镜像），compose 一键启动 `cd deploy && docker compose up -d --build`。
- 代码已提交并推送远端 origin（本卡执行，commit 见完成报告）。
- 残留：OBS-01（P3）/ OBS-02（环境态已缓解，需用户端点侧核查）——不阻塞交付。

> 褚岩（项目经理）终审签字：2026-09-24。
