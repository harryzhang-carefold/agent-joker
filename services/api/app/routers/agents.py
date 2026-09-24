"""Agent 管理端点（S07，AGENT-01/02/03/04/07/08）。

scope 门禁（DB_DESIGN §1.2 / DECISION-004）：
- 管理（增删改/配置）→ `agents:manage`（缺失 403）
- 对话/读会话/记忆 → `agent:use:<agent_id>` 或 `agent:use:*` 通配（缺失 403）
- 租户隔离：全部数据端点强制 tenant_id = X-Auth-Tenant（跨租户 404 不泄露存在性）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import auth_context, db_session, require_scope, scope_allows
from joker_shared.agents import get_agent_service

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _svc():
    return get_agent_service()


def _can_use(auth: dict, agent_id: str) -> None:
    """agent:use 门禁（精确 scope 或 agent:use:* 通配，DECISION-004）。"""
    if not scope_allows(auth["scopes"], f"agent:use:{agent_id}"):
        raise HTTPException(403, f"missing scope: agent:use:{agent_id}")


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "module": "agents", "phase": "S07-agents"}


# ============================================================ 元数据（AGENT-01/02）


@router.get("")
@router.get("/")
async def list_agents(
    status: str | None = Query(None, pattern="^(active|disabled)$"),
    type: str | None = Query(None, pattern="^(simple|third_party)$"),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """本租户 agent 列表（A01 验收 1 可管理可见）。"""
    require_scope("agents:manage", auth=auth)
    return await _svc().list_agents(session, auth["tenant_id"], status, type)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """agent 详情 + 四要素回显（A03 验收 2）。"""
    require_scope("agents:manage", auth=auth)
    d = await _svc().get_full_agent(session, auth["tenant_id"], agent_id)
    return d


@router.post("", status_code=201)
@router.post("/", status_code=201)
async def create_agent(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """创建 agent（A01 验收 1/2）：name 租户内唯一；type=third_party 需 third_party_url；
    自动建 `agent:use:<id>` scope + 授权（DB_DESIGN §1.2）；可一并传四要素勾选。"""
    require_scope("agents:manage", auth=auth)
    return await _svc().create_agent(session, auth["tenant_id"], auth["user_id"], body)


@router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """编辑 agent（A02 验收 1）：元数据 + 四要素勾选（提供键才变更，回显正确）。"""
    require_scope("agents:manage", auth=auth)
    return await _svc().update_agent(session, agent_id, auth["tenant_id"], auth["user_id"], body)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除（软删，A01 验收 2）：会话/消息保留；配置引用清理；scope+动态角色清理。"""
    require_scope("agents:manage", auth=auth)
    return await _svc().delete_agent(session, agent_id, auth["tenant_id"], auth["user_id"])


# ============================================================ 对话（AGENT-04/05/06）


@router.post("/{agent_id}/chat")
async def agent_chat(
    agent_id: str,
    body: dict,
    request: Request,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """对话主入口（A04 验收 1；simple→SAR / third_party→URL 代理）。

    body: {message, session_id?, show_citations?, files?: [{file_name, content, content_type?}]}
    用户 Access Token 取 Authorization: Bearer（BFF 透传）→ ToolInterceptor 强制注入工具入参。
    返回 {session_id, reply, citations, tool_calls, tokens, ...}。
    """
    _can_use(auth, agent_id)
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(422, "message is required")
    # 用户 access token（DECISION-015 ②：拦截器注入工具入参；BFF 已校验签名）
    access_token = ""
    hz = request.headers.get("authorization", "")
    if hz.lower().startswith("bearer "):
        access_token = hz[7:].strip()
    return await _svc().chat(
        session,
        tenant_id=auth["tenant_id"],
        user_id=auth["user_id"] or "",
        scopes=auth["scopes"],
        agent_id=agent_id,
        message=message,
        session_id=body.get("session_id"),
        show_citations=body.get("show_citations"),
        access_token=access_token or (body.get("access_token") or ""),
        files=body.get("files") or [],
    )


# ============================================================ 会话/消息（AGENT-04）


@router.get("/{agent_id}/sessions")
async def list_sessions(
    agent_id: str,
    status: str | None = Query(None, pattern="^(active|closed)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """会话列表（A04 验收 2：本租户+本 agent+本用户）。"""
    _can_use(auth, agent_id)
    return await _svc().list_sessions(
        session, auth["tenant_id"], auth["user_id"], agent_id, status, page, page_size
    )


@router.get("/{agent_id}/sessions/{session_id}/messages")
async def session_messages(
    agent_id: str,
    session_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """对话详情（A04 验收 3）：完整消息流（含 tool_calls/citations/file_ids）。"""
    _can_use(auth, agent_id)
    sess = await _svc().get_session(session, auth["tenant_id"], auth["user_id"], session_id)
    if sess is None or sess["agent_id"] != agent_id:
        raise HTTPException(404, f"session not found: {session_id}")
    return await _svc().list_messages(session, auth["tenant_id"], session_id)


@router.post("/{agent_id}/sessions")
async def create_session(
    agent_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """新建会话（A04）。"""
    _can_use(auth, agent_id)
    return await _svc().create_session(
        session, auth["tenant_id"], auth["user_id"] or "", agent_id, body.get("title")
    )


@router.patch("/{agent_id}/sessions/{session_id}")
async def rename_session(
    agent_id: str,
    session_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """重命名会话（A04 验收 4）。"""
    _can_use(auth, agent_id)
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(422, "title is required")
    sess = await _svc().get_session(session, auth["tenant_id"], auth["user_id"], session_id)
    if sess is None or sess["agent_id"] != agent_id:
        raise HTTPException(404, f"session not found: {session_id}")
    return await _svc().rename_session(session, auth["tenant_id"], auth["user_id"], session_id, title)


@router.post("/{agent_id}/sessions/{session_id}/close")
async def close_session(
    agent_id: str,
    session_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """关闭会话（A04 验收 4）：触发沉淀（长期记忆 + obsidian 笔记，AGENT-07/08）。"""
    _can_use(auth, agent_id)
    sess = await _svc().get_session(session, auth["tenant_id"], auth["user_id"], session_id)
    if sess is None or sess["agent_id"] != agent_id:
        raise HTTPException(404, f"session not found: {session_id}")
    out = await _svc().close_session(session, auth["tenant_id"], auth["user_id"], session_id)
    return out


@router.delete("/{agent_id}/sessions/{session_id}")
async def delete_session(
    agent_id: str,
    session_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """会话删除（软删，A04 验收 4）。"""
    _can_use(auth, agent_id)
    sess = await _svc().get_session(session, auth["tenant_id"], auth["user_id"], session_id)
    if sess is None or sess["agent_id"] != agent_id:
        raise HTTPException(404, f"session not found: {session_id}")
    return await _svc().delete_session(session, auth["tenant_id"], auth["user_id"], session_id)


# ============================================================ 记忆/笔记（AGENT-07/08）


@router.get("/{agent_id}/memories")
async def list_memories(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """长期记忆列表（A07 验收 2 跨会话可引用；用户级 + agent 级）。"""
    _can_use(auth, agent_id)
    return await _svc().list_memories(session, auth["tenant_id"], auth["user_id"] or "", agent_id, limit)


@router.get("/{agent_id}/notes")
async def list_notes(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """obsidian 沉淀笔记（A08 验收 3 后续对话引用）。"""
    _can_use(auth, agent_id)
    return await _svc().list_notes(session, auth["tenant_id"], agent_id, limit)
