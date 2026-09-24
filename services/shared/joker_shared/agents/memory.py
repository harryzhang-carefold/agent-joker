"""三层记忆（AGENT-07/08，DECISION-019）。

- 短期（Redis，会话内）：key `joker:mem:short:<tenant>:<agent>:<session>`，
  存最近 N 轮 {role, content} 对话（TTL 会话活跃期，默认 30min 续期）。
  Redis 不可用 → 退化为单轮（不崩溃，AGENT-07 验收 3）。
- 长期（PG agent_memories，跨会话）：结构化记忆（fact/preference/summary/entity），
  会话结束由 LLM 提炼；新会话构建 prompt 时检索注入 top N（AGENT-07 验收 2）。
- 沉淀（Obsidian vault 目录 + Markdown 笔记 + PG agent_obsidian_notes 索引）：
  同一沉淀事件一次生成长期记忆 + obsidian 笔记（DECISION-019 双写不同源）。

设计要点：
- 短期记忆只存「本会话最近对话」，注入 prompt 供上下文连贯（AGENT-07 验收 1）。
- 长期记忆用户级（user_id 非空）+ agent 级（user_id NULL）；检索按 (tenant, agent, user)。
- 沉淀触发：会话关闭（status→closed）或每 N 轮（本卡=关闭时提炼，简单可验证）。
- LLM 提炼/注入走 agent 绑定的 LLM endpoint（复用 LLMNodeService 的 chat 调用）。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import redis_client
from joker_shared.config import settings

log = logging.getLogger("joker.memory")

DEFAULT_SHORT_TTL = 1800  # 30min（会话活跃期续期）
DEFAULT_SHORT_ROUNDS = 20  # 保留最近 N 轮（每轮=user+assistant 两条）
DEFAULT_LONG_TOP_N = 10  # 注入 top N（DB_DESIGN §7.5【推测】）
DEFAULT_SETTLE_N = 8  # 每 N 轮沉淀一次（关闭时兜底）


def _new_id() -> str:
    return str(uuid.uuid4())


def short_key(tenant_id: str, agent_id: str, session_id: str) -> str:
    return f"joker:mem:short:{tenant_id}:{agent_id}:{session_id}"


# ============================================================ 短期记忆（Redis）


class ShortTermMemory:
    """Redis 会话内短期记忆。Redis 不可用 → 单轮降级（不抛）。"""

    async def get_context(self, tenant_id: str, agent_id: str, session_id: str) -> list[dict]:
        """取最近 N 轮对话（[{role, content}]）；Redis 故障 → []（退化为单轮）。"""
        try:
            raw = await redis_client.get_redis().get(short_key(tenant_id, agent_id, session_id))
        except Exception as exc:
            log.warning("short-term memory read failed (%s); degrade to single-turn", exc)
            return []
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except ValueError:
            return []
        if not isinstance(data, list):
            return []
        return data[-DEFAULT_SHORT_ROUNDS * 2:]

    async def append(self, tenant_id: str, agent_id: str, session_id: str, role: str, content: str) -> bool:
        """追加一条对话（续期 TTL）。Redis 故障 → False（不阻断主流程）。"""
        try:
            k = short_key(tenant_id, agent_id, session_id)
            raw = await redis_client.get_redis().get(k)
            data = json.loads(raw) if raw else []
            if not isinstance(data, list):
                data = []
            data.append({"role": role, "content": content})
            data = data[-DEFAULT_SHORT_ROUNDS * 2:]
            await redis_client.get_redis().setex(k, DEFAULT_SHORT_TTL, json.dumps(data, ensure_ascii=False))
            return True
        except Exception as exc:
            log.warning("short-term memory write failed (%s); degrade to single-turn", exc)
            return False

    async def clear(self, tenant_id: str, agent_id: str, session_id: str) -> None:
        try:
            await redis_client.get_redis().delete(short_key(tenant_id, agent_id, session_id))
        except Exception as exc:
            log.warning("short-term memory clear failed: %s", exc)


# ============================================================ 长期记忆（PG）


async def get_long_term_memories(
    session: AsyncSession, tenant_id: str, agent_id: str, user_id: str, top_n: int = DEFAULT_LONG_TOP_N
) -> list[dict]:
    """检索注入用长期记忆（用户级 + agent 级；按 importance 降序 + 最近访问）。"""
    r = await session.execute(
        text(
            """SELECT id, memory_type, content, importance, access_count, last_accessed_at,
                      source_session_id, created_at
               FROM agent_memories
               WHERE tenant_id = CAST(:t AS uuid) AND agent_id = CAST(:a AS uuid)
                 AND status = 'active' AND (user_id = CAST(:u AS uuid) OR user_id IS NULL)
               ORDER BY importance DESC, last_accessed_at DESC NULLS LAST, created_at DESC
               LIMIT :n"""
        ),
        {"t": tenant_id, "a": agent_id, "u": user_id, "n": top_n},
    )
    out = []
    for row in r.fetchall():
        d = dict(row._mapping)
        for k in ("id", "source_session_id"):
            if d.get(k) is not None:
                d[k] = str(d[k])
        for k in ("last_accessed_at", "created_at"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat()
        d["importance"] = float(d["importance"])
        out.append(d)
    return out


async def touch_memories(session: AsyncSession, ids: list[str]) -> None:
    """注入后计数（access_count+1 / last_accessed_at=now）。"""
    if not ids:
        return
    try:
        await session.execute(
            text(
                "UPDATE agent_memories SET access_count = access_count + 1, last_accessed_at = now() "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": [uuid.UUID(x) for x in ids]},
        )
        await session.commit()
    except Exception as exc:
        log.warning("touch memories failed: %s", exc)


async def store_memory(
    session: AsyncSession,
    *,
    tenant_id: str,
    agent_id: str,
    user_id: str | None,
    memory_type: str,
    content: str,
    source_session_id: str | None,
    importance: float = 5.0,
) -> str | None:
    """写入一条长期记忆（content 去重：同 agent+user+type+content 不重复）。"""
    content = (content or "").strip()
    if not content:
        return None
    dup = await session.execute(
        text(
            "SELECT id FROM agent_memories WHERE tenant_id = CAST(:t AS uuid) "
            "AND agent_id = CAST(:a AS uuid) AND (user_id = CAST(:u AS uuid) OR (user_id IS NULL AND :u IS NULL)) "
            "AND memory_type = :mt AND content = :c AND status = 'active' LIMIT 1"
        ),
        {"t": tenant_id, "a": agent_id, "u": user_id, "mt": memory_type, "c": content},
    )
    if dup.first() is not None:
        return None
    mid = _new_id()
    await session.execute(
        text(
            """INSERT INTO agent_memories (id, tenant_id, agent_id, user_id, memory_type, content,
                 source_session_id, importance, status)
               VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:a AS uuid), CAST(:u AS uuid),
                       :mt, :c, CAST(:ss AS uuid), :imp, 'active')"""
        ),
        {"id": mid, "t": tenant_id, "a": agent_id, "u": user_id, "mt": memory_type,
         "c": content, "ss": source_session_id, "imp": max(1.0, min(9.9, float(importance)))},
    )
    await session.commit()
    return mid


# ============================================================ Obsidian 沉淀（DECISION-019）


def _slugify(title: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (title or "").strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:60] or "note"


def vault_note_path(tenant_code: str, agent_name: str, when: str) -> str:
    """vault/<tenant_code>/<agent_name>/<yyyy-mm>/<slug>.md（DB_DESIGN §12 / DECISION-019）。"""
    ym = when[:7]  # yyyy-mm
    return f"{tenant_code}/{agent_name}/{ym}"


async def write_obsidian_note(
    session: AsyncSession,
    *,
    tenant_id: str,
    tenant_code: str,
    agent_id: str,
    agent_name: str,
    user_id: str | None,
    title: str,
    summary: str,
    body: str,
    tags: list[str],
    source_session_id: str | None,
    now_iso: str,
) -> dict:
    """写 vault markdown 笔记 + PG agent_obsidian_notes 索引（DECISION-019 双写）。

    同一沉淀事件一次生成长期记忆 + 本笔记（不同源：笔记=长篇 markdown，记忆=结构化条目）。
    """
    now_iso = now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ym = now_iso[:7]
    slug = f"{_slugify(title)}-{now_iso[11:16].replace(':', '')}-{uuid.uuid4().hex[:6]}"
    rel_dir = f"{tenant_code}/{agent_name}/{ym}"
    rel_path = f"{rel_dir}/{slug}.md"
    front = {
        "title": title,
        "agent": agent_name,
        "tenant": tenant_code,
        "session": source_session_id,
        "created": now_iso,
        "tags": tags,
    }
    fm = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}" for k, v in front.items())
    md = f"---\n{fm}\n---\n\n# {title}\n\n> {summary}\n\n{body}\n"

    vault_root = Path(settings.OBSIDIAN_VAULT_PATH)
    fpath = vault_root / rel_path
    try:
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(md, encoding="utf-8")
    except Exception as exc:
        log.exception("obsidian note write failed (path=%s); index row still recorded", rel_path)
        # 文件写失败也记录索引（路径保留，文件可补）——不阻断主流程

    nid = _new_id()
    await session.execute(
        text(
            """INSERT INTO agent_obsidian_notes (id, tenant_id, agent_id, user_id, file_path, title,
                 summary, tags, source_session_id)
               VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:a AS uuid), CAST(:u AS uuid),
                       :p, :ti, :s, CAST(:tags AS jsonb), CAST(:ss AS uuid))"""
        ),
        {"id": nid, "t": tenant_id, "a": agent_id, "u": user_id, "p": rel_path,
         "ti": title, "s": summary, "tags": json.dumps(tags, ensure_ascii=False),
         "ss": source_session_id},
    )
    await session.commit()
    return {"id": nid, "file_path": rel_path, "abs_path": str(fpath), "written": fpath.exists()}


async def list_obsidian_notes(
    session: AsyncSession, agent_id: str, tenant_id: str, limit: int = 20
) -> list[dict]:
    """按 tag/agent 查沉淀笔记（AGENT-08 验收 3：后续对话引用）。"""
    r = await session.execute(
        text(
            "SELECT id, file_path, title, summary, tags, source_session_id, created_at "
            "FROM agent_obsidian_notes WHERE agent_id = CAST(:a AS uuid) "
            "AND tenant_id = CAST(:t AS uuid) ORDER BY created_at DESC LIMIT :n"
        ),
        {"a": agent_id, "t": tenant_id, "n": limit},
    )
    out = []
    for row in r.fetchall():
        d = dict(row._mapping)
        for k in ("id", "source_session_id"):
            if d.get(k) is not None:
                d[k] = str(d[k])
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except ValueError:
                d["tags"] = []
        if d.get("created_at") is not None:
            d["created_at"] = d["created_at"].isoformat()
        # 附文件内容（vault 内读取）
        content = None
        try:
            fp = Path(settings.OBSIDIAN_VAULT_PATH) / d["file_path"]
            if fp.exists():
                content = fp.read_text(encoding="utf-8")[:2000]
        except Exception:
            content = None
        d["content"] = content
        out.append(d)
    return out
