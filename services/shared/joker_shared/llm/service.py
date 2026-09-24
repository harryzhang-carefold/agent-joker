"""LLMNodeService（S03，LLM-01/02/03）。

三类平台级节点 CRUD + 连通性探测 + 本地 fallback embedding：
- endpoint：chat 推理端点（OpenAI 兼容 /chat/completions）
- embedding：embedding 模型端点（OpenAI 兼容 /embeddings；provider=local 走本地确定性实现）
- reranker：rerank 模型端点（Jina 兼容 /rerank 契约）

设计要点（DB_DESIGN §3 / DECISION-012 / card_common）：
- 三类节点平台级共享：tenant_id 仅审计归属，**不做行级过滤**（全租户可见）；
  管理（增删改/测试）需 `llm:manage` 平台 scope。
- api_key 一律 Fernet 加密落库（api_key_enc），响应/日志永不回显明文（DECISION-012）。
- 节点配置化：无缓存，每次读库取最新 → CRUD 后即时生效（RAG/Agent 读节点用最新）。
- 连通性探测：轻量请求（chat 发 "ping" / embedding 发短文本 / rerank 发短文本），
  返回可用/不可用 + 错误摘要，写 last_test_at / last_test_result。
- 本地 fallback embedding（确定性字符 n-gram 哈希）：真实端点不可用时自测闭环，
  接口与真实端点一致（同一 embed_texts 抽象：list[str] -> list[list[float]]）。
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

from joker_shared.config import settings
from joker_shared.crypto import decrypt_secret, encrypt_secret
from joker_shared.llm.local_embedding import local_fallback_embeddings

log = logging.getLogger("joker.llm")

STATUSES = ("active", "disabled")
# 明文 key 永不出现在响应中的字段（响应只带 api_key_set 布尔）


def _new_id() -> str:
    return str(uuid.uuid4())


class LLMNodeService:
    """节点 CRUD + 探测 + 统一 embed/rerank 调用抽象（供 S04/S05/S07 复用）。"""

    # ============================================================ 通用工具

    @staticmethod
    def _row_to_node(row: Any, keep_secret: bool = False) -> dict:
        """DB 行 → 节点 dict。

        - 默认（REST 响应）：api_key 脱敏——弹出加密 key，只回 `api_key_set` 布尔
          （DECISION-012 合规：明文/密文 key 永不进入对外响应）。
        - `keep_secret=True`（**内部专用**，BUG-11 修复）：保留 `api_key_enc`，
          仅供进程内探测/agent 运行时/RAG 取 key 使用，**绝不进入任何 REST 响应**。
        """
        d = dict(row._mapping)
        if keep_secret:
            enc = d.get("api_key_enc")  # INTERNAL：保留加密 key（永不写日志/响应）
        else:
            enc = d.pop("api_key_enc", None)  # REST：脱敏，只留 api_key_set
        for k, v in list(d.items()):
            if k in ("id", "tenant_id", "created_by", "updated_by") and v is not None:
                d[k] = str(v)
            elif k == "default_params" and isinstance(v, str):
                try:
                    d[k] = json.loads(v)
                except ValueError:
                    d[k] = None
        d["api_key_set"] = bool(enc)
        return d

    async def _fetch_one(self, session: AsyncSession, sql: str, node_id: str) -> Any:
        r = await session.execute(text(sql), {"id": node_id})
        return r.first()

    async def _name_conflict(self, session: AsyncSession, table: str, name: str, exclude_id: str | None = None) -> bool:
        if exclude_id:
            r = await session.execute(
                text(f"SELECT 1 FROM {table} WHERE name = :n AND id <> :x"), {"n": name, "x": exclude_id}
            )
        else:
            r = await session.execute(text(f"SELECT 1 FROM {table} WHERE name = :n"), {"n": name})
        return r.first() is not None

    # ============================================================ endpoint（LLM-01）

    async def list_endpoints(
        self, session: AsyncSession, status: str | None = None, supports_vision: bool | None = None
    ) -> dict:
        where, params = [], {}
        if status:
            where.append("status = :st"); params["st"] = status
        if supports_vision is not None:
            where.append("supports_vision = :sv"); params["sv"] = supports_vision
        w = ("WHERE " + " AND ".join(where)) if where else ""
        r = await session.execute(text(f"SELECT * FROM llm_endpoints {w} ORDER BY created_at"), params)
        items = [self._row_to_node(row) for row in r.fetchall()]
        return {"items": items, "total": len(items), "page": 1, "page_size": len(items)}

    async def get_endpoint(self, session: AsyncSession, node_id: str) -> dict | None:
        row = await self._fetch_one(session, "SELECT * FROM llm_endpoints WHERE id = :id", node_id)
        return self._row_to_node(row) if row else None

    # ============================================================ 内部取 key 通道（BUG-11 修复，内部专用，绝不进 REST）
    #
    # 脱敏（DECISION-012）只作用于「对外 API 响应」；平台内部探测/agent 运行时/RAG
    # 调用需要真实凭据，走下列 keep_secret 通道。这些方法仅进程内调用，
    # 返回的 dict 含 api_key_enc，**禁止**被任何 REST 端点直接返回给客户端。

    async def get_endpoint_internal(self, session: AsyncSession, node_id: str) -> dict | None:
        """内部专用：返回含 api_key_enc 的 endpoint（探测/agent 运行时取 key）。"""
        row = await self._fetch_one(session, "SELECT * FROM llm_endpoints WHERE id = :id", node_id)
        return self._row_to_node(row, keep_secret=True) if row else None

    async def get_embedding_internal(self, session: AsyncSession, node_id: str) -> dict | None:
        """内部专用：返回含 api_key_enc 的 embedding 模型（embed_texts 取 key）。"""
        row = await self._fetch_one(session, "SELECT * FROM llm_embedding_models WHERE id = :id", node_id)
        return self._row_to_node(row, keep_secret=True) if row else None

    async def get_reranker_internal(self, session: AsyncSession, node_id: str) -> dict | None:
        """内部专用：返回含 api_key_enc 的 reranker（rerank 取 key）。"""
        row = await self._fetch_one(session, "SELECT * FROM llm_reranker_models WHERE id = :id", node_id)
        return self._row_to_node(row, keep_secret=True) if row else None

    async def create_endpoint(self, session: AsyncSession, tenant_id: str | None, user_id: str | None, d: dict) -> dict:
        name, base_url, model = d["name"], d["base_url"], d["model"]
        if await self._name_conflict(session, "llm_endpoints", name):
            raise HTTPException(409, f"endpoint name already exists: {name}")
        api_key_enc = encrypt_secret(d["api_key"]) if d.get("api_key") else None
        nid = _new_id()
        await session.execute(
            text(
                "INSERT INTO llm_endpoints (id, tenant_id, name, base_url, model, api_key_enc, auth_scheme,"
                " supports_vision, default_params, timeout_seconds, status, created_by, updated_by)"
                " VALUES (:id, :t, :n, :bu, :m, :k, :as, :sv, :dp, :to, :st, :cb, :ub)"
            ),
            {
                "id": nid, "t": tenant_id, "n": name, "bu": base_url, "m": model, "k": api_key_enc,
                "as": d.get("auth_scheme", "bearer"), "sv": bool(d.get("supports_vision", False)),
                "dp": json.dumps(d.get("default_params") or {}),
                "to": int(d.get("timeout_seconds", 120)),
                "st": d.get("status", "active"), "cb": user_id, "ub": user_id,
            },
        )
        await session.commit()
        log.info("llm endpoint created: %s (%s)", name, base_url)  # 只记 url/名称，不记 key
        return await self.get_endpoint(session, nid)

    async def update_endpoint(self, session: AsyncSession, node_id: str, user_id: str | None, d: dict) -> dict:
        row = await self._fetch_one(session, "SELECT * FROM llm_endpoints WHERE id = :id", node_id)
        if row is None:
            raise HTTPException(404, f"endpoint not found: {node_id}")
        sets, params = [], {"id": node_id, "ub": user_id}
        for col in ("name", "base_url", "model", "auth_scheme", "supports_vision",
                    "timeout_seconds", "status"):
            if col in d:
                sets.append(f"{col} = :{col}"); params[col] = d[col]
        if "default_params" in d:
            sets.append("default_params = :dp"); params["dp"] = json.dumps(d["default_params"] or {})
        if d.get("api_key"):  # 非空=替换；空/缺省=保持
            sets.append("api_key_enc = :k"); params["k"] = encrypt_secret(d["api_key"])
        if d.get("clear_api_key"):
            sets.append("api_key_enc = :k"); params["k"] = None
        if not sets:
            raise HTTPException(400, "no fields to update")
        sets.append("updated_by = :ub")
        if "name" in d and await self._name_conflict(session, "llm_endpoints", d["name"], node_id):
            raise HTTPException(409, f"endpoint name already exists: {d['name']}")
        await session.execute(text(f"UPDATE llm_endpoints SET {', '.join(sets)} WHERE id = :id"), params)
        await session.commit()
        log.info("llm endpoint updated: %s", node_id)
        return await self.get_endpoint(session, node_id)

    async def delete_endpoint(self, session: AsyncSession, node_id: str) -> dict:
        refs: list[str] = []
        r = await session.execute(
            text("SELECT a.name FROM agent_llm_endpoints l JOIN agents a ON a.id = l.agent_id"
                 " WHERE l.llm_endpoint_id = :id AND l.deleted_at IS NULL"),
            {"id": node_id},
        )
        for row in r.fetchall():
            refs.append(f"agent:{row[0]}")
        r = await session.execute(
            text("SELECT count(*) FROM rag_doc_images WHERE vision_endpoint_id = :id"), {"id": node_id}
        )
        n = r.scalar() or 0
        if n:
            refs.append(f"rag_doc_images:{n}")
        if refs:
            # 删除策略=禁用代替硬删（DB_DESIGN §3.1：被引用禁删，409+引用清单）
            raise HTTPException(409, {"detail": f"endpoint in use (disable instead of delete): {refs}"})
        row = await self._fetch_one(session, "SELECT * FROM llm_endpoints WHERE id = :id", node_id)
        if row is None:
            raise HTTPException(404, f"endpoint not found: {node_id}")
        await session.execute(text("DELETE FROM llm_endpoints WHERE id = :id"), {"id": node_id})
        await session.commit()
        log.info("llm endpoint deleted: %s (%s)", row._mapping["name"], node_id)
        return {"ok": True, "deleted": node_id}

    # ============================================================ embedding（LLM-02）

    async def list_embeddings(self, session: AsyncSession, status: str | None = None) -> dict:
        where = "WHERE status = :st" if status else ""
        params = {"st": status} if status else {}
        r = await session.execute(text(f"SELECT * FROM llm_embedding_models {where} ORDER BY created_at"), params)
        items = [self._row_to_node(row) for row in r.fetchall()]
        return {"items": items, "total": len(items), "page": 1, "page_size": len(items)}

    async def get_embedding(self, session: AsyncSession, node_id: str) -> dict | None:
        row = await self._fetch_one(session, "SELECT * FROM llm_embedding_models WHERE id = :id", node_id)
        return self._row_to_node(row) if row else None

    async def create_embedding(self, session: AsyncSession, tenant_id: str | None, user_id: str | None, d: dict) -> dict:
        if d.get("provider", "api") not in ("api", "local"):
            raise HTTPException(422, "provider must be 'api' or 'local'")
        if await self._name_conflict(session, "llm_embedding_models", d["name"]):
            raise HTTPException(409, f"embedding model name already exists: {d['name']}")
        api_key_enc = encrypt_secret(d["api_key"]) if d.get("api_key") else None
        nid = _new_id()
        await session.execute(
            text(
                "INSERT INTO llm_embedding_models (id, tenant_id, name, provider, base_url, model, api_key_enc,"
                " dimensions, batch_size, status, created_by, updated_by)"
                " VALUES (:id, :t, :n, :p, :bu, :m, :k, :d, :b, :st, :cb, :ub)"
            ),
            {
                "id": nid, "t": tenant_id, "n": d["name"], "p": d.get("provider", "api"),
                "bu": d.get("base_url") or ("local://fallback" if d.get("provider", "api") == "local" else ""),
                "m": d.get("model", ""), "k": api_key_enc,
                "d": int(d["dimensions"]), "b": int(d.get("batch_size", 32)),
                "st": d.get("status", "active"), "cb": user_id, "ub": user_id,
            },
        )
        await session.commit()
        log.info("llm embedding model created: %s (provider=%s, dim=%s)", d["name"], d.get("provider", "api"), d["dimensions"])
        return await self.get_embedding(session, nid)

    async def update_embedding(self, session: AsyncSession, node_id: str, user_id: str | None, d: dict) -> dict:
        row = await self._fetch_one(session, "SELECT * FROM llm_embedding_models WHERE id = :id", node_id)
        if row is None:
            raise HTTPException(404, f"embedding model not found: {node_id}")
        sets, params = [], {"id": node_id, "ub": user_id}
        for col in ("name", "provider", "base_url", "model", "dimensions", "batch_size", "status"):
            if col in d:
                sets.append(f"{col} = :{col}"); params[col] = d[col]
        if d.get("api_key"):
            sets.append("api_key_enc = :k"); params["k"] = encrypt_secret(d["api_key"])
        if d.get("clear_api_key"):
            sets.append("api_key_enc = :k"); params["k"] = None
        if not sets:
            raise HTTPException(400, "no fields to update")
        sets.append("updated_by = :ub")
        if "name" in d and await self._name_conflict(session, "llm_embedding_models", d["name"], node_id):
            raise HTTPException(409, f"embedding model name already exists: {d['name']}")
        await session.execute(text(f"UPDATE llm_embedding_models SET {', '.join(sets)} WHERE id = :id"), params)
        await session.commit()
        log.info("llm embedding model updated: %s", node_id)
        return await self.get_embedding(session, node_id)

    async def delete_embedding(self, session: AsyncSession, node_id: str) -> dict:
        r = await session.execute(
            text("SELECT name FROM rag_knowledge_bases WHERE embedding_model_id = :id"), {"id": node_id}
        )
        kbs = [row[0] for row in r.fetchall()]
        if kbs:
            raise HTTPException(409, {"detail": f"embedding model in use (disable instead of delete): kb={kbs}"})
        row = await self._fetch_one(session, "SELECT * FROM llm_embedding_models WHERE id = :id", node_id)
        if row is None:
            raise HTTPException(404, f"embedding model not found: {node_id}")
        await session.execute(text("DELETE FROM llm_embedding_models WHERE id = :id"), {"id": node_id})
        await session.commit()
        log.info("llm embedding model deleted: %s (%s)", row._mapping["name"], node_id)
        return {"ok": True, "deleted": node_id}

    # ============================================================ reranker（LLM-03）

    async def list_rerankers(self, session: AsyncSession, status: str | None = None) -> dict:
        where = "WHERE status = :st" if status else ""
        params = {"st": status} if status else {}
        r = await session.execute(text(f"SELECT * FROM llm_reranker_models {where} ORDER BY created_at"), params)
        items = [self._row_to_node(row) for row in r.fetchall()]
        return {"items": items, "total": len(items), "page": 1, "page_size": len(items)}

    async def get_reranker(self, session: AsyncSession, node_id: str) -> dict | None:
        row = await self._fetch_one(session, "SELECT * FROM llm_reranker_models WHERE id = :id", node_id)
        return self._row_to_node(row) if row else None

    async def create_reranker(self, session: AsyncSession, tenant_id: str | None, user_id: str | None, d: dict) -> dict:
        if await self._name_conflict(session, "llm_reranker_models", d["name"]):
            raise HTTPException(409, f"reranker model name already exists: {d['name']}")
        api_key_enc = encrypt_secret(d["api_key"]) if d.get("api_key") else None
        nid = _new_id()
        await session.execute(
            text(
                "INSERT INTO llm_reranker_models (id, tenant_id, name, base_url, model, api_key_enc,"
                " max_candidates, status, created_by, updated_by)"
                " VALUES (:id, :t, :n, :bu, :m, :k, :c, :st, :cb, :ub)"
            ),
            {
                "id": nid, "t": tenant_id, "n": d["name"], "bu": d["base_url"], "m": d["model"],
                "k": api_key_enc, "c": int(d.get("max_candidates", 100)),
                "st": d.get("status", "active"), "cb": user_id, "ub": user_id,
            },
        )
        await session.commit()
        log.info("llm reranker model created: %s (%s)", d["name"], d["base_url"])
        return await self.get_reranker(session, nid)

    async def update_reranker(self, session: AsyncSession, node_id: str, user_id: str | None, d: dict) -> dict:
        row = await self._fetch_one(session, "SELECT * FROM llm_reranker_models WHERE id = :id", node_id)
        if row is None:
            raise HTTPException(404, f"reranker model not found: {node_id}")
        sets, params = [], {"id": node_id, "ub": user_id}
        for col in ("name", "base_url", "model", "max_candidates", "status"):
            if col in d:
                sets.append(f"{col} = :{col}"); params[col] = d[col]
        if d.get("api_key"):
            sets.append("api_key_enc = :k"); params["k"] = encrypt_secret(d["api_key"])
        if d.get("clear_api_key"):
            sets.append("api_key_enc = :k"); params["k"] = None
        if not sets:
            raise HTTPException(400, "no fields to update")
        sets.append("updated_by = :ub")
        if "name" in d and await self._name_conflict(session, "llm_reranker_models", d["name"], node_id):
            raise HTTPException(409, f"reranker model name already exists: {d['name']}")
        await session.execute(text(f"UPDATE llm_reranker_models SET {', '.join(sets)} WHERE id = :id"), params)
        await session.commit()
        log.info("llm reranker model updated: %s", node_id)
        return await self.get_reranker(session, node_id)

    async def delete_reranker(self, session: AsyncSession, node_id: str) -> dict:
        r = await session.execute(
            text("SELECT name FROM rag_knowledge_bases WHERE reranker_model_id = :id"), {"id": node_id}
        )
        kbs = [row[0] for row in r.fetchall()]
        if kbs:
            raise HTTPException(409, {"detail": f"reranker model in use (disable instead of delete): kb={kbs}"})
        row = await self._fetch_one(session, "SELECT * FROM llm_reranker_models WHERE id = :id", node_id)
        if row is None:
            raise HTTPException(404, f"reranker model not found: {node_id}")
        await session.execute(text("DELETE FROM llm_reranker_models WHERE id = :id"), {"id": node_id})
        await session.commit()
        log.info("llm reranker model deleted: %s (%s)", row._mapping["name"], node_id)
        return {"ok": True, "deleted": node_id}

    # ============================================================ 连通性探测（LLM-01 验收 3）

    def _auth_header(self, api_key_enc: str | None, scheme: str = "bearer") -> dict:
        """组装 Authorization 头（只进 httpx 请求，不进日志）。"""
        if not api_key_enc:
            return {}
        key = decrypt_secret(api_key_enc)
        if scheme == "api_key_header":
            return {"X-API-Key": key}
        return {"Authorization": "***" + key}

    async def _probe_chat(self, node: dict) -> dict:
        base = (node.get("base_url") or "").rstrip("/")
        if not base:
            return self._probe_fail("base_url empty")
        body = {
            "model": node["model"],
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        }
        params = (node.get("default_params") or {}) if isinstance(node.get("default_params"), dict) else {}
        if "max_tokens" in params:
            body["max_tokens"] = params["max_tokens"]
        t0 = time.monotonic()
        timeout = min(float(node.get("timeout_seconds") or 120), settings.LLM_PROBE_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(
                    f"{base}/chat/completions", json=body, headers=self._auth_header(node.get("api_key_enc"), node.get("auth_scheme", "bearer"))
                )
            latency = int((time.monotonic() - t0) * 1000)
            if r.status_code != 200:
                return self._probe_fail(f"HTTP {r.status_code}", latency)
            data = r.json()
            if not data.get("choices"):
                return self._probe_fail("response has no choices", latency)
            summary = f"ok: model={node['model']} responded in {latency}ms"
            return {"ok": True, "latency_ms": latency, "summary": summary}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            latency = int((time.monotonic() - t0) * 1000)
            log.warning("llm endpoint probe failed: %s -> %s: %s", node["name"], base, type(exc).__name__)
            return self._probe_fail(f"{type(exc).__name__}: {exc}", latency)

    @staticmethod
    def _probe_fail(reason: str, latency_ms: int = 0) -> dict:
        return {"ok": False, "latency_ms": latency_ms, "summary": f"unavailable: {reason}"}

    async def _probe_embedding(self, node: dict) -> dict:
        if (node.get("provider") or "api") == "local":
            t0 = time.monotonic()
            vec = local_fallback_embeddings(["ping"])
            latency = int((time.monotonic() - t0) * 1000)
            if len(vec[0]) != int(node["dimensions"]):
                return self._probe_fail(f"local dim mismatch: got {len(vec[0])} want {node['dimensions']}")
            return {"ok": True, "latency_ms": latency,
                    "summary": f"ok: local fallback embedding produced dim={node['dimensions']} in {latency}ms"}
        base = (node.get("base_url") or "").rstrip("/")
        if not base:
            return self._probe_fail("base_url empty")
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_PROBE_TIMEOUT_SECONDS) as client:
                r = await client.post(
                    f"{base}/embeddings",
                    json={"model": node["model"], "input": "ping"},
                    headers=self._auth_header(node.get("api_key_enc")),
                )
            latency = int((time.monotonic() - t0) * 1000)
            if r.status_code != 200:
                return self._probe_fail(f"HTTP {r.status_code}", latency)
            data = r.json()
            embs = data.get("data") or []
            if not embs or not isinstance(embs[0].get("embedding"), list):
                return self._probe_fail("response has no data[].embedding", latency)
            dim = len(embs[0]["embedding"])
            want = int(node["dimensions"])
            if dim != want:
                return self._probe_fail(f"dim mismatch: endpoint={dim} node={want}", latency)
            return {"ok": True, "latency_ms": latency,
                    "summary": f"ok: model={node['model']} dim={dim} in {latency}ms"}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            latency = int((time.monotonic() - t0) * 1000)
            log.warning("llm embedding probe failed: %s -> %s: %s", node["name"], base, type(exc).__name__)
            return self._probe_fail(f"{type(exc).__name__}: {exc}", latency)

    async def _probe_reranker(self, node: dict) -> dict:
        base = (node.get("base_url") or "").rstrip("/")
        if not base:
            return self._probe_fail("base_url empty")
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_PROBE_TIMEOUT_SECONDS) as client:
                r = await client.post(
                    f"{base}/rerank",
                    json={"model": node["model"], "query": "ping", "documents": ["ping"]},
                    headers=self._auth_header(node.get("api_key_enc")),
                )
            latency = int((time.monotonic() - t0) * 1000)
            if r.status_code != 200:
                return self._probe_fail(f"HTTP {r.status_code}", latency)
            data = r.json()
            results = data.get("results") or []
            if not results or "relevance_score" not in results[0]:
                return self._probe_fail("response has no results[].relevance_score", latency)
            return {"ok": True, "latency_ms": latency,
                    "summary": f"ok: model={node['model']} reranked in {latency}ms"}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            latency = int((time.monotonic() - t0) * 1000)
            log.warning("llm reranker probe failed: %s -> %s: %s", node["name"], base, type(exc).__name__)
            return self._probe_fail(f"{type(exc).__name__}: {exc}", latency)

    async def probe_endpoint(self, session: AsyncSession, node_id: str) -> dict:
        node = await self.get_endpoint_internal(session, node_id)
        if node is None:
            raise HTTPException(404, f"endpoint not found: {node_id}")
        result = await self._probe_chat(node)
        await self._save_test(session, "llm_endpoints", node_id, result)
        return result

    async def probe_embedding(self, session: AsyncSession, node_id: str) -> dict:
        node = await self.get_embedding_internal(session, node_id)
        if node is None:
            raise HTTPException(404, f"embedding model not found: {node_id}")
        result = await self._probe_embedding(node)
        # embedding 表无 last_test_* 列（DB_DESIGN §3.2 未定义）→ 只返回，不落库
        return result

    async def probe_reranker(self, session: AsyncSession, node_id: str) -> dict:
        node = await self.get_reranker_internal(session, node_id)
        if node is None:
            raise HTTPException(404, f"reranker model not found: {node_id}")
        result = await self._probe_reranker(node)
        return result

    async def _save_test(self, session: AsyncSession, table: str, node_id: str, result: dict) -> None:
        await session.execute(
            text(f"UPDATE {table} SET last_test_at = now(), last_test_result = :r WHERE id = :id"),
            {"r": result["summary"], "id": node_id},
        )
        await session.commit()

    # ============================================================ 统一调用抽象（S04/S05/S07 复用）

    async def chat(
        self,
        session: AsyncSession,
        endpoint_id: str,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> dict:
        """统一 chat 推理入口（OpenAI 兼容 /chat/completions）。

        供 S07 SimpleAgentRuntime（tool-calling loop）与记忆提炼复用。
        返回 {content, tool_calls, usage}——tool_calls 为 OpenAI 原生
        [{id, type, function:{name, arguments(JSON str)}}, ...]；失败抛 HTTPException。
        """
        node = await self.get_endpoint_internal(session, endpoint_id)
        if node is None:
            raise HTTPException(404, f"endpoint not found: {endpoint_id}")
        if node.get("status") != "active":
            raise HTTPException(409, f"endpoint disabled: {node['name']}")
        base = (node.get("base_url") or "").rstrip("/")
        if not base:
            raise HTTPException(502, f"endpoint base_url empty: {node['name']}")
        body: dict[str, Any] = {
            "model": node["model"],
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.2,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if top_p is not None:
            body["top_p"] = top_p
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
        headers = self._auth_header(node.get("api_key_enc"), node.get("auth_scheme", "bearer"))
        timeout = float(node.get("timeout_seconds") or 120)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{base}/chat/completions", json=body, headers=headers)
        if r.status_code != 200:
            raise HTTPException(502, f"llm endpoint error: HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        if not data.get("choices"):
            raise HTTPException(502, "llm endpoint returned no choices")
        msg = data["choices"][0].get("message") or {}
        return {
            "content": msg.get("content"),
            "tool_calls": msg.get("tool_calls") or [],
            "usage": data.get("usage") or {},
            "finish_reason": data["choices"][0].get("finish_reason"),
        }

    async def embed_texts(self, session: AsyncSession, model_id: str, texts: list[str]) -> list[list[float]]:
        """统一 embedding 入口：provider=local → 本地确定性实现；provider=api → 端点调用。
        返回与 texts 等长的向量列表（维度=该模型 dimensions，D-C 建库快照同源）。"""
        node = await self.get_embedding_internal(session, model_id)
        if node is None:
            raise HTTPException(404, f"embedding model not found: {model_id}")
        if node.get("status") != "active":
            raise HTTPException(409, f"embedding model disabled: {node['name']}")
        if (node.get("provider") or "api") == "local":
            return local_fallback_embeddings(texts, int(node["dimensions"]))
        base = (node.get("base_url") or "").rstrip("/")
        batch = int(node.get("batch_size") or 32)
        out: list[list[float]] = []
        headers = self._auth_header(node.get("api_key_enc"))
        async with httpx.AsyncClient(timeout=settings.LLM_PROBE_TIMEOUT_SECONDS) as client:
            for i in range(0, len(texts), batch):
                chunk = texts[i : i + batch]
                r = await client.post(
                    f"{base}/embeddings", json={"model": node["model"], "input": chunk}, headers=headers
                )
                if r.status_code != 200:
                    raise HTTPException(502, f"embedding endpoint error: HTTP {r.status_code}")
                data = r.json()
                chunk_vecs = [d["embedding"] for d in sorted(data["data"], key=lambda x: x.get("index", 0))]
                if len(chunk_vecs) != len(chunk):
                    raise HTTPException(502, "embedding endpoint returned mismatched count")
                out.extend(chunk_vecs)
        return out

    async def rerank(
        self, session: AsyncSession, model_id: str, query: str, documents: list[str], top_n: int | None = None
    ) -> list[dict]:
        """统一 rerank 入口（Jina 兼容 /rerank 契约）。返回 [{index, score}]（按分降序）。"""
        node = await self.get_reranker_internal(session, model_id)
        if node is None:
            raise HTTPException(404, f"reranker model not found: {model_id}")
        if node.get("status") != "active":
            raise HTTPException(409, f"reranker model disabled: {node['name']}")
        docs = documents[: int(node.get("max_candidates") or 100)]
        base = (node.get("base_url") or "").rstrip("/")
        async with httpx.AsyncClient(timeout=settings.LLM_PROBE_TIMEOUT_SECONDS) as client:
            r = await client.post(
                f"{base}/rerank",
                json={"model": node["model"], "query": query, "documents": docs},
                headers=self._auth_header(node.get("api_key_enc")),
            )
        if r.status_code != 200:
            raise HTTPException(502, f"reranker endpoint error: HTTP {r.status_code}")
        data = r.json()
        results = [
            {"index": int(x["index"]), "score": float(x.get("relevance_score", 0.0))}
            for x in data.get("results", [])
        ]
        results.sort(key=lambda x: x["score"], reverse=True)
        if top_n:
            results = results[:top_n]
        return results

    # ============================================================ 启动种子（端点配置化 + 本地 fallback 注册）

    async def ensure_default_nodes(self, session: AsyncSession) -> None:
        """幂等种子（startup 调用，CRUD 后仍即时生效——本方法只在缺失时补）：
        1. 本地 fallback embedding 节点（始终注册，真实端点不可用时闭环）。
        2. .env 默认 chat 端点（LLM_FALLBACK_ENDPOINT 非空时注册）。
        """
        # 1) 本地 fallback embedding
        r = await session.execute(
            text("SELECT id FROM llm_embedding_models WHERE name = :n"),
            {"n": "local-fallback-embedding"},
        )
        if r.first() is None:
            nid = _new_id()
            await session.execute(
                text(
                    "INSERT INTO llm_embedding_models (id, name, provider, base_url, model, dimensions,"
                    " batch_size, status)"
                    " VALUES (:id, :n, 'local', 'local://fallback', :m, :d, 32, 'active')"
                ),
                {
                    "id": nid, "n": "local-fallback-embedding",
                    "m": f"hash-ngram-{settings.LLM_LOCAL_FALLBACK_NGRAM}",
                    "d": settings.LLM_LOCAL_FALLBACK_DIM,
                },
            )
            await session.commit()
            log.info("local fallback embedding node registered (dim=%s)", settings.LLM_LOCAL_FALLBACK_DIM)
        # 2) 默认 chat 端点（.env 配置化）
        if settings.LLM_FALLBACK_ENDPOINT:
            r = await session.execute(
                text("SELECT id FROM llm_endpoints WHERE name = :n"),
                {"n": settings.LLM_FALLBACK_NAME},
            )
            if r.first() is None:
                nid = _new_id()
                api_key_enc = encrypt_secret(settings.LLM_FALLBACK_API_KEY) if settings.LLM_FALLBACK_API_KEY else None
                await session.execute(
                    text(
                        "INSERT INTO llm_endpoints (id, name, base_url, model, api_key_enc, auth_scheme,"
                        " default_params, status)"
                        " VALUES (:id, :n, :bu, :m, :k, 'bearer', '{}', 'active')"
                    ),
                    {
                        "id": nid, "n": settings.LLM_FALLBACK_NAME,
                        "bu": settings.LLM_FALLBACK_ENDPOINT,
                        "m": settings.LLM_FALLBACK_MODEL or "unknown",
                        "k": api_key_enc,
                    },
                )
                await session.commit()
                log.info("default chat endpoint seeded from .env: %s (%s)",
                         settings.LLM_FALLBACK_NAME, settings.LLM_FALLBACK_ENDPOINT)


# 进程级单例（无状态；每次调用读库取最新节点 → CRUD 即时生效）
_service: LLMNodeService | None = None


def get_llm_service() -> LLMNodeService:
    global _service
    if _service is None:
        _service = LLMNodeService()
    return _service
