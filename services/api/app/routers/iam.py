"""IAMService（BASE-01/02/03，DECISION-004）：用户/角色/scope 三级 CRUD。

- 用户：CRUD + 启用/禁用 + 重置密码（bcrypt，重置后吊销全部 refresh，BASE-09）
- 角色：CRUD + 角色-scope 绑定（内置角色不可删，可改权限）
- scope：平台级预置（只读）+ 租户级动态 scope（agent:use:<id>，由 agent 切片
  在创建 agent 时 upsert；本切片提供通用 CRUD 供平台管理）
- 租户：平台运营（is_platform_admin / 系统租户）可管理；租户级用户只见本租户
  （tenant_id 过滤强制，BASE-07）
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import crypto
from app.deps import auth_context, db_session, require_scope

router = APIRouter(prefix="/api", tags=["iam"])


# ---------------------------------------------------------------- 用户（BASE-01）

class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str | None = None
    email: str | None = None
    role_names: list[str] = []


class UserUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    status: str | None = Field(None, pattern="^(active|disabled)$")
    role_names: list[str] | None = None


@router.get("/users")
async def list_users(
    page: int = 1, page_size: int = 50,
    auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session),
):
    """用户列表（强制租户过滤，BASE-07 数据行隔离）。"""
    require_scope("iam:manage", auth=auth)
    t = auth["tenant_id"]
    total = (await session.execute(
        text("SELECT count(*) FROM users WHERE tenant_id=:t AND deleted_at IS NULL"), {"t": t}
    )).scalar()
    rows = await session.execute(
        text(
            """
            SELECT u.id, u.username, u.email, u.display_name, u.status,
                   u.is_platform_admin, u.last_login_at, u.created_at,
                   COALESCE(json_agg(DISTINCT r.name) FILTER (WHERE r.name IS NOT NULL), '[]') AS roles
            FROM users u
            LEFT JOIN user_roles ur ON ur.user_id = u.id
            LEFT JOIN roles r ON r.id = ur.role_id AND r.deleted_at IS NULL
            WHERE u.tenant_id = :t AND u.deleted_at IS NULL
            GROUP BY u.id ORDER BY u.created_at
            LIMIT :ps OFFSET :off
            """
        ),
        {"t": t, "ps": page_size, "off": (page - 1) * page_size},
    )
    items = [
        {
            "id": str(r[0]), "username": r[1], "email": r[2], "display_name": r[3],
            "status": r[4], "is_platform_admin": r[5],
            "last_login_at": r[6].isoformat() if r[6] else None,
            "created_at": r[7].isoformat() if r[7] else None,
            "roles": r[8],
        }
        for r in rows.fetchall()
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/users", status_code=201)
async def create_user(
    req: UserCreate, auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session),
):
    require_scope("iam:manage", auth=auth)
    t = auth["tenant_id"]
    uid = str(uuid.uuid4())
    try:
        await session.execute(
            text(
                """
                INSERT INTO users (id, tenant_id, username, email, password_hash, display_name, status, created_by)
                VALUES (:id, :t, :u, :e, :pw, :dn, 'active', :by)
                """
            ),
            {"id": uid, "t": t, "u": req.username, "e": req.email,
             "pw": crypto.hash_password(req.password), "dn": req.display_name, "by": auth["user_id"]},
        )
    except Exception as exc:  # 唯一约束（username/email）→ 409
        if "uq_users" in str(exc):
            raise HTTPException(status_code=409, detail="username or email already exists") from exc
        raise
    for rn in req.role_names:
        await _bind_role(session, t, uid, rn)
        await session.flush()
    await session.commit()
    return {"id": uid, "username": req.username}


@router.get("/users/{user_id}")
async def get_user(
    user_id: str, auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session),
):
    require_scope("iam:manage", auth=auth)
    row = await session.execute(
        text("SELECT id, username, email, display_name, status, is_platform_admin, created_at "
             "FROM users WHERE id=:u AND tenant_id=:t AND deleted_at IS NULL"),
        {"u": user_id, "t": auth["tenant_id"]},
    )
    r = row.first()
    if r is None:
        # 跨租户猜 ID → 404（不泄露存在性，BASE-07 验收 2）
        raise HTTPException(status_code=404, detail="user not found")
    # BUG-04 修复：GET /users/{id} 返回 roles（BASE-02 验收：用户角色分配可经 API 读回）
    rrow = await session.execute(
        text(
            "SELECT r.name FROM user_roles ur "
            "JOIN roles r ON r.id = ur.role_id AND r.deleted_at IS NULL "
            "WHERE ur.user_id = :u ORDER BY r.name"
        ),
        {"u": user_id},
    )
    roles = [x[0] for x in rrow.fetchall()]
    return {
        "id": str(r[0]), "username": r[1], "email": r[2], "display_name": r[3],
        "status": r[4], "is_platform_admin": r[5],
        "created_at": r[6].isoformat() if r[6] else None,
        "roles": roles,
    }


@router.put("/users/{user_id}")
async def update_user(
    user_id: str, req: UserUpdate, auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    require_scope("iam:manage", auth=auth)
    t = auth["tenant_id"]
    sets, params = [], {"id": user_id, "t": t, "by": auth["user_id"]}
    if req.display_name is not None:
        sets.append("display_name=:dn"); params["dn"] = req.display_name
    if req.email is not None:
        sets.append("email=:e"); params["e"] = req.email
    if req.status is not None:
        sets.append("status=:st"); params["st"] = req.status
    # BUG-04 修复：仅 role_names 也是合法更新（BASE-02 验收「用户可分配/变更角色」）
    if not sets and req.role_names is None:
        raise HTTPException(status_code=422, detail="no fields to update")
    if sets:
        r = await session.execute(
            text(f"UPDATE users SET {', '.join(sets)}, updated_by=:by "
                 f"WHERE id=:id AND tenant_id=:t AND deleted_at IS NULL"),
            params,
        )
        if r.rowcount == 0:
            raise HTTPException(status_code=404, detail="user not found")
    else:
        # 仅改角色：校验用户存在（跨租户 → 404，不泄露存在性）
        chk = await session.execute(
            text("SELECT 1 FROM users WHERE id=:id AND tenant_id=:t AND deleted_at IS NULL"),
            params,
        )
        if chk.first() is None:
            raise HTTPException(status_code=404, detail="user not found")
    if req.role_names is not None:
        await session.execute(
            text("DELETE FROM user_roles WHERE user_id=:u"), {"u": user_id}
        )
        for rn in req.role_names:
            await _bind_role(session, t, user_id, rn)
    await session.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str, auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session),
):
    """删除用户 = 禁用 + 软删（保留历史引用，审计/trace 不破坏，DB_DESIGN §1.2）。"""
    require_scope("iam:manage", auth=auth)
    r = await session.execute(
        text("UPDATE users SET status='disabled', deleted_at=now(), updated_by=:by "
             "WHERE id=:u AND tenant_id=:t AND deleted_at IS NULL"),
        {"u": user_id, "t": auth["tenant_id"], "by": auth["user_id"]},
    )
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="user not found")
    # 吊销其全部 refresh（防已删除账号续期）
    await session.execute(
        text("UPDATE auth_refresh_tokens SET revoked_at=now() WHERE user_id=:u AND revoked_at IS NULL"),
        {"u": user_id},
    )
    await session.commit()
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str, req: UserCreate, auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """重置密码（BASE-01 验收 3）+ 吊销全部 refresh（BASE-09）。"""
    require_scope("iam:manage", auth=auth)
    r = await session.execute(
        text("UPDATE users SET password_hash=:pw, updated_by=:by "
             "WHERE id=:u AND tenant_id=:t AND deleted_at IS NULL"),
        {"u": user_id, "t": auth["tenant_id"], "by": auth["user_id"],
         "pw": crypto.hash_password(req.password)},
    )
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="user not found")
    await session.execute(
        text("UPDATE auth_refresh_tokens SET revoked_at=now() WHERE user_id=:u AND revoked_at IS NULL"),
        {"u": user_id},
    )
    await session.commit()
    return {"ok": True}


async def _bind_role(session: AsyncSession, tenant_id: str, user_id: str, role_name: str) -> None:
    row = await session.execute(
        text("SELECT id FROM roles WHERE tenant_id=:t AND name=:n AND deleted_at IS NULL"),
        {"t": tenant_id, "n": role_name},
    )
    role = row.first()
    if role is None:
        raise HTTPException(status_code=404, detail=f"role not found: {role_name}")
    await session.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r) ON CONFLICT DO NOTHING"),
        {"u": user_id, "r": role[0]},
    )


# ---------------------------------------------------------------- 角色（BASE-02）

class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    scope_codes: list[str] = []


class RoleUpdate(BaseModel):
    description: str | None = None
    scope_codes: list[str] | None = None


@router.get("/roles")
async def list_roles(auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session)):
    require_scope("iam:manage", auth=auth)
    rows = await session.execute(
        text(
            """
            SELECT r.id, r.name, r.description, r.is_builtin,
                   COALESCE(json_agg(DISTINCT s.code) FILTER (WHERE s.code IS NOT NULL), '[]') AS scopes
            FROM roles r
            LEFT JOIN role_scopes rs ON rs.role_id = r.id
            LEFT JOIN scopes s ON s.id = rs.scope_id
            WHERE r.tenant_id = :t AND r.deleted_at IS NULL
            GROUP BY r.id ORDER BY r.created_at
            """
        ),
        {"t": auth["tenant_id"]},
    )
    return {
        "items": [
            {"id": str(r[0]), "name": r[1], "description": r[2], "is_builtin": r[3], "scopes": r[4]}
            for r in rows.fetchall()
        ]
    }


@router.post("/roles", status_code=201)
async def create_role(
    req: RoleCreate, auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session),
):
    require_scope("iam:manage", auth=auth)
    t = auth["tenant_id"]
    rid = str(uuid.uuid4())
    try:
        await session.execute(
            text("INSERT INTO roles (id, tenant_id, name, description, is_builtin, created_by) "
                 "VALUES (:id, :t, :n, :d, false, :by)"),
            {"id": rid, "t": t, "n": req.name, "d": req.description, "by": auth["user_id"]},
        )
    except Exception as exc:
        if "uq_roles" in str(exc):
            raise HTTPException(status_code=409, detail="role name already exists") from exc
        raise
    for sc in req.scope_codes:
        await _bind_scope(session, rid, sc)
        await session.flush()
    await session.commit()
    return {"id": rid, "name": req.name}


@router.put("/roles/{role_id}")
async def update_role(
    role_id: str, req: RoleUpdate, auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    require_scope("iam:manage", auth=auth)
    t = auth["tenant_id"]
    r = await session.execute(
        text("UPDATE roles SET description=:d, updated_by=:by WHERE id=:id AND tenant_id=:t AND deleted_at IS NULL"),
        {"d": req.description, "by": auth["user_id"], "id": role_id, "t": t},
    )
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="role not found")
    if req.scope_codes is not None:
        # 内置角色可改权限（DB_DESIGN §1.3）
        await session.execute(text("DELETE FROM role_scopes WHERE role_id=:r"), {"r": role_id})
        for sc in req.scope_codes:
            await _bind_scope(session, role_id, sc)
    await session.commit()
    return {"ok": True}


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str, auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session),
):
    require_scope("iam:manage", auth=auth)
    t = auth["tenant_id"]
    row = await session.execute(
        text("SELECT id, is_builtin FROM roles WHERE id=:id AND tenant_id=:t AND deleted_at IS NULL"),
        {"id": role_id, "t": t},
    )
    role = row.first()
    if role is None:
        raise HTTPException(status_code=404, detail="role not found")
    if role[1]:
        raise HTTPException(status_code=409, detail="builtin role cannot be deleted (edit its scopes instead)")
    # 有用户引用 → 409（BASE-02 验收：删除前校验无引用）
    ref = (await session.execute(
        text("SELECT count(*) FROM user_roles WHERE role_id=:r"), {"r": role_id}
    )).scalar()
    if ref:
        raise HTTPException(status_code=409, detail=f"role in use by {ref} users")
    await session.execute(
        text("UPDATE roles SET deleted_at=now(), updated_by=:by WHERE id=:id"),
        {"id": role_id, "by": auth["user_id"]},
    )
    await session.execute(text("DELETE FROM role_scopes WHERE role_id=:r"), {"r": role_id})
    await session.commit()
    return {"ok": True}


async def _bind_scope(session: AsyncSession, role_id: str, code: str) -> None:
    """按 code 绑 scope：平台级（tenant NULL）优先，其次任意租户级（agent:use:<id> 按 code 定位）。"""
    row = await session.execute(
        text("SELECT id FROM scopes WHERE code=:c ORDER BY (tenant_id IS NULL) DESC LIMIT 1"),
        {"c": code},
    )
    scope = row.first()
    if scope is None:
        raise HTTPException(status_code=404, detail=f"scope not found: {code}")
    await session.execute(
        text("INSERT INTO role_scopes (role_id, scope_id) VALUES (:r, :s) ON CONFLICT DO NOTHING"),
        {"r": role_id, "s": scope[0]},
    )


# ---------------------------------------------------------------- scope（BASE-03）

@router.get("/scopes")
async def list_scopes(auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session)):
    """scope 列表：平台级（tenant NULL）+ 本租户动态 scope。"""
    require_scope("iam:manage", auth=auth)
    rows = await session.execute(
        text(
            "SELECT id, tenant_id, code, description, category FROM scopes "
            "WHERE tenant_id = :t OR tenant_id IS NULL ORDER BY category, code"
        ),
        {"t": auth["tenant_id"]},
    )
    return {
        "items": [
            {"id": str(r[0]), "tenant_id": str(r[1]) if r[1] else None, "code": r[2],
             "description": r[3], "category": r[4]}
            for r in rows.fetchall()
        ]
    }


class ScopeCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    category: str = Field("resource", pattern="^(function|resource|tool)$")


@router.post("/scopes", status_code=201)
async def create_scope(
    req: ScopeCreate, auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session),
):
    """租户级动态 scope（如 agent:use:<id>；agent 切片创建 agent 时自动 upsert）。"""
    require_scope("iam:manage", auth=auth)
    sid = str(uuid.uuid4())
    try:
        await session.execute(
            text("INSERT INTO scopes (id, tenant_id, code, description, category, created_by) "
                 "VALUES (:id, :t, :c, :d, :cat, :by)"),
            {"id": sid, "t": auth["tenant_id"], "c": req.code, "d": req.description,
             "cat": req.category, "by": auth["user_id"]},
        )
    except Exception as exc:
        if "uq_scopes" in str(exc):
            raise HTTPException(status_code=409, detail="scope code already exists in this tenant") from exc
        raise
    await session.commit()
    return {"id": sid, "code": req.code}


# ---------------------------------------------------------------- 租户（平台运营）

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=2, max_length=64, pattern="^[a-z0-9-]+$")
    plan: str = Field("free", pattern="^(free|pro)$")
    storage_quota_mb: int = 1024


def _require_platform_admin(auth: dict) -> None:
    if not (auth.get("is_platform_admin") or auth["tenant_id"] == "00000000-0000-0000-0000-000000000001"):
        raise HTTPException(status_code=403, detail="platform admin required")


@router.get("/tenants")
async def list_tenant_list(auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session)):
    _require_platform_admin(auth)
    rows = await session.execute(text("SELECT id, name, code, status, plan, storage_quota_mb FROM tenants ORDER BY code"))
    return {
        "items": [
            {"id": str(r[0]), "name": r[1], "code": r[2], "status": r[3],
             "plan": r[4], "storage_quota_mb": r[5]}
            for r in rows.fetchall()
        ]
    }


@router.post("/tenants", status_code=201)
async def create_tenant(
    req: TenantCreate, auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session),
):
    """平台运营建租户（含内置角色 admin/member 种子）。"""
    _require_platform_admin(auth)
    tid = str(uuid.uuid4())
    try:
        await session.execute(
            text("INSERT INTO tenants (id, name, code, status, plan, storage_quota_mb, created_by) "
                 "VALUES (:id, :n, :c, 'active', :p, :q, :by)"),
            {"id": tid, "n": req.name, "c": req.code, "p": req.plan,
             "q": req.storage_quota_mb, "by": auth["user_id"]},
        )
    except Exception as exc:
        if "uq_tenants" in str(exc):
            raise HTTPException(status_code=409, detail="tenant name or code already exists") from exc
        raise
    # 内置角色（DB_DESIGN §10.3）
    for rn, desc in (("admin", "租户管理员"), ("member", "普通成员")):
        rid = str(uuid.uuid4())
        await session.execute(
            text("INSERT INTO roles (id, tenant_id, name, description, is_builtin, created_by) "
                 "VALUES (:id, :t, :n, :d, true, :by)"),
            {"id": rid, "t": tid, "n": rn, "d": desc, "by": auth["user_id"]},
        )
        # admin：全部平台级 scope + agent:use:*（agent 通配为动态 scope，随 agent 创建 upsert；
        # 此处预置通配 scope 行使 admin 开箱可用，S07 agent 切片复用同一 upsert 路径）
        if rn == "admin":
            await session.execute(
                text(
                    "INSERT INTO role_scopes (role_id, scope_id) "
                    "SELECT :r, id FROM scopes WHERE tenant_id IS NULL ON CONFLICT DO NOTHING"
                ),
                {"r": rid},
            )
    await session.commit()
    return {"id": tid, "code": req.code}


@router.put("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str, req: TenantCreate, auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    _require_platform_admin(auth)
    r = await session.execute(
        text("UPDATE tenants SET name=:n, plan=:p, storage_quota_mb=:q, updated_by=:by WHERE id=:id"),
        {"n": req.name, "p": req.plan, "q": req.storage_quota_mb, "by": auth["user_id"], "id": tenant_id},
    )
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="tenant not found")
    await session.commit()
    return {"ok": True}
