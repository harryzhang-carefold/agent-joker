"""AuthService（BASE-04/05/09，DECISION-002）。

- POST /api/auth/login      密码登录（bcrypt）→ JWT 双令牌（access 15min / refresh 7d 存表）
- POST /api/auth/refresh    refresh 轮换（旧 jti 标记 replaced_by，重放检测→整族吊销）
- POST /api/auth/logout     登出：吊销 refresh + access 进 Redis 黑名单（TTL=剩余有效期）
- POST /api/auth/logout-all 吊销该用户全部 refresh token（重置密码场景，BASE-09）

租户解析（BASE-07 登录隔离）：登录请求带 `tenant_code`（或 tenant_id），
用户名在指定租户内唯一；跨租户登录 = 404（不泄露其他租户账号存在性）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import crypto, redis_client
from joker_shared.config import settings
from app.deps import auth_context, db_session

log = logging.getLogger("joker.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginReq(BaseModel):
    tenant_code: str = Field(..., min_length=1, max_length=64)
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=128)


class RefreshReq(BaseModel):
    refresh_token: str
    tenant_code: str | None = None  # 缺省=token 内租户（refresh 有状态，自带 tenant）


class LogoutReq(BaseModel):
    refresh_token: str | None = None  # 提供则精确吊销；缺省=按 access jti 吊销对应 refresh


@router.post("/login")
async def login(req: LoginReq, session: AsyncSession = Depends(db_session), request: Request = None):
    # 1) 租户解析（跨租户 = 404，不泄露账号存在性）
    row = await session.execute(text("SELECT id, status FROM tenants WHERE code=:c"), {"c": req.tenant_code})
    tenant = row.first()
    if tenant is None or tenant[1] != "active":
        raise HTTPException(status_code=404, detail="tenant not found")
    tid = str(tenant[0])

    # 2) 用户校验（租户内 username 唯一）
    row = await session.execute(
        text("SELECT id, password_hash, status FROM users WHERE tenant_id=:t AND username=:u AND deleted_at IS NULL"),
        {"t": tid, "u": req.username},
    )
    user = row.first()
    if user is None or not crypto.verify_password(req.password, user[1]) or user[2] != "active":
        raise HTTPException(status_code=401, detail="invalid credentials")
    uid = str(user[0])

    # 3) scopes = 用户全部角色的 scope 并集（BASE-03 验收 2）
    row = await session.execute(
        text(
            """
            SELECT DISTINCT s.code FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id AND r.deleted_at IS NULL
            JOIN role_scopes rs ON rs.role_id = r.id
            JOIN scopes s ON s.id = rs.scope_id
            WHERE ur.user_id = :u
            """
        ),
        {"u": uid},
    )
    scopes = [r[0] for r in row.fetchall()]
    # 内置 admin 角色带 agent:use:*（S01 骨架：admin 的 agent:use:* 由 agent 切片 upsert 动态 scope，
    # 此处对 admin 角色直接注入通配，保证自测闭环；S07 agent 切片接入真实 scope 行）
    row = await session.execute(
        text(
            """
            SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :u AND r.deleted_at IS NULL
            """
        ),
        {"u": uid},
    )
    role_names = [r[0] for r in row.fetchall()]
    if "admin" in role_names and "agent:use:*" not in scopes:
        scopes.append("agent:use:*")

    # 4) 签发双令牌 + refresh 落表（有状态，支持登出吊销，DECISION-002）
    tokens = crypto.issue_tokens(tid, uid, scopes)
    jti = tokens["refresh_jti"]
    import datetime as _dt

    expires_at = _dt.datetime.utcnow() + _dt.timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
    await session.execute(
        text(
            """
            INSERT INTO auth_refresh_tokens
              (id, tenant_id, user_id, token_hash, device_info, expires_at, created_by)
            VALUES (:id, :t, :u, :h, :d, :e, :u)
            """
        ),
        {
            "id": jti,
            "t": tid,
            "u": uid,
            "h": crypto.token_hash(tokens["refresh_token"]),
            "d": json.dumps({"ua": request.headers.get("user-agent", "")[:200], "ip": request.client.host if request.client else ""}, ensure_ascii=False),
            "e": expires_at,
        },
    )
    await session.execute(
        text("UPDATE users SET last_login_at=now() WHERE id=:u"), {"u": uid}
    )
    await session.commit()
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "Bearer",
        "expires_at": tokens["expires_at"],
    }


@router.post("/refresh")
async def refresh(req: RefreshReq, session: AsyncSession = Depends(db_session)):
    # 1) 解码（过期/签名错 → 401）
    try:
        claims = crypto.decode_refresh(req.refresh_token)
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid refresh token: {exc}")
    jti = claims["jti"]
    tid = claims["tenant_id"]
    uid = claims["user_id"]

    # 2) 查表（有状态）：不存在/已吊销 → 401；replaced_by 非空 = 旧 token 重放 → 整族吊销
    row = await session.execute(
        text("SELECT revoked_at, replaced_by, expires_at FROM auth_refresh_tokens WHERE id=:j"),
        {"j": jti},
    )
    rt = row.first()
    if rt is None:
        raise HTTPException(status_code=401, detail="refresh token not found")
    if rt[0] is not None:
        raise HTTPException(status_code=401, detail="refresh token revoked")
    if rt[1] is not None:
        # 重放检测：旧 jti 已轮换 → 吊销整族（该用户全部未吊销 token）
        await session.execute(
            text("UPDATE auth_refresh_tokens SET revoked_at=now() WHERE user_id=:u AND revoked_at IS NULL"),
            {"u": uid},
        )
        await session.commit()
        log.warning("refresh replay detected, family revoked user=%s", uid)
        raise HTTPException(status_code=401, detail="refresh token replay detected, family revoked")

    # 3) 用户/租户仍有效？
    row = await session.execute(
        text("SELECT status FROM users WHERE id=:u AND tenant_id=:t AND deleted_at IS NULL"),
        {"u": uid, "t": tid},
    )
    u = row.first()
    if u is None or u[0] != "active":
        raise HTTPException(status_code=401, detail="user inactive")

    # 4) 轮换：旧 jti → replaced_by=新 jti；签发新双令牌
    new = crypto.issue_tokens(tid, uid, await _scopes_of(session, uid))
    import datetime as _dt

    expires_at = _dt.datetime.utcnow() + _dt.timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
    await session.execute(
        text(
            """
            INSERT INTO auth_refresh_tokens
              (id, tenant_id, user_id, token_hash, device_info, expires_at, created_by)
            VALUES (:id, :t, :u, :h, NULL, :e, :u)
            """
        ),
        {
            "id": new["refresh_jti"],
            "t": tid,
            "u": uid,
            "h": crypto.token_hash(new["refresh_token"]),
            "e": expires_at,
        },
    )
    await session.execute(
        text("UPDATE auth_refresh_tokens SET replaced_by=:n WHERE id=:j"),
        {"n": new["refresh_jti"], "j": jti},
    )
    await session.commit()
    return {
        "access_token": new["access_token"],
        "refresh_token": new["refresh_token"],
        "token_type": "Bearer",
        "expires_at": new["expires_at"],
    }


async def _scopes_of(session: AsyncSession, uid: str) -> list[str]:
    row = await session.execute(
        text(
            """
            SELECT DISTINCT s.code FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id AND r.deleted_at IS NULL
            JOIN role_scopes rs ON rs.role_id = r.id
            JOIN scopes s ON s.id = rs.scope_id
            WHERE ur.user_id = :u
            """
        ),
        {"u": uid},
    )
    scopes = [r[0] for r in row.fetchall()]
    row = await session.execute(
        text(
            "SELECT r.name FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
            "WHERE ur.user_id=:u AND r.deleted_at IS NULL"
        ),
        {"u": uid},
    )
    if "admin" in [r[0] for r in row.fetchall()] and "agent:use:*" not in scopes:
        scopes.append("agent:use:*")
    return scopes


@router.post("/logout")
async def logout(req: LogoutReq, session: AsyncSession = Depends(db_session), request: Request = None):
    """登出（BASE-05 验收 1：登出后令牌不可用）：
    a) refresh 吊销（DB revoked_at=now，有状态即时生效）；
    b) access token 未到期 → Redis 黑名单（TTL=剩余有效期，BFF 侧校验；
       S01 最小集下 BFF 未起，黑名单写入仍执行，BFF 切片消费）。
    """
    revoked = 0
    if req.refresh_token:
        try:
            claims = crypto.decode_refresh(req.refresh_token)
        except pyjwt.PyJWTError:
            claims = None
        if claims:
            r = await session.execute(
                text("UPDATE auth_refresh_tokens SET revoked_at=now() WHERE id=:j AND revoked_at IS NULL"),
                {"j": claims["jti"]},
            )
            revoked = r.rowcount

    # access token 黑名单（BUG-02 修复）：客户端 bearer 有效且未到期 →
    # deny_access(jti, 剩余TTL)。BFF 对公开前缀端点（logout）保留 Authorization
    # 头透传（gateway._forward），此处可直接解码；无效/过期 token 无需拉黑。
    auth_header = request.headers.get("authorization", "") if request else ""
    if auth_header.startswith("Bearer "):
        try:
            ac = crypto.decode_access(auth_header[7:])
            ttl = int(ac["exp"] - time.time())
            if ttl > 0:
                await redis_client.deny_access(ac["jti"], ttl)
        except pyjwt.PyJWTError:
            pass  # access 无效/过期：无需拉黑
    await session.commit()
    return {"ok": True, "refresh_revoked": revoked}


@router.post("/logout-all")
async def logout_all(auth: dict = Depends(auth_context), session: AsyncSession = Depends(db_session)):
    """BASE-09：重置密码/安全登出——吊销该用户全部 refresh token。"""
    r = await session.execute(
        text("UPDATE auth_refresh_tokens SET revoked_at=now() WHERE user_id=:u AND revoked_at IS NULL"),
        {"u": auth["user_id"]},
    )
    await session.commit()
    return {"ok": True, "revoked": r.rowcount}
