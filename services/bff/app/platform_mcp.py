"""PlatformMCPServer：平台内置 MCP server（ARCH §3.1，Streamable HTTP，DECISION-011）。

代码注册 3 工具（is_platform 语义，系统启动自动注册）：
- upload_doc   → PlatformAPI /internal/storage/upload
- query_doc    → PlatformAPI /internal/storage/files
- rag_search   → PlatformAPI /internal/rag/search（S05 实装；RAG-06..10 检索核心
  + D-A official 两级判定 + D-B (agent_id,kb_id) 勾选校验/rag trace 留痕）

身份：工具入参 access_token（S08 ToolInterceptor 强制注入）优先，
回退 HTTP 层 Authorization（BFF 直连/自测）。工具以平台机器凭证
（INTERNAL_HMAC_SECRET）构造 X-Auth-* 签名头代执行内部 API（DECISION-009/012）。
"""
from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from typing import Any

import httpx
from mcp.server.lowlevel.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from app.mcp_auth import identity
from joker_shared.config import settings

log = logging.getLogger("joker.bff.mcp")

PLATFORM_API_BASE = settings.BFF_PLATFORM_API_BASE or "http://api:8001"

# ---------------------------------------------------------------- 工具定义

TOOLS: list[Tool] = [
    Tool(
        name="upload_doc",
        description=(
            "上传文档到平台存储（租户级）。入参 file_name + content（UTF-8 文本）；"
            "成功返回 file_id/file_name/size_bytes。同名文件 409。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_name": {"type": "string", "description": "文件名（含扩展名，租户内唯一）"},
                "content": {"type": "string", "description": "文件内容（UTF-8 文本）"},
                "source": {"type": "string", "description": "来源标记（默认 mcp:platform）"},
                "agent_id": {"type": "string", "description": "可选，关联 agent ID"},
                "access_token": {"type": "string", "description": "用户 Access Token（ToolInterceptor 强制注入）"},
            },
            "required": ["file_name", "content"],
        },
    ),
    Tool(
        name="query_doc",
        description=(
            "按文件名/条件查询平台存储文件（仅本租户）。入参 file_name（精确，可选）或"
            " prefix/limit；返回文件列表（含 content——text 类文件直接内联，二进制返回元数据）。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_name": {"type": "string", "description": "精确文件名（提供时忽略 prefix/limit）"},
                "prefix": {"type": "string", "description": "文件名前缀过滤"},
                "limit": {"type": "integer", "description": "返回条数上限（默认 20）"},
                "access_token": {"type": "string", "description": "用户 Access Token（ToolInterceptor 强制注入）"},
            },
            "required": [],
        },
    ),
    Tool(
        name="rag_search",
        description=(
            "在指定知识库中做 RAG 检索，返回 chunk 内容 + 索引 + 原文档位置 + tag。"
            "（S05 实装检索逻辑；契约：kb_ids[] + query + top_k → items[{chunk_id,content,"
            "kb_id,doc_id,doc_file_name,pos,tag,score}]）"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "kb_ids": {"type": "array", "items": {"type": "string"}, "description": "知识库 ID 列表（必选）"},
                "query": {"type": "string", "description": "检索文本（必选）"},
                "top_k": {"type": "integer", "description": "返回条数（默认 5）"},
                "score_threshold": {"type": "number", "description": "相似度阈值（DECISION-006）"},
                "access_token": {"type": "string", "description": "用户 Access Token（ToolInterceptor 强制注入）"},
            },
            "required": ["kb_ids", "query"],
        },
    ),
]


def _error_result(msg: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=msg)], isError=True)


def _text_result(payload: dict) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))],
        structuredContent=payload,
    )


def _internal_headers(idn) -> dict[str, str]:
    """机器凭证代执行：X-Auth-* HMAC 签名头（DECISION-009），身份=注入的用户 token。"""
    ts = int(time.time())
    nonce = secrets.token_hex(8)
    scopes_csv = ",".join(idn.scopes)
    msg = f"{idn.tenant_id}|{idn.user_id}|{scopes_csv}|{nonce}|{ts}"
    import hashlib
    import hmac

    sig = hmac.new(
        settings.INTERNAL_HMAC_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        "X-Auth-Tenant": idn.tenant_id,
        "X-Auth-User": idn.user_id,
        "X-Auth-Scopes": scopes_csv,
        "X-Auth-Nonce": nonce,
        "X-Auth-Ts": str(ts),
        "X-Auth-Sig": sig,
    }


# ---------------------------------------------------------------- 工具实现（薄封装）

async def _upload_doc(args: dict) -> CallToolResult:
    try:
        idn = identity(args.get("access_token"))
    except ValueError as exc:
        return _error_result(f"auth failed: {exc}")
    file_name = args.get("file_name") or ""
    content = args.get("content") or ""
    if not file_name:
        return _error_result("file_name is required")
    data = content.encode("utf-8")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{PLATFORM_API_BASE}/internal/storage/upload",
            headers=_internal_headers(idn),
            files={"file": (file_name, data, "text/plain")},
            data={"source": args.get("source", "mcp:platform"), "agent_id": args.get("agent_id") or ""},
        )
    if resp.status_code >= 400:
        return _error_result(f"upload failed ({resp.status_code}): {resp.text[:500]}")
    return _text_result(resp.json())


async def _query_doc(args: dict) -> CallToolResult:
    try:
        idn = identity(args.get("access_token"))
    except ValueError as exc:
        return _error_result(f"auth failed: {exc}")
    headers = _internal_headers(idn)
    params: dict[str, Any] = {}
    file_name = args.get("file_name")
    if file_name:
        params["file_name"] = file_name
    else:
        if args.get("prefix"):
            params["prefix"] = args["prefix"]
        params["page_size"] = str(min(int(args.get("limit") or 20), 500))
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(f"{PLATFORM_API_BASE}/internal/storage/files", headers=headers, params=params)
        if resp.status_code >= 400:
            return _error_result(f"query failed ({resp.status_code}): {resp.text[:500]}")
        payload = resp.json()
        # text 类文件内联 content（query_doc 工具出参=内容/列表，STORE-07）
        items = []
        for it in payload.get("items", []):
            row = dict(it)
            if it.get("content_type") and it["content_type"].startswith("text/"):
                r2 = await client.get(
                    f"{PLATFORM_API_BASE}/internal/storage/files/{it['file_name']}", headers=headers
                )
                if r2.status_code == 200:
                    row["content"] = r2.text
                else:
                    row["content"] = None
                    row["content_error"] = f"{r2.status_code}"
            items.append(row)
        payload["items"] = items
    return _text_result(payload)


async def _rag_search(args: dict) -> CallToolResult:
    try:
        idn = identity(args.get("access_token"))
    except ValueError as exc:
        return _error_result(f"auth failed: {exc}")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{PLATFORM_API_BASE}/internal/rag/search",
            headers={**_internal_headers(idn), "Content-Type": "application/json"},
            json={
                "kb_ids": args.get("kb_ids") or [],
                "query": args.get("query") or "",
                "top_k": args.get("top_k") or 5,
                "score_threshold": args.get("score_threshold"),
                "agent_id": args.get("agent_id"),
            },
        )
    if resp.status_code >= 400:
        return _error_result(f"rag_search failed ({resp.status_code}): {resp.text[:500]}")
    return _text_result(resp.json())


_DISPATCH = {
    "upload_doc": _upload_doc,
    "query_doc": _query_doc,
    "rag_search": _rag_search,
}


def build_server() -> Server:
    """构造 lowlevel MCP Server（Streamable HTTP 挂载，DECISION-011）。"""
    server: Server = Server("joker-platform-mcp", version="0.1.0-s02")

    @server.list_tools()
    async def _list() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def _call(name: str, args: dict | None) -> CallToolResult:
        fn = _DISPATCH.get(name)
        if fn is None:
            return _error_result(f"unknown tool: {name}")
        try:
            return await fn(args or {})
        except httpx.HTTPError as exc:
            return _error_result(f"platform api unreachable: {exc}")
        except Exception as exc:  # 工具内异常 → 语义化错误（不崩溃）
            log.exception("mcp tool %s failed", name)
            return _error_result(f"tool {name} failed: {exc}")

    return server
