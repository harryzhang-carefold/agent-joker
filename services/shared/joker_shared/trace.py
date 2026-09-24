"""TraceService（S09，TRACE-01/02，D-D / DECISION-025，DECISION-012）。

统一 trace 写入/检索接口 + 保留策略定期清理 + 全量 payload 脱敏。

写点（ARCH §4.4 / DB_DESIGN §9.2）——全链路事件：
  - SAR（S07）：message（交互/token 用量）/ tool_call / rag / file；
  - BFF（S08）：拦截 tool_call（统一 ToolInterceptor 动作链）；
  - 本卡补：system 会话开始/结束事件（会话生命周期 marker）；
  - request / 鉴权 事件 → 走 api_audit_logs（BASE-06 接口操作日志，S01/S08 已写），
    不进 trace_events（trace_events.session_id NOT NULL，请求发生在会话建立之前）。

检索（TRACE-02）：按 会话 / agent / 用户 / 事件类型 / 时间范围 / 关键词（payload_tsv）。
保留（D-D / DECISION-025）：月分区 + 定期任务按 TRACE_RETENTION_DAYS /
  AUDIT_RETENTION_DAYS DROP 过期分区（参数化，默认 90，非硬编码）。
脱敏（DECISION-012）：所有 trace_events payload 经 redact_obj（复用 audit 单一源）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared.audit import drop_expired_partitions, redact_obj
from joker_shared.config import settings
from joker_shared.db import get_session_factory
from joker_shared.timeutil import parse_iso8601

log = logging.getLogger("joker.trace")


def _parse_time(value: str | None, field: str):
    """BUG-03 修复：start/end ISO8601（含 Z/offset）→ aware datetime。无效 → 400。"""
    if not value:
        return None
    try:
        return parse_iso8601(value)
    except ValueError:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=f"invalid {field} (ISO8601)")

# ============================================================ 写点（统一）


async def _insert_event(
    session: AsyncSession,
    tenant_id: str,
    trace_session_id: str,
    user_id: str | None,
    event_type: str,
    payload: dict,
    *,
    tool_name: str | None = None,
    tool_server_id: str | None = None,
    rag_kb_id: str | None = None,
    file_id: str | None = None,
    message_id: str | None = None,
    token_usage: dict | None = None,
    status: str = "ok",
    latency_ms: int | None = None,
) -> None:
    """单条事件写入（脱敏 + 冗余计数）。不 commit（由调用方控制事务）。"""
    seq = (
        await session.execute(
            text("SELECT COALESCE(MAX(seq), 0) + 1 FROM trace_events WHERE session_id = CAST(:s AS uuid)"),
            {"s": trace_session_id},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO trace_events (id, tenant_id, session_id, event_type, seq, payload, "
            "tool_name, tool_server_id, rag_kb_id, file_id, message_id, token_usage, status, "
            "latency_ms, created_by) "
            "VALUES (gen_random_uuid(), CAST(:t AS uuid), CAST(:s AS uuid), :et, :seq, "
            "CAST(:p AS jsonb), :tn, CAST(:ts AS uuid), CAST(:kb AS uuid), CAST(:f AS uuid), "
            "CAST(:m AS uuid), CAST(:tu AS jsonb), :st, :lat, CAST(:u AS uuid))"
        ),
        {
            "t": tenant_id, "s": trace_session_id, "et": event_type, "seq": seq,
            "p": json.dumps(redact_obj(payload), ensure_ascii=False, default=str),
            "tn": tool_name, "ts": tool_server_id, "kb": rag_kb_id, "f": file_id,
            "m": message_id,
            "tu": json.dumps(token_usage) if token_usage else None,
            "st": status, "lat": latency_ms, "u": user_id,
        },
    )
    await session.execute(
        text(
            "UPDATE trace_sessions SET event_count = event_count + 1, "
            "total_tokens = total_tokens + :tk, "
            "tool_call_count = tool_call_count + :tc, "
            "rag_call_count = rag_call_count + :rc, "
            "file_event_count = file_event_count + :fc "
            "WHERE id = CAST(:s AS uuid)"
        ),
        {
            "s": trace_session_id,
            "tk": (token_usage or {}).get("total_tokens", 0) if token_usage else 0,
            "tc": 1 if event_type == "tool_call" else 0,
            "rc": 1 if event_type == "rag" else 0,
            "fc": 1 if event_type == "file" else 0,
        },
    )


async def write_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    trace_session_id: str | None,
    user_id: str | None,
    event_type: str,
    payload: dict,
    **kw: Any,
) -> None:
    """统一事件写入入口（TRACE-01）。写失败不阻断主流程。"""
    if trace_session_id is None:
        return
    try:
        await _insert_event(
            session, tenant_id, trace_session_id, user_id, event_type, payload, **kw
        )
        await session.commit()
    except Exception:  # noqa: BLE001 — 与审计/工具调用同容错策略
        log.exception("write_event failed (type=%s)", event_type)


async def write_system_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    trace_session_id: str | None,
    user_id: str | None,
    kind: str,
    detail: str | None = None,
) -> None:
    """system 事件（会话 start/end/error）。"""
    await write_event(
        session,
        tenant_id=tenant_id,
        trace_session_id=trace_session_id,
        user_id=user_id,
        event_type="system",
        payload={"kind": kind, "detail": detail},
    )


async def ensure_trace_session(
    session: AsyncSession,
    tenant_id: str,
    agent_id: str | None,
    user_id: str | None,
    *,
    title: str = "agent-chat",
) -> str | None:
    """取/建 trace_sessions（canonical；S07 SAR / S08 BFF / RAG 各写点共用）。

    agent_id 可空 → 回退该租户首个 active agent；user_id 可空 → 回退租户首个
    active 用户（机器凭证代执行）。无可用 agent/user → None（不阻断主流程）。
    首次建 trace_sessions 时写一条 system start 事件（会话生命周期起点）。
    """
    try:
        if not agent_id:
            r = await session.execute(
                text(
                    "SELECT id FROM agents WHERE tenant_id = CAST(:t AS uuid) "
                    "AND status = 'active' AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
                ),
                {"t": tenant_id},
            )
            arow = r.first()
            if arow is None:
                return None
            agent_id = str(arow[0])
        if not user_id:
            r = await session.execute(
                text(
                    "SELECT id FROM users WHERE tenant_id = CAST(:t AS uuid) "
                    "AND status = 'active' AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
                ),
                {"t": tenant_id},
            )
            urow = r.first()
            if urow is None:
                return None
            user_id = str(urow[0])

        r = await session.execute(
            text(
                "SELECT id FROM agent_sessions WHERE tenant_id = CAST(:t AS uuid) "
                "AND agent_id = CAST(:a AS uuid) AND user_id = CAST(:u AS uuid) "
                "AND status = 'active' AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 1"
            ),
            {"t": tenant_id, "a": agent_id, "u": user_id},
        )
        agent_sess = r.first()
        if agent_sess is None:
            sid = str(uuid.uuid4())
            await session.execute(
                text(
                    "INSERT INTO agent_sessions (id, tenant_id, agent_id, user_id, title, status) "
                    "VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:a AS uuid), CAST(:u AS uuid), "
                    ":ti, 'active')"
                ),
                {"id": sid, "t": tenant_id, "a": agent_id, "u": user_id, "ti": title},
            )
            await session.commit()
            agent_sess = (sid,)
        tr = await session.execute(
            text("SELECT id FROM trace_sessions WHERE session_id = CAST(:s AS uuid)"),
            {"s": str(agent_sess[0])},
        )
        row = tr.first()
        if row is not None:
            return str(row[0])
        tsid = str(uuid.uuid4())
        await session.execute(
            text(
                "INSERT INTO trace_sessions (id, tenant_id, session_id, agent_id, user_id, "
                "started_at, status) VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:s AS uuid), "
                "CAST(:a AS uuid), CAST(:u AS uuid), now(), 'active')"
            ),
            {"id": tsid, "t": tenant_id, "s": str(agent_sess[0]), "a": agent_id, "u": user_id},
        )
        # system start 事件（会话生命周期起点；与首条 message 事件共同构成完整链首）
        await _insert_event(session, tenant_id, tsid, user_id, "system", {"kind": "start"})
        await session.commit()
        return tsid
    except Exception:  # noqa: BLE001
        log.exception("ensure_trace_session failed (agent=%s); continue without trace", agent_id)
        return None


# ============================================================ 检索（TRACE-02）


def _sess_dict(r: tuple) -> dict:
    return {
        "id": str(r[0]) if r[0] else None,
        "session_id": str(r[1]) if r[1] else None,
        "agent_id": str(r[2]) if r[2] else None,
        "user_id": str(r[3]) if r[3] else None,
        "started_at": r[4].isoformat() if r[4] else None,
        "ended_at": r[5].isoformat() if r[5] else None,
        "event_count": r[6],
        "tool_call_count": r[7],
        "rag_call_count": r[8],
        "file_event_count": r[9],
        "total_tokens": r[10],
        "status": r[11],
    }


async def list_sessions(
    session: AsyncSession,
    tenant_id: str,
    *,
    agent_id: str | None = None,
    user_id: str | None = None,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """trace 会话列表（按 agent/用户/状态/时间，租户强制过滤，TRACE-02 验收 3）。"""
    where = ["tenant_id = CAST(:t AS uuid)"]
    p: dict = {"t": tenant_id, "ps": page_size, "off": (page - 1) * page_size}
    if agent_id:
        where.append("agent_id = CAST(:a AS uuid)"); p["a"] = agent_id
    if user_id:
        where.append("user_id = CAST(:u AS uuid)"); p["u"] = user_id
    if status:
        where.append("status = :st"); p["st"] = status
    if start:
        p["start"] = _parse_time(start, "start")
        where.append("started_at >= :start")
    if end:
        p["end"] = _parse_time(end, "end")
        where.append("started_at <= :end")
    w = " AND ".join(where)
    total = (
        await session.execute(
            text(f"SELECT count(*) FROM trace_sessions WHERE {w}"), p
        )
    ).scalar()
    rows = await session.execute(
        text(
            "SELECT id, session_id, agent_id, user_id, started_at, ended_at, event_count, "
            "tool_call_count, rag_call_count, file_event_count, total_tokens, status "
            f"FROM trace_sessions WHERE {w} ORDER BY started_at DESC LIMIT :ps OFFSET :off"
        ),
        p,
    )
    return {
        "items": [_sess_dict(r) for r in rows.fetchall()],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_session_row(session: AsyncSession, session_id: str) -> dict | None:
    """按 trace_sessions.id 取行（**不过滤 tenant**，供调用方做跨租户 403 判定）。"""
    r = await session.execute(
        text(
            "SELECT id, session_id, agent_id, user_id, started_at, ended_at, event_count, "
            "tool_call_count, rag_call_count, file_event_count, total_tokens, status "
            "FROM trace_sessions WHERE id = CAST(:s AS uuid)"
        ),
        {"s": session_id},
    )
    row = r.first()
    return _sess_dict(row) if row else None


async def list_events(
    session: AsyncSession,
    tenant_id: str,
    *,
    session_id: str | None = None,
    agent_id: str | None = None,
    event_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict:
    """事件明细检索（会话时间线 / agent / 事件类型 / 时间范围 / 关键词，TRACE-02 验收 1/2）。

    关键词走 payload_tsv（tsvector 生成列 + GIN，simple 分词，闭环够用）。
    """
    where = ["te.tenant_id = CAST(:t AS uuid)"]
    p: dict = {"t": tenant_id, "ps": page_size, "off": (page - 1) * page_size}
    joins = ""
    if session_id:
        where.append("te.session_id = CAST(:s AS uuid)"); p["s"] = session_id
    if agent_id:
        joins += " JOIN trace_sessions ts ON ts.id = te.session_id"
        where.append("ts.agent_id = CAST(:a AS uuid)"); p["a"] = agent_id
    if event_type:
        where.append("te.event_type = :et"); p["et"] = event_type
    if start:
        p["start"] = _parse_time(start, "start")
        where.append("te.created_at >= :start")
    if end:
        p["end"] = _parse_time(end, "end")
        where.append("te.created_at <= :end")
    if keyword:
        where.append("te.payload_tsv @@ plainto_tsquery('simple', :kw)"); p["kw"] = keyword
    w = " AND ".join(where)
    total = (
        await session.execute(
            text(f"SELECT count(*) FROM trace_events te {joins} WHERE {w}"), p
        )
    ).scalar()
    rows = await session.execute(
        text(
            "SELECT te.id, te.session_id, te.event_type, te.seq, te.payload, te.tool_name, "
            "te.rag_kb_id, te.file_id, te.message_id, te.token_usage, te.status, te.latency_ms, "
            f"te.created_at FROM trace_events te {joins} WHERE {w} "
            "ORDER BY te.created_at, te.seq LIMIT :ps OFFSET :off"
        ),
        p,
    )
    items = [
        {
            "id": str(r[0]) if r[0] else None,
            "session_id": str(r[1]) if r[1] else None,
            "event_type": r[2],
            "seq": r[3],
            "payload": r[4],
            "tool_name": r[5],
            "rag_kb_id": str(r[6]) if r[6] else None,
            "file_id": str(r[7]) if r[7] else None,
            "message_id": str(r[8]) if r[8] else None,
            "token_usage": r[9],
            "status": r[10],
            "latency_ms": r[11],
            "created_at": r[12].isoformat() if r[12] else None,
        }
        for r in rows.fetchall()
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ============================================================ 保留策略（D-D / DECISION-025）


async def ensure_partitions() -> None:
    """幂等保证当前月 ±1 的月分区存在（trace_events + api_audit_logs）。"""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SELECT ensure_monthly_partitions('trace_events', 3)"))
        await session.execute(text("SELECT ensure_monthly_partitions('api_audit_logs', 3)"))
        await session.commit()


async def run_maintenance() -> dict:
    """定期任务入口：按配置保留天数 DROP 过期月分区（trace_events + api_audit_logs）。

    保留天数 = settings.TRACE_RETENTION_DAYS / AUDIT_RETENTION_DAYS（.env 可配，默认 90），
    非硬编码；每次调用读当前配置（改 .env 重启后即时按新天数清理）。
    """
    trace_dropped = await drop_expired_partitions("trace_events", settings.TRACE_RETENTION_DAYS)
    audit_dropped = await drop_expired_partitions("api_audit_logs", settings.AUDIT_RETENTION_DAYS)
    log.info(
        "retention maintenance: trace_dropped=%s audit_dropped=%s "
        "(retention trace=%sd audit=%sd)",
        trace_dropped, audit_dropped,
        settings.TRACE_RETENTION_DAYS, settings.AUDIT_RETENTION_DAYS,
    )
    return {
        "trace_dropped": trace_dropped,
        "audit_dropped": audit_dropped,
        "trace_retention_days": settings.TRACE_RETENTION_DAYS,
        "audit_retention_days": settings.AUDIT_RETENTION_DAYS,
    }


async def retention_loop() -> None:
    """后台定期清理（启动立即一次，之后每 RETENTION_CHECK_INTERVAL_HOURS 一次）。"""
    while True:
        try:
            await ensure_partitions()
            await run_maintenance()
        except Exception:  # noqa: BLE001 — 清理失败不崩，下一周期重试
            log.exception("retention loop iteration failed")
        await asyncio.sleep(settings.RETENTION_CHECK_INTERVAL_HOURS * 3600)


# ============================================================ 自测（S09 验收）


async def selftest_retention() -> dict:
    """证明保留天数参数化驱动分区 DROP（隔离测试表，不碰真实数据）：
    retention=90 仅 DROP 2020_01（保 2026_07/2026_09）→ 改 retention=30 再 DROP 2026_07（保 2026_09）。
    返回各步 parts + assert 布尔。真实表过期分区 DROP 由 run_maintenance() 覆盖。
    """
    factory = get_session_factory()
    out: dict = {}

    async def _parts(table: str) -> list[str]:
        async with factory() as s:
            r = await s.execute(
                text(
                    "SELECT c.relname FROM pg_class c "
                    "JOIN pg_inherits i ON i.inhrelid = c.oid "
                    "JOIN pg_class p ON p.oid = i.inhparent "
                    "WHERE p.relname = :tbl ORDER BY 1"
                ),
                {"tbl": table},
            )
            return sorted(x[0] for x in r.fetchall())

    async with factory() as s:
        await s.execute(text("DROP TABLE IF EXISTS trace_events_test CASCADE"))
        await s.execute(
            text("CREATE TABLE trace_events_test (created_at timestamptz NOT NULL, val text) "
                 "PARTITION BY RANGE (created_at)")
        )
        for nm, frm, to in (
            ("2020_01", "2020-01-01", "2020-02-01"),
            ("2026_07", "2026-07-01", "2026-08-01"),
            ("2026_09", "2026-09-01", "2026-10-01"),
        ):
            await s.execute(
                text(f"CREATE TABLE trace_events_test_{nm} PARTITION OF trace_events_test "
                     f"FOR VALUES FROM ('{frm}') TO ('{to}')")
            )
        await s.execute(
            text("INSERT INTO trace_events_test (created_at, val) VALUES "
                 "('2020-01-05','a'),('2026-07-10','b'),('2026-09-10','c')")
        )
        await s.commit()

    out["test_table_parts_initial"] = await _parts("trace_events_test")
    out["drop_90"] = await drop_expired_partitions("trace_events_test", 90)
    out["parts_after_90"] = await _parts("trace_events_test")
    out["drop_30"] = await drop_expired_partitions("trace_events_test", 30)
    out["parts_after_30"] = await _parts("trace_events_test")
    out["assert_90_dropped_2020_01"] = "trace_events_test_2020_01" not in out["parts_after_90"]
    out["assert_90_kept_2026_07"] = "trace_events_test_2026_07" in out["parts_after_90"]
    out["assert_30_dropped_2026_07"] = "trace_events_test_2026_07" not in out["parts_after_30"]
    out["assert_30_kept_2026_09"] = "trace_events_test_2026_09" in out["parts_after_30"]
    async with factory() as s:
        await s.execute(text("DROP TABLE IF EXISTS trace_events_test CASCADE"))
        await s.commit()
    return out


async def selftest_real_drop() -> dict:
    """真实 trace_events 表：建 2020_01 过期分区 → run_maintenance 按当前配置 DROP。
    返回 maintenance 结果 + 前后 parts + assert。"""
    factory = get_session_factory()
    out: dict = {}

    async def _parts() -> list[str]:
        async with factory() as s:
            r = await s.execute(
                text("SELECT c.relname FROM pg_class c JOIN pg_inherits i ON i.inhrelid = c.oid "
                     "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'trace_events' ORDER BY 1")
            )
            return sorted(x[0] for x in r.fetchall())

    async with factory() as s:
        await s.execute(
            text("CREATE TABLE IF NOT EXISTS trace_events_2020_01 PARTITION OF trace_events "
                 "FOR VALUES FROM ('2020-01-01') TO ('2020-02-01')")
        )
        await s.commit()
    out["real_parts_before"] = await _parts()
    out["maintenance"] = await run_maintenance()
    out["real_parts_after"] = await _parts()
    out["assert_real_2020_01_dropped"] = "trace_events_2020_01" not in out["real_parts_after"]
    out["assert_real_current_month_kept"] = any(
        "trace_events_2026_09" in pn for pn in out["real_parts_after"]
    )
    return out
