"""MCP 工具身份上下文（两条路径）：

1) 生产路径（S08 ToolInterceptor）：工具入参 `access_token` 由拦截器强制注入 →
   `identity_from_token(token)` 解析。
2) BFF 直连/自测路径：HTTP 层 Authorization: Bearer <access JWT> →
   `mcp_app` 校验后存入 contextvar（`current_ctx()`）。
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import jwt

from joker_shared.config import settings

_ctx: ContextVar[dict[str, Any] | None] = ContextVar("joker_mcp_ctx", default=None)


@dataclass
class MCPIdentity:
    tenant_id: str
    user_id: str
    scopes: list[str]
    access_token: str


def decode_access_token(token: str) -> dict:
    """校验用户 Access Token（HS256，与 PlatformAPI 共享 JWT_SECRET，DECISION-002）。"""
    try:
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise ValueError("access token expired")
    except jwt.InvalidTokenError:
        raise ValueError("invalid access token")
    if claims.get("type") != "access":
        raise ValueError("not an access token")
    return claims


def current_ctx() -> dict | None:
    return _ctx.get()


def set_ctx(claims: dict, token: str) -> None:
    _ctx.set({
        "tenant_id": claims["tenant_id"],
        "user_id": claims["user_id"],
        "scopes": list(claims.get("scopes", [])),
        "access_token": token,
    })


def identity(access_token: str | None = None) -> MCPIdentity:
    """工具调用身份：入参 token 优先（S08 注入），回退 HTTP 上下文。"""
    if access_token:
        claims = decode_access_token(access_token)
        return MCPIdentity(
            tenant_id=claims["tenant_id"],
            user_id=claims["user_id"],
            scopes=list(claims.get("scopes", [])),
            access_token=access_token,
        )
    ctx = _ctx.get()
    if ctx is None:
        raise ValueError("missing identity: no access_token in args and no HTTP auth context")
    return MCPIdentity(
        tenant_id=ctx["tenant_id"], user_id=ctx["user_id"],
        scopes=ctx["scopes"], access_token=ctx["access_token"],
    )
