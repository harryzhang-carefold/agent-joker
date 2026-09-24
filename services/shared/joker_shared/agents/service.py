"""AgentService（S07，AGENT-01/02/03/04 + 运行时调度入口）。

职责：
- agent 元数据 CRUD（AGENT-01/02）：名称租户内唯一（=OpenAI model 标识，DECISION-016）、
  类型 simple|third_party、system_prompt、model_params、max_tool_rounds（默认 8）、
  show_citations_default、third_party_url（type=third_party 必填）。
- 四要素勾选（AGENT-03，A03「都从已存在列表勾选」）：LLM endpoint（恰好 1 条有效行）、
  RAG 库（可多）、MCP 工具（可多）、skills（可多）。候选校验=目标实体存在且 active/enabled；
  保存持久化（勾选表软删语义），再次打开回显；未勾选不启用。
- 会话/消息（AGENT-04）：会话列表（tenant+agent+user）、对话详情（完整消息流含 tool_calls/
  citations）、会话新建/删除/重命名/关闭。
- chat() 调度：simple → SimpleAgentRuntime.run()；third_party → ThirdPartyAgent.chat()。

scope 门禁：
- 管理（增删改/配置）→ `agents:manage`
- 对话/读会话 → `agent:use:<agent_id>`（或 `agent:use:*` 通配，DECISION-004）
- agent 创建时自动 upsert 租户级 scope `agent:use:<id>`（DB_DESIGN §1.2；删除级联清理）
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import crypto
from joker_shared import trace as _trace
from joker_shared.agents import citations as cit
from joker_shared.agents.memory import (
    ShortTermMemory,
    get_long_term_memories,
    list_obsidian_notes,
    store_memory,
    touch_memories,
    write_obsidian_note,
)
from joker_shared.agents.runtime import SimpleAgentRuntime
from joker_shared.agents.third_party import ThirdPartyAgent

log = logging.getLogger("joker.agents")

AGENT_TYPES = ("simple", "third_party")
MEM_TOP_N = 10


def _new_id() -> str:
    return str(uuid.uuid4())


def _is_uuid(v: str) -> bool:
    """UUID 格式校验（防 CAST(:id AS uuid) 对非法值抛 DB 异常 → 500）。"""
    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _ser_agent(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    for k in ("id", "tenant_id", "created_by", "updated_by"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    enc = d.pop("third_party_auth_enc", None)
    d["third_party_auth_set"] = bool(enc)
    if isinstance(d.get("model_params"), str):
        try:
            d["model_params"] = json.loads(d["model_params"])
        except ValueError:
            d["model_params"] = None
    for k in ("created_at", "updated_at", "deleted_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


class AgentService:
    """agent 元数据 + 四要素勾选 + 会话/消息 + chat 调度。"""

    # ============================================================ 元数据（AGENT-01/02）

    async def _fetch_agent(self, session: AsyncSession, agent_id: str, tenant_id: str) -> Any:
        r = await session.execute(
            text("SELECT * FROM agents WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid) "
                 "AND deleted_at IS NULL"),
            {"id": agent_id, "t": tenant_id},
        )
        return r.first()

    async def list_agents(
        self, session: AsyncSession, tenant_id: str, status: str | None = None, type_: str | None = None
    ) -> dict:
        where = "WHERE tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"
        params: dict[str, Any] = {"t": tenant_id}
        if status in ("active", "disabled"):
            where += " AND status = :st"; params["st"] = status
        if type_ in AGENT_TYPES:
            where += " AND type = :ty"; params["ty"] = type_
        r = await session.execute(text(f"SELECT * FROM agents {where} ORDER BY created_at"), params)
        items = [_ser_agent(row) for row in r.fetchall()]
        return {"items": items, "total": len(items)}

    async def get_agent(self, session: AsyncSession, agent_id: str, tenant_id: str) -> dict | None:
        row = await self._fetch_agent(session, agent_id, tenant_id)
        return _ser_agent(row) if row else None

    async def create_agent(self, session: AsyncSession, tenant_id: str, user_id: str | None, d: dict) -> dict:
        name = (d.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "name is required")
        type_ = (d.get("type") or "simple").strip()
        if type_ not in AGENT_TYPES:
            raise HTTPException(422, f"type must be one of {AGENT_TYPES}")
        # 名称租户内唯一（DECISION-016：=OpenAI model 标识）
        dup = await session.execute(
            text("SELECT 1 FROM agents WHERE tenant_id = CAST(:t AS uuid) AND name = :n AND deleted_at IS NULL"),
            {"t": tenant_id, "n": name},
        )
        if dup.first():
            raise HTTPException(409, f"agent name already exists: {name}")
        if type_ == "third_party":
            url = (d.get("third_party_url") or "").strip()
            if not url or not url.startswith(("http://", "https://")):
                raise HTTPException(422, "third_party_url (http/https) is required for type=third_party")

        aid = _new_id()
        auth_enc = None
        if d.get("third_party_auth"):
            auth_enc = crypto.encrypt_secret(str(d["third_party_auth"]))
        await session.execute(
            text(
                """INSERT INTO agents (id, tenant_id, name, description, type, system_prompt, model_params,
                     max_tool_rounds, show_citations_default, third_party_url, third_party_transport,
                     third_party_auth_enc, third_party_session_param, status, created_by, updated_by)
                   VALUES (CAST(:id AS uuid), CAST(:t AS uuid), :n, :desc, :ty, :sp, CAST(:mp AS jsonb),
                           :mtr, :scd, :tpu, :tpt, :tpa, :tps, :st, CAST(:cb AS uuid), CAST(:cb AS uuid))"""
            ),
            {
                "id": aid, "t": tenant_id, "n": name, "desc": d.get("description"), "ty": type_,
                "sp": d.get("system_prompt"), "mp": json.dumps(d.get("model_params") or {}),
                "mtr": int(d.get("max_tool_rounds") or 8),
                "scd": bool(d.get("show_citations_default", False)),
                "tpu": (d.get("third_party_url") or "").strip() or None,
                "tpt": d.get("third_party_transport") or "openai_compat",
                "tpa": auth_enc, "tps": d.get("third_party_session_param"),
                "st": d.get("status") or "active", "cb": user_id,
            },
        )
        # agent:use:<id> 动态 scope + 自动授权（DB_DESIGN §1.2）：
        # 建租户级 scope + 专属角色 agent-user:<id>（挂该 scope）+ 授予租户全体 active 用户。
        # 删除时级联清理（delete_agent）。
        await self._grant_agent_use(session, tenant_id, user_id, aid)

        # 四要素勾选（A03；创建时可一并传入）——与 agent 行同一事务提交
        await self._apply_config(session, tenant_id, user_id, aid, d)
        await session.commit()
        return await self.get_full_agent(session, tenant_id, aid)

    async def update_agent(
        self, session: AsyncSession, agent_id: str, tenant_id: str, user_id: str | None, d: dict
    ) -> dict:
        row = await self._fetch_agent(session, agent_id, tenant_id)
        if row is None:
            raise HTTPException(404, f"agent not found: {agent_id}")
        sets: list[str] = []
        params: dict[str, Any] = {"id": agent_id, "t": tenant_id, "ub": user_id}
        name = (d.get("name") or "").strip()
        if name:
            dup = await session.execute(
                text("SELECT 1 FROM agents WHERE tenant_id = CAST(:t AS uuid) AND name = :n "
                     "AND id <> CAST(:id AS uuid) AND deleted_at IS NULL"),
                {"t": tenant_id, "n": name, "id": agent_id},
            )
            if dup.first():
                raise HTTPException(409, f"agent name already exists: {name}")
            sets.append("name = :name"); params["name"] = name
        for col in ("description", "type", "system_prompt", "max_tool_rounds",
                    "show_citations_default", "third_party_url", "third_party_transport",
                    "third_party_session_param", "status"):
            if col in d and d[col] is not None:
                if col == "type" and d[col] not in AGENT_TYPES:
                    raise HTTPException(422, f"type must be one of {AGENT_TYPES}")
                if col == "status" and d[col] not in ("active", "disabled"):
                    raise HTTPException(422, "status must be active/disabled")
                sets.append(f"{col} = :{col}"); params[col] = d[col]
        if "model_params" in d:
            sets.append("model_params = :mp"); params["mp"] = json.dumps(d["model_params"] or {})
        if d.get("third_party_auth"):
            sets.append("third_party_auth_enc = :tpa"); params["tpa"] = crypto.encrypt_secret(str(d["third_party_auth"]))
        if d.get("clear_third_party_auth"):
            sets.append("third_party_auth_enc = NULL")
        if not sets and not (
            "llm_endpoint_ids" in d or "llm_endpoint_id" in d
            or "knowledge_base_ids" in d or "mcp_tool_ids" in d or "skill_ids" in d
        ):
            raise HTTPException(400, "no fields to update")
        if sets:
            sets.append("updated_by = :ub")
            await session.execute(text(f"UPDATE agents SET {', '.join(sets)} WHERE id = CAST(:id AS uuid)"), params)
        # 四要素勾选变更（若提供）
        await self._apply_config(session, tenant_id, user_id, agent_id, d)
        await session.commit()
        return await self.get_full_agent(session, tenant_id, agent_id)

    async def delete_agent(self, session: AsyncSession, agent_id: str, tenant_id: str, user_id: str | None) -> dict:
        """删除（软删，AGENT-01 验收 2 策略）：会话/消息保留（历史可查）；配置引用表级联清理；
        Redis 短期记忆按 key 前缀清除；obsidian 笔记保留（知识资产）。"""
        row = await self._fetch_agent(session, agent_id, tenant_id)
        if row is None:
            raise HTTPException(404, f"agent not found: {agent_id}")
        await session.execute(
            text("UPDATE agents SET deleted_at = now(), updated_by = CAST(:u AS uuid) WHERE id = CAST(:id AS uuid)"),
            {"id": agent_id, "u": user_id},
        )
        # 级联清理配置引用（勾选表；软删语义保留历史由 FK cascade 处理——此处显式软删以留痕）
        for tbl in ("agent_llm_endpoints", "agent_knowledge_bases", "agent_mcp_tools", "agent_skills"):
            await session.execute(
                text(f"UPDATE {tbl} SET deleted_at = now() WHERE agent_id = CAST(:id AS uuid) AND deleted_at IS NULL"),
                {"id": agent_id},
            )
        # agent:use:<id> scope + 动态角色清理（DB_DESIGN §1.2）
        await session.execute(
            text("DELETE FROM scopes WHERE tenant_id = CAST(:t AS uuid) AND code = :c"),
            {"t": tenant_id, "c": f"agent:use:{agent_id}"},
        )
        await session.execute(
            text("DELETE FROM roles WHERE tenant_id = CAST(:t AS uuid) AND name = :n"),
            {"t": tenant_id, "n": f"agent-user:{agent_id}"},
        )
        await session.commit()
        # Redis 短期记忆清除（按 agent 前缀，best-effort）
        try:
            from joker_shared import redis_client

            r = redis_client.get_redis()
            keys = [k async for k in r.scan_iter(f"joker:mem:short:{tenant_id}:{agent_id}:*")]
            if keys:
                await r.delete(*keys)
        except Exception as exc:
            log.warning("clear short-term memory on delete failed: %s", exc)
        log.info("agent deleted: %s (%s)", agent_id, row._mapping["name"])
        return {"ok": True, "deleted": agent_id}

    # ============================================================ agent:use:<id> 授权（DB_DESIGN §1.2）

    async def _grant_agent_use(self, session: AsyncSession, tenant_id: str, user_id: str | None, agent_id: str) -> None:
        """建租户级 scope `agent:use:<id>` + 专属角色 `agent-user:<id>`（挂该 scope）+ 授予全体 active 用户。"""
        code = f"agent:use:{agent_id}"
        await session.execute(
            text(
                """INSERT INTO scopes (id, tenant_id, code, description, category, created_by)
                   VALUES (gen_random_uuid(), CAST(:t AS uuid), :c, 'agent 使用权限（动态）', 'function', CAST(:u AS uuid))
                   ON CONFLICT (tenant_id, code) DO NOTHING"""
            ),
            {"t": tenant_id, "c": code, "u": user_id},
        )
        role_name = f"agent-user:{agent_id}"
        rrow = await session.execute(
            text("SELECT id FROM roles WHERE tenant_id = CAST(:t AS uuid) AND name = :n AND deleted_at IS NULL"),
            {"t": tenant_id, "n": role_name},
        )
        role_id = rrow.first()
        if role_id is None:
            role_id = _new_id()
            await session.execute(
                text(
                    """INSERT INTO roles (id, tenant_id, name, description, is_builtin, created_by)
                       VALUES (CAST(:id AS uuid), CAST(:t AS uuid), :n, 'agent 自动授权角色（动态）', false, CAST(:u AS uuid))"""
                ),
                {"id": role_id, "t": tenant_id, "n": role_name, "u": user_id},
            )
        scope_id = (await session.execute(
            text("SELECT id FROM scopes WHERE tenant_id = CAST(:t AS uuid) AND code = :c"),
            {"t": tenant_id, "c": code})).scalar_one()
        await session.execute(
            text("INSERT INTO role_scopes (role_id, scope_id) VALUES (CAST(:r AS uuid), CAST(:s AS uuid)) ON CONFLICT DO NOTHING"),
            {"r": role_id, "s": scope_id},
        )
        # 授予全体 active 用户（含创建者）
        await session.execute(
            text(
                """INSERT INTO user_roles (user_id, role_id)
                   SELECT u.id, CAST(:r AS uuid) FROM users u
                   WHERE u.tenant_id = CAST(:t AS uuid) AND u.status = 'active' AND u.deleted_at IS NULL
                   ON CONFLICT DO NOTHING"""
            ),
            {"r": role_id, "t": tenant_id},
        )

    # ============================================================ 四要素勾选（AGENT-03）

    async def _apply_config(self, session: AsyncSession, tenant_id: str, user_id: str | None, agent_id: str, d: dict) -> None:
        """按请求体 upsert 四要素勾选（提供键才处理；未提供=不变）。

        - llm_endpoint_ids: list（恰好 1 条有效；>1 取首个并告警，<1 解勾）
        - knowledge_base_ids: list（可多）
        - mcp_tool_ids: list（可多）
        - skill_ids: list（可多）
        候选校验：目标实体存在且 active/enabled（A03 验收 1「候选来自已存在列表」）。
        """
        # LLM endpoint（恰好 1 条有效行，部分唯一索引 uk_agent_llm_single）
        if "llm_endpoint_ids" in d or "llm_endpoint_id" in d:
            ids = d.get("llm_endpoint_ids") or ([d["llm_endpoint_id"]] if d.get("llm_endpoint_id") else [])
            ids = [str(x) for x in ids]
            if len(ids) > 1:
                log.warning("agent %s: %d llm endpoints provided, using first (single-select semantics)", agent_id, len(ids))
            await self._sync_checklist(
                session, "agent_llm_endpoints", "llm_endpoint_id", "llm_endpoints", "id",
                agent_id, ids, tenant_id, user_id, status_col="status",
            )
        if "knowledge_base_ids" in d:
            await self._sync_checklist(
                session, "agent_knowledge_bases", "knowledge_base_id", "rag_knowledge_bases", "id",
                agent_id, [str(x) for x in (d.get("knowledge_base_ids") or [])], tenant_id, user_id, status_col="status",
            )
        if "mcp_tool_ids" in d:
            await self._sync_checklist(
                session, "agent_mcp_tools", "mcp_tool_id", "mcp_tools", "id",
                agent_id, [str(x) for x in (d.get("mcp_tool_ids") or [])], tenant_id, user_id, status_col="enabled",
            )
        if "skill_ids" in d:
            await self._sync_checklist(
                session, "agent_skills", "skill_id", "skills", "id",
                agent_id, [str(x) for x in (d.get("skill_ids") or [])], tenant_id, user_id, status_col="status",
            )

    async def _sync_checklist(
        self, session, table, col, ref_table, ref_id, agent_id, wanted_ids, tenant_id, user_id, status_col
    ) -> None:
        """勾选表 upsert（软删语义）：wanted 内存在→解软删/插入；不在→软删。"""
        # 校验候选存在且启用（A03 验收 1：候选来自已存在列表）
        for wid in wanted_ids:
            if not wid or not isinstance(wid, str) or not _is_uuid(wid):
                raise HTTPException(422, f"invalid {ref_table} id (not a UUID): {wid!r}")
            if col == "llm_endpoint_id":
                r = await session.execute(
                    text(f"SELECT status FROM {ref_table} WHERE id = CAST(:id AS uuid)"), {"id": wid})
            elif col == "mcp_tool_id":
                r = await session.execute(
                    text(
                        "SELECT t.enabled FROM mcp_tools t JOIN mcp_servers s ON s.id = t.server_id "
                        "WHERE t.id = CAST(:id AS uuid) AND t.deleted_at IS NULL "
                        "AND (s.tenant_id = CAST(:t AS uuid) OR s.is_platform = true) AND s.deleted_at IS NULL"
                    ), {"id": wid, "t": tenant_id})
            else:
                r = await session.execute(
                    text(f"SELECT status FROM {ref_table} WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"),
                    {"id": wid, "t": tenant_id})
            row = r.first()
            if row is None:
                raise HTTPException(422, f"{ref_table} not found or not in tenant: {wid}")
            val = row[0]
            if col == "mcp_tool_id":
                if not val:
                    raise HTTPException(422, f"mcp tool disabled: {wid}")
            elif val != "active":
                raise HTTPException(422, f"{ref_table} not active: {wid}")

        # upsert wanted
        for wid in dict.fromkeys(wanted_ids):
            await session.execute(
                text(
                    f"""INSERT INTO {table} (agent_id, {col}, created_by)
                        VALUES (CAST(:a AS uuid), CAST(:id AS uuid), CAST(:u AS uuid))
                        ON CONFLICT (agent_id, {col}) DO UPDATE SET deleted_at = NULL, created_by = COALESCE({table}.created_by, EXCLUDED.created_by)"""
                ),
                {"a": agent_id, "id": wid, "u": user_id},
            )
        # soft-delete unwanted
        if wanted_ids:
            await session.execute(
                text(
                    f"UPDATE {table} SET deleted_at = now() WHERE agent_id = CAST(:a AS uuid) "
                    f"AND deleted_at IS NULL AND {col} <> ALL(CAST(:ids AS uuid[]))"
                ),
                {"a": agent_id, "ids": [uuid.UUID(x) for x in wanted_ids]},
            )
        else:
            # 空列表=清空该要素（解勾全部）
            await session.execute(
                text(f"UPDATE {table} SET deleted_at = now() WHERE agent_id = CAST(:a AS uuid) AND deleted_at IS NULL"),
                {"a": agent_id},
            )

    # ============================================================ 配置回显（A03 验收 2）

    async def get_full_agent(self, session: AsyncSession, tenant_id: str, agent_id: str) -> dict:
        """agent + 四要素回显（A03 验收 2「再次打开回显正确」）。"""
        agent = await self.get_agent(session, agent_id, tenant_id)
        if agent is None:
            raise HTTPException(404, f"agent not found: {agent_id}")
        llm = await session.execute(
            text("SELECT llm_endpoint_id FROM agent_llm_endpoints WHERE agent_id = CAST(:a AS uuid) AND deleted_at IS NULL"),
            {"a": agent_id})
        agent["llm_endpoint_ids"] = [str(r[0]) for r in llm.fetchall()]
        kb = await session.execute(
            text("SELECT knowledge_base_id FROM agent_knowledge_bases WHERE agent_id = CAST(:a AS uuid) AND deleted_at IS NULL"),
            {"a": agent_id})
        agent["knowledge_base_ids"] = [str(r[0]) for r in kb.fetchall()]
        tools = await session.execute(
            text("SELECT mcp_tool_id FROM agent_mcp_tools WHERE agent_id = CAST(:a AS uuid) AND deleted_at IS NULL"),
            {"a": agent_id})
        agent["mcp_tool_ids"] = [str(r[0]) for r in tools.fetchall()]
        skills = await session.execute(
            text("SELECT skill_id FROM agent_skills WHERE agent_id = CAST(:a AS uuid) AND deleted_at IS NULL"),
            {"a": agent_id})
        agent["skill_ids"] = [str(r[0]) for r in skills.fetchall()]
        # 会话数（冗余字段刷新）
        sc = await session.execute(
            text("SELECT count(*) FROM agent_sessions WHERE agent_id = CAST(:a AS uuid) AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"),
            {"a": agent_id, "t": tenant_id})
        agent["session_count"] = sc.scalar_one()
        return agent

    # ============================================================ 会话/消息（AGENT-04）

    async def list_sessions(
        self, session: AsyncSession, tenant_id: str, user_id: str | None,
        agent_id: str | None = None, status: str | None = None,
        page: int = 1, page_size: int = 50,
    ) -> dict:
        where = ["s.tenant_id = CAST(:t AS uuid)", "s.deleted_at IS NULL"]
        params: dict[str, Any] = {"t": tenant_id, "ps": page_size, "off": (page - 1) * page_size}
        if user_id:
            where.append("s.user_id = CAST(:u AS uuid)"); params["u"] = user_id
        if agent_id:
            where.append("s.agent_id = CAST(:a AS uuid)"); params["a"] = agent_id
        if status in ("active", "closed"):
            where.append("s.status = :st"); params["st"] = status
        wsql = " AND ".join(where)
        total = (await session.execute(
            text(f"SELECT count(*) FROM agent_sessions s WHERE {wsql}"), params)).scalar_one()
        r = await session.execute(
            text(
                f"""SELECT s.id, s.agent_id, a.name AS agent_name, s.user_id, s.title, s.status,
                           s.message_count, s.total_tokens, s.last_message_at, s.external_session_id,
                           s.created_at, s.updated_at
                    FROM agent_sessions s JOIN agents a ON a.id = s.agent_id
                    WHERE {wsql} ORDER BY s.updated_at DESC LIMIT :ps OFFSET :off"""
            ),
            params,
        )
        items = []
        for row in r.fetchall():
            d = dict(row._mapping)
            for k in ("id", "agent_id", "user_id"):
                d[k] = str(d[k])
            for k in ("last_message_at", "created_at", "updated_at"):
                if d.get(k) is not None:
                    d[k] = d[k].isoformat()
            items.append(d)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_session(self, session: AsyncSession, tenant_id: str, user_id: str | None, session_id: str) -> dict | None:
        r = await session.execute(
            text("SELECT id, agent_id, user_id, title, status, message_count, total_tokens, "
                 "last_message_at, external_session_id, created_at, updated_at "
                 "FROM agent_sessions WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"),
            {"id": session_id, "t": tenant_id})
        row = r.first()
        if row is None:
            return None
        d = dict(row._mapping)
        for k in ("id", "agent_id", "user_id"):
            d[k] = str(d[k])
        for k in ("last_message_at", "created_at", "updated_at"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat()
        return d

    async def list_messages(self, session: AsyncSession, tenant_id: str, session_id: str) -> dict:
        """对话详情（A04 验收 3）：完整消息流（user/assistant/tool/system，含 tool_calls/citations/file_ids）。"""
        r = await session.execute(
            text(
                """SELECT id, role, content, tool_calls, tool_call_id, citations, file_ids,
                           token_usage, status, error_message, created_at
                   FROM agent_messages WHERE tenant_id = CAST(:t AS uuid) AND session_id = CAST(:s AS uuid)
                   ORDER BY created_at ASC, id"""
            ),
            {"t": tenant_id, "s": session_id},
        )
        items = []
        for row in r.fetchall():
            d = dict(row._mapping)
            d["id"] = str(d["id"])
            for k in ("tool_calls", "citations", "file_ids", "token_usage"):
                if isinstance(d.get(k), str):
                    try:
                        d[k] = json.loads(d[k])
                    except ValueError:
                        d[k] = None
            if d.get("created_at") is not None:
                d["created_at"] = d["created_at"].isoformat()
            items.append(d)
        return {"items": items, "total": len(items)}

    async def create_session(
        self, session: AsyncSession, tenant_id: str, user_id: str, agent_id: str, title: str | None = None
    ) -> dict:
        agent = await self._fetch_agent(session, agent_id, tenant_id)
        if agent is None:
            raise HTTPException(404, f"agent not found: {agent_id}")
        if agent._mapping["status"] != "active":
            raise HTTPException(409, f"agent disabled (cannot chat): {agent_id}")
        sid = _new_id()
        await session.execute(
            text(
                "INSERT INTO agent_sessions (id, tenant_id, agent_id, user_id, title, status, created_by) "
                "VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:a AS uuid), CAST(:u AS uuid), :ti, 'active', CAST(:u AS uuid))"
            ),
            {"id": sid, "t": tenant_id, "a": agent_id, "u": user_id, "ti": title},
        )
        await session.commit()
        return await self.get_session(session, tenant_id, user_id, sid)

    async def rename_session(self, session: AsyncSession, tenant_id: str, user_id: str, session_id: str, title: str) -> dict:
        r = await session.execute(
            text("UPDATE agent_sessions SET title = :ti, updated_by = CAST(:u AS uuid) "
                 "WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"),
            {"id": session_id, "t": tenant_id, "u": user_id, "ti": title})
        if r.rowcount == 0:
            raise HTTPException(404, f"session not found: {session_id}")
        await session.commit()
        return await self.get_session(session, tenant_id, user_id, session_id)

    async def close_session(
        self, session: AsyncSession, tenant_id: str, user_id: str, session_id: str
    ) -> dict:
        """关闭会话（status→closed）：触发 obsidian 沉淀（ARCH §9-17【推测：触发点】）。"""
        sess = await self.get_session(session, tenant_id, user_id, session_id)
        if sess is None:
            raise HTTPException(404, f"session not found: {session_id}")
        if sess["status"] == "closed":
            return sess
        await session.execute(
            text("UPDATE agent_sessions SET status = 'closed', updated_by = CAST(:u AS uuid) "
                 "WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"),
            {"id": session_id, "t": tenant_id, "u": user_id})
        await session.execute(
            text("UPDATE trace_sessions SET status = 'ended', ended_at = now() WHERE session_id = CAST(:s AS uuid)"),
            {"s": session_id})
        await session.commit()
        # system end 事件（会话生命周期终点；S09 Trace）
        try:
            tr = await session.execute(
                text("SELECT id, tenant_id FROM trace_sessions WHERE session_id = CAST(:s AS uuid)"),
                {"s": session_id})
            row = tr.first()
            if row is not None:
                await _trace.write_system_event(
                    session,
                    tenant_id=str(row[1]),
                    trace_session_id=str(row[0]),
                    user_id=user_id,
                    kind="end",
                    detail="session closed",
                )
        except Exception:
            log.exception("system end trace event failed (session=%s)", session_id)
        # 沉淀（best-effort，不阻断）
        try:
            await self._settle_session(session, tenant_id, user_id, session_id)
        except Exception:
            log.exception("settle session failed (session=%s); session still closed", session_id)
        return await self.get_session(session, tenant_id, user_id, session_id)

    async def delete_session(self, session: AsyncSession, tenant_id: str, user_id: str, session_id: str) -> dict:
        """会话删除（软删，A04 验收 4）：消息保留（trace 可查）。"""
        r = await session.execute(
            text("UPDATE agent_sessions SET deleted_at = now(), updated_by = CAST(:u AS uuid) "
                 "WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"),
            {"id": session_id, "t": tenant_id, "u": user_id})
        if r.rowcount == 0:
            raise HTTPException(404, f"session not found: {session_id}")
        await session.commit()
        return {"ok": True, "deleted": session_id}

    # ============================================================ chat 调度（AGENT-04 验收 1）

    async def chat(
        self, session: AsyncSession, tenant_id: str, user_id: str, scopes: list[str],
        agent_id: str, message: str,
        session_id: str | None = None, show_citations: bool | None = None,
        access_token: str = "", files: list[dict] | None = None,
    ) -> dict:
        """对话主入口（simple → SAR；third_party → URL 代理）。

        返回 {session_id, reply, citations, tool_calls, tokens, ...}。
        """
        agent = await self.get_full_agent(session, tenant_id, agent_id)
        if agent is None:
            raise HTTPException(404, f"agent not found: {agent_id}")
        if agent["status"] != "active":
            raise HTTPException(409, f"agent disabled (cannot chat): {agent_id}")
        # 会话：复用或新建
        if session_id:
            sess = await self.get_session(session, tenant_id, user_id, session_id)
            if sess is None:
                raise HTTPException(404, f"session not found: {session_id}")
            if sess["agent_id"] != agent_id:
                raise HTTPException(409, f"session belongs to a different agent")
            if sess["status"] == "closed":
                raise HTTPException(409, "session closed; create a new one")
        else:
            title = message[:40]
            sess = await self.create_session(session, tenant_id, user_id, agent_id, title)

        if agent["type"] == "simple":
            runtime = SimpleAgentRuntime(session)
            result = await runtime.run(
                tenant_id=tenant_id, user_id=user_id, scopes=scopes,
                agent=agent, session_id=sess["id"], user_message=message,
                show_citations=show_citations, access_token=access_token,
                files=files,
            )
        else:
            tp = ThirdPartyAgent(session)
            result = await tp.chat(
                tenant_id=tenant_id, user_id=user_id, scopes=scopes,
                agent=agent, session_id=sess["id"], user_message=message,
                show_citations=show_citations, access_token=access_token,
            )
        return {
            "session_id": sess["id"],
            "agent_id": agent_id,
            "agent_type": agent["type"],
            **result,
        }

    # ============================================================ 沉淀（AGENT-07/08，DECISION-019）

    async def _settle_session(
        self, session: AsyncSession, tenant_id: str, user_id: str, session_id: str
    ) -> dict:
        """会话关闭沉淀：LLM 从对话提炼长期记忆（结构化）+ obsidian 笔记（长篇 markdown）。

        同一沉淀事件一次生成两者（DECISION-019 双写不同源）。LLM 不可用 → 降级
        （仍写一条 summary 长期记忆 + 笔记，保证闭环可验证）。
        """
        agent = await session.execute(
            text("SELECT id, name, type FROM agents WHERE id = (SELECT agent_id FROM agent_sessions WHERE id = CAST(:s AS uuid))"),
            {"s": session_id})
        arow = agent.first()
        if arow is None:
            return {"settled": False, "reason": "agent not found"}
        agent_id, agent_name, agent_type = str(arow[0]), arow[1], arow[2]
        # 第三方 agent 记忆由提供方实现（AGENT-09：平台不存其记忆）→ 跳过沉淀
        if agent_type == "third_party":
            return {"settled": False, "reason": "third_party agent memory owned by provider (AGENT-09)"}
        trow = await session.execute(
            text("SELECT code FROM tenants WHERE id = CAST(:t AS uuid)"), {"t": tenant_id})
        tenant_code = (trow.first() or ("acme",))[0]
        msgs = await self.list_messages(session, tenant_id, session_id)
        dialog = msgs["items"]
        if not dialog:
            return {"settled": False, "reason": "no messages"}
        # 组装对话文本（user/assistant，截断）
        transcript = "\n".join(
            f"{m['role']}: {(m['content'] or '')[:500]}" for m in dialog if m["role"] in ("user", "assistant")
        )[:6000]

        # LLM 提炼（agent 绑定的 endpoint；失败 → 降级）
        memories: list[dict] = []
        summary = ""
        er = await session.execute(
            text("SELECT llm_endpoint_id FROM agent_llm_endpoints "
                 "WHERE agent_id = CAST(:a AS uuid) AND deleted_at IS NULL LIMIT 1"),
            {"a": agent_id},
        )
        erow = er.first()
        endpoint_id = str(erow[0]) if erow else None
        if endpoint_id:
            try:
                from joker_shared.llm import get_llm_service

                llm = get_llm_service()
                prompt = (
                    "你是记忆提炼助手。从下面对话中提炼值得长期记住的信息。\n"
                    "只输出 JSON：{\"memories\": [{\"type\": \"fact|preference|summary|entity\", "
                    "\"content\": \"一句话事实/偏好\", \"importance\": 1-9}], \"summary\": \"会话一句话摘要\"}\n"
                    "没有值得记住的就返回空数组。\n\n对话：\n" + transcript
                )
                out = await llm.chat(session, endpoint_id, [{"role": "user", "content": prompt}])
                parsed = _extract_json(out)
                memories = parsed.get("memories") or []
                summary = (parsed.get("summary") or "").strip()
            except Exception as exc:
                log.warning("LLM memory extraction failed (%s); degrade to summary-only", exc)
        if not summary:
            summary = f"会话 {session_id[:8]} 共 {len(dialog)} 条消息"
        # 写长期记忆（用户级）
        stored = []
        for m in memories[:5]:
            mid = await store_memory(
                session, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id,
                memory_type=(m.get("type") or "fact"), content=(m.get("content") or "").strip(),
                source_session_id=session_id, importance=float(m.get("importance") or 5.0),
            )
            if mid:
                stored.append(mid)
        # 会话摘要长期记忆（保证跨会话可引用，AGENT-07 验收 2）
        smid = await store_memory(
            session, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id,
            memory_type="summary", content=f"会话摘要：{summary}",
            source_session_id=session_id, importance=5.0,
        )
        if smid:
            stored.append(smid)
        # obsidian 笔记（DECISION-019 双写）
        import time as _time

        now_iso = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
        note = await write_obsidian_note(
            session, tenant_id=tenant_id, tenant_code=tenant_code, agent_id=agent_id,
            agent_name=agent_name, user_id=user_id, title=summary[:60] or "会话沉淀",
            summary=summary,
            body=f"## 对话记录\n\n{transcript[:3000]}",
            tags=["session-summary", f"agent:{agent_name}"],
            source_session_id=session_id, now_iso=now_iso,
        )
        return {"settled": True, "memories": len(stored), "note": note.get("file_path")}

    # ============================================================ 记忆/笔记查询（AGENT-07/08 联动）

    async def list_memories(
        self, session: AsyncSession, tenant_id: str, user_id: str, agent_id: str, limit: int = 50
    ) -> dict:
        r = await session.execute(
            text(
                """SELECT id, memory_type, content, importance, access_count, source_session_id,
                           last_accessed_at, created_at
                   FROM agent_memories WHERE tenant_id = CAST(:t AS uuid) AND agent_id = CAST(:a AS uuid)
                     AND status = 'active' AND (user_id = CAST(:u AS uuid) OR user_id IS NULL)
                   ORDER BY created_at DESC LIMIT :n"""
            ),
            {"t": tenant_id, "a": agent_id, "u": user_id, "n": limit},
        )
        items = []
        for row in r.fetchall():
            d = dict(row._mapping)
            for k in ("id", "source_session_id"):
                if d.get(k) is not None:
                    d[k] = str(d[k])
            if d.get("created_at") is not None:
                d["created_at"] = d["created_at"].isoformat()
            if d.get("last_accessed_at") is not None:
                d["last_accessed_at"] = d["last_accessed_at"].isoformat()
            d["importance"] = float(d["importance"])
            items.append(d)
        return {"items": items, "total": len(items)}

    async def list_notes(self, session: AsyncSession, tenant_id: str, agent_id: str, limit: int = 20) -> dict:
        items = await list_obsidian_notes(session, agent_id, tenant_id, limit)
        return {"items": items, "total": len(items)}


def _extract_json(text: str) -> dict:
    """从 LLM 输出提取 JSON（容错：截取首个 {...} 块）。"""
    import re

    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


_service: AgentService | None = None


def get_agent_service() -> AgentService:
    global _service
    if _service is None:
        _service = AgentService()
    return _service
