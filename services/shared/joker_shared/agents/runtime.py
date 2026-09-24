"""SimpleAgentRuntime（S07，AGENT-02..09，LangChain tool-calling loop，DECISION-007）。

架构落位（本切片）：SAR 以共享库形态运行在 PlatformAPI 进程内（S08 起 BFF OpenAI
adapter 经内部调用驱动同一运行时；DECISION-015 的「SAR 与拦截器同容器组」在 S08
BFF 切片落地）。工具调用 100% 经 InterceptorTool 工厂 → ToolInterceptor 进程内
直调（占位拦截链；S08 替换为完整动作链）。无裸 Tool 注册路径（BFF-07 不变量）。

推理循环（DECISION-007 function-calling，非 ReAct）：
  messages = [system(+skills+长期记忆+RAG 预检索上下文)] + 短期记忆 + [user]
  loop ≤ max_tool_rounds:
    resp = llm.ainvoke(messages)            # LangChain ChatOpenAI（OpenAI 兼容端点）
    if resp.tool_calls: 逐条经 InterceptorTool 执行（拦截器）→ ToolMessage 回填
    else: 最终回复 → break

三层记忆（AGENT-07/08，DECISION-019）：
  短期 = Redis 会话内（读上下文 / 追加；Redis 故障退化为单轮）
  长期 = PG agent_memories（注入 top N；跨会话）
  沉淀 = 会话关闭时 LLM 提炼 → 长期记忆 + obsidian 笔记（service._settle_session）

引用（AGENT-05，DECISION-017 + D-A）：
  RAG 预检索（内部 API 直调，D-B：不产生 tool_call，保留身份/勾选 403/rag 事件）
  + rag_search MCP 工具（经拦截器，双路径 RISK-003）→ official 命中强制附来源 /
  show_citations 或 LLM 意图兜底附来源。

文件（AGENT-06）：用户消息携带附件 → StorageService 上传（source=agent，file 事件留痕）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field, create_model
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import crypto
from joker_shared import trace as _trace
from joker_shared.agents import interceptor as ti
from joker_shared.agents.citations import build_citations, llm_intent_fallback_requires_citation, render_citations_markdown
from joker_shared.agents.memory import (
    ShortTermMemory,
    get_long_term_memories,
    store_memory,
    touch_memories,
)
from joker_shared.llm import get_llm_service

log = logging.getLogger("joker.sar")

_RAG_PRE_TOP_K = 5
_MAX_CONTEXT_CHARS = 12000  # 短期记忆注入上限（防 token 爆炸）


def _new_id() -> str:
    return str(uuid.uuid4())


# ============================================================ InterceptorTool 工厂（DECISION-015）


def _schema_to_pydantic(input_schema: dict[str, Any]) -> type[BaseModel]:
    """JSON Schema → pydantic 模型（LangChain BaseTool.args_schema）。

    只支持基础类型（string/number/integer/boolean/array/object）；未知 → str。
    """
    props = (input_schema or {}).get("properties") or {}
    required = set((input_schema or {}).get("required") or [])
    fields: dict[str, Any] = {}
    for name, spec in props.items():
        t = (spec or {}).get("type")
        if t in ("integer", "number"):
            py = float if t == "number" else int
        elif t == "boolean":
            py = bool
        elif t == "array":
            py = list
        elif t == "object":
            py = dict
        else:
            py = str
        desc = (spec or {}).get("description")
        if name in required:
            fields[name] = (py, Field(..., description=desc))
        else:
            fields[name] = (py | None, Field(None, description=desc))
    if not fields:
        # 无参数工具：允许任意 kwargs（LLM 常传空 {}）
        fields["args"] = (dict, Field({}, description="无参数工具（忽略）"))
    return create_model("ToolArgs", **fields)


class InterceptorTool:
    """拦截包装 Tool（DECISION-015）：执行入口 100% 直调 ToolInterceptor。

    以 LangChain StructuredTool 承载（LLM tool-calling 兼容）；类工厂方法
    make_tool 是唯一构造路径——不存在绕过拦截器的裸 Tool 注册（BFF-07 验收 3）。
    """

    @staticmethod
    def make_tool(
        *, tool_id: str, tool_name: str, description: str, input_schema: dict[str, Any]
    ) -> Any:
        from langchain_core.tools import StructuredTool

        args_schema = _schema_to_pydantic(input_schema)

        async def _arun(**kwargs: Any) -> str:
            # 执行闭包在 SAR 进程内；身份/session 由工厂注入的 contextvar 提供
            ctx = _SAR_CTX.get()
            if ctx is None:
                return json.dumps({"ok": False, "error": "no SAR context (internal bug)"})
            result = await ti.execute_tool_call(
                ctx["session"],
                tenant_id=ctx["tenant_id"], user_id=ctx["user_id"], scopes=ctx["scopes"],
                agent_id=ctx["agent_id"], tool_id=tool_id, args=kwargs,
                access_token=ctx["access_token"], trace_session_id=ctx["trace_session_id"],
            )
            # 工具结果 → 文本（LLM 可读）；ok=False 时错误文本同样回给 LLM（让其处理/换路）
            if result.get("ok"):
                return json.dumps(result.get("result"), ensure_ascii=False, default=str)[:8000]
            return json.dumps(result, ensure_ascii=False, default=str)[:4000]

        from langchain_core.tools import StructuredTool as _ST

        return _ST(
            name=tool_name,
            description=description or "（无描述）",
            args_schema=args_schema,
            coroutine=_arun,
        )


from contextvars import ContextVar  # noqa: E402

_SAR_CTX: ContextVar[dict[str, Any] | None] = ContextVar("joker_sar_ctx", default=None)


# ============================================================ 消息持久化辅助


async def _append_message(
    session: AsyncSession, tenant_id: str, session_id: str, user_id: str,
    *, role: str, content: str | None = None, tool_calls: list | None = None,
    tool_call_id: str | None = None, citations: list | None = None,
    file_ids: list | None = None, token_usage: dict | None = None,
    status: str = "done", error_message: str | None = None,
) -> str:
    mid = _new_id()
    await session.execute(
        text(
            """INSERT INTO agent_messages (id, tenant_id, session_id, role, content, tool_calls,
                 tool_call_id, citations, file_ids, token_usage, status, error_message, created_by)
               VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:s AS uuid), :role, :c,
                       CAST(:tc AS jsonb), :tci, CAST(:ci AS jsonb), CAST(:fi AS jsonb),
                       CAST(:tu AS jsonb), :st, :em, CAST(:u AS uuid))"""
        ),
        {
            "id": mid, "t": tenant_id, "s": session_id, "role": role, "c": content,
            "tc": json.dumps(tool_calls, ensure_ascii=False) if tool_calls is not None else None,
            "tci": tool_call_id,
            "ci": json.dumps(citations, ensure_ascii=False) if citations is not None else None,
            "fi": json.dumps(file_ids, ensure_ascii=False) if file_ids is not None else None,
            "tu": json.dumps(token_usage) if token_usage else None,
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


async def _write_message_trace_event(
    session: AsyncSession, *, tenant_id: str, trace_session_id: str | None, user_id: str | None,
    agent_id: str, message_id: str, role: str, payload: dict, token_usage: dict | None = None,
) -> None:
    """message 事件（交互内容 + token 用量；payload 脱敏；S09 统一 TraceService）。"""
    await _trace.write_event(
        session,
        tenant_id=tenant_id,
        trace_session_id=trace_session_id,
        user_id=user_id,
        event_type="message",
        payload={"role": role, **payload},
        message_id=message_id,
        token_usage=token_usage,
    )


async def _write_file_trace_event(
    session: AsyncSession, *, tenant_id: str, trace_session_id: str | None, user_id: str | None,
    agent_id: str, file_name: str, file_id: str,
) -> None:
    """file 事件（上传/生成文件；payload 脱敏；S09 统一 TraceService）。"""
    await _trace.write_event(
        session,
        tenant_id=tenant_id,
        trace_session_id=trace_session_id,
        user_id=user_id,
        event_type="file",
        payload={"file_name": file_name, "direction": "in"},
        file_id=file_id,
    )


# ============================================================ 运行时


class SimpleAgentRuntime:
    """简易 agent 运行时（LangChain tool-calling loop）。进程内单例，无状态。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- 上下文装配 ----------

    async def _build_tools(self, agent: dict) -> tuple[list[Any], dict[str, str]]:
        """agent 勾选的 MCP 工具 → LangChain InterceptorTool 列表（唯一注册路径）。

        工具名（LLM function name）= 标识符去冒号：platform:upload_doc → platform_upload_doc；
        mcp:<server>:<tool> → mcp_<server>_<tool>（OpenAI function name 规则 ^[a-zA-Z0-9_-]+$）。
        返回 (tools, name→tool_id 映射)。
        """
        tools: list[Any] = []
        name_to_id: dict[str, str] = {}
        if not agent.get("mcp_tool_ids"):
            return tools, name_to_id
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
        for row in r.fetchall():
            d = dict(row._mapping)
            if isinstance(d.get("input_schema"), str):
                try:
                    d["input_schema"] = json.loads(d["input_schema"])
                except ValueError:
                    d["input_schema"] = {}
            ident = f"platform:{d['name']}" if d["is_platform"] else f"mcp:{d['server_id']}:{d['name']}"
            lc_name = ident.replace(":", "_")[:64]
            try:
                tool = InterceptorTool.make_tool(
                    tool_id=d["id"], tool_name=lc_name,
                    description=d.get("description") or "", input_schema=d.get("input_schema") or {},
                )
            except Exception as exc:
                log.warning("skip tool %s (schema build failed: %s)", lc_name, exc)
                continue
            tools.append(tool)
            name_to_id[lc_name] = d["id"]
        return tools, name_to_id

    async def _rag_presearch(self, agent: dict, user_message: str, tenant_id: str,
                             user_id: str) -> tuple[list[dict], dict | None]:
        """RAG 预检索（内部 API 直调路径，D-B / RISK-003 双通道之一）。

        直调检索核心（与 /internal/rag/search 同函数）：(agent_id,kb_id) 勾选校验
        （未勾选 403 → 本处捕获=不检索，不崩溃）+ rag trace 事件留痕（不产生 tool_call）。
        返回 (items, error|None)。
        """
        if not agent.get("knowledge_base_ids"):
            return [], None
        try:
            from joker_shared.rag import retrieval

            result = await retrieval.search_with_trace(
                self.session,
                tenant_id=tenant_id, agent_id=agent["id"], user_id=user_id,
                kb_ids=agent["knowledge_base_ids"], query=user_message, top_k=_RAG_PRE_TOP_K,
            )
            return result.get("items", []), None
        except HTTPException as exc:
            # 未勾选 KB（403）/ 库非 active（409）等 → 不检索（未勾选不启用，A03 验收 3）
            log.info("rag presearch skipped for agent %s: %s", agent["id"], exc.detail)
            return [], {"error": str(exc.detail)}
        except Exception as exc:
            log.warning("rag presearch failed (agent=%s): %s", agent["id"], exc)
            return [], {"error": str(exc)}

    async def _system_prompt(self, agent: dict, long_memories: list[dict], rag_items: list[dict]) -> str:
        parts: list[str] = []
        if agent.get("system_prompt"):
            parts.append(agent["system_prompt"])
        # skills 注入（ARCH §1.2：system prompt 追加）
        skills = agent.get("_skills") or []
        for sk in skills:
            if sk.get("content"):
                parts.append(f"## 技能：{sk['name']}\n{sk['content'][:2000]}")
        # 长期记忆注入（AGENT-07 验收 2：跨会话引用）
        if long_memories:
            mem_lines = "\n".join(
                f"- [{m['memory_type']}]{m['content']}" for m in long_memories
            )
            parts.append(f"## 长期记忆（之前会话沉淀，供参考）\n{mem_lines}")
        # RAG 预检索上下文（D-B 内部直调结果；供 LLM 回答与引用）
        if rag_items:
            rag_lines = "\n\n".join(
                f"[来源 {i} | {it.get('doc_file_name')} | official={it.get('is_official')}]\n{it.get('content') or ''}"
                for i, it in enumerate(rag_items, 1)
            )
            parts.append(
                "## 知识库检索结果（平台内部检索，可直接引用；标注 official 的来源必须在回复末尾以"
                "「来源」列表列出文档名+定位）\n" + rag_lines[:8000]
            )
        if not parts:
            parts.append("你是一个有用的助手。")
        return "\n\n".join(parts)

    async def _upload_attachment_files(
        self, tenant_id: str, user_id: str, agent_id: str, files: list[dict],
        trace_session_id: str | None,
    ) -> list[dict]:
        """用户附件 → StorageService（source=agent，AGENT-06）+ file 事件留痕。"""
        out = []
        from joker_shared.storage.service import get_storage_service

        svc = get_storage_service()
        for f in files or []:
            fname = (f.get("file_name") or "").strip()
            content = f.get("content")
            if not fname or content is None:
                continue
            data = content.encode("utf-8")
            try:
                res = await svc.upload(
                    self.session, tenant_id=tenant_id, user_id=user_id, file_name=fname,
                    data=data, content_type=f.get("content_type") or "text/plain",
                    source="agent", agent_id=agent_id,
                )
                out.append({"file_id": res["id"], "direction": "in", "file_name": fname})
                await _write_file_trace_event(
                    self.session, tenant_id=tenant_id, trace_session_id=trace_session_id,
                    user_id=user_id, agent_id=agent_id, file_name=fname, file_id=res["id"],
                )
            except HTTPException as exc:
                log.warning("attachment upload failed (%s): %s", fname, exc.detail)
        return out

    # ---------- 主入口 ----------

    async def run(
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
        files: list[dict] | None = None,
    ) -> dict:
        t0 = time.monotonic()
        session = self.session
        agent_id = agent["id"]
        endpoint_ids = agent.get("llm_endpoint_ids") or []
        if not endpoint_ids:
            raise HTTPException(409, "agent has no LLM endpoint configured (bind one first)")
        endpoint_id = endpoint_ids[0]

        # skills 内容（注入 system prompt）
        skills = []
        if agent.get("skill_ids"):
            r = await session.execute(
                text("SELECT id, name, content FROM skills WHERE id = ANY(CAST(:ids AS uuid[])) "
                     "AND deleted_at IS NULL AND status = 'active'"),
                {"ids": [uuid.UUID(x) for x in agent["skill_ids"]]},
            )
            skills = [dict(row._mapping) for row in r.fetchall()]
        agent = {**agent, "_skills": skills}

        # trace session（tool_call/rag/file/message 事件挂点）
        trace_session_id = await ti.ensure_trace_session(session, tenant_id, agent_id, user_id)

        # 1) 短期记忆（Redis 会话内；故障 → 单轮降级，AGENT-07 验收 3）
        stm = ShortTermMemory()
        short_ctx = await stm.get_context(tenant_id, agent_id, session_id)

        # 2) 长期记忆注入（top N，AGENT-07 验收 2）
        long_memories = await get_long_term_memories(session, tenant_id, agent_id, user_id)
        await touch_memories(session, [m["id"] for m in long_memories])

        # 3) RAG 预检索（D-B 内部直调；未勾选不检索）
        rag_items, rag_err = await self._rag_presearch(agent, user_message, tenant_id, user_id)

        # 4) 文件（AGENT-06：附件入存储模块 + file 事件）
        file_refs = await self._upload_attachment_files(
            tenant_id, user_id, agent_id, files or [], trace_session_id
        )

        # 5) 工具（InterceptorTool 工厂，唯一注册路径）
        tools, name_to_id = await self._build_tools(agent)

        # 6) 消息组装
        system_text = await self._system_prompt(agent, long_memories, rag_items)
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        messages: list = [SystemMessage(content=system_text)]
        for m in short_ctx[-_MAX_CONTEXT_CHARS // 300:]:
            messages.append(
                HumanMessage(content=m["content"]) if m["role"] == "user"
                else AIMessage(content=m["content"] or "")
            )
        messages.append(HumanMessage(content=user_message))

        # 用户消息落库 + trace
        user_msg_id = await _append_message(
            session, tenant_id, session_id, user_id, role="user", content=user_message,
            file_ids=file_refs or None,
        )
        await _write_message_trace_event(
            session, tenant_id=tenant_id, trace_session_id=trace_session_id, user_id=user_id,
            agent_id=agent_id, message_id=user_msg_id, role="user",
            payload={"content": user_message[:1000], "files": file_refs},
        )

        # 7) LLM（agent 绑定的 endpoint）
        from langchain_openai import ChatOpenAI

        llm_svc = get_llm_service()
        node = await llm_svc.get_endpoint(session, endpoint_id)
        if node is None:
            raise HTTPException(404, f"llm endpoint not found: {endpoint_id}")
        if node.get("status") != "active":
            raise HTTPException(409, f"llm endpoint disabled: {node.get('name')}")
        params = {**(node.get("default_params") or {}), **(agent.get("model_params") or {})}
        api_key = None
        if node.get("api_key_enc"):
            try:
                api_key = crypto.decrypt_secret(node["api_key_enc"])
            except ValueError:
                api_key = ""
        llm = ChatOpenAI(
            base_url=(node.get("base_url") or "").rstrip("/"),
            api_key=api_key or "not-needed",
            model=node["model"],
            temperature=params.get("temperature", 0.2),
            max_tokens=params.get("max_tokens"),
            timeout=float(node.get("timeout_seconds") or 120),
            max_retries=1,
        )
        if tools:
            llm = llm.bind_tools(tools)

        # 8) tool-calling loop（DECISION-007）
        max_rounds = int(agent.get("max_tool_rounds") or 8)
        final_content: str | None = None
        tool_call_events: list[dict] = []
        all_rag_items: list[dict] = list(rag_items)
        total_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        rounds_used = 0
        error_out: str | None = None

        ctx = {
            "session": session, "tenant_id": tenant_id, "user_id": user_id,
            "scopes": scopes, "agent_id": agent_id, "access_token": access_token,
            "trace_session_id": trace_session_id,
        }
        token = _SAR_CTX.set(ctx)
        try:
            for round_idx in range(max_rounds):
                rounds_used = round_idx + 1
                try:
                    resp = await llm.ainvoke(messages)
                except Exception as exc:
                    error_out = f"LLM call failed (round {rounds_used}): {type(exc).__name__}: {str(exc)[:300]}"
                    log.exception("llm ainvoke failed (agent=%s)", agent_id)
                    break
                usage = getattr(resp, "usage_metadata", None) or {}
                if usage:
                    total_usage["prompt_tokens"] += int(usage.get("input_tokens", 0))
                    total_usage["completion_tokens"] += int(usage.get("output_tokens", 0))
                    total_usage["total_tokens"] += int(usage.get("total_tokens", 0))

                tcs = getattr(resp, "tool_calls", None) or []
                if not tcs:
                    final_content = resp.content or ""
                    break
                # assistant 消息（含 tool_calls）落库 + trace
                tc_ser = [
                    {"id": tc.get("id"), "function": {"name": tc.get("name"),
                                                       "arguments": json.dumps(tc.get("args") or {}, ensure_ascii=False)}}
                    for tc in tcs
                ]
                mid = await _append_message(
                    session, tenant_id, session_id, user_id, role="assistant",
                    content=resp.content or "", tool_calls=tc_ser,
                    token_usage=total_usage,
                )
                await _write_message_trace_event(
                    session, tenant_id=tenant_id, trace_session_id=trace_session_id, user_id=user_id,
                    agent_id=agent_id, message_id=mid, role="assistant",
                    payload={"tool_calls": tc_ser}, token_usage=total_usage,
                )
                messages.append(resp)
                # 逐条执行（100% 经 InterceptorTool → ToolInterceptor）
                for tc in tcs:
                    name = tc.get("name") or ""
                    args = tc.get("args") or {}
                    tool_id = name_to_id.get(name)
                    if tool_id is None:
                        result_text = json.dumps({"ok": False, "error": f"unknown tool: {name}"})
                        ok_flag = False
                        tool_name = name
                    else:
                        result = await ti.execute_tool_call(
                            session, tenant_id=tenant_id, user_id=user_id, scopes=scopes,
                            agent_id=agent_id, tool_id=tool_id, args=args,
                            access_token=access_token, trace_session_id=trace_session_id,
                        )
                        ok_flag = bool(result.get("ok"))
                        tool_name = result.get("tool_name", name)
                        result_text = json.dumps(
                            result.get("result") if ok_flag else result,
                            ensure_ascii=False, default=str,
                        )[:8000]
                        # rag_search 工具结果 → 汇总进引用候选（双通道 RISK-003）
                        if ok_flag and result.get("result") and isinstance(result.get("result"), dict):
                            if isinstance(result["result"].get("body"), dict):
                                body = result["result"]["body"]
                                if isinstance(body.get("items"), list):
                                    all_rag_items.extend(body["items"])
                    tool_call_events.append({"name": tool_name, "ok": ok_flag, "args": {k: v for k, v in args.items() if k != "access_token"}})
                    mid = await _append_message(
                        session, tenant_id, session_id, user_id, role="tool",
                        content=result_text, tool_call_id=tc.get("id"),
                    )
                    await _write_message_trace_event(
                        session, tenant_id=tenant_id, trace_session_id=trace_session_id, user_id=user_id,
                        agent_id=agent_id, message_id=mid, role="tool",
                        payload={"tool_name": tool_name, "ok": ok_flag},
                    )
                    messages.append(ToolMessage(content=result_text, tool_call_id=tc.get("id") or _new_id()))
            else:
                # 轮次耗尽：返回部分结果 + 提示（ARCH §4.3 模式②同款语义）
                final_content = ("（已达到最大工具调用轮次 %d，以下为当前部分结果）\n%s" % (
                    max_rounds, (resp.content or "") if 'resp' in dir() else ""))
                error_out = f"max_tool_rounds exceeded ({max_rounds})"
        finally:
            _SAR_CTX.reset(token)

        if final_content is None:
            # 失败语义：assistant failed 消息 + 抛出（API → 502/500 由调用方决定）
            await _append_message(
                session, tenant_id, session_id, user_id, role="assistant",
                status="failed", error_message=error_out,
            )
            raise HTTPException(502, error_out or "agent run failed (no LLM response)")

        # 9) 引用判定（AGENT-05 / DECISION-017 / D-A）
        has_official = any(it.get("is_official") for it in all_rag_items)
        want_citations = bool(
            has_official
            or llm_intent_fallback_requires_citation(user_message, show_citations)
        )
        citations = build_citations(all_rag_items, force=has_official, show=want_citations)
        if citations:
            final_content = final_content + render_citations_markdown(citations)

        # 10) assistant 最终消息落库 + trace
        final_msg_id = await _append_message(
            session, tenant_id, session_id, user_id, role="assistant", content=final_content,
            citations=citations or None, token_usage=total_usage or None,
        )
        await _write_message_trace_event(
            session, tenant_id=tenant_id, trace_session_id=trace_session_id, user_id=user_id,
            agent_id=agent_id, message_id=final_msg_id, role="assistant",
            payload={"content": final_content[:1000], "citations": len(citations)},
            token_usage=total_usage,
        )

        # 11) 短期记忆写回（会话内多轮连贯，AGENT-07 验收 1）
        await stm.append(tenant_id, agent_id, session_id, "user", user_message)
        await stm.append(tenant_id, agent_id, session_id, "assistant", final_content[:2000])

        return {
            "reply": final_content,
            "citations": citations,
            "citations_forced_official": has_official,
            "tool_calls": tool_call_events,
            "tool_rounds_used": rounds_used,
            "rag_hits": len(all_rag_items),
            "files": file_refs,
            "tokens": total_usage,
            "error": error_out,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }
