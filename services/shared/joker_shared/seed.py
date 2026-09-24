"""启动种子（幂等）：
1. 应用 init_schema.sql（34 表 + 分区 + 动态表函数 + 基础种子）；
2. 保证自测租户存在：acme + globex（跨租户隔离验收用），各含
   内置角色（admin/member）+ admin 用户（bcrypt 密码，SQL 内不可生成，占位补写）。

asyncpg 不支持单条 prepare 里放多条语句，因此这里用一个
``$$`` / 字符串 / 注释 感知的分割器把脚本拆成独立语句逐条执行。
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import text

from joker_shared.config import settings
from joker_shared.crypto import hash_password
from joker_shared.db import get_engine

log = logging.getLogger("joker.seed")

SCHEMA_FILE = Path(__file__).parent / "db" / "init_schema.sql"

SYSTEM_TENANT = "00000000-0000-0000-0000-000000000001"

# 自测租户（code → name）；S01 验收需要两个业务租户验证跨租户隔离
SEED_TENANTS: dict[str, str] = {
    "acme": "Acme",
    "globex": "Globex",
}


def split_sql_statements(sql: str) -> list[str]:
    """把 SQL 脚本拆成独立语句。

    感知：
    - 单引号字符串（'' 转义）
    - ``--`` 行注释
    - ``/* */`` 块注释
    - ``$$ ... $$`` plpgsql 体（内含分号不是边界）
    以分号（处于"裸"状态）作为语句边界。
    """
    out: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_squote = False
    in_dquote = False
    in_line = False
    in_block = False
    in_dollar = False

    def flush() -> None:
        s = "".join(buf).strip()
        if s:
            out.append(s)
        buf.clear()

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line:
            buf.append(ch)
            if ch == "\n":
                in_line = False
            i += 1
            continue
        if in_block:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append("/")
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_dollar:
            buf.append(ch)
            if ch == "$" and nxt == "$":
                buf.append("$")
                in_dollar = False
                i += 2
                continue
            i += 1
            continue
        if in_squote:
            buf.append(ch)
            if ch == "'":
                if nxt == "'":
                    buf.append(nxt)
                    i += 2
                    continue
                in_squote = False
            i += 1
            continue
        if in_dquote:
            buf.append(ch)
            if ch == '"':
                in_dquote = False
            i += 1
            continue

        # 裸状态
        if ch == "-" and nxt == "-":
            in_line = True
            buf.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            buf.append(ch)
            i += 1
            continue
        if ch == "'":
            in_squote = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_dquote = True
            buf.append(ch)
            i += 1
            continue
        if ch == "$" and nxt == "$":
            in_dollar = True
            buf.append(ch)
            buf.append(nxt)
            i += 2
            continue
        if ch == ";":
            flush()
            i += 1
            continue
        buf.append(ch)
        i += 1

    flush()
    return out


async def apply_schema() -> None:
    """执行 init_schema.sql（逐句、单事务；脚本幂等可重复执行）。"""
    engine = get_engine()
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    statements = split_sql_statements(sql)
    async with engine.begin() as conn:
        for st in statements:
            await conn.execute(text(st))
    log.info("init_schema.sql applied (%d statements, idempotent)", len(statements))


async def ensure_seed_users() -> None:
    """每个自测租户：补租户/内置角色/admin 用户（密码 = SEED_ADMIN_PASSWORD，幂等）。

    另为 system 租户补平台管理员用户（S17/BUG-07）：
    username = SEED_PLATFORM_ADMIN_USERNAME（默认 platform），
    密码 = SEED_ADMIN_PASSWORD，绑定 system 租户内置 admin 角色。
    平台管理员登录后（tenant_id=系统租户）即可使用「租户管理」（/api/tenants）。
    """
    engine = get_engine()
    pw = hash_password(settings.SEED_ADMIN_PASSWORD)
    async with engine.begin() as conn:
        # 1) 补写 init_schema.sql 的占位哈希
        await conn.execute(
            text("UPDATE users SET password_hash=:pw WHERE password_hash='$2b$12$REPLACE_BY_BOOTSTRAP'"),
            {"pw": pw},
        )
        for code, name in SEED_TENANTS.items():
            # 2) 租户
            row = await conn.execute(text("SELECT id FROM tenants WHERE code=:c"), {"c": code})
            t = row.first()
            if t is None:
                tid = str(uuid.uuid4())
                await conn.execute(
                    text("INSERT INTO tenants (id, name, code, status, plan, storage_quota_mb) "
                         "VALUES (:id, :n, :c, 'active', 'free', 1024)"),
                    {"id": tid, "n": name, "c": code},
                )
                t = (tid,)
            tid = str(t[0])
            # 3) 内置角色
            for rn, desc in (("admin", "租户管理员"), ("member", "普通成员")):
                row = await conn.execute(
                    text("SELECT id FROM roles WHERE tenant_id=:t AND name=:n AND deleted_at IS NULL"),
                    {"t": tid, "n": rn},
                )
                role = row.first()
                if role is None:
                    rid = str(uuid.uuid4())
                    await conn.execute(
                        text("INSERT INTO roles (id, tenant_id, name, description, is_builtin) "
                             "VALUES (:id, :t, :n, :d, true)"),
                        {"id": rid, "t": tid, "n": rn, "d": desc},
                    )
                    role = (rid,)
                if rn == "admin":
                    # admin 绑全部平台级 scope（平台级 scope 行由 schema 种子保证存在）
                    await conn.execute(
                        text("INSERT INTO role_scopes (role_id, scope_id) "
                             "SELECT :r, id FROM scopes WHERE tenant_id IS NULL ON CONFLICT DO NOTHING"),
                        {"r": role[0]},
                    )
            # 4) admin 用户
            row = await conn.execute(
                text("SELECT id, password_hash FROM users WHERE tenant_id=:t AND username=:u AND deleted_at IS NULL"),
                {"t": tid, "u": settings.SEED_ADMIN_USERNAME},
            )
            u = row.first()
            if u is None:
                uid = str(uuid.uuid4())
                await conn.execute(
                    text("INSERT INTO users (id, tenant_id, username, password_hash, display_name, status) "
                         "VALUES (:id, :t, :u, :pw, :dn, 'active')"),
                    {"id": uid, "t": tid, "u": settings.SEED_ADMIN_USERNAME, "pw": pw, "dn": f"{code} admin"},
                )
                row = await conn.execute(
                    text("SELECT id FROM roles WHERE tenant_id=:t AND name='admin' AND deleted_at IS NULL"),
                    {"t": tid},
                )
                role = row.first()
                if role:
                    await conn.execute(
                        text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r) ON CONFLICT DO NOTHING"),
                        {"u": uid, "r": role[0]},
                    )
                log.info("seed user %s@%s created", settings.SEED_ADMIN_USERNAME, code)
            elif "REPLACE_BY_BOOTSTRAP" in (u[1] or ""):
                await conn.execute(
                    text("UPDATE users SET password_hash=:pw WHERE id=:id"),
                    {"pw": pw, "id": u[0]},
                )

        # 5) 平台管理员（system 租户，S17/BUG-07；init_schema.sql 已建 system 租户
        #    + 内置 admin/member 角色并绑平台级 scope，这里只补用户行 + 角色绑定，幂等）
        await _ensure_platform_admin(conn, pw)


async def _ensure_platform_admin(conn, pw: str) -> None:
    """system 租户平台管理员用户（幂等）：不存在则创建并绑 admin 角色。"""
    row = await conn.execute(text("SELECT id FROM tenants WHERE code='system'"))
    t = row.first()
    if t is None:
        log.warning("system tenant missing; skip platform admin seed")
        return
    tid = str(t[0])
    uname = settings.SEED_PLATFORM_ADMIN_USERNAME
    row = await conn.execute(
        text("SELECT id, password_hash FROM users WHERE tenant_id=:t AND username=:u AND deleted_at IS NULL"),
        {"t": tid, "u": uname},
    )
    u = row.first()
    if u is None:
        uid = str(uuid.uuid4())
        await conn.execute(
            text("INSERT INTO users (id, tenant_id, username, password_hash, display_name, status) "
                 "VALUES (:id, :t, :u, :pw, :dn, 'active')"),
            {"id": uid, "t": tid, "u": uname, "pw": pw, "dn": "平台管理员"},
        )
        row = await conn.execute(
            text("SELECT id FROM roles WHERE tenant_id=:t AND name='admin' AND deleted_at IS NULL"),
            {"t": tid},
        )
        role = row.first()
        if role:
            await conn.execute(
                text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r) ON CONFLICT DO NOTHING"),
                {"u": uid, "r": role[0]},
            )
        log.info("seed platform admin user %s@system created", uname)
    elif "REPLACE_BY_BOOTSTRAP" in (u[1] or ""):
        await conn.execute(
            text("UPDATE users SET password_hash=:pw WHERE id=:id"),
            {"pw": pw, "id": u[0]},
        )


async def seed_all() -> None:
    await apply_schema()
    await ensure_seed_users()
