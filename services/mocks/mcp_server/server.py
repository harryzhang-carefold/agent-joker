"""S06 E2E 用 mock MCP server（Streamable HTTP，DECISION-011）。

工具清单动态读 /tools.json（E2E 用 docker exec 改写它，验证 refresh 的
upsert / removed_remote 反向同步）：
  /tools.json = {"tools": [{"name","description","input_schema"}, ...]}

协议端点：POST /mcp（stateless Streamable HTTP；每次请求新建 transport）。
无鉴权（自测内网容器）。
"""
from __future__ import annotations

import json
import logging
import time

from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mock-mcp")

TOOLS_FILE = "/tools.json"

# 内置默认工具（mock 自包含，S11 card：echo/calc；/tools.json 存在且非空时覆盖，
# 兼容 S12 refresh 反向同步场景动态改写工具清单）。
DEFAULT_TOOLS = [
    Tool(name="echo", description="回显工具：返回 x 的值（mock 默认工具）",
         inputSchema={"type": "object",
                      "properties": {"x": {"type": "string", "description": "要回显的内容"}},
                      "required": ["x"]}),
    Tool(name="calc", description="计算器工具：返回 a + b 的和（mock 默认工具）",
         inputSchema={"type": "object",
                      "properties": {"a": {"type": "number", "description": "第一个数"},
                                     "b": {"type": "number", "description": "第二个数"}},
                      "required": ["a", "b"]}),
]


def load_tools() -> list[Tool]:
    try:
        raw = json.loads(open(TOOLS_FILE, encoding="utf-8").read())
        tools = raw.get("tools") or []
        if tools:
            return [
                Tool(name=t["name"], description=t.get("description", ""),
                     inputSchema=t.get("input_schema", {}))
                for t in tools
            ]
    except Exception as exc:
        log.warning("tools.json unreadable/empty (%s); using built-in default tools", exc)
    return list(DEFAULT_TOOLS)


def build_server() -> Server:
    srv = Server("mock-mcp")

    @srv.list_tools()
    async def _list() -> list[Tool]:
        return load_tools()

    @srv.call_tool()
    async def _call(name: str, arguments: dict) -> list:
        from mcp.types import TextContent

        return [TextContent(type="text", text=json.dumps({"name": name, "arguments": arguments}))]

    return srv


manager = StreamableHTTPSessionManager(
    app=build_server(), stateless=True, security_settings=None
)


async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
    await manager.handle_request(scope, receive, send)


class McpDispatch(ASGIApp):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            async with manager.run():
                m = await receive()
                if m["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                m = await receive()
                if m["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
            return
        if scope.get("method") == "GET" and scope.get("path") == "/healthz":
            body = json.dumps({"status": "ok", "tool_count": len(load_tools())}).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        if scope.get("path", "").rstrip("/") in ("", "/mcp"):
            await handle_mcp(scope, receive, send)
            return
        body = json.dumps({"detail": "not found"}).encode()
        await send({"type": "http.response.start", "status": 404,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})


app = McpDispatch()

if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MOCK_MCP_PORT", "9100")))
