"""平台 MCP server 对外暴露（STORE-06/07/RAG-10，DECISION-011）：/mcp 端点。

- 传输 = Streamable HTTP（MCP 规范现行标准，DECISION-011），无状态会话（可水平扩展）。
- 暴露平台内置三工具 upload_doc / query_doc / rag_search（S02/S05 已实装；工具 schema
  与 DB 注册行同源 = joker_shared.mcp.platform_tools.PLATFORM_TOOLS）。
- **工具调用 100% 经 ToolInterceptor 统一动作链**（BFF-06/07，D-B / DECISION-015）：
  ① scope 校验（mcp_tools.required_scopes × 用户 scopes，未勾选 403 语义）
  ② Access Token 强制注入（入参 access_token 一律覆写为用户真实 token，BFF-09 验收 2）
  ③ 机器凭证代理执行（平台工具 → /internal/* HMAC 签名头，DECISION-009）
  ④ tool_call 事件落 trace（/mcp 直连路径无特定 agent → 回退租户首个 active agent 建 trace）

身份来源（两条路径，与 S02 同一薄封装语义）：
  - 生产/工具入参：args.access_token（ToolInterceptor 强制注入）；
  - /mcp HTTP 直连/自测：Authorization: Bearer <JWT>（管线鉴权后存 contextvar，回退使用）。

管线（GatewayPipeline）已对 /mcp 做 JWT 鉴权 + 限流；本模块仅做 MCP 协议处理 + 拦截。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import CallToolResult, TextContent, Tool
from starlette.types import ASGIApp, Receive, Send

from app.mcp_auth import identity
from joker_shared.agents import interceptor as ti
from joker_shared.config import settings
from joker_shared.db import get_session_factory
from joker_shared.mcp.platform_tools import PLATFORM_TOOLS

log = logging.getLogger("joker.bff.mcp")


def _tools() -> list[Tool]:
    """平台三工具 schema（与 DB 注册行同源，platform_tools.PLATFORM_TOOLS）。"""
    return [
        Tool(name=t["name"], description=t["description"] or "",
             inputSchema=t["input_schema"] or {"type": "object", "properties": {}})
        for t in PLATFORM_TOOLS
    ]


def _error_result(msg: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=msg)], isError=True)


def _text_result(payload: Any) -> CallToolResult:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        return CallToolResult(content=[TextContent(type="text", text=text)], structuredContent=payload)
    return CallToolResult(content=[TextContent(type="text", text=str(payload))])


async def _resolve_platform_tool_id(session: Any, tool_name: str) -> str | None:
    """平台内置工具 name → mcp_tools.id（is_platform server + source=platform + enabled + online）。"""
    from sqlalchemy import text

    r = await session.execute(
        text(
            """SELECT t.id FROM mcp_tools t JOIN mcp_servers s ON s.id = t.server_id
               WHERE s.is_platform = true AND t.source = 'platform' AND t.name = :n
                 AND t.enabled = true AND t.removed_remote = false
                 AND s.status = 'online' AND t.deleted_at IS NULL AND s.deleted_at IS NULL"""
        ),
        {"n": tool_name},
    )
    row = r.first()
    return str(row[0]) if row else None


def _build_server() -> Server:
    server: Server = Server("joker-platform-mcp", version="0.1.0-s08")

    @server.list_tools()
    async def _list() -> list[Tool]:
        return _tools()

    @server.call_tool()
    async def _call(name: str, args: dict | None) -> CallToolResult:
        args = dict(args or {})
        # ② 身份：入参 access_token（ToolInterceptor 注入）优先，回退 HTTP 上下文
        try:
            idn = identity(args.get("access_token"))
        except ValueError:
            try:
                idn = identity(None)
            except ValueError as exc:
                return _error_result(f"auth failed: {exc}")
        # 强制注入（BFF-09 验收 2）：agent 传入的 token 一律覆写为用户真实 token
        args["access_token"] = idn.access_token

        factory = get_session_factory()
        async with factory() as session:
            tool_id = await _resolve_platform_tool_id(session, name)
            if tool_id is None:
                return _error_result(f"unknown or unavailable platform tool: {name}")
            # 统一动作链（①scope 校验 ②token 注入 ③机器凭证代理执行 ④tool_call trace）
            try:
                res = await ti.execute_tool_call(
                    session,
                    tenant_id=idn.tenant_id, user_id=idn.user_id, scopes=idn.scopes,
                    agent_id=None,  # /mcp 直连无特定 agent → 回退租户首个 active agent 建 trace
                    tool_id=tool_id, args=args, access_token=idn.access_token,
                    trace_session_id=None,  # 由 write_tool_call_event 按需回退建
                )
            except Exception as exc:
                log.exception("mcp tool %s via interceptor failed", name)
                return _error_result(f"tool {name} failed: {exc}")
        if res.get("ok"):
            return _text_result(res.get("result"))
        # 拒绝语义（①scope 不足 / 工具不可用 / 执行失败）→ agent 可理解的错误
        return _error_result(json.dumps(res, ensure_ascii=False, default=str))

    return server


def build_mcp_manager() -> StreamableHTTPSessionManager:
    """构造 MCP 会话管理器（stateless，DECISION-011）。

    **重要**：MCP SDK v1.30 规定 `manager.run()` 每实例只能进入一次（创建 task group，
    生命周期=整个 app）。因此本函数只建 manager；run() 由 BFFGateway 在 lifespan 里进入
    一次（见 gateway.create_app），每请求走 `handle_request()`（不再自开 run()）。
    """
    return StreamableHTTPSessionManager(
        app=_build_server(),
        stateless=True,
        security_settings=None,  # 本地 compose 自测（同源 localhost）；S11 接 nginx 后按需收紧
    )


def make_mcp_request_handler(manager: StreamableHTTPSessionManager):
    """/mcp 每请求 ASGI：鉴权前置（HTTP 层 Authorization）+ 委托 MCP 管理器。

    鉴权：校验 Bearer access token（HS256，与 PlatformAPI 共享 JWT_SECRET）；
    通过 → 身份存 contextvar（工具回退使用）→ 交 manager.handle_request（stateless）。
    （GatewayPipeline 已对 /mcp 做 JWT+黑名单+限流；此处再次校验是「MCP 端点自洽」
    的薄封装——保证管理器收到的请求必然带合法身份，防止管理器被其它路径复用。）
    """
    from app.mcp_auth import decode_access_token, set_ctx

    async def app(scope: dict, receive: Receive, send: Send) -> None:
        import json as _json

        # lifespan 不透传到这里（BFFGateway 已在 outer 层管理 manager.run()）。
        if scope.get("type") == "lifespan":
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            msg = await receive()
            if msg["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
            return

        # 身份：优先复用 BFFGateway 管线已鉴权的身份（scope.state.joker_id）；
        # 独立挂载（S02 自测）时回退到 HTTP 层 Bearer 校验（MCP 端点自洽）。
        state = scope.get("state") or {}
        gid = state.get("joker_id")
        if gid and state.get("joker_token"):
            set_ctx({"tenant_id": gid["tenant_id"], "user_id": gid["user_id"],
                     "scopes": gid.get("scopes", [])}, state["joker_token"])
        else:
            auth = ""
            for k, v in scope.get("headers", []):
                if k == b"authorization":
                    auth = v.decode("latin-1")
            if not auth.lower().startswith("bearer "):
                await _send_json(send, 401, _json.dumps({"detail": "mcp auth failed: missing Bearer access token"}).encode())
                return
            token = auth[7:].strip()
            try:
                claims = decode_access_token(token)
            except ValueError as exc:
                await _send_json(send, 401, _json.dumps({"detail": f"mcp auth failed: {exc}"}).encode())
                return
            set_ctx(claims, token)
        # stateless：handle_request 直接处理（task group 已由 lifespan 的 run() 建好）
        await manager.handle_request(scope, receive, send)

    return app


# 向后兼容：旧调用 build_mcp_asgi() 仍可用（返回带 manager 的 ASGI，但 run() 需由
# 调用方在 lifespan 管理）。新代码用 build_mcp_manager() + make_mcp_request_handler()。
def build_mcp_asgi() -> ASGIApp:
    manager = build_mcp_manager()
    return make_mcp_request_handler(manager)


async def _send_json(send: Send, status: int, body: bytes) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
