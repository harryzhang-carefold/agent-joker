"""中间件：X-Auth-* HMAC 校验（DECISION-009）+ 审计（BASE-06）。

- 白名单（无需内部签名的公开端点）：
- GET /healthz、GET /openapi.json、GET /docs、GET /redoc
- POST /api/auth/login（登录=公开入口；BFF 侧负责限流与 JWT 签发透传，
  S01 最小集下客户端/BFF 均可直连登录端点，登录本身不需要身份头）
其余所有 /api/* 与 /internal/* 必须携带有效 X-Auth-* 签名（否则 401）。
/internal/*（S02 起：PlatformMCPServer 以机器凭证代执行，DECISION-009 签名头）。

**安全不变量**：签名校验通过后，tenant 只信头（X-Auth-Tenant），
请求体中的任何 tenant 字段一律忽略（BFF-09 验收 3）。
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from fastapi import Request, Response
from fastapi.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from joker_shared import audit, crypto
from joker_shared.db import set_auth_context

log = logging.getLogger("joker.api")

PUBLIC_PATHS = {
    "/healthz",
    "/openapi.json",
    "/docs",
    "/redoc",
}
PUBLIC_PREFIXES = (
    "/api/auth/login",      # 登录=公开入口（凭据本身鉴权）
    "/api/auth/refresh",    # refresh token 本身鉴权（有状态，防重放）
    "/api/auth/logout",     # refresh token / access jti 本身鉴权
)


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """X-Auth-* HMAC 签名校验（BFF→API 内部鉴权，DECISION-009）。"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        if path.startswith("/api/") or path.startswith("/internal/"):
            try:
                tenant, user, scopes = crypto.verify_internal_headers(dict(request.headers))
            except crypto.InternalAuthError as exc:
                await audit.write_audit(
                    tenant_id=None,
                    user_id=None,
                    method=request.method,
                    path=path,
                    status_code=401,
                    latency_ms=0,
                    client_ip=request.client.host if request.client else None,
                )
                return JSONResponse(status_code=401, content={"detail": f"internal auth failed: {exc}"})
            set_auth_context(tenant, user, scopes)
            request.state.joker_tenant = tenant
            request.state.joker_user = user
            request.state.joker_scopes = scopes
        return await call_next(request)


class AuditMiddleware(BaseHTTPMiddleware):
    """接口操作日志（BASE-06）：全量 /api/* 写审计，异步不阻断。

    401/403/429/5xx 均记录（DB_DESIGN §1.8）。请求体在 BaseHTTPMiddleware 中
    已被消费，body digest 仅在可安全读取时记录（S01：记录 query 与脱敏 body 的
    尽力而为版本——中间件层拿不到原始 body 时记 None，登录端点在路由层补记）。

    身份回退（BUG-06 修复）：公开前缀端点（/api/auth/logout 等）经 BFF 转发时
    客户端 Authorization 头已被剥离、X-Auth-* 签名头未注入（DECISION-009 登录
    例外），审计行 tenant/user 会落 NULL → 按租户查询时不可见。此处尽力解码
    access token（只读 claims，不改变鉴权语义），把 jti/tenant 挂到 request.state
    供审计与 logout 黑名单使用。
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        self._try_fallback_identity(request)
        start = time.monotonic()
        try:
            response = await call_next(request)
        except HTTPException as exc:
            latency = int((time.monotonic() - start) * 1000)
            await audit.write_audit(
                tenant_id=self._audit_tenant(request),
                user_id=getattr(request.state, "joker_user", None)
                or getattr(request.state, "joker_access_user", None),
                method=request.method,
                path=request.url.path,
                status_code=exc.status_code,
                latency_ms=latency,
                client_ip=request.client.host if request.client else None,
                query=dict(request.query_params),
            )
            raise
        latency = int((time.monotonic() - start) * 1000)
        await audit.write_audit(
            tenant_id=self._audit_tenant(request),
            user_id=getattr(request.state, "joker_user", None)
            or getattr(request.state, "joker_access_user", None),
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency,
            client_ip=request.client.host if request.client else None,
            query=dict(request.query_params),
        )
        return response

    @staticmethod
    def _try_fallback_identity(request: Request) -> None:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return
        try:
            claims = crypto.decode_access(auth_header[7:])
        except Exception:
            return
        st = request.state
        if getattr(st, "joker_access_jti", None) is None:
            st.joker_access_jti = claims.get("jti")
        if getattr(st, "joker_access_tenant", None) is None:
            st.joker_access_tenant = claims.get("tenant_id")
        if getattr(st, "joker_access_user", None) is None:
            st.joker_access_user = claims.get("user_id")

    @staticmethod
    def _audit_tenant(request: Request) -> str | None:
        return getattr(request.state, "joker_tenant", None) \
            or getattr(request.state, "joker_access_tenant", None)
