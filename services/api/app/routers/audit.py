"""AuditLogService 查询端点（BASE-06）。

GET /api/audit/logs — 时间范围/用户/接口/状态码 多维筛选（BASE-06 验收 2），
强制租户过滤（tenant_id 打头索引，BASE-07）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import auth_context, db_session, require_scope
from joker_shared.timeutil import parse_iso8601

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/logs")
async def list_logs(
    start: str | None = Query(None, description="ISO8601 start (UTC)"),
    end: str | None = Query(None, description="ISO8601 end (UTC)"),
    user_id: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    require_scope("trace:read", auth=auth)
    t = auth["tenant_id"]
    where = ["tenant_id = :t"]
    params: dict = {"t": t, "ps": page_size, "off": (page - 1) * page_size}
    # BUG-03 修复：start/end 解析为 aware datetime（asyncpg 不接受裸字符串）
    if start:
        try:
            params["start"] = parse_iso8601(start)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid start (ISO8601)")
        where.append("created_at >= :start")
    if end:
        try:
            params["end"] = parse_iso8601(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid end (ISO8601)")
        where.append("created_at <= :end")
    if user_id:
        where.append("user_id = :uid"); params["uid"] = user_id
    if path:
        where.append("path LIKE :path"); params["path"] = f"%{path}%"
    if status_code is not None:
        where.append("status_code = :sc"); params["sc"] = status_code
    wsql = " AND ".join(where)

    total = (await session.execute(
        text(f"SELECT count(*) FROM api_audit_logs WHERE {wsql}"), params
    )).scalar()
    rows = await session.execute(
        text(
            f"""
            SELECT id, tenant_id, user_id, method, path, query_digest, request_digest,
                   status_code, latency_ms, client_ip, created_at
            FROM api_audit_logs WHERE {wsql}
            ORDER BY created_at DESC LIMIT :ps OFFSET :off
            """
        ),
        params,
    )
    items = [
        {
            "id": str(r[0]), "tenant_id": str(r[1]) if r[1] else None,
            "user_id": str(r[2]) if r[2] else None,
            "method": r[3], "path": r[4],
            "query_digest": r[5], "request_digest": r[6],
            "status_code": r[7], "latency_ms": r[8], "client_ip": r[9],
            "created_at": r[10].isoformat() if r[10] else None,
        }
        for r in rows.fetchall()
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
