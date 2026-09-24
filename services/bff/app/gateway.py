"""BFF 统一网关（S08，BFF-01..09，ARCH §4，DECISION-002/009/013/014/015/016/023）。

统一请求处理管线（ARCH §4.1，固定顺序）——根级 ASGI 分发（非 BaseHTTPMiddleware，
以支持 /v1 流式 SSE 与 /mcp Streamable HTTP 的原生 send 透传）：
  ① 限流（DECISION-013）：登录接口 IP 限流（未鉴权即做）→ 鉴权后 租户QPS + 用户QPS。超限 429。
  ② 统一鉴权（BFF-01，DECISION-002）：JWT access 本地校验（HS256）+ Redis 登出黑名单。
     **业务服务不重复实现 token 校验**——BFF 校验后透传签名身份头。
  ③ 身份提取（BFF-05）：从 JWT claims 取 tenant/user/scopes（**只信 token，绝不信任请求体**，
     BFF-09 验收 3）。身份存 contextvar + scope.state（路由/MCP 回调可读）。
  ④ 路由（BFF-03，DECISION-014）：配置化路由表（routes.yml，最长前缀匹配），新增端点不改代码。
  ⑤ scope 校验（BFF-05）：chat 请求校验 agent:use（openai_compat 内做）。
  ⑥ 协议转换（BFF-04，DECISION-016）：/v1/chat/completions OpenAI 兼容（块式 + SSE）。
  ⑦ 审计/trace：/api/* 由 PlatformAPI 侧 AuditMiddleware 记；BFF 本地端点记日志 + 拦截事件落 trace。

路径分派（根级 ASGI）：
- /healthz → 公开。
- /api/auth/login → 公开入口，仅 IP 限流。
- /v1/*, /mcp(/), /api/bff/*, /docs → 鉴权+限流后 **委派 FastAPI ASGI**（send 透传，支持流式）。
- /api/*, /internal/*（其余）→ 鉴权+限流后 **转发 PlatformAPI**（注入 X-Auth-* HMAC 签名头，DECISION-009）。
- 未知 → 404。
"""
from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from typing import Any

import httpx
import jwt as pyjwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Send

from joker_shared import crypto, redis_client
from joker_shared.config import settings
from app import rate_limit
from app.routes import get_router

log = logging.getLogger("joker.bff.gateway")

_id_ctx: ContextVar[dict[str, Any] | None] = ContextVar("joker_bff_id", default=None)
_token_ctx: ContextVar[str] = ContextVar("joker_bff_token", default="")


def current_identity(request: Any = None) -> dict[str, Any] | None:
    """当前请求身份：request.state（最可靠）→ contextvar 回退。"""
    if request is not None:
        st = getattr(request, "state", None)
        if st is not None:
            return getattr(st, "joker_id", None)
    return _id_ctx.get()


def current_token(request: Any = None) -> str:
    if request is not None:
        st = getattr(request, "state", None)
        tok = getattr(st, "joker_token", None) if st is not None else None
        if tok:
            return tok
    return _token_ctx.get()


def identity_for(request: Any) -> dict[str, Any]:
    """取身份（带 request），缺 → 401。"""
    idn = current_identity(request)
    if idn is None:
        raise HTTPException(401, "missing identity (auth required)")
    return idn


def set_identity(claims: dict, token: str) -> None:
    _id_ctx.set({
        "tenant_id": claims["tenant_id"],
        "user_id": claims["user_id"],
        "scopes": list(claims.get("scopes", [])),
    })
    _token_ctx.set(token)


def reset_identity() -> None:
    _id_ctx.set(None)
    _token_ctx.set("")


PUBLIC_PATHS = {"/healthz", "/"}
LOGIN_PATHS = ("/api/auth/login",)
# 公开前缀端点（与 API 侧 middleware.PUBLIC_PREFIXES 对齐）：不经 BFF JWT 鉴权/
# 不注入 X-Auth-* 签名头，保留客户端 Authorization 头透传（BUG-02 修复：logout
# 需要原始 bearer 写 access 黑名单；refresh/login 本身凭据即鉴权）。
PUBLIC_AUTH_PREFIXES = (
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/logout",
)


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS


def is_login(path: str) -> bool:
    return any(path == p for p in LOGIN_PATHS)


def is_bff_local(path: str) -> bool:
    """BFF 本地端点（不转发上游，委派 FastAPI/MCP ASGI）。"""
    return (
        path in ("/v1/chat/completions", "/mcp", "/mcp/")
        or path.startswith("/api/bff/")
        or path in ("/docs", "/openapi.json", "/redoc")
    )


# ---------------------------------------------------------------- 鉴权（BFF-01，DECISION-002）

class AuthError(Exception):
    def __init__(self, code: int, detail: str, hint: str | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.hint = hint


def extract_bearer(headers: dict) -> str:
    auth = headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


async def verify_access(token: str) -> dict:
    """JWT access 本地校验（HS256 + exp）+ Redis 登出黑名单（BFF-01）。"""
    if not token:
        raise AuthError(401, "missing access token")
    try:
        claims = pyjwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        raise AuthError(401, "access token expired", hint="refresh")
    except pyjwt.InvalidTokenError as exc:
        raise AuthError(401, f"invalid access token: {exc}")
    if claims.get("type") != "access":
        raise AuthError(401, "not an access token")
    jti = claims.get("jti")
    if jti:
        try:
            denied = await redis_client.is_denied(jti)
        except Exception as exc:
            log.warning("blacklist check failed (%s); continue (fail-open for redis down)", exc)
            denied = False
        if denied:
            # BUG-02 修复（第二根因）：AuthError 必须抛出黑名单检查的 try 之外——
            # 原先 raise 在 try 内被 except Exception 自捕（AuthError 是 Exception
            # 子类）→ 登出黑名单形同虚设（fail-open 吞掉 401）。
            raise AuthError(401, "access token revoked (logged out)", hint="refresh")
    return claims


# ---------------------------------------------------------------- 根级 ASGI 分发

class BFFGateway(ASGIApp):
    """统一网关（管线 ①限流 ②鉴权 ③身份 ④路由 ⑤scope ⑥转换 ⑦审计）。"""

    def __init__(self, inner: ASGIApp, mcp: ASGIApp, mcp_manager=None) -> None:
        self.inner = inner      # FastAPI 应用（/healthz, /v1, /api/bff, /docs）
        self.mcp = mcp          # MCP Streamable HTTP 每请求 handler（/mcp）
        self.mcp_manager = mcp_manager  # MCP 会话管理器（lifespan 里进入一次 run()）
        self._client: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=settings.BFF_PROXY_TIMEOUT, follow_redirects=False,
                headers={"User-Agent": "agent-joker-bff/1.0"},
            )
        return self._client

    async def __call__(self, scope: dict, receive: Receive, send: Send) -> None:
        if scope.get("type") == "lifespan":
            # MCP 会话管理器 run() 每实例只能进入一次（SDK v1.30）→ 在 lifespan 里进入
            # 一次，task group 覆盖整个 app 生命周期；inner（FastAPI）的 lifespan 在其内
            # 正常运行（startup→shutdown 全程阻塞，正好=app 生命周期）。
            if self.mcp_manager is not None:
                async with self.mcp_manager.run():
                    await self.inner({"type": "lifespan"}, receive, send)
            else:
                await self.inner({"type": "lifespan"}, receive, send)
            return

        path: str = scope.get("path", "")
        client_ip = (scope.get("client") or ("unknown", 0))[0]
        _id_ctx.set(None)
        _token_ctx.set("")
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}

        # ① 限流：登录接口 IP 限流（未鉴权即做，DECISION-013）
        if is_login(path):
            try:
                await rate_limit.check_login_ip(None, client_ip)
            except rate_limit.RateLimitExceeded as e:
                return await self._send_json(send, 429, _rl_body(e))

        # 健康检查（公开）
        if is_public(path):
            return await self.inner(scope, receive, send)

        # 登录端点（公开入口，产出 token）：仅 IP 限流，直接转发上游（不要求 bearer、
        # 不注入签名头——PlatformAPI 白名单放行，DECISION-009 登录例外）
        if is_login(path):
            return await self._forward(scope, receive, send)

        # ② 鉴权（BFF-01，DECISION-002）
        token = extract_bearer(headers)
        try:
            claims = await verify_access(token)
        except AuthError as e:
            log.info("auth failed path=%s ip=%s: %s", path, client_ip, e.detail)
            return await self._send_json(send, e.code, _auth_body(e))
        tid, uid = claims["tenant_id"], claims["user_id"]

        # ①(续) 限流：租户 QPS + 用户 QPS（DECISION-013）
        try:
            await rate_limit.check_tenant(None, tid)
            await rate_limit.check_user(None, uid, tid)
        except rate_limit.RateLimitExceeded as e:
            return await self._send_json(send, 429, _rl_body(e))

        # ③ 身份提取（BFF-05，只信 token，存 scope.state + contextvar）
        set_identity(claims, token)
        scope.setdefault("state", {})
        scope["state"]["joker_id"] = {"tenant_id": tid, "user_id": uid,
                                      "scopes": claims.get("scopes", [])}
        scope["state"]["joker_token"] = token
        try:
            # BFF 本地：/mcp → MCP ASGI（ToolInterceptor 拦截）；其余 → FastAPI（send 透传）
            if path in ("/mcp", "/mcp/"):
                return await self.mcp(scope, receive, send)
            if is_bff_local(path):
                return await self.inner(scope, receive, send)
            # 上游转发（/api/*, /internal/*，DECISION-009 签名头）
            return await self._forward(scope, receive, send)
        finally:
            reset_identity()

    async def _forward(self, scope: dict, receive: Receive, send: Send) -> None:
        """配置化路由转发（BFF-03，DECISION-014）→ PlatformAPI（DECISION-009 签名头）。"""
        path = scope.get("path", "")
        route = get_router().table.get(path)
        if route is None or route.target != "platformapi":
            return await self._send_json(send, 404, {"detail": f"no route for {path}"})
        base = settings.BFF_PLATFORM_API_BASE.rstrip("/")
        upstream_path = route.build_upstream_path(path)
        upstream_url = base + upstream_path

        # 组装转发头：注入签名头（登录/refresh/logout 等公开前缀端点不注入——
        # DECISION-009 登录例外）。**保留客户端 Authorization 头**（BUG-02 修复）：
        # 公开前缀端点（logout/refresh/login）不经过 BFF JWT 鉴权，API 侧需要原始
        # bearer 做 access token 黑名单（logout）/ refresh 校验；签名头端点上
        # API 只信 X-Auth-*（安全不变量不变，请求体 tenant 一律忽略）。
        fwd_headers = [(k, v) for (k, v) in scope.get("headers", [])
                       if k.lower() not in (b"host", b"content-length", b"transfer-encoding")]
        if not is_login(path) and not path.startswith(PUBLIC_AUTH_PREFIXES):
            idn = scope["state"]["joker_id"]
            sig = crypto.build_internal_headers(idn["tenant_id"], idn["user_id"], idn["scopes"])
            fwd_headers += [(k.encode(), v.encode()) for k, v in sig.items()]

        # 读完整 body（转发为整包；上游 PlatformAPI 端点无 SSE 流式需求）
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if msg.get("more_body") is False:
                break

        t0 = time.monotonic()
        query = scope.get("query_string", b"").decode("latin-1")
        try:
            r = await self._http_client().request(
                scope.get("method", "GET"), upstream_url,
                headers={k.decode(): v.decode() for k, v in fwd_headers},
                content=body, params=query,
            )
        except httpx.TimeoutException:
            return await self._send_json(send, 504, {"detail": "upstream timeout (platformapi)"})
        except httpx.HTTPError as exc:
            log.warning("upstream forward failed path=%s: %s", path, exc)
            return await self._send_json(send, 502, {"detail": f"upstream unreachable: {type(exc).__name__}"})
        log.info("forward %s %s -> %s %s (%dms)", scope.get("method"), path,
                 r.status_code, upstream_path, int((time.monotonic() - t0) * 1000))
        resp_headers = [(k.encode(), v.encode()) for (k, v) in r.headers.items()
                        if k.lower() not in ("content-length", "transfer-encoding", "connection")]
        await send({"type": "http.response.start", "status": r.status_code,
                    "headers": resp_headers or [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": r.content})

    @staticmethod
    async def _send_json(send: Send, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(data)).encode())]})
        await send({"type": "http.response.body", "body": data})


def _rl_body(e: rate_limit.RateLimitExceeded) -> dict:
    retry_after = max(1, e.window - (int(time.time()) % e.window)) if e.window > 0 else 1
    return {"detail": f"rate limit exceeded ({e.dim})", "retry_after": retry_after,
            "limit": e.limit, "count": e.count}


def _auth_body(e: AuthError) -> dict:
    body: dict[str, Any] = {"detail": e.detail}
    if e.hint:
        body["hint"] = e.hint
    return body


# ---------------------------------------------------------------- FastAPI 应用（BFF 本地端点）

def _build_inner() -> FastAPI:
    app = FastAPI(title="agent-joker BFFGateway", version="0.1.0-s08",
                  docs_url="/docs", openapi_url="/openapi.json")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": "bffgateway", "phase": "S08-bff"}

    # OpenAI 兼容（BFF-04，DECISION-016）
    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        from app.openai_compat import handle_chat_completions
        return await handle_chat_completions(request)

    # BFF 管理端点（限流配置 / 路由热加载，DECISION-013/014）
    from app.admin import router as admin_router
    app.include_router(admin_router)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code,
                                content={"detail": str(exc.detail)},
                                headers=getattr(exc, "headers", None))
        log.exception("bff unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    return app


def create_app() -> BFFGateway:
    """构建 BFF 网关：内层 FastAPI（BFF 本地端点）+ MCP ASGI（/mcp），外层统一管线。

    MCP 会话管理器只建一次；其 run() 由 BFFGateway 在 lifespan 进入一次（见 __call__）。
    """
    from app.mcp_endpoint import build_mcp_manager, make_mcp_request_handler

    inner = _build_inner()
    mcp_manager = build_mcp_manager()
    mcp = make_mcp_request_handler(mcp_manager)
    return BFFGateway(inner=inner, mcp=mcp, mcp_manager=mcp_manager)
