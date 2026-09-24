"""Trace 检索端点（S09，TRACE-02）。

- GET /api/trace/sessions — trace 会话列表（按 agent/用户/状态/时间，租户强制过滤）。
- GET /api/trace/sessions/{sid} — 会话详情（trace_sessions 汇总）。
- GET /api/trace/sessions/{sid}/events — 会话事件时间线（全链路：system/message/tool_call/rag/file）。
- GET /api/trace/events — 事件多维检索（agent/事件类型/时间范围/关键词，TRACE-02 验收 1/2）。

scope：`trace:read`（缺失 403）；租户隔离强制（跨租户 403 不泄露，DB_DESIGN §9 / TRACE-02 验收 3）。
payload 已脱敏（DECISION-012，写点统一 redact）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import auth_context, db_session, require_scope
from joker_shared import trace as _trace

router = APIRouter(prefix="/api/trace", tags=["trace"])


async def _require_tenant_session(session: AsyncSession, sid: str, tenant_id: str) -> None:
    """跨租户 403 判定（trace_sessions.id 为全表主键，须显式比对 tenant，TRACE-02 验收 3）。"""
    t = (
        await session.execute(
            text("SELECT tenant_id FROM trace_sessions WHERE id = CAST(:s AS uuid)"), {"s": sid}
        )
    ).scalar()
    if t is None or str(t) != tenant_id:
        raise HTTPException(403, "cross-tenant trace access denied")


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "module": "trace", "phase": "S09-trace"}


@router.get("/sessions")
async def list_sessions(
    agent_id: str | None = None,
    user_id: str | None = None,
    status: str | None = Query(None, pattern="^(active|ended|failed)$"),
    start: str | None = Query(None, description="ISO8601 start (UTC)"),
    end: str | None = Query(None, description="ISO8601 end (UTC)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """trace 会话列表（按 agent/用户/状态/时间，租户强制过滤）。"""
    require_scope("trace:read", auth=auth)
    return await _trace.list_sessions(
        session, auth["tenant_id"], agent_id=agent_id, user_id=user_id,
        status=status, start=start, end=end, page=page, page_size=page_size,
    )


@router.get("/sessions/{sid}")
async def get_session(
    sid: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """会话详情（trace_sessions 汇总）。跨租户 → 403（不泄露存在性，TRACE-02 验收 3）。"""
    require_scope("trace:read", auth=auth)
    await _require_tenant_session(session, sid, auth["tenant_id"])
    row = await _trace.get_session_row(session, sid)
    if row is None:
        raise HTTPException(404, "trace session not found")
    return row


@router.get("/sessions/{sid}/events")
async def list_session_events(
    sid: str,
    event_type: str | None = Query(None, description="message|file|tool_call|rag|system"),
    start: str | None = Query(None, description="ISO8601 start (UTC)"),
    end: str | None = Query(None, description="ISO8601 end (UTC)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """会话事件时间线（全链路；跨租户 → 403）。"""
    require_scope("trace:read", auth=auth)
    await _require_tenant_session(session, sid, auth["tenant_id"])
    return await _trace.list_events(
        session, auth["tenant_id"], session_id=sid, event_type=event_type,
        start=start, end=end, page=page, page_size=page_size,
    )


@router.get("/events")
async def list_events(
    session_id: str | None = None,
    agent_id: str | None = None,
    event_type: str | None = Query(None, description="message|file|tool_call|rag|system"),
    start: str | None = Query(None, description="ISO8601 start (UTC)"),
    end: str | None = Query(None, description="ISO8601 end (UTC)"),
    keyword: str | None = Query(None, description="关键词（payload 全文，tsvector）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """事件多维检索（会话/agent/事件类型/时间范围/关键词，租户强制过滤）。"""
    require_scope("trace:read", auth=auth)
    return await _trace.list_events(
        session, auth["tenant_id"], session_id=session_id, agent_id=agent_id,
        event_type=event_type, start=start, end=end, keyword=keyword,
        page=page, page_size=page_size,
    )
