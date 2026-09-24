# DEV_REPORT_S04 — agent-joker RAG 解析 + 切分（t_8c8f30e0）

PROGRESS: 100% — 全部交付 + 自测 40/40 PASS，可进入 S05（检索）

## 范围（RAG-01/02/03/04/05/11 + 建库/向量化流水线）

| 项 | 状态 | 说明 |
|---|---|---|
| RAG-01 知识库管理 | ✅ | 建库/更新/删除/列表；建库选 embedding 模型→固化 `embedding_dim`（D-C 建库快照）→动态建独立向量表 `rag_chunks_vec_<kb_id>`（HNSW 按实际维度 N）；删库级联删文档/chunk+DROP 向量表；换模型 reindex（影子表重算→切换→DROP 旧表，期间检索走旧表） |
| RAG-02 文档上传 | ✅ | 6 类文档（txt/docx/xlsx/pdf/png/jpg）经 StorageService 落盘（source=kb，上传记录可查）；状态机 `uploaded→parsing→splitting→embedded→ready/failed`（DECISION-021 进程内队列，worker 单并发串行，每步独立 commit 可断点续做）；.doc 旧格式 422 提示转 .docx |
| RAG-03 文档解析 | ✅ | pymupdf（pdf 文本层+内嵌图+扫描检测）/python-docx（段落/表格/标题层级→section_path）/openpyxl（sheet→Markdown 表格+行列范围）/直读 txt（DECISION-005）；图片/扫描页/内嵌图→视觉 LLM（调 supports_vision endpoint，OpenAI 兼容 chat+image_url data URI）；**视觉不可用→降级**（占位块 `[图片未解析: ...]` + `rag_doc_images.status=skipped` + 日志，不阻断） |
| RAG-04 切分引擎 | ✅ | 5 策略工厂（fixed 500/50、parent_child 父2000子500、semantic 阈值0.25、structured_tree 按 section_path、table 整表/超大表按行组），基于 LangChain text-splitters 思路扩展（DECISION-020）；参数库级默认+文档级覆盖；重切分=删旧 chunk+重建向量 |
| 向量化 | ✅ | chunk embedding 批量（32）写入该库独立向量表（D-C 检索只走本库表） |
| RAG-05 原文查看+编辑 chunk | ✅ | 原文二进制经 StorageService 取回（Content-Type 按 doc_type）；编辑 chunk 文本→重算向量写本库表+`edited_at`/`updated_by` 留痕；右栏刷新、左栏原文不可变 |
| RAG-11 切分对比 | ✅ | 原文档-chunk 双向联动（ARCH §2.2.1）：chunk 列表（含 pos）/ chunk→pos / pos→chunk 反查（重叠多命中+primary_chunk_id）；pos 按文档类型坐标结构（文本=page+char 区间、表格=table_row{sheet,table,row/col 区间}、图片=page） |

## 新增 API 端点清单（全部 `/api/rag`，需 X-Auth-* HMAC 签名头）

scope：管理端点 `kb:manage`；读端点 `kb:manage` 或 `storage:read`。租户行级隔离（跨租户 404）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/kbs` | 知识库列表（含 embedding_dim/vec_table/vec_table_exists/doc_count） |
| POST | `/kbs` | 建库（必选 name+embedding_model_id）；404/409 |
| GET/PUT/DELETE | `/kbs/{kb_id}` | 详情/更新配置/删除（级联 DROP 向量表） |
| POST | `/kbs/{kb_id}/reindex` | 换 embedding 模型=全库重算（D-C 流程 c，异步） |
| POST | `/kbs/{kb_id}/docs` | 上传文档（multipart file + tag/split_strategy/split_params） |
| GET | `/kbs/{kb_id}/docs` | 文档列表（status/parse_method/chunk_count/error_message） |
| GET/PUT/DELETE | `/kbs/{kb_id}/docs/{doc_id}` | 详情/文档级更新（tag/切分配置）/删除 |
| POST | `/kbs/{kb_id}/docs/{doc_id}/retry` | failed 文档重试 |
| POST | `/kbs/{kb_id}/docs/{doc_id}/resplit` | 重切分（删旧 chunk+重建向量，异步） |
| GET | `/kbs/{kb_id}/docs/{doc_id}/file` | 原文档二进制 |
| GET | `/kbs/{kb_id}/docs/{doc_id}/chunks` | chunk 列表（含 pos，chunk_index 升序） |
| GET | `/kbs/{kb_id}/docs/{doc_id}/chunks/{chunk_id}/location` | chunk→pos（右→左） |
| GET | `/kbs/{kb_id}/docs/{doc_id}/chunks/by-location?pos=<JSON>` | pos→chunk 反查（左→右，重叠多命中+primary） |
| PUT | `/kbs/{kb_id}/docs/{doc_id}/chunks/{chunk_id}` | 编辑 chunk+重新嵌入 |
| GET | `/healthz` | 模块健康 |

API 面已同步 `02-development/API_NOTES.md`（新增「rag（RAGService，S04 已实装）」章节 + 占位表更新）。

## 表/索引变更

无新增静态表（34 表定稿，S01 init_schema.sql 已含 rag_knowledge_bases/rag_docs/rag_chunks/rag_doc_images）。
本切片使用既有动态向量表机制：`create_rag_chunks_vec(kb_id, dim)` SQL 函数建
`rag_chunks_vec_<kb_id>`（chunk_id PK FK CASCADE / knowledge_base_id FK CASCADE / embedding vector(N) / HNSW vector_cosine_ops m=16 ef_construction=64）。
S04 未改 init_schema.sql（动态表由建库 API 创建，符合"禁止散落 DDL"约束）。

## 新增文件

- `services/shared/joker_shared/rag/__init__.py`（导出 service/splitter/parser 关键符号）
- `services/shared/joker_shared/rag/parser.py`（555 行：6 类解析 + 视觉分支 + 降级）
- `services/shared/joker_shared/rag/splitter.py`（353 行：5 策略工厂 + effective_strategy）
- `services/shared/joker_shared/rag/service.py`（1069 行：KB/文档/chunk CRUD + 进程内队列流水线 + reindex + 重试）
- `services/api/app/routers/rag.py`（357 行：端点 + scope 门禁）
- `05-temp/e2e_s04.py`（E2E 自测脚本，40 断言）
- 修改：`services/api/app/main.py`（启动/停止 rag doc worker）、`services/requirements.txt`（pymupdf/python-docx/openpyxl）、`02-development/API_NOTES.md`

## 自测命令与结果

```
# 前提：docker compose up -d（joker-api s04 + joker-pg healthy）
cd /home/hermes/hermes-workspace/projects/agent-joker
python3 05-temp/e2e_s04.py            # S04 E2E（真实 HTTP + 真实 PG + 真实 worker）
bash 05-temp/smoke_s02.sh             # S02 回归
bash 05-temp/smoke_s01.sh             # S01 回归
```

结果（docker compose 实测，2026-09-23）：
- **S04 E2E：40/40 PASS**（证据 `05-temp/e2e_s04_run2.log`）：
  登录/找到 local-fallback-embedding(256 维)/建库 201（embedding_dim=256 + 独立向量表已建）
  /上传 txt+docx+xlsx+pdf+png 全 201/.doc 422/5 文档状态机全走到 ready
  （txt=text 9 块、docx=text 4 块、xlsx=text 1 表格块、pdf=text 1 块、png=vision 1 块[视觉降级占位]）
  /5 策略 resplit 各产出 chunk（fixed 9 / parent_child 12 / semantic 240 / structured_tree 10 / table 9）
  /fixed 参数生效（chunk_size 200→22 块 vs 800→6 块）/chunk 列表含 pos
  /chunk→pos 200 /pos→chunk 反查 200 含本 chunk /xlsx 表格 chunk is_table=true + pos=table_row
  /编辑 chunk 200（sha 变 + edited_at 留痕）/向量表含编辑后 chunk 行 count=1 /向量表维度=256
  /跨租户 404 /无 kb:manage scope 403 /删除库 200 + 向量表已 DROP（to_regclass=NULL）。
- **S02 回归：27/27 PASS**（`05-temp/smoke_s02_run.log`）
- **S01 回归：21/21 PASS**（`05-temp/smoke_s01_run.log`）

## 部署

镜像 `agent-joker-api:s03`→`s04`（`docker compose -f deploy/docker-compose.yml up -d --build api` 平滑替换；
8080 端口/卷/网络不变，无数据丢失——数据在 joker-pg 独立实例）。实测 healthy：
joker-api 103.8Mi/1Gi、joker-pg 59.2Mi/1Gi、joker-redis 8.7Mi/256Mi、joker-bff 49.7Mi/512Mi。
台账 `~/hermes-workspace/shared/infrastructure/SERVER_REGISTRY.md` 已更新（joker-api s04 + 动态向量表 + S04 部署记录）。

## 本轮修复（断点续做：上一轮耗预算未重建镜像，旧代码上线导致文档卡 splitting）

1. **向量化 batch 循环解包 bug**（service.py 向量化段）：
   `for (cid, _content), vec in zip([r[0] for r in all_chunks[...]], vecs)` 把裸 UUID 当二元组解包
   → `TypeError: cannot unpack non-iterable UUID` → **每个文档都在 embed 步失败**。
   修：`for cid, vec in zip([str(r[0]) for r in all_chunks[...]], vecs)`。
   上一轮已在 host 源码修好但**未重建镜像**（容器内仍是 20:55 的旧代码），本轮重建后生效。
2. **E2E 测试夹具 bug**（05-temp/e2e_s04.py，仅测试侧，非产品代码）：
   - docx：`'<w:t>概述正文内容。' * 30 + '</w:t></w:r></w:p>'` 字符串拼接优先级错误
     → `*` 先于 `+` 把整段（含 `<?xml...` 声明）重复 30 次 → XML 声明不在开头 → XMLSyntaxError。
     修：把 `*30` 正文预计算为变量再 f-string 拼接。
   - xlsx：手工 zip 缺 `xl/_rels/workbook.xml.rels`（openpyxl 必需）→ KeyError。修：补该 rels 文件。
   修复后夹具在容器内验证：docx 4 段落 / xlsx 3 行解析成功。

## 已知问题 / 遗留（RISK）

- **视觉降级路径已验证不阻断**（png 文档 parse_method=vision，占位块 + `rag_doc_images.status=skipped`，
  文档正常走到 ready），但**当前环境无 supports_vision endpoint**（唯一 LLM 27B 纯文本），
  视觉文字化内容实际不可用 → RISK：扫描 PDF/图片类文档只有占位块、无真实转录。
  待接入视觉模型后自动生效（无需改代码，`_find_vision_endpoint` 取第一个 active+supports_vision=true 的 endpoint）。
- 真实 LLM 端点当前 401（S03 已记录的环境态，非代码缺陷）；本切片 embedding 走 local-fallback（256 维确定性 n-gram），闭环不受影响。
- `rag_doc_images` 图片落盘失败分支用随机 `image_file_id`（非真实文件 id）记 skipped——仅留痕用，无检索依赖；可接受。
- reindex（换模型）闭环逻辑已实现（影子表+逐文档重嵌入+rename 切换+DROP 旧），E2E 未单独跑换模型场景
  （需第二个不同维度的 active embedding 模型；当前仅 local-fallback-embedding 256 维）。S05/S12 可补。
- 6 个占位模块（mcp/skills/agents/trace 等）仍 /healthz 占位，后续切片实装。

## 给 S05（检索）的交接

- 每库独立向量表名：`joker_shared.rag.service.vec_table(kb_id)` = `rag_chunks_vec_<kb_id 去连字符>`，
  维度=该库 `rag_knowledge_bases.embedding_dim`（建库快照，D-C）。
- 向量表结构：`chunk_id UUID PK` / `knowledge_base_id UUID` / `embedding vector(N)`（HNSW vector_cosine_ops，cosine 距离）。
- chunk 元数据在 `rag_chunks`（content/pos JSONB/is_table/parent_id/split_strategy/edited_at/...），
  按 `doc_id`/`knowledge_base_id`/`tenant_id` 过滤；`rag_docs.tag`（D-A：NULL 继承库级 `rag_knowledge_bases.tag`）。
- 检索只走本库表（D-C）；跨库 = 多张独立表分别查后合并（库级 top_k/score_threshold 在
  `rag_knowledge_bases.top_k_default`/`score_threshold`）。
- 内部检索入口契约见 API_NOTES「storage /internal/storage/rag-search」+ MCP `rag_search`（S05 接通后 501→200）。
- embedding 调用：`joker_shared.llm.get_llm_service().embed_texts(session, kb.embedding_model_id, [query])`。
- rerank：`get_llm_service().rerank(session, kb.reranker_model_id, query, docs, top_n)`（当前无 active reranker → 跳过/原序）。
