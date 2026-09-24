"""StorageService 端点（S02，STORE-01..05）。

两类面：
- `/api/storage/*`：管理面（X-Auth-* 签名头 + scope 校验）
- `/internal/storage/*`：机器凭证代执行面（DECISION-009 签名头，供 PlatformMCPServer；
  无 scope 门禁——拦截/scope 校验由 S08 ToolInterceptor 统一接入，本卡只实现存储语义）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import auth_context, db_session, require_scope
from joker_shared.storage.base import StorageConfigError
from joker_shared.storage.service import get_storage_service

router = APIRouter(prefix="/api/storage", tags=["storage"])
internal_router = APIRouter(prefix="/internal/storage", tags=["storage-internal"])


def _svc():
    try:
        return get_storage_service()
    except StorageConfigError as exc:
        raise HTTPException(503, f"storage backend not configured: {exc}") from exc


# ---------------------------------------------------------------- 管理面

@router.get("/healthz")
async def healthz():
    return {"status": "ok", "module": "storage", "phase": "S02-storage"}


@router.get("/backends")
async def backends(auth: dict = Depends(auth_context)):
    """后端配置状态（不含凭证，DECISION-012）。"""
    require_scope("storage:read", auth=auth)
    return {"items": _svc().backend_status()}


@router.post("/files")
async def upload_file(
    file: UploadFile = File(...),
    source: str = Query("api", description="api / mcp:platform / mcp:<server> / agent / kb / skill"),
    agent_id: str | None = Query(None),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """上传文件（multipart）。同名 → 409；超配额 → 403；空文件 → 422；超限 → 413。"""
    require_scope("storage:write", auth=auth)
    data = await file.read()
    return await _svc().upload(
        session,
        tenant_id=auth["tenant_id"],
        user_id=auth["user_id"],
        file_name=file.filename or "unnamed",
        data=data,
        content_type=file.content_type,
        source=source,
        agent_id=agent_id,
    )


@router.get("/files")
async def list_files(
    prefix: str | None = None,
    status: str | None = None,
    source: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """文件列表（本租户，STORE-04 按文件名访问的前置查询）。"""
    require_scope("storage:read", auth=auth)
    return await _svc().list_files(
        session, auth["tenant_id"], prefix=prefix, status=status, source=source,
        page=page, page_size=page_size,
    )


@router.get("/files/{file_name}")
async def download_file(
    file_name: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """按文件名下载（STORE-04：统一 URL 语义，调用方不感知后端；不存在 404，跨租户 404→由 tenant 行过滤天然实现）。"""
    require_scope("storage:read", auth=auth)
    row, data = await _svc().download(session, auth["tenant_id"], file_name)
    return Response(
        content=data,
        media_type=row["content_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{row["file_name"]}"',
                 "X-Storage-Backend": row["backend"],
                 "X-Storage-File-Id": row["id"]},
    )


@router.delete("/files/{file_name}")
async def delete_file(
    file_name: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除文件（软删 status=deleted + 物理删除；被 RAG 文档引用 → 409）。"""
    require_scope("storage:manage", auth=auth)
    return await _svc().delete_file(session, auth["tenant_id"], file_name)


@router.get("/upload-records")
async def list_upload_records(
    file_name: str | None = None,
    uploader_user_id: str | None = None,
    source: str | None = None,
    status: str | None = None,
    start: str | None = Query(None, description="ISO8601 start (UTC)"),
    end: str | None = Query(None, description="ISO8601 end (UTC)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """上传记录查询（STORE-05：时间范围/文件名/上传者筛选）。"""
    require_scope("storage:read", auth=auth)
    return await _svc().list_upload_records(
        session, auth["tenant_id"], file_name=file_name, uploader_user_id=uploader_user_id,
        source=source, status=status, start=start, end=end, page=page, page_size=page_size,
    )


# ---------------------------------------------------------------- 内部面（机器凭证代执行）
#
# 鉴权 = 中间件 X-Auth-* HMAC（DECISION-009，租户只信签名头）。
# scope 门禁/工具拦截由 S08 ToolInterceptor 统一接入（D-B）；本卡只定义存储语义。
# 契约（供 S08/S13 与 BFF 对接，同步 API_NOTES.md）：
#   POST /internal/storage/upload   multipart（同 /api/storage/files）
#   GET  /internal/storage/files    ?file_name= / 列表
#   GET  /internal/storage/files/{file_name}  下载
#   POST /internal/storage/rag-search  → 501（S05 实装；契约见 API_NOTES）

@internal_router.post("/upload")
async def internal_upload(
    file: UploadFile = File(...),
    source: str = Query("mcp:platform"),
    agent_id: str | None = Query(None),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    data = await file.read()
    return await _svc().upload(
        session,
        tenant_id=auth["tenant_id"],
        user_id=auth["user_id"],
        file_name=file.filename or "unnamed",
        data=data,
        content_type=file.content_type,
        source=source,
        agent_id=agent_id,
    )


@internal_router.get("/files")
async def internal_list(
    file_name: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    if file_name:
        row = await _svc().get_file_row(session, auth["tenant_id"], file_name)
        if row is None:
            raise HTTPException(404, f"file not found: {file_name}")
        return {"items": [row], "total": 1, "page": page, "page_size": page_size}
    return await _svc().list_files(
        session, auth["tenant_id"], page=page, page_size=page_size
    )


@internal_router.get("/files/{file_name}")
async def internal_download(
    file_name: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    row, data = await _svc().download(session, auth["tenant_id"], file_name)
    return Response(
        content=data,
        media_type=row["content_type"] or "application/octet-stream",
        headers={"X-Storage-Backend": row["backend"], "X-Storage-File-Id": row["id"]},
    )


@internal_router.post("/rag-search")
async def internal_rag_search(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """RAG 检索（S02 契约路径；S05 实装）：委托 /internal/rag/search 同一核心
    （D-B (agent_id,kb_id) 勾选校验 + rag trace 留痕；出参含 chunk_index/pos/is_official）。
    规范路径 = /internal/rag/search；本路径保留为 S02 契约兼容别名（1:1 同参同出参）。"""
    kb_ids = body.get("kb_ids")
    if not isinstance(kb_ids, list) or not kb_ids:
        raise HTTPException(422, "kb_ids is required (non-empty list)")
    if not isinstance(body.get("query"), str) or not body["query"].strip():
        raise HTTPException(422, "query is required (non-empty string)")
    from joker_shared.rag import retrieval

    return await retrieval.search_with_trace(
        session,
        tenant_id=auth["tenant_id"],
        agent_id=body.get("agent_id"),
        user_id=auth["user_id"],
        kb_ids=[str(k) for k in (body.get("kb_ids") or [])],
        query=body.get("query") or "",
        top_k=body.get("top_k"),
        score_threshold=body.get("score_threshold"),
    )
