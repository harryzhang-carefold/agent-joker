# DEV_REPORT_S38 — agent-joker RAG 三缺陷修复（md 支持 + reindex 状态一致性 + 检索向量化容错）

- 任务：S38（t_bda82f31，zhangbeihai）
- 日期：2026-09-30
- 上游：S37 终审 PASS 交付（5d741a8 / push 后远端最终态）；用户 2026-09-30 报 3 个 RAG 缺陷（主 agent 本地复现定因）

## 1. 任务与根因核对

| # | 缺陷（用户报） | 根因（代码定位） |
|---|---|---|
| ① | RAG 不支持 md | `parser.py:36 SUPPORTED_TYPES` 无 `md`；`DOC_TYPE_BY_EXT` 无 `.md` → 上传 `.md` 直接 422 `unsupported file type`。前端 `KbDetailView.vue` 的 `accept` 已含 `.md`（文件选择器放行），但后端拒绝 |
| ② | 上传后切分/检索出错 + 对比按钮无法点击 | reindex（换 embedding 模型）完成后，该库 `failed` 文档**不刷新**：reindex 只重嵌入已有 chunk、不重算 failed 文档。旧文档永久停在 `failed`+旧错误 → 前端「对比」按钮 `:disabled="row.status !== 'ready' && row.status !== 'embedded'"` 持续不可点（UI 无感知）。切分/检索出错本质是文档 failed 后无自动恢复 |
| ③ | 检索首次 500（httpcore 连接失败） | `retrieval.search_kbs` 查询向量化 `embed_texts` **无重试**：embedding 端点瞬时连接失败 → 裸 ASGI 500 + traceback 透传前端（复现：首次 500，重试 3/3 200） |

> 用户报的「②切分/检索出错」与「③对比按钮不可点」是**同一根因**的两面：文档 failed 卡死 → 无 chunk → 检索命中不到 + 对比按钮 disabled。S38 修 ② 的 reindex 一致性后，③ 的对比按钮随文档 ready 自动恢复可点（已自测验证）。

## 2. 代码改动（4 后端文件 + 1 前端已就位 + 2 部署/文档）

| 文件 | 改动 |
|---|---|
| `services/shared/joker_shared/rag/parser.py` | `SUPPORTED_TYPES` 加 `"md"`；`DOC_TYPE_BY_EXT` 加 `.md`/`.markdown`→`md`；`parse_document` 入口 `doc_type in ("txt","md")` 走 `_parse_txt`（markdown 按纯文本解析，**不做 markdown 语义切分**）；模块 docstring 加 md 行 |
| `services/shared/joker_shared/rag/service.py` | 新增 `_requeue_failed_docs()`：reindex 完成后查该库 `status='failed'` 文档 → 逐文档状态回 `uploaded` + `enqueue`（复用 retry 语义，worker 从 parsing 重算）。`_run_reindex` 成功路径（切换 active 后）调用它，try/except 兜底（requeue 失败不影响库已 active） |
| `services/shared/joker_shared/rag/retrieval.py` | 新增 `_embed_query_with_retry()`：查询 embed 失败 1 次重试（2s 退避）；仅对网络/5xx 错误重试，4xx 业务错误原样抛；仍失败 → 可读 502（`embedding 服务暂时不可用（已自动重试 1 次仍失败）…`），不裸 500 traceback。`search_kbs` 查询向量化改走该函数 |
| `services/api/app/routers/rag.py` | doc-file `media` 加 `md: text/markdown; charset=utf-8`；上传/reindex docstring 同步（7 类 / S38 语义） |
| `frontend/src/views/rag/KbDetailView.vue` | **无需改**：`accept` 已含 `.md`；「对比」按钮 disabled 逻辑随文档 ready 自动恢复（缺陷③ 由② 修复连带解决）。`CompareView.vue` 左栏渲染已支持 `md`（`type === 'md'` 走文本高亮） |
| `deploy/docker-compose.yml` | 镜像 tag `api:s36→s38`、`webconsole:s36→s38` |
| `02-development/API_NOTES.md` | rag 章节：6 类→7 类（md）；reindex 行加 S38 自动重算语义；search 行加 502 容错语义 |

**BFF 无需改**：`/api/` 前缀统一转发 platformapi。

## 3. 部署（docker compose，s38 镜像）

```
cd deploy && docker compose build api webconsole && docker compose up -d api webconsole
```
- `agent-joker-api:s38` / `agent-joker-webconsole:s38`，两容器 **healthy**（bff s32 / pg / redis 未动）。
- **容器实码核验**（`docker exec` 铁证，非自报）：
  - `joker-api` `grep SUPPORTED_TYPES /app/joker_shared/rag/parser.py` → `("txt","md","docx","xlsx","pdf","png","jpg")`（L37）
  - `joker-api` `grep '_requeue_failed_docs' /app/joker_shared/rag/service.py` → L1080（reindex 调用）+ L1097（函数定义）
  - `joker-api` `grep '_embed_query_with_retry' /app/joker_shared/rag/retrieval.py` → L119（定义）+ L226（search 调用）
  - `joker-api` `grep 'text/markdown' /app/api/app/routers/rag.py` → L281
  - `joker-webconsole` `grep -rl ".txt,.md,.docx" assets/` → `KbDetailView-CRrQ3Qrg.js`（bundle 含 md accept）
- 健康：`joker-api/bff/webconsole` 全 healthy；`localhost:8080/healthz` = 200 `ok`。

## 4. 自测（真实 HTTP 全链路，localhost:8080 → bff → api → pg，零 mock）

脚本 `05-temp/s38/probe_s38.py`，结果 **15/15 PASS**（17 份原始 HTTP 响应日志
`03-testing/dev_probe_s38_01..17`，含完整请求/响应体）：

| # | 步骤 | 结果 | 对应缺陷 |
|---|---|---|---|
| 1 | 登录 acme/admin | 200 | — |
| 2 | 建 3 个 embedding 模型（好=真实 1536 端点 34.64.61.208 / 坏=不可达 256 / 坏2=不可达 1536） | 201×3 | — |
| 3 | **md 支持**：建 1536 库 → 上传 `.md` → 201（修复前 422） | 201, doc_type=md | ① |
| 4 | md 文档轮询至 ready | status=ready, parse_method=text | ① |
| 5 | 检索命中 md 唯一标记词 | 200, top1=0.53712, content 含 `s38_md_unique_marker_zebra_quartz` | ① |
| 6 | **reindex 一致性**：坏 256 端点建库 + 上传 txt → 流水线 failed | status=failed, err=ConnectError | ② |
| 7 | `POST /kbs/{id}/reindex`（换真实 1536 模型） | 200, status=reindexing | ② |
| 8 | 等库 active（reindex 完成） | status=active, dim=1536 | ② |
| 9 | **failed 文档自动重算**（无需手动 retry） | status=ready, error_message 清空（旧=ConnectError） | ② |
| 10 | **检索 502 容错**：不可达 1536 端点建库 → 检索 | **502** 可读 `embedding 服务暂时不可用（已自动重试 1 次仍失败）…（ConnectError）` | ③ |
| 11 | 502 响应无 Traceback/asyncpg/httpcore 泄露 | PASS（body 无裸 traceback） | ③ |
| 12 | 502 含 2s 退避重试 | elapsed=2.0s | ③ |
| 13 | reindex 后 1536 维库正常检索命中 | 200, 3 hits, top1=0.80363 | ② |
| 14 | 清理（禁用 4 模型 + 删 3 库） | 200×7 | — |

**关键铁证（防造假）**：
- md：上传 201 + doc_type=md + ready + 检索命中真实 md 内容（含代码块/标题/列表）。
- reindex 一致性：failed→reindex→**自动** ready（全程无手动 `/retry` 调用）+ error_message 清空。
- 502 容错：真实 ConnectError → 502 可读中文 + 无 traceback + 2.0s 退避（证明重试确实发生）。

## 5. 已知问题 / 边界

1. **reindex 期间（reindexing 态）检索走旧表**：旧表维度=旧模型，查询用旧模型向量化（reindex 切换 `embedding_model_id` 后，旧表向量仍在，语义一致）。reindex 完成后切新表。failed 文档的重算在 reindex 完成（active）后异步触发，与主流程无竞争（worker 单并发串行）。
2. **重算失败保持 failed**：若 requeue 后重算仍失败（如新端点也不可达），worker 异常分支置 failed + 刷新 error_message（符合任务要求「重算失败保持 failed 并刷新 error_message」）。本自测用可达 1536 端点验证成功路径；失败路径逻辑与 S36 retry 一致（已测）。
3. **md 按纯文本解析**：不做 markdown 语义切分（任务明确）。表格/代码块按文本流切分（fixed 策略），非结构化表格块。
4. **502 重试仅 1 次**：任务要求 1 次重试（2s 退避）。4xx（模型不存在/禁用）不重试、原样抛（404/409 语义保留）。
5. **前端无改动**：KbDetailView accept 已含 `.md`、CompareView 已支持 md 渲染、对比按钮 disabled 随状态恢复——均为既有代码，无需 rebuild 前端（webconsole 镜像随 api 同源重建以统一 tag，bundle 实码核验含 md）。

## 6. 台账回写

SERVER_REGISTRY.md 已更新：joker-api / joker-webconsole 镜像 tag s36→s38 + S38 修复说明 + 实测内存占用。

## 7. 交接

- 交付 S39（t_d5ad526f，yuntianming 复测）：重点复测 md 上传→ready→检索、reindex 后 failed 自动恢复、检索 502 容错。
- 证据：`03-testing/dev_probe_s38_01..17`（原始 HTTP）+ `05-temp/s38/probe_s38.py`（可复跑）。
- **不 push**（push 由 S40 终审 chuyan 统一）。
