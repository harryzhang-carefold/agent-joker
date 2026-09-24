"""SkillsService（S06，SKILL-01/02）。

- 手动添加 skill（SKILL-01 验收 1）：name + content（prompt 文本/说明）+ description。
- 上传 skill 文件（SKILL-01 验收 2）：multipart 上传 → 经 StorageService 落存储
  （source=skill，SKILL-02 验收 2 上传记录可见来源=skill）；文本类文件内容同步进
  skills.content；多文件 = 1 个 main + N 个 asset（skill_files 清单）。
- 元数据存 DB（skills 表，SKILL-02 验收 1）；文件走存储模块（skill_files 引用
  storage_files，STORE-04 统一文件接口）。
- 删除（SKILL-02 验收 3 清理策略一致）：元数据软删 + skill_files 软删 +
  存储文件物理删除（经 StorageService.delete_file；被 rag_docs 引用的文件跳过并
  报告——与存储模块 409 语义一致，不静默丢数据）。
- 内容修改 version +1（DB_DESIGN §6.1）。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared.storage.service import get_storage_service

log = logging.getLogger("joker.skills")

# 文本类 content-type：上传时内容同步进 skills.content（SKILL-01 验收 2「skill 内容可见」）
_TEXT_CONTENT_TYPES = (
    "text/markdown", "text/plain", "text/x-markdown", "application/x-yaml",
    "application/json", "application/yaml",
)
_TEXT_EXTS = {".md", ".markdown", ".txt", ".yaml", ".yml", ".json"}


def _ser_skill(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    for k in ("id", "tenant_id", "created_by", "updated_by"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


class SkillsService:
    """skill 元数据 CRUD + 文件（存储模块）管理。"""

    async def _fetch_skill(self, session: AsyncSession, skill_id: str, tenant_id: str) -> Any:
        r = await session.execute(
            text("SELECT * FROM skills WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid) "
                 "AND deleted_at IS NULL"),
            {"id": skill_id, "t": tenant_id},
        )
        return r.first()

    async def list_skills(
        self, session: AsyncSession, tenant_id: str,
        status: str | None = None, source: str | None = None,
    ) -> dict:
        where = "WHERE tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"
        params: dict[str, Any] = {"t": tenant_id}
        if status in ("active", "disabled"):
            where += " AND status = :st"
            params["st"] = status
        if source in ("manual", "upload"):
            where += " AND source = :src"
            params["src"] = source
        r = await session.execute(
            text(f"SELECT * FROM skills {where} ORDER BY created_at"), params
        )
        items = [_ser_skill(row) for row in r.fetchall()]
        return {"items": items, "total": len(items)}

    async def get_skill(self, session: AsyncSession, skill_id: str, tenant_id: str) -> dict | None:
        row = await self._fetch_skill(session, skill_id, tenant_id)
        if row is None:
            return None
        d = _ser_skill(row)
        d["files"] = await self._files(session, skill_id)
        return d

    async def _files(self, session: AsyncSession, skill_id: str) -> list[dict]:
        r = await session.execute(
            text("SELECT id, file_id, file_name, role, created_at FROM skill_files "
                 "WHERE skill_id = CAST(:s AS uuid) AND deleted_at IS NULL ORDER BY created_at"),
            {"s": skill_id},
        )
        return [
            {"file_id": str(x[0]), "storage_file_id": str(x[1]), "file_name": x[2],
             "role": x[3], "created_at": x[4].isoformat() if x[4] else None}
            for x in r.fetchall()
        ]

    async def create_skill(self, session: AsyncSession, tenant_id: str, user_id: str | None, d: dict) -> dict:
        """手动添加（SKILL-01 验收 1）。必选 name + content；可选 description。"""
        name = (d.get("name") or "").strip()
        content = d.get("content")
        if not name:
            raise HTTPException(422, "name is required")
        if not content or not str(content).strip():
            raise HTTPException(422, "content is required (manual skill needs prompt text)")
        dup = await session.execute(
            text("SELECT 1 FROM skills WHERE tenant_id = CAST(:t AS uuid) AND name = :n AND deleted_at IS NULL"),
            {"t": tenant_id, "n": name},
        )
        if dup.first():
            raise HTTPException(409, f"skill name already exists: {name}")
        skill_id = str(uuid.uuid4())
        await session.execute(
            text(
                """INSERT INTO skills
                   (id, tenant_id, name, description, content, source, version, status, created_by, updated_by)
                   VALUES (:id, CAST(:t AS uuid), :n, :desc, :c, 'manual', 1, 'active', :by, :by)"""
            ),
            {"id": skill_id, "t": tenant_id, "n": name, "desc": d.get("description"),
             "c": str(content), "by": user_id},
        )
        await session.commit()
        return await self.get_skill(session, skill_id, tenant_id)  # type: ignore[return-value]

    async def upload_skill(
        self, session: AsyncSession, tenant_id: str, user_id: str | None,
        name: str, files: list[tuple[str, bytes, str | None]], description: str | None = None,
    ) -> dict:
        """上传 skill 文件（SKILL-01 验收 2 / SKILL-02 验收 2）。

        files: [(file_name, data, content_type)]。第一个=main（入口文件，如 SKILL.md，
        文本类内容同步进 skills.content）；其余=asset。文件经 StorageService 落存储
        （source=skill，上传记录可查来源=skill）。
        """
        name = (name or "").strip()
        if not name:
            raise HTTPException(422, "name is required")
        if not files:
            raise HTTPException(422, "at least one file is required")
        for fn, data, _ in files:
            if not fn or not data:
                raise HTTPException(422, f"invalid file (empty name or content): {fn!r}")
        dup = await session.execute(
            text("SELECT 1 FROM skills WHERE tenant_id = CAST(:t AS uuid) AND name = :n AND deleted_at IS NULL"),
            {"t": tenant_id, "n": name},
        )
        if dup.first():
            raise HTTPException(409, f"skill name already exists: {name}")

        skill_id = str(uuid.uuid4())
        storage = get_storage_service()
        # 预检同名文件（storage.upload 内部逐文件 commit；避免中途 409 留下孤儿文件）
        for fn, _, _ in files:
            r = await session.execute(
                text("SELECT 1 FROM storage_files WHERE tenant_id = CAST(:t AS uuid) AND file_name = :n "
                     "AND status <> 'deleted'"),
                {"t": tenant_id, "n": fn},
            )
            if r.first():
                raise HTTPException(409, f"file_name already exists in storage: {fn}")
        content: str | None = None
        file_count = 0
        # 先插 skills 行（skill_files FK→skills）；content/file_count 最后回写
        await session.execute(
            text(
                """INSERT INTO skills
                   (id, tenant_id, name, description, content, source, version, status, file_count,
                    created_by, updated_by)
                   VALUES (:id, CAST(:t AS uuid), :n, :desc, NULL, 'upload', 1, 'active', 0, :by, :by)"""
            ),
            {"id": skill_id, "t": tenant_id, "n": name, "desc": description, "by": user_id},
        )
        for i, (fn, data, ctype) in enumerate(files):
            role = "main" if i == 0 else "asset"
            rec = await storage.upload(
                session, tenant_id=tenant_id, user_id=user_id, file_name=fn,
                data=data, content_type=ctype, source="skill",
            )
            # text 类 main 文件：内容同步进 skills.content（skill 内容可见）
            if role == "main" and content is None and (
                (ctype or "").lower() in _TEXT_CONTENT_TYPES
                or fn.lower().rsplit(".", 1)[-1] in {e.lstrip(".") for e in _TEXT_EXTS}
            ):
                try:
                    content = data.decode("utf-8")
                except UnicodeDecodeError:
                    content = None
            await session.execute(
                text(
                    """INSERT INTO skill_files (id, tenant_id, skill_id, file_id, file_name, role, created_by, updated_by)
                       VALUES (gen_random_uuid(), CAST(:t AS uuid), CAST(:s AS uuid),
                               CAST(:f AS uuid), :n, :r, :by, :by)"""
                ),
                {"t": tenant_id, "s": skill_id, "f": rec["id"], "n": fn, "r": role, "by": user_id},
            )
            file_count += 1

        await session.execute(
            text("UPDATE skills SET content = :c, file_count = :fc WHERE id = CAST(:id AS uuid)"),
            {"c": content, "fc": file_count, "id": skill_id},
        )
        await session.commit()
        return await self.get_skill(session, skill_id, tenant_id)  # type: ignore[return-value]

    async def update_skill(
        self, session: AsyncSession, skill_id: str, tenant_id: str, user_id: str | None, d: dict
    ) -> dict:
        """更新 name/description/content/status。content 变更 → version+1（DB_DESIGN §6.1）。"""
        row = await self._fetch_skill(session, skill_id, tenant_id)
        if row is None:
            raise HTTPException(404, f"skill not found: {skill_id}")
        sets: list[str] = []
        params: dict[str, Any] = {"id": skill_id, "by": user_id}
        if "name" in d and d["name"] is not None:
            n = str(d["name"]).strip()
            if not n:
                raise HTTPException(422, "name must not be empty")
            dup = await session.execute(
                text("SELECT 1 FROM skills WHERE tenant_id = CAST(:t AS uuid) AND name = :n "
                     "AND id <> CAST(:id AS uuid) AND deleted_at IS NULL"),
                {"t": tenant_id, "n": n, "id": skill_id},
            )
            if dup.first():
                raise HTTPException(409, f"skill name already exists: {n}")
            sets.append("name = :name")
            params["name"] = n
        if "description" in d:
            sets.append("description = :desc")
            params["desc"] = d["description"]
        if "content" in d and d["content"] is not None:
            if not str(d["content"]).strip():
                raise HTTPException(422, "content must not be empty")
            sets.append("content = :c")
            params["c"] = str(d["content"])
            sets.append("version = version + 1")
        if "status" in d and d["status"] is not None:
            if d["status"] not in ("active", "disabled"):
                raise HTTPException(422, "status must be active|disabled")
            sets.append("status = :st")
            params["st"] = d["status"]
        if not sets:
            raise HTTPException(422, "no updatable fields provided")
        await session.execute(
            text(f"UPDATE skills SET {', '.join(sets)}, updated_by = :by WHERE id = CAST(:id AS uuid)"),
            params,
        )
        await session.commit()
        return await self.get_skill(session, skill_id, tenant_id)  # type: ignore[return-value]

    async def delete_skill(
        self, session: AsyncSession, skill_id: str, tenant_id: str, user_id: str | None
    ) -> dict:
        """删除（SKILL-02 验收 3）：元数据软删 + skill_files 软删 + 存储文件物理删除。

        被 rag_docs 引用的文件：跳过删除并在结果中列出（与存储模块 409 语义一致）。
        agent_skills 勾选行由 FK CASCADE 清理（S07 建 agent 时勾选后生效）。
        """
        row = await self._fetch_skill(session, skill_id, tenant_id)
        if row is None:
            raise HTTPException(404, f"skill not found: {skill_id}")
        files = await self._files(session, skill_id)
        storage = get_storage_service()
        deleted_files: list[str] = []
        skipped_files: list[str] = []
        for f in files:
            try:
                await storage.delete_file(session, tenant_id, f["file_name"])
                deleted_files.append(f["file_name"])
            except HTTPException as exc:
                if exc.status_code in (404, 409):
                    skipped_files.append(f["file_name"])
                else:
                    raise
        await session.execute(
            text("UPDATE skill_files SET deleted_at = now(), updated_by = :by "
                 "WHERE skill_id = CAST(:s AS uuid) AND deleted_at IS NULL"),
            {"by": user_id, "s": skill_id},
        )
        await session.execute(
            text("UPDATE skills SET deleted_at = now(), updated_by = :by WHERE id = CAST(:s AS uuid)"),
            {"by": user_id, "s": skill_id},
        )
        await session.commit()
        return {
            "ok": True, "deleted": skill_id,
            "files_deleted": deleted_files, "files_skipped": skipped_files,
            "message": (f"skill deleted; {len(deleted_files)} file(s) removed from storage"
                        + (f", {len(skipped_files)} skipped (referenced elsewhere)" if skipped_files else ""))
            if files else "skill deleted (no files)",
        }


_service: SkillsService | None = None


def get_skills_service() -> SkillsService:
    global _service
    if _service is None:
        _service = SkillsService()
    return _service
