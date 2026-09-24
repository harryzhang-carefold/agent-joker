"""Redis 客户端（黑名单/限流/缓存，DB_DESIGN §11 key 设计）。

key 统一前缀 `joker:`（共享实例隔离约定；本地独立实例也保留）。
"""
from __future__ import annotations

import json
import time

import redis.asyncio as aioredis

from joker_shared.config import settings

_pool: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _pool


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


# ---------------------------------------------------------------- JWT 黑名单（DECISION-002）

async def deny_access(jti: str, ttl_seconds: int) -> None:
    """登出/重置密码：access token 进黑名单（TTL=剩余有效期）。"""
    if ttl_seconds <= 0:
        return
    await get_redis().setex(f"joker:jwt:deny:{jti}", ttl_seconds, "1")


async def is_denied(jti: str) -> bool:
    return await get_redis().exists(f"joker:jwt:deny:{jti}") == 1


# ---------------------------------------------------------------- 限流（DECISION-013，固定窗口）

async def rate_limit_check(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    """固定窗口计数。返回 (是否放行, 当前计数)。"""
    r = get_redis()
    window = int(time.time() // window_seconds)
    k = f"joker:rl:{key}:{window}"
    count = await r.incr(k)
    if count == 1:
        await r.expire(k, window_seconds)
    return (count <= limit, count)
