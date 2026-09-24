"""密码学工具：bcrypt / JWT 双令牌（DECISION-002）/ HMAC 内部签名（DECISION-009）/ Fernet。"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from joker_shared.config import settings

ACCESS_TTL_SECONDS = settings.ACCESS_TOKEN_TTL_MINUTES * 60
REFRESH_TTL_SECONDS = settings.REFRESH_TOKEN_TTL_DAYS * 86400


# ---------------------------------------------------------------- bcrypt

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ---------------------------------------------------------------- JWT

def _jti() -> str:
    return str(uuid.uuid4())


def issue_tokens(tenant_id: str, user_id: str, scopes: list[str]) -> dict[str, Any]:
    """签发 access（15min 无状态）+ refresh（7d 有状态，落 auth_refresh_tokens）。

    返回 {access_token, refresh_token, refresh_jti, expires_at}。
    refresh_token 为 JWT（HS256，jti 写表；表内只存 SHA-256 哈希）。
    """
    now = int(time.time())
    access_claims: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "scopes": scopes,
        "type": "access",
        "jti": _jti(),
        "iat": now,
        "exp": now + ACCESS_TTL_SECONDS,
    }
    access = jwt.encode(access_claims, settings.JWT_SECRET, algorithm="HS256")

    refresh_jti = _jti()
    refresh_claims: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "type": "refresh",
        "jti": refresh_jti,
        "iat": now,
        "exp": now + REFRESH_TTL_SECONDS,
    }
    refresh = jwt.encode(refresh_claims, settings.JWT_SECRET, algorithm="HS256")

    return {
        "access_token": access,
        "refresh_token": refresh,
        "refresh_jti": refresh_jti,
        "expires_at": now + ACCESS_TTL_SECONDS,
        "access_jti": access_claims["jti"],
    }


def decode_access(token: str) -> dict[str, Any]:
    """校验 access token（HS256 + exp）。失败抛 jwt.PyJWTError。"""
    claims = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    if claims.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return claims


def decode_refresh(token: str) -> dict[str, Any]:
    claims = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    if claims.get("type") != "refresh":
        raise jwt.InvalidTokenError("not a refresh token")
    return claims


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- HMAC 内部签名（DECISION-009）

def build_internal_headers(tenant_id: str, user_id: str, scopes: list[str]) -> dict[str, str]:
    """BFF→API：构造 X-Auth-* 身份头 + X-Auth-Sig（HMAC-SHA256）。

    签名消息 = tenant|user|scopes_csv|nonce|ts（| 分隔，scopes 逗号连接）。
    """
    ts = int(time.time())
    nonce = secrets.token_hex(8)
    scopes_csv = ",".join(scopes)
    msg = f"{tenant_id}|{user_id}|{scopes_csv}|{nonce}|{ts}"
    sig = hmac.new(settings.INTERNAL_HMAC_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Auth-Tenant": tenant_id,
        "X-Auth-User": user_id,
        "X-Auth-Scopes": scopes_csv,
        "X-Auth-Nonce": nonce,
        "X-Auth-Ts": str(ts),
        "X-Auth-Sig": sig,
    }


_REQ = object()  # sentinel：默认=必填（缺失抛 KeyError）


def _hget(headers: dict[str, str], key: str, default=_REQ) -> str:
    """大小写不敏感的 header 取值（Starlette headers dict 键为小写，
    但签名头约定为混合大小写；统一小写比较，兼容两种来源）。
    - 不传 default（必填）：缺失抛 KeyError（→ 401 缺头诊断）。
    - 传 default（可选）：缺失返回 default。"""
    lk = key.lower()
    for k, v in headers.items():
        if k.lower() == lk:
            return v
    if default is _REQ:
        raise KeyError(key)
    return default


def verify_internal_headers(headers: dict[str, str]) -> tuple[str, str, list[str]]:
    """PlatformAPI 侧校验 X-Auth-* + X-Auth-Sig。

    通过返回 (tenant_id, user_id, scopes)；**只信签名头中的 tenant，不信请求体**
    （BFF-09 验收 3）。任何缺失/签名不符/过期 → 抛 InternalAuthError（→ 401）。
    """
    try:
        tenant = _hget(headers, "X-Auth-Tenant")
        user = _hget(headers, "X-Auth-User")
        scopes_csv = _hget(headers, "X-Auth-Scopes", "")
        nonce = _hget(headers, "X-Auth-Nonce")
        ts = int(_hget(headers, "X-Auth-Ts"))
        sig = _hget(headers, "X-Auth-Sig")
    except (KeyError, ValueError) as exc:
        raise InternalAuthError(f"missing/invalid X-Auth-* header: {exc}") from exc

    if abs(int(time.time()) - ts) > settings.INTERNAL_HMAC_MAX_SKEW_SECONDS:
        raise InternalAuthError("X-Auth-Ts out of skew window")
    if not nonce or len(nonce) < 8:
        raise InternalAuthError("invalid X-Auth-Nonce")

    msg = f"{tenant}|{user}|{scopes_csv}|{nonce}|{ts}"
    expected = hmac.new(settings.INTERNAL_HMAC_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise InternalAuthError("X-Auth-Sig mismatch")

    return tenant, user, [s for s in scopes_csv.split(",") if s]


class InternalAuthError(Exception):
    """内部 HMAC 鉴权失败（→ 401）。"""


# ---------------------------------------------------------------- Fernet（DECISION-012）

_fernet: Fernet | None = None


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.FERNET_KEY or ""
        if len(key) != 44 or not _is_base64url(key):
            # 空=自测环境随机生成；非法值（如误填）=启动告警并重新生成，
            # 避免崩溃（S03：LLM 节点 Fernet 加密首次真正启用时暴露此隐患）
            if key:
                logging.getLogger("joker.crypto").warning(
                    "FERNET_KEY invalid (len=%s, not 44-char urlsafe base64); generating a new one",
                    len(key),
                )
            key = Fernet.generate_key().decode("utf-8")
        _fernet = Fernet(key.encode("utf-8"))
    return _fernet


def _is_base64url(s: str) -> bool:
    import base64
    try:
        base64.urlsafe_b64decode(s)
        return True
    except Exception:
        return False


def encrypt_secret(plain: str) -> str:
    return get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(blob: str) -> str:
    try:
        return get_fernet().decrypt(blob.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("invalid ciphertext (FERNET_KEY mismatch?)")


def dumps_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
