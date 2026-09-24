"""依赖注入：会话、鉴权上下文。"""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import crypto
from joker_shared.db import current_scopes, current_tenant, current_user, get_session


async def db_session() -> AsyncSession:  # type: ignore[misc]
    """请求级会话（不自动 commit，写端点显式 commit）。"""
    async for session in get_session():
        yield session


def auth_context(request: Request) -> dict:
    """从 request.state 取 HMAC 校验后的身份（中间件已设置）。"""
    st = request.state
    tenant = getattr(st, "joker_tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="missing internal auth context")
    return {
        "tenant_id": tenant,
        "user_id": getattr(st, "joker_user", None),
        "scopes": list(getattr(st, "joker_scopes", [])),
        # is_platform_admin 由 BFF 切片从 JWT claims / DB 注入（S01 最小集恒 False）；
        # 系统租户上下文同样视为平台运营（DB_DESIGN §10.1 管理面例外）
        "is_platform_admin": (
            getattr(st, "joker_platform_admin", False)
            or tenant == "00000000-0000-0000-0000-000000000001"
        ),
    }


def require_tenant(auth: dict = Depends(auth_context)) -> str:
    return auth["tenant_id"]


def require_scope(*required: str, auth: dict = Depends(auth_context)) -> None:
    """scope 校验，支持 `agent:use:*` 通配（DECISION-004）。"""
    for r in required:
        if not scope_allows(auth["scopes"], r):
            raise HTTPException(status_code=403, detail=f"missing scope: {r}")


def scope_allows(scopes: list[str], required: str) -> bool:
    if required in scopes:
        return True
    if required.startswith("agent:use:") and "agent:use:*" in scopes:
        return True
    return False


def reexport_context() -> tuple[str | None, str | None, list[str]]:
    return current_tenant(), current_user(), list(current_scopes())
