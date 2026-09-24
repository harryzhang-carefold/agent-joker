"""AuditLogService（BASE-06）：接口操作日志异步写入。

- 月分区表 api_audit_logs（保留天数 AUDIT_RETENTION_DAYS 可配置，D-D / DECISION-025）；
- 写失败不阻断主流程（BASE-06 验收 4）；
- 敏感字段脱敏：password/token/Authorization 等 → ***（BASE-06 验收 3）。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from joker_shared.config import settings
from joker_shared.db import get_session_factory

log = logging.getLogger("joker.audit")

_SENSITIVE_KEYS = re.compile(
    r"(password|token|secret|authorization|api_key|api-key|apikey|credential|access_key|secret_key|private_key)",
    re.I,
)
_MAX_BODY = 2048  # 截断 2KB（DB_DESIGN §1.8）
# 月分区名：init_schema.sql ensure_monthly_partitions 用 to_char 'YYYY_MM'
#   → 真实名如 trace_events_2026_09 / api_audit_logs_2026_09（<table>_YYYY_MM）。
# 兼容旧格式 <table>_YYYYMM（两种都识别，避免旧分区无法被清理）。
# group(2)=YY, group(3)=MM(下划线式), group(4)=MM(紧凑式)
_PART_NAME = re.compile(r"^(.+)_20(\d{2})(?:_(\d{2})|(\d{2}))$")


def redact_obj(obj: Any) -> Any:
    """递归脱敏 dict/list（敏感 key 的 value 替换为 ***）。"""
    if isinstance(obj, dict):
        return {k: ("***" if _SENSITIVE_KEYS.search(str(k)) else redact_obj(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj


def body_digest(body: Any) -> str | None:
    if body is None:
        return None
    try:
        s = body if isinstance(body, str) else json.dumps(redact_obj(body), ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(redact_obj(body))
    return s[:_MAX_BODY]


async def write_audit(
    *,
    tenant_id: str | None,
    user_id: str | None,
    method: str,
    path: str,
    status_code: int,
    latency_ms: int,
    client_ip: str | None = None,
    query: dict[str, Any] | None = None,
    body: Any = None,
) -> None:
    """写一条接口操作日志。失败只记日志、不抛出（BASE-06 验收 4）。"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO api_audit_logs
                      (id, tenant_id, user_id, method, path, query_digest,
                       request_digest, status_code, latency_ms, client_ip)
                    VALUES (:id, :t, :u, :m, :p, :q, :b, :s, :l, :ip)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "t": tenant_id,
                    "u": user_id,
                    "m": method,
                    "p": path,
                    "q": json.dumps(redact_obj(query), ensure_ascii=False) if query else None,
                    "b": body_digest(body),
                    "s": status_code,
                    "l": latency_ms,
                    "ip": client_ip,
                },
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — 审计写失败不阻断主流程
        log.exception("audit write failed (non-blocking) path=%s", path)


async def drop_expired_partitions(table: str = "api_audit_logs", retention_days: int = 90) -> int:
    """按保留天数 DROP 过期月分区（定期任务入口；S08 切片挂定时器）。

    分区名 <table>_YYYYMM；整月粒度——分区起始月 < (now - retention_days) 才 DROP，
    保守保证保留期内的数据完整。返回被 DROP 的分区数。
    """
    factory = get_session_factory()
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    async with factory() as session:
        rows = await session.execute(
            text(
                """
                SELECT c.relname FROM pg_class c
                JOIN pg_inherits i ON i.inhrelid = c.oid
                JOIN pg_class p ON p.oid = i.inhparent
                WHERE p.relname = :parent AND c.relispartition
                """
            ),
            {"parent": table},
        )
        dropped = 0
        for (name,) in rows.fetchall():
            m = _PART_NAME.match(name)
            if not m:
                continue
            mm = m.group(3) or m.group(4)  # 下划线式 group3 / 紧凑式 group4
            ym = f"20{m.group(2)}{mm}"  # YYYYMM
            part_start = datetime.strptime(ym, "%Y%m")
            if part_start < cutoff:
                await session.execute(text(f'DROP TABLE "{name}"'))
                dropped += 1
                log.info("dropped expired partition %s", name)
        await session.commit()
    return dropped


async def audit_drop_expired_partitions() -> int:
    return await drop_expired_partitions("api_audit_logs", settings.AUDIT_RETENTION_DAYS)
