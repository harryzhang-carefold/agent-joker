"""MCP 注册管理端点（S06，MCP-01/02/03）。

scope 门禁（DB_DESIGN §10.2 内置 scope）：
- 管理（注册/编辑/删除/刷新/工具启用禁用删除）需 `mcp:manage`（缺失 → 403）
- 读（列表/详情/工具列表/缓存）`mcp:manage` 或 `mcp:tool`（对话级可见工具清单，
  供 S07 agent 配置界面候选列表）

租户隔离：全部数据端点强制 tenant_id = X-Auth-Tenant（跨租户 server 404 不泄露存在性）。
平台内置 server（is_platform=true）：系统租户行；管理面（is_platform_admin 上下文）
可见；不可编辑/删除（409）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import auth_context, db_session, require_scope
from joker_shared.mcp import get_mcp_registry

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _svc():
    return get_mcp_registry()


def _require_manage(auth: dict) -> None:
    require_scope("mcp:manage", auth=auth)


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "module": "mcp", "phase": "S06-mcp"}


# ============================================================ server（MCP-01）

@router.get("/servers")
async def list_servers(
    status: str | None = Query(None, pattern="^(online|offline|unreachable|disabled)$"),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """本租户 MCP server 列表（含平台内置行，source 视角统一展示）。

    读门禁：`mcp:manage` 或 `mcp:tool`（对话级可见候选清单）。
    """
    require_scope("mcp:manage", "mcp:tool", auth=auth)
    items = await _svc().list_servers(session, auth["tenant_id"], status)
    return items


@router.get("/servers/{server_id}")
async def get_server(
    server_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """server 详情；404（不存在/跨租户）。"""
    d = await _svc().get_server(session, server_id, auth["tenant_id"])
    if d is None:
        raise HTTPException(404, f"server not found: {server_id}")
    return d


@router.post("/servers", status_code=201)
async def register_server(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """URL 注册 MCP server（MCP-01）。

    必选 name/url；可选 transport(streamable_http|sse，默认 streamable_http)/
    auth_headers（对象，Fernet 加密落库 auth_headers_enc，响应只回 auth_headers_set）。
    注册即做连通性探测 + 工具全量同步（DECISION-010）：
    成功 → status=online + sync.ok=true；失败 → server 保留为 unreachable + sync.error。
    """
    _require_manage(auth)
    return await _svc().register_server(session, auth["tenant_id"], auth["user_id"], body)


@router.put("/servers/{server_id}")
async def update_server(
    server_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """编辑已注册 server（MCP-01 验收 3）：name/url/transport/status/disable 启用。

    `status=disabled` = 禁用 server（工具全部不可用）；`status=online` 且 url 变更时
    建议随后 POST /servers/{id}/refresh 重新同步。平台内置 server → 409。
    """
    _require_manage(auth)
    return await _svc().update_server(session, server_id, auth["tenant_id"], auth["user_id"], body)


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: str,
    confirm: bool = Query(False),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除 server（MCP-01 验收 3 + MCP-03）。

    有 agent 引用（agent_mcp_tools 勾选该 server 的工具）且 confirm=false →
    409 + `referring_agents` 清单（需确认）；confirm=true → 软删 + 关联 agent 失去工具。
    无引用 → 直接删除。平台内置 → 409。
    """
    _require_manage(auth)
    return await _svc().delete_server(session, server_id, auth["tenant_id"], auth["user_id"], confirm)


@router.post("/servers/{server_id}/refresh")
async def refresh_server(
    server_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """手动刷新全量同步（MCP-02 / DECISION-010）：tools/list 探测 + upsert 同步
    + removed_remote 反向标记 + 缓存失效。调用失败触发一次重新同步亦走此端点
    （S08 ToolInterceptor 调用失败后调用）。"""
    _require_manage(auth)
    row = await _svc().get_server(session, server_id, auth["tenant_id"])
    if row is None:
        raise HTTPException(404, f"server not found: {server_id}")
    result = await _svc().probe_and_sync(session, server_id, auth["tenant_id"], auth["user_id"])
    return {"server_id": server_id, **result}


@router.get("/servers/{server_id}/referring-agents")
async def server_referring_agents(
    server_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """该 server 的关联调用方（MCP-03，供删除/禁用前提示）。"""
    if await _svc().get_server(session, server_id, auth["tenant_id"]) is None:
        raise HTTPException(404, f"server not found: {server_id}")
    return await _svc().referring_agents(session, None, server_id)


# ============================================================ tools（MCP-02）

@router.get("/servers/{server_id}/tools")
async def list_tools(
    server_id: str,
    status: str | None = Query(None, pattern="^(enabled|disabled|removed)$"),
    source: str | None = Query(None, pattern="^(remote|platform)$"),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """server 工具列表（MCP-02 验收 1/4）：名称/描述/入参 schema/来源/状态。

    含平台内置工具（source=platform）与远端工具（source=remote）；
    `usable` = enabled && !removed_remote && server online（agent 可见可用工具语义）。
    """
    require_scope("mcp:manage", "mcp:tool", auth=auth)
    return await _svc().list_tools(session, server_id, auth["tenant_id"], status, source)


@router.post("/tools/{tool_id}/disable")
async def disable_tool(
    tool_id: str,
    confirm: bool = Query(False),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """禁用工具（MCP-02 验收 2 + MCP-03）：agent 侧不可调用（从可用工具剔除；
    S08 拦截器按 enabled 拒绝调用）。有 agent 引用且 confirm=false → 409 + 清单。"""
    _require_manage(auth)
    return await _svc().set_tool_enabled(session, tool_id, auth["tenant_id"], auth["user_id"],
                                         enabled=False, confirm=confirm)


@router.post("/tools/{tool_id}/enable")
async def enable_tool(
    tool_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """启用工具（恢复可调用）。已 removed_remote 的工具 → 409（需先 refresh 复活）。"""
    _require_manage(auth)
    return await _svc().set_tool_enabled(session, tool_id, auth["tenant_id"], auth["user_id"], enabled=True)


@router.delete("/tools/{tool_id}")
async def delete_tool(
    tool_id: str,
    confirm: bool = Query(False),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除工具（MCP-02 验收 3：平台侧移除，不删远端工具）；删除后不可选。

    有 agent 引用且 confirm=false → 409 + `referring_agents` 清单（MCP-03）。
    """
    _require_manage(auth)
    return await _svc().delete_tool(session, tool_id, auth["tenant_id"], auth["user_id"], confirm)


@router.get("/tools/{tool_id}/referring-agents")
async def tool_referring_agents(
    tool_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """该工具的关联调用方（MCP-03）。"""
    from sqlalchemy import text

    row = await session.execute(
        text("SELECT 1 FROM mcp_tools t JOIN mcp_servers s ON s.id = t.server_id "
             "WHERE t.id = CAST(:id AS uuid) AND (s.tenant_id = CAST(:t AS uuid) OR s.is_platform = true)"),
        {"id": tool_id, "t": auth["tenant_id"]},
    )
    if row.first() is None:
        raise HTTPException(404, f"tool not found: {tool_id}")
    return await _svc().referring_agents(session, tool_id, None)


# ============================================================ 工具 schema 缓存（DECISION-010）

@router.get("/servers/{server_id}/tools-cache")
async def tools_cache(
    server_id: str,
    refresh: bool = Query(False),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """工具 schema/scope 快照（Redis 10min TTL；S08 ToolInterceptor 消费入口）。

    refresh=true 强制绕过缓存重建（手动/调用失败触发的重新同步走 /refresh）。
    出参含 cache=hit|miss|refreshed。
    """
    require_scope("mcp:manage", "mcp:tool", auth=auth)
    return await _svc().get_tools_cached(session, server_id, auth["tenant_id"], refresh)
