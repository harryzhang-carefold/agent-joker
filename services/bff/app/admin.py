"""BFF 管理端点（BFF-02 配置 API / BFF-03 热加载，平台级权限）。

- GET  /api/bff/rate-limits          查限流阈值（当前租户 + 全局，含生效值）
- POST /api/bff/rate-limits          运行时调整阈值（写 DB + Redis 镜像，即时生效，DECISION-013）
- POST /api/bff/routes/reload        路由表热加载（DECISION-014，新增端点不改 BFF 代码）
- GET  /api/bff/routes               当前路由表快照

scope 门禁：限流/路由调整 = 平台级（`iam:manage` 或系统租户）；查询对本租户开放。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app import rate_limit
from app.gateway import current_identity, current_token, identity_for
from app.routes import get_router

log = logging.getLogger("joker.bff.admin")
router = APIRouter(prefix="/api/bff", tags=["bff-admin"])

VALID_DIMS = ("tenant_qps", "user_qps", "login_ip_per_min")


def _require_platform_admin(auth: dict) -> None:
    """平台级权限：iam:manage scope 或系统租户（管理面例外，DB_DESIGN §10.1）。"""
    if "iam:manage" in auth.get("scopes", []) or _is_sys(auth.get("tenant_id", "")):
        return
    raise HTTPException(403, "platform admin required (iam:manage or system tenant)")


@router.get("/rate-limits")
async def list_rate_limits(request: Request):
    auth = identity_for(request)
    tid = auth["tenant_id"]
    out = {}
    for dim in VALID_DIMS:
        # 生效值（Redis 镜像 → DB → default，与限流判定同源）
        limit, window, enabled = await rate_limit.get_limit(None, dim, tid)
        out[dim] = {"limit": limit, "window_seconds": window, "enabled": enabled,
                    "scope": "tenant" if dim != "login_ip_per_min" else "global-ip"}
    return {"items": out, "tenant_id": tid}


@router.post("/rate-limits")
async def set_rate_limit(request: Request):
    auth = identity_for(request)
    _require_platform_admin(auth)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(422, "invalid JSON body")
    dim = body.get("dimension")
    if dim not in VALID_DIMS:
        raise HTTPException(422, f"dimension must be one of {VALID_DIMS}")
    limit = body.get("limit_value")
    if not isinstance(limit, int) or limit < 1:
        raise HTTPException(422, "limit_value must be int >= 1")
    # 租户级：login_ip_per_min 仅全局（无租户维度）；其余可租户级（tenant_id 缺省=全局）
    tenant_id = body.get("tenant_id") or (auth["tenant_id"] if dim != "login_ip_per_min" else None)
    if dim == "login_ip_per_min" and tenant_id:
        raise HTTPException(422, "login_ip_per_min is a global (per-IP) dimension")

    from joker_shared.db import get_session_factory

    async with get_session_factory()() as session:
        res = await rate_limit.set_limit(
            session, dim, limit, tenant_id,
            window_seconds=body.get("window_seconds"), user_id=auth["user_id"],
        )
    return {"ok": True, **res}


@router.get("/routes")
async def list_routes(request: Request):
    identity_for(request)
    r = get_router()
    return {"source": r.source, "count": len(r.table.snapshot()), "routes": r.table.snapshot()}


@router.post("/routes/reload")
async def reload_routes(request: Request):
    auth = identity_for(request)
    _require_platform_admin(auth)
    r = get_router()
    try:
        res = r.reload()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        log.exception("routes reload failed")
        raise HTTPException(500, f"reload failed: {e}")
    return {"ok": True, **res}


def _is_sys(tenant_id: str) -> bool:
    return tenant_id == "00000000-0000-0000-0000-000000000001"
