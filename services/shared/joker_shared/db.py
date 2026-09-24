"""DB 会话层：SQLAlchemy 2.0 async（asyncpg）+ 租户行级过滤（DECISION-004）。

选型决策（DECISION-026，S01 骨架）：
- **SQLAlchemy 2.0 + asyncpg（async）**：FastAPI 原生 async（DECISION-001），
  长耗时 LLM 调用不阻塞事件循环；asyncpg 是 PG 生态最快的异步驱动；
  同步 psql 子进程方案无法在 FastAPI 请求路径上复用连接池、事务语义弱，弃用。
- **租户过滤**：不采用全局 event 注入 WHERE（对裸 SQL / 分区表 / 跨租户
  管理面场景侵入性过强、绕过路径难审计）；改为**会话级 TenantScope 依赖**
  （显式、可审计、管理面可显式关闭），等价保证由：
  1) 所有业务查询必须经 `tenant_scoped` 包装（code review 拦截裸 SQL，
     与 DB_DESIGN §10.1 的 code review 拦截约定一致）；
  2) 唯一约束/索引 tenant 打头（DB 层兜底）。
  DB_DESIGN §10.1 原文即「绕过框架的裸 SQL 路径在 code review 中拦截」，
  显式包装与该约定兼容（每个 tenant 过滤点都可见于调用栈）。
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from joker_shared.config import settings

# 当前请求上下文租户（由 X-Auth-* HMAC 校验中间件设置）
_tenant_ctx: ContextVar[str | None] = ContextVar("joker_tenant", default=None)
_user_ctx: ContextVar[str | None] = ContextVar("joker_user", default=None)
_scopes_ctx: ContextVar[tuple[str, ...]] = ContextVar("joker_scopes", default=())


def set_auth_context(tenant_id: str, user_id: str, scopes: list[str] | tuple[str, ...] = ()) -> None:
    _tenant_ctx.set(tenant_id)
    _user_ctx.set(user_id)
    _scopes_ctx.set(tuple(scopes))


def current_tenant() -> str | None:
    return _tenant_ctx.get()


def current_user() -> str | None:
    return _user_ctx.get()


def current_scopes() -> tuple[str, ...]:
    return _scopes_ctx.get()


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            settings.DB_DSN,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncSession:
    """FastAPI 依赖：请求级会话（不自动 commit；写端点必须显式 commit，
    与 carefold 经验一致）。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session


def require_tenant() -> str:
    """当前请求必须有已校验的租户上下文，否则 403（BASE-07）。"""
    t = _tenant_ctx.get()
    if not t:
        raise TenantNotScoped()
    return t


class TenantNotScoped(Exception):
    """请求缺少租户上下文（未通过 HMAC 鉴权或非租户路由）。"""


class TenantFilter:
    """租户行级过滤辅助（DECISION-004）。

    用法：
        where = tenant_where()            # 追加到 select/where 条件
        或   stmt = tenant_scoped(stmt)   # 包装已构造的 stmt（需含 tenant_id 列）
    """

    @staticmethod
    def where(column_name: str = "tenant_id", tenant_id: str | None = None) -> Any:
        from sqlalchemy import column as sa_column

        t = tenant_id if tenant_id is not None else _tenant_ctx.get()
        if t is None:
            raise TenantNotScoped()
        return sa_column(column_name) == uuid.UUID(t)

    @staticmethod
    def fill(tenant_id: str | None = None) -> str:
        """INSERT 时填充 tenant_id（只信上下文，不信请求体）。"""
        t = tenant_id if tenant_id is not None else _tenant_ctx.get()
        if t is None:
            raise TenantNotScoped()
        return t
