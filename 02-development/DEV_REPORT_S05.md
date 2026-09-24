# DEV_REPORT_S05 — agent-joker RAG 检索 + MCP 化（t_1a9e41b6）

PROGRESS: 100% — 全部交付 + 自测 44/44 PASS + 回归全绿，可进入 S06（MCP/skills）

## 范围（RAG-06/07/08/09/10 + 接通平台 MCP 工具 rag_search）

| 项 | 状态 | 说明 |
|---|---|---|
| 检索核心（D-C） | ✅ | `joker_shared.rag.retrieval.search_kbs`：逐库查**该 KB 自己的**独立向量表 `rag_chunks_vec_<kb_id>`（不跨库 join），同库元数据 join（rag_chunks + rag_docs + rag_knowledge_bases + 父 chunk）；查询向量化用**该库建库快照 embedding 模型**（RAG-06）；多库=逐库召回后应用层合并 |
| RAG-07 rerank 可选 | ✅ | 任一库配 active reranker 且未显式关闭（`use_rerank`）→ 对合并候选重排（Jina 兼容 /rerank）；**端点不可用→降级纯向量**（记日志不阻断）；`reranked` 字段标明本轮是否重排 |
| 阈值双语义（DECISION-006） | ✅ | 有 rerank 时阈值作用 **rerank 分数**、无 rerank 时作用**余弦相似度**（两情况阈值均生效）；E2E 用 mock reranker 验证两种语义分别生效 |
| RAG-08 topK+阈值可配 | ✅ | 单次 `top_k`/`score_threshold` 覆盖，未传回落库级默认（`top_k_default`/`score_threshold`）；多库默认取各库最大值（最严格）；每库召回 N = `recall_top_n` 或 max(3*topK, 20) |
| RAG-09 反向定位 | ✅ | 每条 item 含 `chunk_id`/`chunk_index` + `pos`（原文坐标 JSONB，与 chunk 表一致；供 RAG-11 切分对比/原文高亮） |
| D-A official 两级判定 | ✅ | `is_official` = 文档级 `rag_docs.tag` 优先（=official→true / 其他→false），NULL 继承库级 `rag_knowledge_bases.tag=official`（NULL+NULL→false）；E2E 4 文档矩阵全对 |
| RAG-10 rag_search MCP 工具 | ✅ | BFF `platform_mcp.rag_search` 接通 S02 stub（501→200 items），经 ToolInterceptor 身份（access_token 优先/HTTP Authorization 回退），代执行 `/internal/rag/search` |
| 内部检索端点（D-B） | ✅ | `POST /internal/rag/search`（签名头+`agent_knowledge_bases` 勾选校验未勾选 403+落 trace `rag` 事件，不产生 tool_call；S09 SAR 直调同端点） |

## 新增 API 端点清单

scope：`/api/rag/search` 要 `rag:search`（缺失 403）；`/internal/*` 无 scope 门禁（D-B，S08 ToolInterceptor 统一接入）。租户行级隔离（跨租户 404）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/rag/search` | 知识库检索（RAG-06/07/08/09）。体 `{kb_ids[]（必选，同租户）, query（必选）, top_k?, score_threshold?, use_rerank?=true, agent_id?}` → `{items[], total, top_k, threshold, reranked}`；404/409/422 |
| POST | `/internal/rag/search` | 内部检索（DECISION-009 签名头，D-B）。= 上表 + agent_id 勾选校验（403）+ rag trace 留痕 + 出参 `agent_id`；401 未签名 |
| POST | `/internal/storage/rag-search` | **S02 契约兼容别名**（501 stub → 检索核心，1:1 同参同出参于 `/internal/rag/search`）；补 422 校验（kb_ids/query 空→422） |

MCP 工具 `rag_search`（BFF `/mcp`）：入参 `kb_ids[]/query/top_k?/score_threshold?/agent_id?/access_token?`，出参同上表。

API 面已同步 `02-development/API_NOTES.md`（rag 章节新增「检索（S05 已实装）」小节 + storage `/internal/storage/rag-search` 行 + MCP `rag_search` 行 + 占位表 mcp 更新）。

## 表/索引变更

无新增表。复用：
- `rag_chunks_vec_<kb_id>`（S04 动态向量表，D-C）——检索只读本库表，`embedding <=> query`（pgvector 余弦距离）。
- `trace_sessions` / `trace_events`（S01）——内部检索落 `rag` 事件 + `trace_sessions.rag_call_count`/`event_count` 累计。
- `agent_knowledge_bases`（S01）——`(agent_id, kb_id)` 勾选校验（D-B）。

## 关键实现与修复

1. **pgvector 余弦相似度语义修正**：`<=>` 返回余弦**距离**（0=相同，2=相反），原写 `(- distance)` 得错误分数→改 `(1 - distance)` 得余弦相似度（E2E 阈值/排序验证依赖此修正）。
2. **`ensure_trace_session` user_id=None 回退**：机器凭证内部调用 `auth_context.user_id` 可能为 None，原直接 `return None` 跳过留痕→改为回退**租户首个 active 用户**（`trace_sessions.user_id NOT NULL` 约束；D-B 要求内部检索也落 rag 事件）。
3. **`/internal/storage/rag-search` 补 422 校验**：S02 契约路径（别名）此前对空 kb_ids/query 走检索核心返回 500→补与 `/internal/rag/search` 一致的 422 校验。
4. **`search_with_trace` 异常留痕**：403（未勾选 KB）= `denied`、其余 = `error`，落 `trace_events.status`（含 `error_detail`）。

## 部署

- 镜像：`agent-joker-api:s04`→`s05`、`agent-joker-bff:s02`→`s05`（`docker compose build` + `create` + `start` 平滑替换；8080/8000 端口/卷/网络不变，无数据丢失——数据在 joker-pg 独立实例）。
- 启动命令：`cd deploy && docker compose up -d`（api + bff + pg + redis 全 healthy）。
- 实测回写（`docker stats`）：joker-api 75.8Mi/1Gi、joker-bff 48.4Mi/512Mi、joker-pg 63.5Mi/1Gi、joker-redis 8.7Mi/256Mi（均 healthy）。无新增宿主端口。
- 台账 `~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md` 已更新（joker-api/joker-bff 镜像版本 s05 + 项目关系行 + S05 部署更新记录）。

## 自测命令与结果

- **S05 E2E：`python3 05-temp/e2e_s05.py` → 44/44 PASS**（`05-temp/e2e_s05_run2.log`）。真实 HTTP（127.0.0.1:8080 api / 127.0.0.1:8000 bff）+ 真实 PG + mock reranker（Jina 兼容 /rerank，容器经 Docker 网关访问宿主）。覆盖：
  - topK 正确（top_k 覆盖 + 库级默认回落 3）
  - 阈值过滤（=1.0→0 条；=0.0→全召回）
  - 有/无 rerank 两种阈值语义（mock rerank 分数面 0.5 只留高相关 / 余弦面 docD 保留；`use_rerank=false` 显式关闭）
  - 返回含 chunk_index + pos（与 chunk 表一致）
  - official 两级判定 4 矩阵（文档级 official 优先 / NULL 继承库级 / 文档级 internal 覆盖 / NULL+NULL）
  - rag_search MCP 工具可调用（非 501 stub，返回 items）+ MCP 无 Bearer token 401
  - 未勾选 KB 的 agent 检索 403 / 已勾选 200 / 检索未勾选 KB2 403
  - trace rag 事件落痕（>=2）+ trace_sessions.rag_call_count 累计
  - 跨租户/不存在库 404 / 空 query 422 / 内部未签名 401 / 缺 rag:search scope 403
  - S04 回归：kb 列表含 vec_table/vec_table_exists
- **S04 回归：`python3 05-temp/e2e_s04.py` → 40/40 PASS**
- **S02 回归：`bash 05-temp/smoke_s02.sh` → 27/27 PASS**（2 处断言更新：`/internal/storage/rag-search` 由 501 stub→已实装 404；MCP `rag_search` 由 stub 错误文本→已实装）
- **S01 回归：`bash 05-temp/smoke_s01.sh` → 21/21 PASS**

## 遗留问题 / 风险

- 真实 LLM 端点（34.121.9.233:4000/v1）当前 401（S03 已记录环境态，非代码缺陷）；本切片 embedding 走 local-fallback 256 维确定性 n-gram 闭环，检索/阈值/排序不受影响。接入真实 embedding 端点后自动生效（维度随库快照，无需改代码）。
- rerank 用 Jina 兼容 `/rerank` 契约（推测，S03 已记）；当前环境无 active reranker → 默认跳过 rerank，E2E 用 mock reranker 验证 rerank 路径。
- 内部检索 user_id=None 回退「租户首个 active 用户」仅为满足 `trace_sessions.user_id NOT NULL` 的留痕需要（D-B），非真实用户身份；S09 trace 切片如引入机器身份专用用户/系统用户可替换此回退策略。
- `/internal/storage/rag-search` 为 S02 契约兼容别名，规范路径 = `/internal/rag/search`（BFF 已用规范路径）；后续 S11 集成可评估是否保留别名。
