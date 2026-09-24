"""RAGService 端点（S04：RAG-01/02/03/04/05/11 + 建库/向量化流水线；S05：检索 RAG-06..10）。

scope 门禁（与 init_schema 平台级 scope 对齐）：
- 库/文档/chunk 管理（增删改/重切分/重嵌入）→ `kb:manage`
- 读（列表/详情/原文/chunk 列表/定位/对比）→ `storage:read`（原文经存储读取）
  或 `kb:manage`（管理面同域；admin 两者都有）
- 上传文档 → `kb:manage`（库级操作；存储侧另记 source=kb 上传记录）
- 检索（S05）→ `rag:search`

租户隔离：全部数据端点强制 tenant_id = X-Auth-Tenant（行级，跨租户 404）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import auth_context, db_session, require_scope
from joker_shared.rag import service as rag
from joker_shared.rag import retrieval

router = APIRouter(prefix="/api/rag", tags=["rag"])
internal_router = APIRouter(prefix="/internal/rag", tags=["rag-internal"])


def _require_kb_manage(auth: dict) -> None:
    require_scope("kb:manage", auth=auth)


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "module": "rag", "phase": "S04-rag"}


# ============================================================ 知识库（RAG-01）

@router.get("/kbs")
async def list_kbs(
    status: str | None = Query(None, pattern="^(active|reindexing|disabled)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """知识库列表（本租户；含文档数/配置摘要；D-C 每库独立向量表信息）。"""
    require_scope("kb:manage", auth=auth)
    return await rag.list_kbs(session, auth["tenant_id"], status=status, page=page, page_size=page_size)


@router.post("/kbs", status_code=201)
async def create_kb(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """建库（RAG-01）：选 embedding 模型（必选，来自 LLM-02）→ 固化 embedding_dim（D-C
    建库快照）→ 动态建独立向量表 rag_chunks_vec_<kb_id>（HNSW 按实际维度）。
    404 embedding 不存在；409 模型 disabled / 库重名。"""
    _require_kb_manage(auth)
    return await rag.create_kb(session, auth["tenant_id"], auth["user_id"], body)


@router.get("/kbs/{kb_id}")
async def get_kb(
    kb_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    d = await rag.get_kb(session, auth["tenant_id"], kb_id)
    if d is None:
        raise HTTPException(404, f"kb not found: {kb_id}")
    return d


@router.put("/kbs/{kb_id}")
async def update_kb(
    kb_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """更新库配置（name/description/tag/检索参数/切分默认/status；D-A 库级 tag）。
    换 embedding 模型 → 用 POST /kbs/{id}/reindex（全库重算向量，D-C）。"""
    _require_kb_manage(auth)
    return await rag.update_kb(session, auth["tenant_id"], auth["user_id"], kb_id, body)


@router.delete("/kbs/{kb_id}")
async def delete_kb(
    kb_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除库：级联删文档/chunk + DROP 独立向量表（RAG-01 验收 5）。"""
    _require_kb_manage(auth)
    return await rag.delete_kb(session, auth["tenant_id"], kb_id)


@router.post("/kbs/{kb_id}/reindex")
async def reindex_kb(
    kb_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """换 embedding 模型 = 全库重算向量（D-C / DECISION-024 流程 c）：
    影子表（新维度）→ 全量重嵌入（status=reindexing，期间检索走旧表）→ 切换 → DROP 旧表。
    体：{embedding_model_id: UUID}。异步执行；GET /kbs/{id} 查 status。"""
    _require_kb_manage(auth)
    if not body.get("embedding_model_id"):
        raise HTTPException(422, "embedding_model_id is required")
    return await rag.reindex_kb(session, auth["tenant_id"], auth["user_id"], kb_id, body["embedding_model_id"])


# ============================================================ 文档（RAG-02）

@router.post("/kbs/{kb_id}/docs", status_code=201)
async def upload_doc(
    kb_id: str,
    file: UploadFile = File(...),
    tag: str | None = Query(None, description="文档级 tag（D-A：NULL 继承库级）"),
    split_strategy: str | None = Query(None, description="文档级切分策略覆盖（fixed/parent_child/semantic/structured_tree/table）"),
    split_params: str | None = Query(None, description="文档级切分参数 JSON（如 {\"chunk_size\":300,\"overlap\":30}）"),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """上传文档到知识库（RAG-02，6 类：txt/docx/xlsx/pdf/png/jpg）：
    StorageService 落盘（source=kb，上传记录可查）→ rag_docs（status=uploaded）→
    进程内任务队列（uploaded→parsing→splitting→embedded→ready/failed）。
    422：非支持类型 / .doc 旧格式（提示转 .docx）/ 空文件。"""
    _require_kb_manage(auth)
    import json as _json

    sp = None
    if split_params:
        try:
            sp = _json.loads(split_params)
        except ValueError:
            raise HTTPException(422, "split_params must be valid JSON") from None
    data = await file.read()
    if not data:
        raise HTTPException(422, "empty file")
    return await rag.upload_doc(
        session,
        auth["tenant_id"],
        auth["user_id"],
        kb_id,
        file.filename or "unnamed",
        data,
        file.content_type,
        tag=tag,
        split_strategy=split_strategy,
        split_params=sp,
    )


@router.get("/kbs/{kb_id}/docs")
async def list_docs(
    kb_id: str,
    status: str | None = Query(None, description="uploaded/parsing/splitting/embedded/ready/failed/reindexing"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """文档列表（本库；含状态/parse_method/chunk_count/error_message）。"""
    require_scope("kb:manage", auth=auth)
    return await rag.list_docs(session, auth["tenant_id"], kb_id, status=status, page=page, page_size=page_size)


@router.get("/kbs/{kb_id}/docs/{doc_id}")
async def get_doc(
    kb_id: str,
    doc_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    d = await rag.get_doc(session, auth["tenant_id"], kb_id, doc_id)
    if d is None:
        raise HTTPException(404, f"doc not found: {doc_id}")
    return d


@router.put("/kbs/{kb_id}/docs/{doc_id}")
async def update_doc(
    kb_id: str,
    doc_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """文档级更新：tag（D-A 文档级官方标记）/ split_strategy / split_params。"""
    _require_kb_manage(auth)
    from sqlalchemy import text

    doc = await rag.get_doc(session, auth["tenant_id"], kb_id, doc_id)
    if doc is None:
        raise HTTPException(404, f"doc not found: {doc_id}")
    sets, params = [], {"id": doc_id, "t": auth["tenant_id"], "u": auth["user_id"]}
    if "tag" in body:
        sets.append("tag = :tag"); params["tag"] = body["tag"]
    if "split_strategy" in body:
        from joker_shared.rag.splitter import STRATEGIES

        if body["split_strategy"] not in STRATEGIES:
            raise HTTPException(422, f"split_strategy must be one of {list(STRATEGIES)}")
        sets.append("split_strategy = :ss"); params["ss"] = body["split_strategy"]
    if "split_params" in body:
        import json as _json

        sets.append("split_params = :sp"); params["sp"] = _json.dumps(body["split_params"] or {})
    if not sets:
        raise HTTPException(400, "no fields to update (tag/split_strategy/split_params)")
    sets.append("updated_by = :u")
    await session.execute(
        text(f"UPDATE rag_docs SET {', '.join(sets)} WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"),
        params,
    )
    await session.commit()
    return await rag.get_doc(session, auth["tenant_id"], kb_id, doc_id)


@router.delete("/kbs/{kb_id}/docs/{doc_id}")
async def delete_doc(
    kb_id: str,
    doc_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除文档（级联删 chunk + 向量）。"""
    _require_kb_manage(auth)
    return await rag.delete_doc(session, auth["tenant_id"], kb_id, doc_id)


@router.post("/kbs/{kb_id}/docs/{doc_id}/retry")
async def retry_doc(
    kb_id: str,
    doc_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """failed 文档重试（状态回 uploaded 重新入队）。"""
    _require_kb_manage(auth)
    return await rag.retry_doc(session, auth["tenant_id"], kb_id, doc_id)


@router.post("/kbs/{kb_id}/docs/{doc_id}/resplit")
async def resplit_doc(
    kb_id: str,
    doc_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """重切分（RAG-04 验收 2）：体 {split_strategy?, split_params?}（省略=用当前库/文档配置）。
    删旧 chunk + 重建向量（异步，文档状态 → splitting → ready）。"""
    _require_kb_manage(auth)
    return await rag.resplit_doc(
        session, auth["tenant_id"], kb_id, doc_id,
        body.get("split_strategy"), body.get("split_params"), auth["user_id"],
    )


@router.get("/kbs/{kb_id}/docs/{doc_id}/file")
async def doc_file(
    kb_id: str,
    doc_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """原文档二进制（RAG-05 验收 1 / RAG-11 左栏渲染源；Content-Type 按 doc_type，
    经 StorageService → 后端透明，S02 统一文件 API 同路径）。"""
    require_scope("storage:read", auth=auth)
    doc, data = await rag.doc_file_bytes(session, auth["tenant_id"], kb_id, doc_id)
    media = {
        "txt": "text/plain; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
    }.get(doc["doc_type"], "application/octet-stream")
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'inline; filename="{doc["file_name"]}"'},
    )


# ============================================================ chunk（RAG-05 / RAG-11）

@router.get("/kbs/{kb_id}/docs/{doc_id}/chunks")
async def list_chunks(
    kb_id: str,
    doc_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """chunk 切片列表（右栏；RAG-05 验收 3 / RAG-11 接口 2）：
    {items:[{chunk_id, chunk_index, content, pos, is_table, parent_id, edited_at,...}], total}，
    按 chunk_index 升序。"""
    require_scope("kb:manage", auth=auth)
    return await rag.list_chunks(session, auth["tenant_id"], kb_id, doc_id, page=page, page_size=page_size)


@router.get("/kbs/{kb_id}/docs/{doc_id}/chunks/{chunk_id}/location")
async def chunk_location(
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """chunk → 原文位置（RAG-11 接口 3：右→左联动）：{pos: <pos JSONB 全文>}。"""
    require_scope("kb:manage", auth=auth)
    return await rag.chunk_location(session, auth["tenant_id"], kb_id, doc_id, chunk_id)


@router.get("/kbs/{kb_id}/docs/{doc_id}/chunks/by-location")
async def chunks_by_location(
    kb_id: str,
    doc_id: str,
    pos: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """原文位置 → chunk 反查（RAG-11 接口 4：左→右联动）：
    query pos = JSON（按文档类型子集，见 ARCH §2.2.1 坐标结构表）；
    返回包含该位置的全部 chunk（重叠可能多命中）+ primary_chunk_id（chunk_index 最小）。"""
    require_scope("kb:manage", auth=auth)
    import json as _json

    try:
        p = _json.loads(pos)
    except ValueError:
        raise HTTPException(422, "pos must be valid JSON") from None
    if not isinstance(p, dict):
        raise HTTPException(422, "pos must be a JSON object")
    return await rag.chunks_by_location(session, auth["tenant_id"], kb_id, doc_id, p)


@router.put("/kbs/{kb_id}/docs/{doc_id}/chunks/{chunk_id}")
async def edit_chunk(
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """编辑 chunk 文本（RAG-05 验收 2/4）：体 {content}；更新 content + 重算向量
    写本库向量表（D-C）+ edited_at/updated_by 留痕；右栏刷新、左栏原文不可变。"""
    _require_kb_manage(auth)
    if "content" not in body:
        raise HTTPException(422, "content is required")
    return await rag.edit_chunk(
        session, auth["tenant_id"], kb_id, doc_id, chunk_id, body["content"], auth["user_id"]
    )


# ============================================================ 检索（S05，RAG-06..09）

@router.post("/search")
async def search(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """知识库检索（RAG-06/07/08/09；scope `rag:search`）：
    体 {kb_ids:UUID[]（必选，同租户）, query:str（必选）, top_k?:int,
        score_threshold?:float, use_rerank?:bool=true, agent_id?:UUID}。
    - embedding 模型 = 各库建库快照（D-C 只走本库向量表，多库逐库召回后合并）；
    - rerank 可选（库配 active reranker 时启用；端点不可用降级纯向量）；
    - 阈值语义 DECISION-006：有 rerank 作用 rerank 分、无则余弦相似度；
    - topK/阈值 单次覆盖，未传回落库级默认；
    - 出参每条含 chunk_index + pos（RAG-09 反向定位）+ tag/is_official
      （D-A 两级判定：文档级优先，NULL 继承库级）。
    403 缺 scope / 404 库不存在或跨租户 / 409 库非 active。"""
    require_scope("rag:search", auth=auth)
    kb_ids = body.get("kb_ids")
    if not isinstance(kb_ids, list) or not kb_ids:
        raise HTTPException(422, "kb_ids is required (non-empty list)")
    if not isinstance(body.get("query"), str) or not body["query"].strip():
        raise HTTPException(422, "query is required (non-empty string)")
    return await retrieval.search_with_trace(
        session,
        tenant_id=auth["tenant_id"],
        agent_id=body.get("agent_id"),
        user_id=auth["user_id"],
        kb_ids=[str(k) for k in kb_ids],
        query=body["query"],
        top_k=body.get("top_k"),
        score_threshold=body.get("score_threshold"),
        use_rerank=bool(body.get("use_rerank", True)),
    )


# ============================================================ 内部检索（S05，D-B；供 SAR/BFF 机器凭证调用）

@internal_router.post("/search")
async def internal_search(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """内部 RAG 检索（DECISION-009 签名头；D-B 非拦截范围）。

    与 /api/rag/search 同一核心；附加（D-B / DECISION-023 / ARCH §4.2）：
    - 身份校验 = X-Auth-* HMAC 签名头（中间件，只信头不信体）；
    - `agent_id` 提供时校验 (agent_id, kb_id) ∈ agent_knowledge_bases（未勾选 403）；
    - 落 trace `rag` 事件（不产生 tool_call 事件；S09 SAR 直调路径同端点）。
    契约（S02 stub 501 → 本卡接通）：
      入参 {kb_ids:UUID[]（必选）, query:str（必选）, top_k?:int,
            score_threshold?:float, agent_id?:UUID}
      出参 {items:[{chunk_id, content, kb_id, doc_id, doc_file_name, chunk_index,
             pos, tag, is_official, score, parent_content?}], total,
            top_k, threshold, reranked, agent_id}
    """
    kb_ids = body.get("kb_ids")
    if not isinstance(kb_ids, list) or not kb_ids:
        raise HTTPException(422, "kb_ids is required (non-empty list)")
    if not isinstance(body.get("query"), str) or not body["query"].strip():
        raise HTTPException(422, "query is required (non-empty string)")
    return await retrieval.search_with_trace(
        session,
        tenant_id=auth["tenant_id"],
        agent_id=body.get("agent_id"),
        user_id=auth["user_id"],
        kb_ids=[str(k) for k in kb_ids],
        query=body["query"],
        top_k=body.get("top_k"),
        score_threshold=body.get("score_threshold"),
        use_rerank=bool(body.get("use_rerank", True)),
    )
