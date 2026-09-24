"""PlatformAPI 应用工厂（FastAPI）。

S01 骨架：
- 中间件：X-Auth-* HMAC 校验（DECISION-009）+ 审计（BASE-06）
- 启动种子：init_schema.sql + 自测租户/用户
- 9+1 模块 router
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from joker_shared.config import settings
from app.middleware import AuditMiddleware, InternalAuthMiddleware
from app.routers import router as api_router

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("joker.api")


def create_app() -> FastAPI:
    app = FastAPI(
        title="agent-joker PlatformAPI",
        version="0.1.0-s01",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # 中间件顺序：后添加的先执行。先加 Audit（外层计时）→ 再加 InternalAuth（内层鉴权）
    app.add_middleware(AuditMiddleware)
    app.add_middleware(InternalAuthMiddleware)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": "platformapi", "phase": "S01-skeleton"}

    app.include_router(api_router)

    @app.on_event("startup")
    async def _startup() -> None:
        from joker_shared.seed import seed_all

        try:
            await seed_all()
            log.info("bootstrap seed done")
        except Exception:
            log.exception("bootstrap seed failed (service continues; check DB)")
        # S03：注册默认 LLM 节点（本地 fallback embedding + .env 默认 chat 端点，幂等）
        try:
            from joker_shared.db import get_session
            from joker_shared.llm import get_llm_service

            async for session in get_session():
                await get_llm_service().ensure_default_nodes(session)
                break
        except Exception:
            log.exception("llm default nodes seed failed")
        # 分区兜底：保证当前月±1 的月分区存在（幂等）
        try:
            from sqlalchemy import text

            from joker_shared.db import get_engine

            engine = get_engine()
            async with engine.begin() as conn:
                await conn.execute(text("SELECT ensure_monthly_partitions('trace_events', 3)"))
                await conn.execute(text("SELECT ensure_monthly_partitions('api_audit_logs', 3)"))
        except Exception:
            log.exception("partition ensure failed")
        # S04：RAG 文档流水线 worker（进程内队列，DECISION-021，单并发串行）
        try:
            from joker_shared.rag.service import get_task_queue

            await get_task_queue().start()
            log.info("rag doc worker started")
        except Exception:
            log.exception("rag doc worker start failed")
        # S06：平台内置 MCP server 幂等注册（is_platform=true 行 + 3 平台工具行）
        try:
            from joker_shared.db import get_session
            from joker_shared.mcp import get_mcp_registry

            async for session in get_session():
                res = await get_mcp_registry().ensure_platform_server(session)
                break
            log.info("platform mcp server ensured: %s", res.get("server_id"))
        except Exception:
            log.exception("platform mcp server seed failed")
        # S09：trace/审计保留策略定期清理（D-D / DECISION-025）——
        # 启动即跑一次 + 每 RETENTION_CHECK_INTERVAL_HOURS 读当前配置 DROP 过期月分区。
        try:
            import asyncio

            from joker_shared import trace as _trace

            app.state.retention_task = asyncio.create_task(_trace.retention_loop())
            log.info("trace/audit retention maintenance loop started (interval=%sh)",
                     settings.RETENTION_CHECK_INTERVAL_HOURS)
        except Exception:
            log.exception("retention loop start failed")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        try:
            from joker_shared.rag.service import get_task_queue

            await get_task_queue().stop()
        except Exception:
            log.exception("rag doc worker stop failed")
        try:
            task = getattr(app.state, "retention_task", None)
            if task is not None:
                task.cancel()
        except Exception:
            log.exception("retention loop stop failed")

    return app


app = create_app()
