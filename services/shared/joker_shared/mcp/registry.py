"""MCPRegistryService（S06，MCP-01/02/03，DECISION-010/011）。

职责（本卡范围：注册/管理/同步；工具**调用**执行链路由 S08 ToolInterceptor 统一接入）：
- URL 注册 MCP server（支持多个，租户级）：
  元数据（name/url/transport=streamable_http|sse/auth_headers_enc）
  + 注册时连通性探测（tools/list）+ 工具列表全量同步（MCP-01）。
- 工具列表管理（MCP-02）：禁用/启用/删除工具；手动刷新全量同步。
- 关联调用方提示（MCP-03）：删除/禁用时提示哪些 agent 在引用（agent_mcp_tools 勾选表）。
- 同步策略（DECISION-010）：注册时 + 手动刷新时全量同步（upsert by server_id+tool_name），
  运行时不轮询；调用失败触发一次后台重新同步（S08 经 refresh 端点触发，本卡提供能力）。
- 工具 schema 缓存（Redis 10min，DB_DESIGN §11 `joker:mcp:tools:<tenant>:<server>`）：
  ToolInterceptor（S08）快速查工具 schema/scope 免 DB；禁用/同步操作主动 DEL。

平台内置 server（DB_DESIGN §5.1 `is_platform=true`）：启动时幂等 upsert
（tenant=系统租户，url=BFF /mcp），3 个平台工具行（source=platform，required_scopes
见 platform_tools.PLATFORM_TOOL_SCOPES）；不可删除（409）。
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import redis_client
from joker_shared.config import settings
from joker_shared.crypto import encrypt_secret
from joker_shared.mcp.client import MCPProbeError, list_remote_tools
from joker_shared.mcp.platform_tools import PLATFORM_TOOLS, PLATFORM_TOOL_SCOPES

log = logging.getLogger("joker.mcp.registry")

SYSTEM_TENANT = "00000000-0000-0000-0000-000000000001"
PLATFORM_SERVER_NAME = "joker-platform"
SERVER_STATUSES = ("online", "offline", "unreachable", "disabled")
TRANSPORTS = ("streamable_http", "sse")


# ============================================================ 序列化

def _ser_server(row: Any, with_auth: bool = False) -> dict[str, Any]:
    d = dict(row._mapping)
    enc = d.pop("auth_headers_enc", None)
    for k in ("id", "tenant_id", "created_by", "updated_by"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    d["auth_headers_set"] = bool(enc)
    if with_auth and enc:
        d["auth_headers_enc"] = enc
    for k in ("last_sync_at", "created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def _ser_tool(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    for k in ("id", "tenant_id", "server_id", "created_by", "updated_by"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if isinstance(d.get("input_schema"), str):
        try:
            d["input_schema"] = json.loads(d["input_schema"])
        except ValueError:
            d["input_schema"] = None
    if isinstance(d.get("required_scopes"), str):
        try:
            d["required_scopes"] = json.loads(d["required_scopes"])
        except ValueError:
            d["required_scopes"] = ["mcp:tool"]
    for k in ("last_sync_at", "created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def cache_key(tenant_id: str, server_id: str) -> str:
    return f"joker:mcp:tools:{tenant_id}:{server_id}"


# ============================================================ Service

class MCPRegistryService:
    """MCP server 注册/同步/工具管理 + 关联调用方提示。"""

    # ---------- server 查询 ----------

    async def _fetch_server(
        self, session: AsyncSession, server_id: str, tenant_id: str | None = None
    ) -> Any:
        if tenant_id:
            r = await session.execute(
                text("SELECT * FROM mcp_servers WHERE id = CAST(:id AS uuid) "
                     "AND (tenant_id = CAST(:t AS uuid) OR is_platform = true) AND deleted_at IS NULL"),
                {"id": server_id, "t": tenant_id},
            )
        else:
            r = await session.execute(
                text("SELECT * FROM mcp_servers WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"),
                {"id": server_id},
            )
        return r.first()

    async def list_servers(self, session: AsyncSession, tenant_id: str, status: str | None = None) -> dict:
        where = (
            "WHERE (s.tenant_id = CAST(:t AS uuid) OR s.is_platform = true) "
            "AND s.deleted_at IS NULL"
        )
        params: dict[str, Any] = {"t": tenant_id}
        if status:
            where += " AND s.status = :st"
            params["st"] = status
        r = await session.execute(
            text(
                f"""SELECT s.*, (SELECT count(*) FROM mcp_tools t
                     WHERE t.server_id = s.id AND t.deleted_at IS NULL AND t.removed_remote = false
                     AND t.enabled = true) AS usable_tool_count
                    FROM mcp_servers s {where} ORDER BY s.created_at"""
            ),
            params,
        )
        items = []
        for row in r.fetchall():
            d = _ser_server(row)
            d["usable_tool_count"] = row._mapping["usable_tool_count"]
            items.append(d)
        return {"items": items, "total": len(items)}

    async def get_server(self, session: AsyncSession, server_id: str, tenant_id: str | None = None) -> dict | None:
        row = await self._fetch_server(session, server_id, tenant_id)
        return _ser_server(row) if row else None

    # ---------- MCP-01 注册/编辑 ----------

    async def register_server(self, session: AsyncSession, tenant_id: str, user_id: str | None, d: dict) -> dict:
        name = (d.get("name") or "").strip()
        url = (d.get("url") or "").strip()
        transport = (d.get("transport") or "streamable_http").strip()
        if not name or not url:
            raise HTTPException(422, "name and url are required")
        if transport not in TRANSPORTS:
            raise HTTPException(422, f"transport must be one of {TRANSPORTS}")
        dup = await session.execute(
            text("SELECT 1 FROM mcp_servers WHERE tenant_id = CAST(:t AS uuid) AND name = :n AND deleted_at IS NULL"),
            {"t": tenant_id, "n": name},
        )
        if dup.first():
            raise HTTPException(409, f"server name already exists: {name}")
        if not url.startswith(("http://", "https://")):
            raise HTTPException(422, "url must start with http:// or https://")

        server_id = str(uuid.uuid4())
        auth_enc = None
        if d.get("auth_headers"):
            if not isinstance(d["auth_headers"], dict) or not d["auth_headers"]:
                raise HTTPException(422, "auth_headers must be a non-empty object")
            auth_enc = encrypt_secret(json.dumps(d["auth_headers"], ensure_ascii=False))

        await session.execute(
            text(
                """INSERT INTO mcp_servers
                   (id, tenant_id, name, url, transport, is_platform, auth_headers_enc,
                    status, created_by)
                   VALUES (:id, CAST(:t AS uuid), :n, :url, :tr, false, :enc, 'unreachable', :by)"""
            ),
            {"id": server_id, "t": tenant_id, "n": name, "url": url, "tr": transport,
             "enc": auth_enc, "by": user_id},
        )
        await session.commit()

        # 注册时连通性探测 + 工具全量同步（MCP-01 验收 4：失败有明确错误，server 保留为 unreachable）
        result = await self.probe_and_sync(session, server_id, tenant_id, user_id)
        return {**(await self.get_server(session, server_id, tenant_id)), "sync": result}

    async def update_server(
        self, session: AsyncSession, server_id: str, tenant_id: str, user_id: str | None, d: dict
    ) -> dict:
        row = await self._fetch_server(session, server_id, tenant_id)
        if row is None:
            raise HTTPException(404, f"server not found: {server_id}")
        if row._mapping["is_platform"]:
            raise HTTPException(409, "platform built-in server cannot be modified")

        sets: list[str] = []
        params: dict[str, Any] = {"id": server_id, "by": user_id}
        for f in ("name", "url", "transport"):
            if f in d and d[f] is not None:
                v = str(d[f]).strip()
                if f == "url" and not v.startswith(("http://", "https://")):
                    raise HTTPException(422, "url must start with http:// or https://")
                if f == "transport" and v not in TRANSPORTS:
                    raise HTTPException(422, f"transport must be one of {TRANSPORTS}")
                if f == "name" and not v:
                    raise HTTPException(422, "name must not be empty")
                sets.append(f"{f} = :{f}")
                params[f] = v
        if "status" in d and d["status"] is not None:
            if d["status"] not in SERVER_STATUSES:
                raise HTTPException(422, f"status must be one of {SERVER_STATUSES}")
            sets.append("status = :status")
            params["status"] = d["status"]
        if "auth_headers" in d and d["auth_headers"]:
            if not isinstance(d["auth_headers"], dict):
                raise HTTPException(422, "auth_headers must be an object")
            sets.append("auth_headers_enc = :enc")
            params["enc"] = encrypt_secret(json.dumps(d["auth_headers"], ensure_ascii=False))
        if d.get("clear_auth_headers"):
            sets.append("auth_headers_enc = NULL")

        if not sets:
            raise HTTPException(422, "no updatable fields provided")
        if "name" in params:
            dup = await session.execute(
                text("SELECT 1 FROM mcp_servers WHERE tenant_id = CAST(:t AS uuid) AND name = :n "
                     "AND id <> CAST(:id AS uuid) AND deleted_at IS NULL"),
                {"t": tenant_id, "n": params["name"], "id": server_id},
            )
            if dup.first():
                raise HTTPException(409, f"server name already exists: {params['name']}")

        await session.execute(
            text(f"UPDATE mcp_servers SET {', '.join(sets)} WHERE id = CAST(:id AS uuid)"), params
        )
        await session.commit()
        return await self.get_server(session, server_id, tenant_id)  # type: ignore[return-value]

    async def delete_server(
        self, session: AsyncSession, server_id: str, tenant_id: str, user_id: str | None, confirm: bool = False
    ) -> dict:
        row = await self._fetch_server(session, server_id, tenant_id)
        if row is None:
            raise HTTPException(404, f"server not found: {server_id}")
        if row._mapping["is_platform"]:
            raise HTTPException(409, "platform built-in server cannot be deleted (use disable)")
        refs = await self._referring_agents(session, tool_ids=None, server_id=server_id)
        if refs and not confirm:
            raise HTTPException(
                409,
                {
                    "detail": f"server referenced by {len(refs)} agents; pass confirm=true to delete anyway "
                              f"(agents will lose these tools)",
                    "referring_agents": refs,
                },
            )
        await session.execute(
            text("UPDATE mcp_servers SET deleted_at = now(), updated_by = :by WHERE id = CAST(:id AS uuid)"),
            {"id": server_id, "by": user_id},
        )
        # 工具行保留（软引用历史；removed 状态随 server 删除不可再勾选）
        await session.execute(
            text("DELETE FROM mcp_tools WHERE server_id = CAST(:id AS uuid)"), {"id": server_id}
        )
        await session.commit()
        await self._del_cache(tenant_id, server_id)
        log.info("mcp server deleted: %s (%s) confirm=%s refs=%d", row._mapping["name"], server_id, confirm, len(refs))
        return {"ok": True, "deleted": server_id, "referring_agents": refs,
                "message": f"deleted; {len(refs)} referring agent(s) will lose these tools" if refs
                           else "deleted (no referring agents)"}

    # ---------- 连通性探测 + 全量同步（DECISION-010） ----------

    async def probe_and_sync(self, session: AsyncSession, server_id: str, tenant_id: str, user_id: str | None) -> dict:
        """tools/list 探测 + 全量同步。成功 → status=online；失败 → status=unreachable + last_error。

        同步语义（upsert by server_id+tool_name，DECISION-010）：
        - 远端存在且本地不存在 → 插入（enabled=true, removed_remote=false）
        - 远端存在且本地存在（含 removed_remote=true 复活）→ 更新快照 + removed_remote=false
        - 本地存在但远端已无 → removed_remote=true（保留记录、不可选，MCP-02 验收 3 反向同步）
        - 既有工具的 enabled/required_scopes 人工配置保留（同步只更新远端快照字段）
        """
        row = await self._fetch_server(session, server_id)
        if row is None:
            raise HTTPException(404, f"server not found: {server_id}")
        try:
            tools = await list_remote_tools(row._mapping["url"], row._mapping["transport"], row._mapping["auth_headers_enc"])
        except MCPProbeError as exc:
            await session.execute(
                text("UPDATE mcp_servers SET status = 'unreachable', last_error = :e "
                     "WHERE id = CAST(:id AS uuid)"),
                {"id": server_id, "e": str(exc)[:500]},
            )
            await session.commit()
            return {"ok": False, "error": str(exc)[:500], "status": "unreachable"}

        # 全量同步
        remote_names = {t["name"] for t in tools}
        existing = await session.execute(
            text("SELECT id, name FROM mcp_tools WHERE server_id = CAST(:s AS uuid) AND deleted_at IS NULL"),
            {"s": server_id},
        )
        local: dict[str, str] = {r._mapping["name"]: r._mapping["id"] for r in existing.fetchall()}

        for t in tools:
            name = t["name"]
            if name in local:
                await session.execute(
                    text(
                        """UPDATE mcp_tools
                           SET description = :d, input_schema = CAST(:s AS jsonb), removed_remote = false,
                               last_sync_at = now(), updated_by = :by
                           WHERE id = CAST(:id AS uuid)"""
                    ),
                    {"d": t["description"], "s": json.dumps(t["input_schema"], ensure_ascii=False),
                     "by": user_id, "id": local[name]},
                )
            else:
                await session.execute(
                    text(
                        """INSERT INTO mcp_tools
                           (id, tenant_id, server_id, name, description, input_schema, source,
                            required_scopes, enabled, removed_remote, last_sync_at, created_by, updated_by)
                           VALUES (gen_random_uuid(), CAST(:t AS uuid), CAST(:s AS uuid), :n, :d, CAST(:sc AS jsonb),
                                   'remote', '["mcp:tool"]', true, false, now(), :by, :by)"""
                    ),
                    {"t": tenant_id, "s": server_id, "n": name, "d": t["description"],
                     "sc": json.dumps(t["input_schema"], ensure_ascii=False), "by": user_id},
                )
        for name, tid in local.items():
            if name not in remote_names:
                await session.execute(
                    text("UPDATE mcp_tools SET removed_remote = true, last_sync_at = now() "
                         "WHERE id = CAST(:id AS uuid)"),
                    {"id": tid},
                )
        await session.execute(
            text("UPDATE mcp_servers SET status = 'online', last_error = NULL, "
                 "last_sync_at = now(), tool_count = :c, updated_by = :by WHERE id = CAST(:id AS uuid)"),
            {"c": len(tools), "by": user_id, "id": server_id},
        )
        await session.commit()
        await self._del_cache(tenant_id, server_id)  # 同步后缓存失效（DECISION-010）
        log.info("mcp server %s synced: %d tools (online)", server_id, len(tools))
        return {"ok": True, "status": "online", "tool_count": len(tools)}

    # ---------- MCP-02 工具管理 ----------

    async def _fetch_tool(self, session: AsyncSession, tool_id: str, tenant_id: str) -> Any:
        r = await session.execute(
            text("SELECT t.* FROM mcp_tools t JOIN mcp_servers s ON s.id = t.server_id "
                 "WHERE t.id = CAST(:id AS uuid) AND (s.tenant_id = CAST(:t AS uuid) OR s.is_platform = true) "
                 "AND t.deleted_at IS NULL"),
            {"id": tool_id, "t": tenant_id},
        )
        return r.first()

    async def list_tools(
        self, session: AsyncSession, server_id: str, tenant_id: str,
        status: str | None = None, source: str | None = None,
    ) -> dict:
        server = await self.get_server(session, server_id, tenant_id)
        if server is None:
            raise HTTPException(404, f"server not found: {server_id}")
        where = "WHERE t.server_id = CAST(:s AS uuid) AND t.deleted_at IS NULL"
        params: dict[str, Any] = {"s": server_id}
        if status == "enabled":
            where += " AND t.enabled = true AND t.removed_remote = false"
        elif status == "disabled":
            where += " AND t.enabled = false"
        elif status == "removed":
            where += " AND t.removed_remote = true"
        if source in ("remote", "platform"):
            where += " AND t.source = :src"
            params["src"] = source
        r = await session.execute(
            text(f"""SELECT t.* FROM mcp_tools t {where} ORDER BY t.name"""), params
        )
        items = [_ser_tool(row) for row in r.fetchall()]
        for it in items:
            it["usable"] = (
                it["enabled"] and not it["removed_remote"] and server["status"] == "online"
            )
        return {"server_id": server_id, "server_status": server["status"],
                "items": items, "total": len(items)}

    async def set_tool_enabled(
        self, session: AsyncSession, tool_id: str, tenant_id: str, user_id: str | None,
        enabled: bool, confirm: bool = False,
    ) -> dict:
        """禁用/启用工具（MCP-02 验收 2 + MCP-03）。

        禁用时若有 agent 引用：无 confirm → 409 + 引用清单（需确认）；confirm → 生效
        （agent 侧工具不再可用：勾选行保留但 enabled=false，S07/S08 按工具状态拦截调用）。
        """
        row = await self._fetch_tool(session, tool_id, tenant_id)
        if row is None:
            raise HTTPException(404, f"tool not found: {tool_id}")
        if row._mapping["removed_remote"]:
            raise HTTPException(409, "tool was removed remotely; re-sync the server to restore it")
        if not enabled:
            refs = await self._referring_agents(session, tool_ids=[tool_id])
            if refs and not confirm:
                raise HTTPException(
                    409,
                    {
                        "detail": f"tool referenced by {len(refs)} agents; pass confirm=true to disable anyway",
                        "referring_agents": refs,
                    },
                )
        await session.execute(
            text("UPDATE mcp_tools SET enabled = :e, updated_by = :by WHERE id = CAST(:id AS uuid)"),
            {"e": enabled, "by": user_id, "id": tool_id},
        )
        await session.commit()
        await self._del_cache(tenant_id, row._mapping["server_id"])
        after = await self._fetch_tool(session, tool_id, tenant_id)
        return {**_ser_tool(after), "enabled": enabled}

    async def delete_tool(
        self, session: AsyncSession, tool_id: str, tenant_id: str, user_id: str | None, confirm: bool = False
    ) -> dict:
        """删除工具（平台侧移除，不删远端，MCP-02 验收 3）。

        有 agent 引用：无 confirm → 409 + 引用清单；confirm → 软删 + agent 勾选级联清理。
        """
        row = await self._fetch_tool(session, tool_id, tenant_id)
        if row is None:
            raise HTTPException(404, f"tool not found: {tool_id}")
        refs = await self._referring_agents(session, tool_ids=[tool_id])
        if refs and not confirm:
            raise HTTPException(
                409,
                {
                    "detail": f"tool referenced by {len(refs)} agents; pass confirm=true to delete anyway",
                    "referring_agents": refs,
                },
            )
        await session.execute(
            text("UPDATE mcp_tools SET deleted_at = now(), updated_by = :by WHERE id = CAST(:id AS uuid)"),
            {"by": user_id, "id": tool_id},
        )
        await session.commit()
        await self._del_cache(tenant_id, row._mapping["server_id"])
        return {"ok": True, "deleted": tool_id, "referring_agents": refs,
                "message": f"removed from platform registry (remote tool untouched); "
                           f"{len(refs)} referring agent(s) unchecked" if refs
                           else "removed (no referring agents)"}

    # ---------- MCP-03 关联调用方 ----------

    async def _referring_agents(
        self, session: AsyncSession, tool_ids: list[str] | None, server_id: str | None = None
    ) -> list[dict[str, str]]:
        """查 agent_mcp_tools（deleted_at IS NULL）中引用指定工具/server 的 agent（MCP-03）。"""
        if tool_ids:
            r = await session.execute(
                text(
                    """SELECT DISTINCT a.id, a.name FROM agent_mcp_tools m
                       JOIN agents a ON a.id = m.agent_id AND a.deleted_at IS NULL
                       WHERE m.mcp_tool_id = ANY(:ids) AND m.deleted_at IS NULL
                       ORDER BY a.name"""
                ),
                {"ids": [uuid.UUID(x) for x in tool_ids]},
            )
        elif server_id:
            r = await session.execute(
                text(
                    """SELECT DISTINCT a.id, a.name FROM agent_mcp_tools m
                       JOIN mcp_tools t ON t.id = m.mcp_tool_id
                       JOIN agents a ON a.id = m.agent_id AND a.deleted_at IS NULL
                       WHERE t.server_id = CAST(:s AS uuid) AND m.deleted_at IS NULL
                       ORDER BY a.name"""
                ),
                {"s": server_id},
            )
        else:
            return []
        return [{"agent_id": str(x[0]), "agent_name": x[1]} for x in r.fetchall()]

    async def referring_agents(self, session: AsyncSession, tool_id: str | None, server_id: str | None) -> dict:
        return {"referring_agents": await self._referring_agents(session, [tool_id] if tool_id else None, server_id)}

    # ---------- 工具 schema 缓存（Redis 10min，DECISION-010） ----------

    async def get_tools_cached(
        self, session: AsyncSession, server_id: str, tenant_id: str, refresh: bool = False
    ) -> dict:
        """工具 schema/scope 快照：Redis 命中（10min TTL）→ 直接返回；未命中 → DB 读 + 回填。

        出参（S08 ToolInterceptor 消费）：
        {server_id, server_status, tools: [{id, name, description, input_schema,
          source, required_scopes, enabled, removed_remote, usable}], cache: hit|miss}
        """
        k = cache_key(tenant_id, server_id)
        server = await self.get_server(session, server_id, tenant_id)
        if server is None:
            raise HTTPException(404, f"server not found: {server_id}")
        if not refresh:
            try:
                raw = await redis_client.get_redis().get(k)
                if raw:
                    cached = json.loads(raw)
                    cached["server_status"] = server["status"]
                    cached["cache"] = "hit"
                    return cached
            except Exception as exc:  # Redis 抖动 → 降级 DB（不阻断）
                log.warning("mcp tools cache read failed (%s); falling back to DB", exc)
        data = await self._tools_from_db(session, server_id, server)
        data["server_status"] = server["status"]
        data["cache"] = "miss" if not refresh else "refreshed"
        try:
            await redis_client.get_redis().setex(k, settings.MCP_TOOL_CACHE_TTL, json.dumps(data, ensure_ascii=False))
        except Exception as exc:
            log.warning("mcp tools cache write failed: %s", exc)
        return data

    async def _tools_from_db(self, session: AsyncSession, server_id: str, server: dict) -> dict:
        r = await session.execute(
            text("SELECT * FROM mcp_tools WHERE server_id = CAST(:s AS uuid) AND deleted_at IS NULL ORDER BY name"),
            {"s": server_id},
        )
        tools = []
        for row in r.fetchall():
            d = _ser_tool(row)
            d["usable"] = d["enabled"] and not d["removed_remote"] and server["status"] == "online"
            tools.append(d)
        return {"server_id": server_id, "tools": tools, "total": len(tools)}

    async def _del_cache(self, tenant_id: str, server_id: str) -> None:
        try:
            await redis_client.get_redis().delete(cache_key(tenant_id, server_id))
        except Exception as exc:
            log.warning("mcp tools cache delete failed: %s", exc)

    # ---------- 平台内置 server（启动幂等注册） ----------

    async def ensure_platform_server(self, session: AsyncSession, bff_mcp_url: str | None = None) -> dict:
        """幂等 upsert 平台内置 server（系统租户）+ 3 平台工具行（source=platform）。

        url = BFF /mcp（compose 网络内 bff:8000/mcp）；status=online（本地部署事实，
        远端 tools/list 即 BFF 自身，探测循环无意义；S11 集成后如需校验可改配置）。
        """
        url = bff_mcp_url or settings.BFF_MCP_URL
        r = await session.execute(
            text("SELECT id FROM mcp_servers WHERE is_platform = true AND deleted_at IS NULL "
                 "ORDER BY created_at LIMIT 1")
        )
        row = r.first()
        if row is None:
            server_id = str(uuid.uuid4())
            await session.execute(
                text(
                    """INSERT INTO mcp_servers
                       (id, tenant_id, name, url, transport, is_platform, status, tool_count)
                       VALUES (:id, CAST(:t AS uuid), :n, :url, 'streamable_http', true, 'online', 3)"""
                ),
                {"id": server_id, "t": SYSTEM_TENANT, "n": PLATFORM_SERVER_NAME, "url": url},
            )
        else:
            server_id = str(row[0])
            await session.execute(
                text("UPDATE mcp_servers SET url = :url, status = 'online' WHERE id = :id"),
                {"url": url, "id": server_id},
            )
        for t in PLATFORM_TOOLS:
            await session.execute(
                text(
                    """INSERT INTO mcp_tools
                       (id, tenant_id, server_id, name, description, input_schema, source,
                        required_scopes, enabled, removed_remote)
                       VALUES (gen_random_uuid(), CAST(:t AS uuid), CAST(:s AS uuid), :n, :d, CAST(:sc AS jsonb),
                               'platform', CAST(:rs AS jsonb), true, false)
                       ON CONFLICT (server_id, name) DO UPDATE
                       SET description = EXCLUDED.description,
                           input_schema = EXCLUDED.input_schema,
                           required_scopes = EXCLUDED.required_scopes,
                           removed_remote = false"""
                ),
                {"t": SYSTEM_TENANT, "s": server_id, "n": t["name"], "d": t["description"],
                 "sc": json.dumps(t["input_schema"], ensure_ascii=False),
                 "rs": json.dumps(PLATFORM_TOOL_SCOPES[t["name"]])},
            )
        await session.commit()
        await self._del_cache(SYSTEM_TENANT, server_id)
        return {"ok": True, "server_id": server_id, "url": url}


_service: MCPRegistryService | None = None


def get_mcp_registry() -> MCPRegistryService:
    global _service
    if _service is None:
        _service = MCPRegistryService()
    return _service
