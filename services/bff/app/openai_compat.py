"""OpenAI 兼容协议转换（BFF-04，DECISION-016，ARCH §4.5）：POST /v1/chat/completions。

- `model` = agent 名称（agents.name，租户内唯一）——单一语义（DECISION-016 修订）。
  解析路径（跨租户不暴露存在性）：① JWT 取 tenant → ② 本租户按 name=model 查 agent
  （不存在 → 404，天然排除跨租户）→ ③ 校验 scopes 含 agent:use:<id>（或 agent:use:*）
  （无权限 → 403）→ ④ 路由到运行时（simple→SAR / third_party→URL 代理，S07）。
- 双模式：`stream: false` 块式（单 JSON）；`stream: true` SSE（`data: {...}` 增量 + `data: [DONE]`）。
  标准 OpenAI SDK 可直接 `base_url=http://bff:8000/v1, api_key=<jwt>` 调用（BFF-04 验收 2）。
- 出参 = OpenAI Chat Completions schema：id/object/created/model/choices[].message
  (role/content/tool_calls)/usage。工具调用以 choices[].message.tool_calls 表达（块式）。
- `show_citations`（可选，DECISION-017）透传到运行时。

说明：运行时（SAR / 第三方代理）内部已跑完 tool-calling loop，最终回复含引用；
本 adapter 负责「OpenAI 协议封装 + agent 解析 + scope 校验 + 会话续接」，工具拦截
（ToolInterceptor）在运行时进程内执行（DECISION-015），BFF 侧经同一共享库。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway import current_identity, current_token, identity_for
from joker_shared.config import settings
from joker_shared.db import get_session_factory

log = logging.getLogger("joker.bff.openai")

# BFF 侧独立 DB 会话（SAR 运行时进程内执行，BFF 提供身份/agent 解析/会话）
def _session() -> AsyncSession:
    factory = get_session_factory()
    return factory()


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- agent 解析（DECISION-016）

async def resolve_agent(session: AsyncSession, tenant_id: str, model: str) -> dict:
    """本租户按 name=model 查 agent（跨租户 404 不暴露存在性）。"""
    r = await session.execute(
        text("SELECT id, name, type, status, max_tool_rounds, show_citations_default, "
             "system_prompt, model_params, third_party_url, third_party_auth_enc, "
             "third_party_session_param FROM agents "
             "WHERE tenant_id = CAST(:t AS uuid) AND name = :n AND deleted_at IS NULL"),
        {"t": tenant_id, "n": model},
    )
    row = r.first()
    if row is None:
        raise HTTPException(404, f"agent not found: {model}")
    d = dict(row._mapping)
    d["id"] = str(d["id"])
    if isinstance(d.get("model_params"), str):
        try:
            d["model_params"] = json.loads(d["model_params"])
        except ValueError:
            d["model_params"] = None
    return d


def _can_use(scopes: list[str], agent_id: str) -> None:
    """agent:use 门禁（精确 scope 或 agent:use:* 通配，BFF-05）。"""
    if agent_id not in ("",) and f"agent:use:{agent_id}" not in scopes and "agent:use:*" not in scopes:
        raise HTTPException(403, f"missing scope: agent:use:{agent_id}")


# ---------------------------------------------------------------- 会话（续接）

async def _resolve_session(
    session: AsyncSession, tenant_id: str, user_id: str, agent_id: str,
    session_id: str | None, title: str,
) -> str:
    """复用 session_id（校验归属+active）或新建。返回 session_id。"""
    if session_id:
        r = await session.execute(
            text("SELECT id, agent_id, status FROM agent_sessions "
                 "WHERE id = CAST(:s AS uuid) AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"),
            {"s": session_id, "t": tenant_id},
        )
        s = r.first()
        if s is None or str(s[1]) != agent_id:
            raise HTTPException(404, f"session not found: {session_id}")
        if s[2] == "closed":
            raise HTTPException(409, "session closed; start a new one")
        return str(s[0])
    sid = _new_id()
    await session.execute(
        text("INSERT INTO agent_sessions (id, tenant_id, agent_id, user_id, title, status, created_by) "
             "VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:a AS uuid), CAST(:u AS uuid), :ti, 'active', CAST(:u AS uuid))"),
        {"id": sid, "t": tenant_id, "a": agent_id, "u": user_id, "ti": title[:40] or "chat", "u": user_id},
    )
    await session.commit()
    return sid


# ---------------------------------------------------------------- 运行时调用（S07）

async def _run_agent(
    session: AsyncSession, *, tenant_id: str, user_id: str, scopes: list[str],
    agent: dict, session_id: str, message: str, show_citations: bool | None,
    access_token: str,
) -> dict:
    """simple → SimpleAgentRuntime；third_party → ThirdPartyAgent（S07，进程内，DECISION-015）。"""
    from joker_shared.agents.service import AgentService

    # 运行时需要完整 agent（四要素勾选）；用 get_full_agent 补齐
    full = await AgentService().get_full_agent(session, tenant_id, agent["id"])
    if full is None:
        raise HTTPException(404, "agent not found")
    if full["status"] != "active":
        raise HTTPException(409, f"agent disabled: {agent['id']}")
    return await AgentService().chat(
        session, tenant_id=tenant_id, user_id=user_id, scopes=scopes,
        agent_id=agent["id"], message=message, session_id=session_id,
        show_citations=show_citations, access_token=access_token, files=[],
    )


# ---------------------------------------------------------------- OpenAI 响应组装

def _tool_calls_openai(tool_calls: list[dict]) -> list[dict]:
    """运行时 tool_calls 事件 → OpenAI message.tool_calls 结构。"""
    out = []
    for tc in tool_calls or []:
        fn_name = tc.get("name") or ""
        out.append({
            "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {"name": fn_name,
                         "arguments": json.dumps(tc.get("args") or {}, ensure_ascii=False)},
        })
    return out


def _usage(tokens: dict | None) -> dict:
    tokens = tokens or {}
    pt = int(tokens.get("prompt_tokens", 0))
    ct = int(tokens.get("completion_tokens", 0))
    tt = int(tokens.get("total_tokens", pt + ct))
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt}


def _block_response(model: str, result: dict) -> dict:
    """块式 OpenAI Chat Completions（BFF-04 验收 1）。"""
    return {
        "id": f"chatcmpl-{result.get('session_id', 'x')[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": result.get("reply") or "",
                "tool_calls": _tool_calls_openai(result.get("tool_calls")),
            },
        }],
        "usage": _usage(result.get("tokens")),
        # 平台扩展字段（非标准，OpenAI SDK 忽略）：会话续接 + 引用
        "joker": {
            "session_id": result.get("session_id"),
            "citations": result.get("citations"),
            "agent_id": result.get("agent_id"),
        },
    }


async def _sse_stream(model: str, result: dict) -> AsyncIterator[bytes]:
    """SSE 流式（BFF-04 验收 2）：role 增量 → content 增量 → tool_calls → usage → [DONE]。"""
    cid = f"chatcmpl-{result.get('session_id', 'x')[:24]}"

    def _chunk(obj: dict) -> bytes:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")

    base = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model}
    # 1) role
    yield _chunk({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""},
                                        "finish_reason": None}]})
    # 2) content（分块，模拟增量）
    content = result.get("reply") or ""
    step = max(1, len(content) // 8) if content else 0
    if content:
        for i in range(0, len(content), step):
            yield _chunk({**base, "choices": [{"index": 0,
                                                "delta": {"content": content[i:i + step]},
                                                "finish_reason": None}]})
    # 3) tool_calls（若运行时产生）
    tcs = _tool_calls_openai(result.get("tool_calls"))
    if tcs:
        yield _chunk({**base, "choices": [{"index": 0, "delta": {"tool_calls": tcs},
                                            "finish_reason": None}]})
    # 4) finish + usage
    yield _chunk({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                  "usage": _usage(result.get("tokens"))})
    yield b"data: [DONE]\n\n"


# ---------------------------------------------------------------- 主入口

async def handle_chat_completions(request: Request):
    idn = identity_for(request)
    token = current_token(request)
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(422, "invalid JSON body")

    model = (body.get("model") or "").strip()
    if not model:
        raise HTTPException(422, "model (agent name) is required")
    messages = body.get("messages") or []
    stream = bool(body.get("stream", False))
    show_citations = body.get("show_citations")
    session_id = body.get("session_id")  # 平台扩展：会话续接（OpenAI SDK 不传则新建）

    # 取最后一条 user 消息
    user_message = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                user_message = c
            elif isinstance(c, list):
                user_message = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            break
    if not user_message.strip():
        raise HTTPException(422, "no user message found")

    tenant_id, user_id, scopes = idn["tenant_id"], idn["user_id"], idn["scopes"]

    async with _session() as session:
        # ① 解析 agent（跨租户 404）② scope 校验（403）
        agent = await resolve_agent(session, tenant_id, model)
        _can_use(scopes, agent["id"])
        # ③ 会话
        sid = await _resolve_session(session, tenant_id, user_id, agent["id"], session_id,
                                     user_message)
        # ④ 运行时（S07，进程内，DECISION-015）
        result = await _run_agent(
            session, tenant_id=tenant_id, user_id=user_id, scopes=scopes, agent=agent,
            session_id=sid, message=user_message, show_citations=show_citations,
            access_token=token,
        )

    if stream:
        return StreamingResponse(
            _sse_stream(model, result),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return JSONResponse(_block_response(model, result))
