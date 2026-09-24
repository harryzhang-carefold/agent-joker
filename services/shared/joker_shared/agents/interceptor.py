"""ToolInterceptor 占位实现（S07；S08 统一替换为完整拦截动作链）。

DECISION-015：模式①拦截 = 进程内共享库调用（SimpleAgentRuntime 与拦截器同容器组）。
本卡以「进程内直调 / 占位拦截」实现完整闭环（三动作骨架）：
  ① scope 校验（mcp_tools.required_scopes × 用户 scopes；失败 → 拒绝语义，不执行）
  ② 身份注入（用户 Access Token 强制注入工具入参 access_token，防 LLM 伪造）
  ③ 代理执行（平台工具 → /internal/* 机器凭证代执行；远端 MCP → mcp client tools/call）
  + tool_call trace 事件留痕（SAR 进程内写点，ARCH §4.4）

S08 将本模块替换为统一 ToolInterceptor 动作链（与 BFF 模式②完全一致的 ①②③），
本卡保持调用接口不变（execute_tool_call / register_agent_tools）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import crypto
from joker_shared import trace as _trace
from joker_shared.config import settings

log = logging.getLogger("joker.tool_interceptor")

PLATFORM_API_BASE = settings.BFF_PLATFORM_API_BASE or "http://api:8001"

# 平台工具名 → 内部 API 代执行（S02/S05 已实装端点；RISK-003 双路径之一=平台 MCP 工具）
_PLATFORM_TOOL_EXEC: dict[str, dict[str, str]] = {
    "upload_doc": {"method": "POST", "path": "/internal/storage/upload"},
    "query_doc": {"method": "GET", "path": "/internal/storage/files"},
    "rag_search": {"method": "POST", "path": "/internal/rag/search"},
}


class ToolExecutionError(Exception):
    """工具执行失败（语义化错误文本返回给 LLM，不崩溃）。"""


def _new_id() -> str:
    return str(uuid.uuid4())


async def ensure_trace_session(
    session: AsyncSession, tenant_id: str, agent_id: str | None, user_id: str
) -> str | None:
    """取/建 trace_sessions（S09 统一 TraceService；agent/user 回退语义见 trace.ensure_trace_session）。"""
    return await _trace.ensure_trace_session(session, tenant_id, agent_id, user_id)


async def write_tool_call_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    trace_session_id: str | None,
    user_id: str | None,
    agent_id: str | None,
    tool_name: str,
    tool_server_id: str | None,
    payload: dict,
    status: str,
    latency_ms: int,
    file_id: str | None = None,
    rag_kb_id: str | None = None,
    message_id: str | None = None,
) -> None:
    """tool_call trace 事件（SAR/BFF 进程内写点；写失败不阻断主流程；payload 脱敏）。

    trace_session_id 缺失时（如 BFF /mcp 直连路径）按需回退建 trace session
    （D-B：MCP 工具调用 100% 留痕，BFF-06 验收 1）。
    """
    if trace_session_id is None:
        trace_session_id = await ensure_trace_session(session, tenant_id, agent_id, user_id)
        if trace_session_id is None:
            return
    await _trace.write_event(
        session,
        tenant_id=tenant_id,
        trace_session_id=trace_session_id,
        user_id=user_id,
        event_type="tool_call",
        payload=payload,
        tool_name=tool_name,
        tool_server_id=tool_server_id,
        rag_kb_id=rag_kb_id,
        file_id=file_id,
        message_id=message_id,
        status=status,
        latency_ms=latency_ms,
    )


# ============================================================ 工具解析（标识 → 行 + schema）


async def resolve_tool(
    session: AsyncSession, tenant_id: str, tool_id: str
) -> dict[str, Any] | None:
    """按 mcp_tools.id 取工具行（含 server），usable=false 返回 None（不可调用语义）。"""
    r = await session.execute(
        text(
            """SELECT t.id, t.server_id, t.name, t.source, t.enabled, t.removed_remote,
                      t.required_scopes, t.input_schema, s.status AS server_status, s.url AS server_url,
                      s.transport AS server_transport,
                      s.is_platform, s.tenant_id AS server_tenant_id, s.auth_headers_enc
               FROM mcp_tools t JOIN mcp_servers s ON s.id = t.server_id
               WHERE t.id = CAST(:id AS uuid) AND t.deleted_at IS NULL
                 AND (s.tenant_id = CAST(:t AS uuid) OR s.is_platform = true) AND s.deleted_at IS NULL"""
        ),
        {"id": tool_id, "t": tenant_id},
    )
    row = r.first()
    if row is None:
        return None
    d = dict(row._mapping)
    for k in ("id", "server_id", "server_tenant_id"):
        d[k] = str(d[k])
    if isinstance(d.get("required_scopes"), str):
        try:
            d["required_scopes"] = json.loads(d["required_scopes"])
        except ValueError:
            d["required_scopes"] = ["mcp:tool"]
    if isinstance(d.get("input_schema"), str):
        try:
            d["input_schema"] = json.loads(d["input_schema"])
        except ValueError:
            d["input_schema"] = {}
    return d


def scope_denied(tool: dict, scopes: list[str]) -> list[str]:
    """① scope 校验：返回缺失的 scope 列表（空 = 通过）。

    平台工具 scope（storage:write 等）与远端工具通用 scope（mcp:tool）；
    agent:use:* 通配不满足工具 scope（工具 scope 与 agent 访问 scope 分域）。
    """
    required = tool.get("required_scopes") or ["mcp:tool"]
    missing = [s for s in required if s not in scopes]
    return missing


# ============================================================ 执行（③ 代理执行）


def _internal_headers(tenant_id: str, user_id: str, scopes: list[str]) -> dict[str, str]:
    return crypto.build_internal_headers(tenant_id, user_id, scopes)


async def _exec_platform_tool(
    tool: dict, args: dict, tenant_id: str, user_id: str, scopes: list[str]
) -> dict:
    """平台工具 → /internal/* 代执行（DECISION-009 机器凭证；身份=用户）。"""
    spec = _PLATFORM_TOOL_EXEC.get(tool["name"])
    if spec is None:
        raise ToolExecutionError(f"unknown platform tool: {tool['name']}")
    headers = _internal_headers(tenant_id, user_id, scopes)
    out: dict[str, Any] = {}
    if spec["method"] == "POST":
        async with httpx.AsyncClient(timeout=60) as client:
            if tool["name"] == "upload_doc":
                data = (args.get("content") or "").encode("utf-8")
                r = await client.post(
                    f"{PLATFORM_API_BASE}{spec['path']}",
                    headers=headers,
                    files={"file": (args.get("file_name") or "unnamed", data, "text/plain")},
                    data={"source": args.get("source", "agent"), "agent_id": args.get("agent_id") or ""},
                )
            else:  # rag_search
                r = await client.post(
                    f"{PLATFORM_API_BASE}{spec['path']}",
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "kb_ids": args.get("kb_ids") or [],
                        "query": args.get("query") or "",
                        "top_k": args.get("top_k") or 5,
                        "score_threshold": args.get("score_threshold"),
                        "agent_id": args.get("agent_id"),
                    },
                )
        out = {"status_code": r.status_code}
        try:
            out["body"] = r.json()
        except ValueError:
            out["body"] = r.text[:500]
    else:  # GET query_doc
        params: dict[str, Any] = {}
        if args.get("file_name"):
            params["file_name"] = args["file_name"]
        else:
            if args.get("prefix"):
                params["prefix"] = args["prefix"]
            params["page_size"] = str(min(int(args.get("limit") or 20), 500))
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{PLATFORM_API_BASE}{spec['path']}", headers=headers, params=params)
        out = {"status_code": r.status_code}
        try:
            payload = r.json()
            # text 类文件内联 content（query_doc 契约，S02 同款）
            for it in payload.get("items", []):
                if (it.get("content_type") or "").startswith("text/"):
                    r2 = await client.get(
                        f"{PLATFORM_API_BASE}/internal/storage/files/{it['file_name']}", headers=headers
                    )
                    it["content"] = r2.text if r2.status_code == 200 else None
            out["body"] = payload
        except ValueError:
            out["body"] = r.text[:500]
    return out


async def _exec_remote_mcp(
    tool: dict, args: dict, tenant_id: str, user_id: str, scopes: list[str], access_token: str
) -> dict:
    """远端 MCP 工具 → mcp client tools/call（streamable_http / sse 按 server 配置）。

    身份注入（②）：access_token 强制写入 args（LLM 传入值一律覆写）。
    机器凭证：server 注册的 auth_headers_enc（Fernet 解密，DECISION-012）。
    """
    from mcp import ClientSession
    from mcp.client import sse, streamable_http

    from joker_shared.mcp.client import MCPProbeError

    headers: dict[str, str] = {}
    if tool.get("auth_headers_enc"):
        try:
            dec = json.loads(crypto.decrypt_secret(tool["auth_headers_enc"]))
            if isinstance(dec, dict):
                headers.update({str(k): str(v) for k, v in dec.items()})
        except Exception as exc:
            raise ToolExecutionError(f"server auth_headers decrypt failed: {exc}") from exc
    args = dict(args)
    args["access_token"] = access_token  # ② 强制注入（覆写 LLM 传值）

    t0 = time.monotonic()
    timeout = settings.MCP_PROBE_TIMEOUT_SECONDS
    transport = tool.get("server_transport") or "streamable_http"
    try:
        if transport == "sse":
            async with sse.sse_client(
                tool["server_url"], headers=headers or None, timeout=timeout,
                sse_read_timeout=timeout * 10,
            ) as (read, write):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    result = await s.call_tool(tool["name"], args)
        else:
            async with streamable_http.streamablehttp_client(
                tool["server_url"], headers=headers or None, timeout=timeout
            ) as (read, write, _):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    result = await s.call_tool(tool["name"], args)
    except MCPProbeError as exc:
        raise ToolExecutionError(f"mcp server unreachable: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ToolExecutionError(f"mcp call failed: {type(exc).__name__}: {exc}") from exc

    latency = int((time.monotonic() - t0) * 1000)
    texts: list[str] = []
    for c in getattr(result, "content", []) or []:
        t = getattr(c, "text", None)
        if t is not None:
            texts.append(t)
    return {
        "status_code": 200,
        "body": {"result": texts[0] if len(texts) == 1 else texts,
                 "is_error": bool(getattr(result, "isError", False))},
        "latency_ms": latency,
    }


# ============================================================ 拦截器主入口


async def execute_tool_call(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    scopes: list[str],
    agent_id: str,
    tool_id: str,
    args: dict,
    access_token: str,
    trace_session_id: str | None = None,
) -> dict:
    """三动作链（S07 占位拦截器；S08 替换为统一 ToolInterceptor 动作链）。

    返回 {ok, tool_name, result|error, denied?}——result 为工具执行结果（dict），
    失败时 error=语义化错误文本（回给 LLM 作为 tool 消息内容）。
    100% 经本函数（D-B 不变量：无裸执行路径）。
    """
    t0 = time.monotonic()
    tool = await resolve_tool(session, tenant_id, tool_id)
    if tool is None:
        return await _fail(session, tenant_id, user_id, agent_id, trace_session_id,
                           f"tool not found or unavailable: {tool_id}", {"ok": False}, t0)

    # ① scope 校验（失败 → 拒绝 + 权限不足语义，不执行）
    missing = scope_denied(tool, scopes)
    if missing:
        denied = f"tool call denied: missing required scopes {missing} (ToolInterceptor ①)"
        await write_tool_call_event(
            session, tenant_id=tenant_id, trace_session_id=trace_session_id,
            user_id=user_id, agent_id=agent_id, tool_name=tool["name"],
            tool_server_id=tool["server_id"], payload={"args": _redact(args), "denied": True},
            status="denied", latency_ms=int((time.monotonic() - t0) * 1000),
        )
        return {"ok": False, "tool_name": tool["name"], "error": denied, "denied": True}

    # 可用性：enabled && !removed_remote && server online（ARCH §3.2 工具状态机）
    if not (tool["enabled"] and not tool["removed_remote"] and tool["server_status"] == "online"):
        err = (f"tool {tool['name']} not callable "
               f"(enabled={tool['enabled']}, removed_remote={tool['removed_remote']}, "
               f"server={tool['server_status']})")
        return await _fail(session, tenant_id, user_id, agent_id, trace_session_id,
                           err, {"ok": False, "tool_name": tool["name"]}, t0)

    # ② 身份注入 + ③ 代理执行
    try:
        if tool["source"] == "platform":
            result = await _exec_platform_tool(tool, args, tenant_id, user_id, scopes)
        else:
            result = await _exec_remote_mcp(tool, args, tenant_id, user_id, scopes, access_token)
    except ToolExecutionError as exc:
        return await _fail(session, tenant_id, user_id, agent_id, trace_session_id,
                           str(exc), {"ok": False, "tool_name": tool["name"]}, t0)

    status = "ok" if result.get("status_code") < 400 else "error"
    await write_tool_call_event(
        session, tenant_id=tenant_id, trace_session_id=trace_session_id,
        user_id=user_id, agent_id=agent_id, tool_name=tool["name"],
        tool_server_id=tool["server_id"],
        payload={"args": _redact(args), "status_code": result.get("status_code"),
                 "result_preview": _preview(result.get("body"))},
        status=status, latency_ms=int((time.monotonic() - t0) * 1000),
    )
    if status != "ok":
        return {"ok": False, "tool_name": tool["name"],
                "error": f"tool {tool['name']} returned HTTP {result.get('status_code')}: "
                         f"{_preview(result.get('body'))}"}
    return {"ok": True, "tool_name": tool["name"], "result": result.get("body")}


async def _fail(session, tenant_id, user_id, agent_id, trace_session_id, err, payload, t0) -> dict:
    await write_tool_call_event(
        session, tenant_id=tenant_id, trace_session_id=trace_session_id,
        user_id=user_id, agent_id=agent_id, tool_name=payload.get("tool_name", "?"),
        tool_server_id=None, payload={**payload, "error": err},
        status="error", latency_ms=int((time.monotonic() - t0) * 1000),
    )
    return {"ok": False, "error": err}


def _redact(args: dict) -> dict:
    """args 留痕脱敏（access_token 一律剔除，DECISION-012 不落明文凭证）。"""
    return {k: v for k, v in (args or {}).items() if k != "access_token"}


def _preview(body: Any, limit: int = 300) -> str:
    try:
        s = json.dumps(body, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = str(body)
    return s[:limit]
