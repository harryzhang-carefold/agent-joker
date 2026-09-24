"""BFF 流量控制（BFF-02，DECISION-013）：Redis 固定窗口计数，三维度。

维度（DECISION-013）：
- 租户级 QPS（默认 50）      key = rl:tenant:<tid>
- 用户级 QPS（默认 10）      key = rl:user:<uid>
- 登录接口 IP（默认 5/分钟） key = rl:loginip:<ip>  window=60s

阈值可配（DECISION-013）：
- 运行时调整即时生效：`bff_rate_limit_configs` 表（租户级/全局行）→ 写后镜像到
  Redis（`joker:rl:cfg:<dim>`，TTL=BFF_RL_CACHE_TTL≈10s）；BFF 读限流阈值时优先
  读 Redis 镜像，miss 回退 DB，再回退 .env 默认（三级降级，Redis 故障不阻断主流程）。
- 超限返回 429（BFF 统一错误码，ARCH §4.7）。

实现用共享 `joker_shared.redis_client.rate_limit_check`（INCR + EXPIRE 固定窗口）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import redis_client
from joker_shared.config import settings

log = logging.getLogger("joker.bff.rl")

RL_CACHE_TTL = max(1, int(settings.BFF_RL_CACHE_TTL))
_LOGIN_WINDOW = 60  # 登录 IP 限流窗口（秒，= 每分钟）

# 维度 → 默认值 + 窗口（秒）；.env 默认（可被 DB/Redis 覆盖）
DEFAULTS: dict[str, dict[str, Any]] = {
    "tenant_qps": {"limit": settings.BFF_RATE_LIMIT_TENANT_QPS, "window": 1},
    "user_qps": {"limit": settings.BFF_RATE_LIMIT_USER_QPS, "window": 1},
    "login_ip_per_min": {"limit": settings.BFF_RATE_LIMIT_LOGIN_IP_PER_MIN, "window": _LOGIN_WINDOW},
}


class RateLimitExceeded(Exception):
    """限流超限（→ 429）。携带维度与当前计数用于响应体。"""

    def __init__(self, dim: str, count: int, limit: int, window: int) -> None:
        super().__init__(f"rate limit exceeded: {dim}")
        self.dim = dim
        self.count = count
        self.limit = limit
        self.window = window


# ---------------------------------------------------------------- 阈值读取（DB→Redis→default）

async def _cfg_from_redis(dim: str, tenant_id: str | None) -> dict | None:
    r = redis_client.get_redis()
    key = f"joker:rl:cfg:{tenant_id}:{dim}" if tenant_id else f"joker:rl:cfg:{dim}"
    try:
        raw = await r.get(key)
    except Exception as exc:
        log.warning("rl cfg redis read failed (%s); fallback db/default", exc)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def _cfg_from_db(session: AsyncSession, dim: str, tenant_id: str | None) -> dict | None:
    """bff_rate_limit_configs：租户级行（tenant_id=当前租户）→ 全局行（tenant_id NULL）。"""
    try:
        if tenant_id:
            row = await session.execute(
                text("SELECT limit_value, window_seconds, enabled FROM bff_rate_limit_configs "
                     "WHERE dimension = :d AND tenant_id = CAST(:t AS uuid)"),
                {"d": dim, "t": tenant_id},
            )
        else:
            row = None
        if row is None or row.first() is None:
            g = await session.execute(
                text("SELECT limit_value, window_seconds, enabled FROM bff_rate_limit_configs "
                     "WHERE dimension = :d AND tenant_id IS NULL"),
                {"d": dim},
            )
            row = g
        r = row.first()
        if r is None:
            return None
        return {"limit": int(r[0]), "window": int(r[1] or 1), "enabled": bool(r[2])}
    except Exception as exc:
        log.warning("rl cfg db read failed (%s); fallback default", exc)
        return None


async def get_limit(
    session: AsyncSession | None, dim: str, tenant_id: str | None = None
) -> tuple[int, int, bool]:
    """取维度阈值 (limit, window, enabled)。Redis 镜像 → DB → .env 默认。"""
    cfg = await _cfg_from_redis(dim, tenant_id)
    if cfg is None:
        cfg = await _cfg_from_db(session, dim, tenant_id) if session is not None else None
    if cfg is None:
        d = DEFAULTS[dim]
        return d["limit"], d["window"], True
    return int(cfg.get("limit", DEFAULTS[dim]["limit"])), int(cfg.get("window", DEFAULTS[dim]["window"])), bool(cfg.get("enabled", True))


async def set_limit(session: AsyncSession, dim: str, limit_value: int, tenant_id: str | None,
                    window_seconds: int | None = None, user_id: str | None = None) -> dict:
    """运行时调整阈值（写 DB upsert + 镜像 Redis，即时生效，DECISION-013）。"""
    if limit_value < 1:
        raise ValueError("limit_value must be >= 1")
    window = int(window_seconds or DEFAULTS[dim]["window"])
    if tenant_id:
        await session.execute(
            text(
                """INSERT INTO bff_rate_limit_configs
                   (id, tenant_id, dimension, limit_value, window_seconds, enabled, created_by, updated_by)
                   VALUES (gen_random_uuid(), CAST(:t AS uuid), :d, :l, :w, true,
                          CAST(:u AS uuid), CAST(:u AS uuid))
                   ON CONFLICT (tenant_id, dimension) WHERE tenant_id IS NOT NULL
                   DO UPDATE SET limit_value = :l, window_seconds = :w,
                                 updated_by = CAST(:u AS uuid), updated_at = now()"""
            ),
            {"t": tenant_id, "d": dim, "l": limit_value, "w": window, "u": user_id or ""},
        )
    else:
        await session.execute(
            text(
                """INSERT INTO bff_rate_limit_configs
                   (id, tenant_id, dimension, limit_value, window_seconds, enabled, created_by, updated_by)
                   VALUES (gen_random_uuid(), NULL, :d, :l, :w, true,
                          CAST(:u AS uuid), CAST(:u AS uuid))
                   ON CONFLICT (dimension) WHERE tenant_id IS NULL
                   DO UPDATE SET limit_value = :l, window_seconds = :w,
                                 updated_by = CAST(:u AS uuid), updated_at = now()"""
            ),
            {"d": dim, "l": limit_value, "w": window, "u": user_id or ""},
        )
    await session.commit()
    # 镜像 Redis（即时生效，≤ TTL 秒）
    payload = json.dumps({"limit": int(limit_value), "window": window, "enabled": True})
    r = redis_client.get_redis()
    try:
        if tenant_id:
            await r.setex(f"joker:rl:cfg:{tenant_id}:{dim}", RL_CACHE_TTL, payload)
        else:
            await r.setex(f"joker:rl:cfg:{dim}", RL_CACHE_TTL, payload)
    except Exception as exc:
        log.warning("rl cfg redis mirror failed (%s); DB value still authoritative", exc)
    return {"dim": dim, "limit_value": int(limit_value), "window_seconds": window, "tenant_id": tenant_id}


# ---------------------------------------------------------------- 限流执行

async def check_login_ip(session: AsyncSession | None, ip: str) -> None:
    """登录接口 IP 限流（5/min，DECISION-013）。超限 → RateLimitExceeded。"""
    limit, window, enabled = await get_limit(session, "login_ip_per_min", None)
    if not enabled or limit <= 0:
        return
    try:
        ok, count = await redis_client.rate_limit_check(f"loginip:{ip}", limit, window)
    except Exception as exc:
        log.warning("login ip rl check failed (%s); allow through", exc)
        return
    if not ok:
        raise RateLimitExceeded("login_ip", count, limit, window)


async def check_tenant(session: AsyncSession | None, tenant_id: str) -> None:
    """租户级 QPS 限流（默认 50）。超限 → RateLimitExceeded。"""
    limit, window, enabled = await get_limit(session, "tenant_qps", tenant_id)
    if not enabled or limit <= 0:
        return
    try:
        ok, count = await redis_client.rate_limit_check(f"tenant:{tenant_id}", limit, window)
    except Exception as exc:
        log.warning("tenant rl check failed (%s); allow through", exc)
        return
    if not ok:
        raise RateLimitExceeded("tenant", count, limit, window)


async def check_user(session: AsyncSession | None, user_id: str, tenant_id: str) -> None:
    """用户级 QPS 限流（默认 10）。超限 → RateLimitExceeded。"""
    limit, window, enabled = await get_limit(session, "user_qps", tenant_id)
    if not enabled or limit <= 0:
        return
    try:
        ok, count = await redis_client.rate_limit_check(f"user:{user_id}", limit, window)
    except Exception as exc:
        log.warning("user rl check failed (%s); allow through", exc)
        return
    if not ok:
        raise RateLimitExceeded("user", count, limit, window)
