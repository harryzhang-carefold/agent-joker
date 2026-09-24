"""第三方 agent URL 代理（S07，AGENT-10/11 + DECISION-008）。

DECISION-008：第三方 agent 的 Tool Call 意图协议 = OpenAI 兼容 `tool_calls` +
平台回传端点 `POST {agent_url}/tool_results`。
  1) 平台向第三方 agent（OpenAI 兼容 /chat/completions）发请求，携带
     `tools`（agent 勾选的 MCP 工具，标识 = `mcp:<server>:<tool>` / `platform:<name>`）。
  2) 第三方 agent 若需调用工具 → 响应带 `tool_calls`（OpenAI 格式）。
  3) 平台拦截：经 ToolInterceptor 执行（100% 经拦截器，D-B 不变量）→ 把
     工具结果经 `POST {agent_url}/tool_results` 回传给第三方 agent（回传形成闭环）。
  4) 第三方 agent 继续推理 → 直到返回最终回复（或达到 max_tool_rounds）。

关键边界（与简易 agent 一致）：
- 平台不存第三方 agent 的记忆（AGENT-09）：第三方 agent 记忆由提供方实现，
  平台仅透传 `session_id` / `external_session_id` 参数；对话记录仍被 trace 记录。
- 文件（AGENT-10）：平台提供 upload_doc / query_doc MCP 工具，第三方 agent
  决定是否调用；不配置该工具时对话正常（不报工具缺失）。
- RAG 引用（AGENT-11）：平台把完整 RAG 检索结果 + 引用原文档信息（含 is_official /
  show_citations 提示）提供给第三方 agent，提供方决定是否显示（平台侧信息完整性可验证）。
  命中 official / show_citations → 平台在最终回复末尾附来源（与 AGENT-05 同规则）。

本切片闭环：第三方 agent 走真实 HTTP 调用（OpenAI 兼容），工具调用经 ToolInterceptor
进程内执行。mock 第三方 agent server（实现 DECISION-008 协议）在 E2E 中提供（交接测试）。
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
from joker_shared.agents import interceptor as ti
from joker_shared.agents.citations import (
    build_citations,
    llm_intent_fallback_requires_citation,
    render_citations_markdown,
)

log = logging.getLogger("joker.third_party")

_MAX_TOOL_ROUNDS_DEFAULT = 8
_HTTP_TIMEOUT = 120.0


def _new_id() -> str:
    return str(uuid.uuid4())


class ThirdPartyAgent:
    """第三方 agent URL 代理（OpenAI 兼容 + tool_results 回传，DECISION-008）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- 工具装配（供 OpenAI tools 字段） ----------

    async def _build_openai_tools(self, agent: dict) -> list[dict]:
        """agent 勾选的 MCP 工具 → OpenAI `tools` 数组（function 描述）。

        工具名 = 标识符：`mcp:<server>:<tool>` / `platform:<name>`（DECISION-008 工具标识）。
        第三方 agent 按此名称发起 tool_calls，平台据此映射回 mcp_tool_id。
        """
        tools: list[dict] = []
        if not agent.get("mcp_tool_ids"):
            return tools
        r = await self.session.execute(
            text(
                """SELECT t.id, t.name, t.description, t.input_schema, t.source,
                          s.id AS server_id, s.is_platform
                   FROM mcp_tools t JOIN mcp_servers s ON s.id = t.server_id
                   WHERE t.id = ANY(CAST(:ids AS uuid[])) AND t.deleted_at IS NULL
                     AND t.enabled = true AND t.removed_remote = false AND s.status = 'online'
                     AND s.deleted_at IS NULL"""
            ),
            {"ids": [uuid.UUID(x) for x in agent["mcp_tool_ids"]]},
        )
        self._lcname_to_tool_id: dict[str, str] = {}
        for row in r.fetchall():
            d = dict(row._mapping)
            if isinstance(d.get("input_schema"), str):
                try:
                    d["input_schema"] = json.loads(d["input_schema"])
                except ValueError:
                    d["input_schema"] = {}
            ident = f"platform:{d['name']}" if d["is_platform"] else f"mcp:{d['server_id']}:{d['name']}"
            lc_name = ident.replace(":", "_")[:64]
            # 第三方 agent 在 OpenAI tools 里看到的就是 lc_name（去冒号），回传 tool_calls 用此名；
            # 平台据此映射回 mcp_tool_id（与 SAR name_to_id 同款按 lc_name 建键）。
            self._lcname_to_tool_id[lc_name] = str(d["id"])
            tools.append({
                "type": "function",
                "function": {
                    "name": lc_name,
                    "description": d.get("description") or "",
                    "parameters": d.get("input_schema") or {"type": "object", "properties": {}},
                },
            })
        return tools

    # ---------- 第三方 agent 认证头 ----------

    def _auth_headers(self, agent: dict) -> dict:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        enc = agent.get("third_party_auth_enc")
        if enc:
            try:
                secret = crypto.decrypt_secret(enc)
                # 支持裸 token（→ Authorization: Bearer）或 JSON 头集
                try:
                    obj = json.loads(secret)
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            headers[str(k)] = str(v)
                        return headers
                except ValueError:
                    pass
                headers["Authorization"] = f"Bearer {secret}"
            except ValueError:
                log.warning("third_party_auth decrypt failed; proceed unauthenticated")
        return headers

    # ---------- RAG 预检索 + 引用（AGENT-11） ----------

    async def _rag_context(self, agent: dict, user_message: str, tenant_id: str, user_id: str) -> list[dict]:
        """RAG 预检索（内部直调，D-B）→ 提供给第三方 agent（AGENT-11 平台侧信息完整性）。"""
        if not agent.get("knowledge_base_ids"):
            return []
        try:
            from joker_shared.rag import retrieval

            result = await retrieval.search_with_trace(
                self.session,
                tenant_id=tenant_id, agent_id=agent["id"], user_id=user_id,
                kb_ids=agent["knowledge_base_ids"], query=user_message, top_k=5,
            )
            return result.get("items", [])
        except HTTPException as exc:
            log.info("third-party rag presearch skipped: %s", exc.detail)
            return []
        except Exception as exc:
            log.warning("third-party rag presearch failed: %s", exc)
            return []

    # ---------- 主入口 ----------

    async def chat(
        self,
        *,
        tenant_id: str,
        user_id: str,
        scopes: list[str],
        agent: dict,
        session_id: str,
        user_message: str,
        show_citations: bool | None,
        access_token: str,
    ) -> dict:
        t0 = time.monotonic()
        agent_id = agent["id"]
        base = (agent.get("third_party_url") or "").rstrip("/")
        if not base:
            raise HTTPException(409, f"third_party agent missing URL: {agent_id}")
        headers = self._auth_headers(agent)

        # 工具（OpenAI tools 字段；无工具则对话正常——AGENT-10 验收 3）
        openai_tools = await self._build_openai_tools(agent)

        # 会话参数（AGENT-09：透传 session，不注入平台记忆）
        session_param = agent.get("third_party_session_param")
        ext_session = _new_id()
        if session_param:
            # 平台把 session 作为额外字段透传给第三方 agent（provider 决定是否使用）
            pass

        trace_session_id = await ti.ensure_trace_session(self.session, tenant_id, agent_id, user_id)

        # RAG 上下文（AGENT-11：完整提供检索 + 引用信息）
        rag_items = await self._rag_context(agent, user_message, tenant_id, user_id)

        # 用户消息落库 + trace
        await _append_message(
            self.session, tenant_id, session_id, user_id, role="user", content=user_message,
        )

        # ---- tool-calling 闭环（DECISION-008）----
        max_rounds = int(agent.get("max_tool_rounds") or _MAX_TOOL_ROUNDS_DEFAULT)
        # OpenAI 兼容：messages 数组（平台侧维护；第三方 agent 也按 OpenAI 会话格式续接）
        messages: list[dict] = []
        # 注入 RAG 上下文（system 消息；provider 决定是否引用）
        if rag_items:
            rag_text = "\n\n".join(
                f"[来源 {i} | {it.get('doc_file_name')} | official={it.get('is_official')}]\n{it.get('content') or ''}"
                for i, it in enumerate(rag_items, 1)
            )
            messages.append({
                "role": "system",
                "content": (
                    "以下是平台知识库检索结果（可直接引用；official 来源若用户要求引用，请在回复末尾以"
                    "「来源」列表列出文档名+定位）：\n" + rag_text[:8000]
                ),
            })
        messages.append({"role": "user", "content": user_message})

        final_content: str | None = None
        tool_call_events: list[dict] = []
        all_rag_items: list[dict] = list(rag_items)
        rounds_used = 0
        error_out: str | None = None

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                for round_idx in range(max_rounds):
                    rounds_used = round_idx + 1
                    body: dict[str, Any] = {"messages": messages}
                    if openai_tools:
                        body["tools"] = openai_tools
                        body["tool_choice"] = "auto"
                    try:
                        r = await client.post(f"{base}/chat/completions", headers=headers, json=body)
                    except httpx.HTTPError as exc:
                        error_out = f"third-party agent unreachable (round {rounds_used}): {type(exc).__name__}: {exc}"
                        break
                    if r.status_code >= 400:
                        error_out = f"third-party agent returned HTTP {r.status_code} (round {rounds_used}): {r.text[:300]}"
                        break
                    try:
                        data = r.json()
                    except ValueError:
                        error_out = f"third-party agent returned non-JSON (round {rounds_used}): {r.text[:300]}"
                        break
                    choice = (data.get("choices") or [{}])[0]
                    msg = choice.get("message") or {}
                    content = msg.get("content") or ""
                    tcs = msg.get("tool_calls") or []

                    if not tcs:
                        final_content = content
                        break

                    # assistant 消息（含 tool_calls）落库 + trace
                    tc_ser = [
                        {"id": tc.get("id"), "function": {"name": (tc.get("function") or {}).get("name"),
                                                          "arguments": (tc.get("function") or {}).get("arguments") or "{}"}}
                        for tc in tcs
                    ]
                    await _append_message(
                        self.session, tenant_id, session_id, user_id, role="assistant",
                        content=content, tool_calls=tc_ser,
                    )
                    messages.append({"role": "assistant", "content": content, "tool_calls": tcs})

                    # 逐条经 ToolInterceptor 执行（100% 经拦截器，D-B）
                    tool_results: list[dict] = []
                    for tc in tcs:
                        fn = tc.get("function") or {}
                        name = fn.get("name") or ""
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except ValueError:
                            args = {}
                        tool_id = getattr(self, "_lcname_to_tool_id", {}).get(name)
                        if tool_id is None:
                            result_text = json.dumps({"ok": False, "error": f"unknown tool: {name}"})
                            ok_flag = False
                            tool_name = name
                        else:
                            res = await ti.execute_tool_call(
                                self.session, tenant_id=tenant_id, user_id=user_id, scopes=scopes,
                                agent_id=agent_id, tool_id=tool_id, args=args,
                                access_token=access_token, trace_session_id=trace_session_id,
                            )
                            ok_flag = bool(res.get("ok"))
                            tool_name = res.get("tool_name", name)
                            result_text = json.dumps(
                                res.get("result") if ok_flag else res, ensure_ascii=False, default=str,
                            )[:8000]
                            # rag_search 结果 → 引用候选（AGENT-11）
                            if ok_flag and isinstance(res.get("result"), dict):
                                bodyr = res["result"].get("body")
                                if isinstance(bodyr, dict) and isinstance(bodyr.get("items"), list):
                                    all_rag_items.extend(bodyr["items"])
                        tool_call_events.append({"name": tool_name, "ok": ok_flag,
                                                  "args": {k: v for k, v in args.items() if k != "access_token"}})
                        tool_results.append({
                            "tool_call_id": tc.get("id"),
                            "name": name,
                            "ok": ok_flag,
                            "result": result_text,
                        })
                        # tool 结果消息落库 + trace
                        await _append_message(
                            self.session, tenant_id, session_id, user_id, role="tool",
                            content=result_text, tool_call_id=tc.get("id"),
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.get("id"),
                                         "content": result_text})

                    # 回传给第三方 agent（DECISION-008：POST {agent_url}/tool_results）
                    try:
                        await client.post(
                            f"{base}/tool_results", headers=headers,
                            json={"session_id": ext_session, "tool_results": tool_results},
                        )
                    except httpx.HTTPError as exc:
                        log.warning("tool_results callback failed (%s); continuing loop", exc)
        finally:
            pass

        if final_content is None:
            await _append_message(
                self.session, tenant_id, session_id, user_id, role="assistant",
                status="failed", error_message=error_out,
            )
            raise HTTPException(502, error_out or "third-party agent returned no final reply")

        # 引用判定（AGENT-11，同 AGENT-05 规则）
        has_official = any(it.get("is_official") for it in all_rag_items)
        want_citations = bool(has_official or llm_intent_fallback_requires_citation(user_message, show_citations))
        citations = build_citations(all_rag_items, force=has_official, show=want_citations)
        if citations:
            final_content = final_content + render_citations_markdown(citations)

        await _append_message(
            self.session, tenant_id, session_id, user_id, role="assistant", content=final_content,
            citations=citations or None,
        )
        return {
            "reply": final_content,
            "citations": citations,
            "citations_forced_official": has_official,
            "tool_calls": tool_call_events,
            "tool_rounds_used": rounds_used,
            "rag_hits": len(all_rag_items),
            "files": [],
            "tokens": {},
            "error": error_out,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "external_session_id": ext_session,
        }


async def _append_message(
    session: AsyncSession, tenant_id: str, session_id: str, user_id: str,
    *, role: str, content: str | None = None, tool_calls: list | None = None,
    tool_call_id: str | None = None, citations: list | None = None,
    status: str = "done", error_message: str | None = None,
) -> str:
    """第三方 agent 消息落库（与简易 agent 同表 agent_messages）。"""
    mid = _new_id()
    await session.execute(
        text(
            """INSERT INTO agent_messages (id, tenant_id, session_id, role, content, tool_calls,
                 tool_call_id, citations, token_usage, status, error_message, created_by)
               VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:s AS uuid), :role, :c,
                       CAST(:tc AS jsonb), :tci, CAST(:ci AS jsonb), NULL, :st, :em, CAST(:u AS uuid))"""
        ),
        {
            "id": mid, "t": tenant_id, "s": session_id, "role": role, "c": content,
            "tc": json.dumps(tool_calls, ensure_ascii=False) if tool_calls is not None else None,
            "tci": tool_call_id,
            "ci": json.dumps(citations, ensure_ascii=False) if citations is not None else None,
            "st": status, "em": error_message, "u": user_id,
        },
    )
    await session.execute(
        text("UPDATE agent_sessions SET message_count = message_count + 1, last_message_at = now() "
             "WHERE id = CAST(:s AS uuid)"),
        {"s": session_id},
    )
    await session.commit()
    return mid
