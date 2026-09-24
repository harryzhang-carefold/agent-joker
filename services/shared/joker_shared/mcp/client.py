"""MCP 远端 server 客户端（S06）：tools/list 全量拉取（DECISION-010/011）。

传输（DECISION-011）：
- streamable_http（默认，MCP 现行标准）
- sse（兼容旧 server）

只实现「注册/刷新时的 tools/list 探测」；工具**调用**执行链路（经 ToolInterceptor
代理）由 S08 统一接入，本模块不做 tools/call。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from joker_shared.config import settings

log = logging.getLogger("joker.mcp.client")


class MCPProbeError(Exception):
    """连通性探测 / tools/list 失败（带明确错误摘要，MCP-01 验收 4）。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _headers(auth_headers_enc: str | None, plain_headers: dict[str, str] | None) -> dict[str, str]:
    """机器凭证（Fernet 密文，注册时解密）+ 显式请求头（探测用明文头，不落库）。"""
    out: dict[str, str] = {}
    if auth_headers_enc:
        from joker_shared.crypto import decrypt_secret

        try:
            import json

            dec = json.loads(decrypt_secret(auth_headers_enc))
            if isinstance(dec, dict):
                out.update({str(k): str(v) for k, v in dec.items()})
        except Exception as exc:  # 密文不可解（FERNET_KEY 更换）→ 明确错误而非崩溃
            raise MCPProbeError(f"auth_headers decrypt failed: {exc}") from exc
    if plain_headers:
        out.update({str(k): str(v) for k, v in plain_headers.items()})
    return out


async def list_remote_tools(
    url: str,
    transport: str,
    auth_headers_enc: str | None = None,
    plain_headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """对远端 MCP server 发起 initialize + tools/list，返回工具快照列表。

    每项：{name, description, input_schema}（MCP tools/list 原样，JSON 可序列化）。
    失败抛 MCPProbeError（明确错误摘要：不可达 / HTTP 状态 / 协议错误）。
    """
    from mcp import ClientSession
    from mcp.client import sse, streamable_http

    timeout = timeout or settings.MCP_PROBE_TIMEOUT_SECONDS
    headers = _headers(auth_headers_enc, plain_headers)
    tools: list[dict[str, Any]] = []

    try:
        if transport == "sse":
            async with sse_client_ctx(url, headers, timeout) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    tools = [_tool_to_dict(t) for t in result.tools]
        else:  # streamable_http（默认）
            async with streamable_http.streamablehttp_client(
                url, headers=headers or None, timeout=timeout
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    tools = [_tool_to_dict(t) for t in result.tools]
    except MCPProbeError:
        raise
    except httpx.ConnectError as exc:
        raise MCPProbeError(f"server unreachable (connect error): {exc}") from exc
    except httpx.TimeoutException as exc:
        raise MCPProbeError(f"server unreachable (timeout {timeout}s): {exc}") from exc
    except httpx.HTTPStatusError as exc:
        raise MCPProbeError(f"server returned HTTP {exc.response.status_code}", exc.response.status_code) from exc
    except Exception as exc:  # 协议/解析/其他 → 统一明确错误
        raise MCPProbeError(f"tools/list failed: {type(exc).__name__}: {exc}") from exc

    return tools


def sse_client_ctx(url: str, headers: dict[str, str], timeout: float):
    from mcp.client import sse

    return sse.sse_client(url, headers=headers or None, timeout=timeout, sse_read_timeout=timeout * 10)


def _tool_to_dict(t: Any) -> dict[str, Any]:
    """mcp.types.Tool → JSON 可序列化快照（name/description/input_schema）。"""
    return {
        "name": getattr(t, "name", ""),
        "description": getattr(t, "description", None) or "",
        "input_schema": getattr(t, "inputSchema", None) or {},
    }
