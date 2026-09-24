"""StorageService：统一文件访问接口（STORE-04）+ 上传记录（STORE-05）+ 后端分派（STORE-03）。

设计要点：
- 租户内文件名唯一（UQ tenant_id+file_name）；同名上传 → 409（ARCH §9-10 裁定）
- 物理 key = `<tenant_id 前 8 位>/<file_name>`（本地）；gcs/oss 同 key 作 object key
- storage_files.backend 行级记录实际落点 → 后端切换后既有文件按行分派（STORE-03 验收 3）
- 每次上传（成功/失败/拒绝）写 storage_upload_records（STORE-05：任意来源留痕）
- 配额校验 tenants.storage_quota_mb（DB_DESIGN §2.1）
- 被 rag_docs 引用的文件禁删（DB_DESIGN §13.3 应用层 409）
- 同步 SDK 调用经 asyncio.to_thread 调度，不阻塞事件循环
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared.config import settings
from joker_shared.timeutil import parse_iso8601
from joker_shared.storage.base import (
    StorageBackend,
    StorageConfigError,
    StorageError,
)
from joker_shared.storage.gcs import GCSBackend
from joker_shared.storage.local import LocalFSBackend
from joker_shared.storage.oss import OSSBackend

log = logging.getLogger("joker.storage")

_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB 单文件上限【推测：闭环规模足够，超限 413】


class StorageService:
    """统一文件访问服务。后端按 settings.STORAGE_BACKEND 构造（重启生效，DECISION-027）。"""

    def __init__(self) -> None:
        self._backends: dict[str, StorageBackend] = {}
        # 默认后端不做构造期校验：配置不完整时由 backend() 在调用点抛
        # StorageConfigError → API 503 明确配置错误（而非服务崩溃，STORE-02 验收 2）

    def _init_default_backend(self) -> None:  # noqa: D401 - 保留为显式 no-op 入口
        return None

    def _build_backend(self, name: str) -> StorageBackend:
        if name == "local":
            return LocalFSBackend()
        if name == "gcs":
            return GCSBackend()
        if name == "oss":
            return OSSBackend()
        raise StorageConfigError(f"unknown STORAGE_BACKEND: {name!r} (local|gcs|oss)")

    def backend(self, name: str | None) -> StorageBackend:
        """按行内 backend 取实例（懒构造，支持混合后端：切换配置后旧文件仍可从原后端读）。"""
        key = (name or settings.STORAGE_BACKEND or "local").lower()
        if key not in self._backends:
            self._backends[key] = self._build_backend(key)
        return self._backends[key]

    def backend_status(self) -> list[dict]:
        out = []
        for n in ("local", "gcs", "oss"):
            try:
                self.backend(n)
                out.append(self.backend(n).describe())
            except StorageConfigError as exc:
                out.append({"name": n, "configured": False, "error": str(exc)})
        out.insert(0, {"active": (settings.STORAGE_BACKEND or "local").lower()})
        return out

    # ------------------------------------------------------------ 上传

    async def upload(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        user_id: str | None,
        file_name: str,
        data: bytes,
        content_type: str | None,
        source: str = "api",
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """上传文件 → storage_files + storage_upload_records（STORE-05 留痕）。

        错误语义：409 同名 / 413 超限 / 422 空文件 / 403 配额超限 / 503 后端配置错误。
        """
        file_name = (file_name or "").strip().lstrip("/")

        async def _reject(status_code: int, detail: str) -> None:
            """记录一条 failed 上传记录（STORE-05：拒绝也留痕）后抛出 HTTP 错误。"""
            rec_id = str(uuid.uuid4())
            try:
                await self._record(
                    session, rec_id, tenant_id, None, file_name or "(invalid)", source,
                    user_id, len(data) if data else 0, "failed", detail, agent_id,
                )
                await session.commit()
            except Exception:  # 记录失败不应掩盖原始错误语义
                log.warning("failed to write rejection upload record: %s", detail, exc_info=True)
            raise HTTPException(status_code, detail)

        if not file_name or file_name in (".", ".."):
            await _reject(422, "invalid file_name")
        if "/" in file_name or "\\" in file_name:
            await _reject(422, "file_name must not contain path separators")
        if not data:
            await _reject(422, "empty file")
        if len(data) > _MAX_UPLOAD_BYTES:
            await _reject(413, f"file exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit")

        # 配额校验（tenants.storage_quota_mb，DB_DESIGN §2.1）
        quota_mb = (
            await session.execute(
                text("SELECT storage_quota_mb FROM tenants WHERE id = CAST(:t AS uuid)"),
                {"t": tenant_id},
            )
        ).scalar_one_or_none()
        if quota_mb is not None:
            used = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(size_bytes), 0) FROM storage_files "
                        "WHERE tenant_id = CAST(:t AS uuid) AND status = 'ready'"
                    ),
                    {"t": tenant_id},
                )
            ).scalar_one()
            if used + len(data) > quota_mb * 1024 * 1024:
                await _reject(403, "storage quota exceeded")

        # 同名冲突（租户内唯一，ARCH §9-10）
        existing = (
            await session.execute(
                text(
                    "SELECT id FROM storage_files WHERE tenant_id = CAST(:t AS uuid) "
                    "AND file_name = :n AND status <> 'deleted'"
                ),
                {"t": tenant_id, "n": file_name},
            )
        ).first()
        if existing:
            await _reject(409, f"file_name already exists: {file_name}")

        key = f"{tenant_id[:8]}/{file_name}"
        backend_name = (settings.STORAGE_BACKEND or "local").lower()
        file_id = str(uuid.uuid4())

        def _put() -> str:
            return self.backend(backend_name).put(key, data, content_type)

        record_id = str(uuid.uuid4())
        try:
            await asyncio.to_thread(_put)
        except StorageConfigError as exc:
            await self._record(
                session, record_id, tenant_id, None, file_name, source, user_id,
                len(data), "failed", str(exc), agent_id,
            )
            await session.commit()
            raise HTTPException(503, f"storage backend not configured: {exc}") from exc
        except StorageError as exc:
            await self._record(
                session, record_id, tenant_id, None, file_name, source, user_id,
                len(data), "failed", str(exc), agent_id,
            )
            await session.commit()
            raise HTTPException(502, f"storage backend error: {exc}") from exc

        await session.execute(
            text(
                """INSERT INTO storage_files
                (id, tenant_id, file_name, content_type, size_bytes, backend,
                 storage_key, checksum_sha256, source, status, owner_user_id, created_by)
                VALUES (CAST(:id AS uuid), CAST(:t AS uuid), :n, CAST(:ct AS text), :sz, :b, :k, :ck, :s, 'ready',
                        CAST(:u AS uuid), CAST(:u AS uuid))"""
            ),
            {
                "id": file_id, "t": tenant_id, "n": file_name, "ct": content_type,
                "sz": len(data), "b": backend_name, "k": key,
                "ck": LocalFSBackend.checksum(data), "s": source, "u": user_id or None,
            },
        )
        await self._record(
            session, record_id, tenant_id, file_id, file_name, source, user_id,
            len(data), "success", None, agent_id,
        )
        await session.commit()
        log.info("storage upload ok tenant=%s file=%s backend=%s bytes=%d", tenant_id, file_name, backend_name, len(data))
        return {
            "id": file_id,
            "file_name": file_name,
            "size_bytes": len(data),
            "content_type": content_type,
            "backend": backend_name,
            "checksum_sha256": LocalFSBackend.checksum(data),
            "upload_record_id": record_id,
        }

    async def _record(
        self,
        session: AsyncSession,
        record_id: str,
        tenant_id: str,
        file_id: str | None,
        file_name: str,
        source: str,
        user_id: str | None,
        size: int,
        status: str,
        error: str | None,
        agent_id: str | None,
    ) -> None:
        await session.execute(
            text(
                """INSERT INTO storage_upload_records
                (id, tenant_id, file_id, file_name, source, uploader_user_id, agent_id,
                 size_bytes, status, error_message, created_by)
                VALUES (:id, CAST(:t AS uuid), CAST(:f AS uuid),
                        :n, :s,
                        CAST(:u AS uuid),
                        CAST(:a AS uuid),
                        :sz, :st, :e,
                        CAST(:u AS uuid))"""
            ),
            {
                "id": record_id, "t": tenant_id, "f": file_id, "n": file_name,
                "s": source, "u": user_id, "a": agent_id, "sz": size, "st": status, "e": error,
            },
        )

    # ------------------------------------------------------------ 查询 / 下载

    async def get_file_row(self, session: AsyncSession, tenant_id: str, file_name: str) -> dict | None:
        row = (
            await session.execute(
                text(
                    """SELECT id, tenant_id, file_name, content_type, size_bytes, backend,
                    storage_key, checksum_sha256, source, status, owner_user_id, created_at
                    FROM storage_files
                    WHERE tenant_id = CAST(:t AS uuid) AND file_name = :n
                      AND status <> 'deleted'"""
                ),
                {"t": tenant_id, "n": file_name},
            )
        ).first()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "tenant_id": str(row[1]),
            "file_name": row[2],
            "content_type": row[3],
            "size_bytes": row[4],
            "backend": row[5],
            "storage_key": row[6],
            "checksum_sha256": row[7],
            "source": row[8],
            "status": row[9],
            "owner_user_id": str(row[10]) if row[10] else None,
            "created_at": row[11].isoformat() if row[11] else None,
        }

    async def download(self, session: AsyncSession, tenant_id: str, file_name: str) -> tuple[dict, bytes]:
        """按 (租户, 文件名) 取内容：查行 → 按行内 backend 分派读取（STORE-03/04）。"""
        row = await self.get_file_row(session, tenant_id, file_name)
        if row is None:
            raise HTTPException(404, f"file not found: {file_name}")
        data = await asyncio.to_thread(self.backend(row["backend"]).get, row["storage_key"])
        return row, data

    async def list_files(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        prefix: str | None = None,
        status: str | None = None,
        source: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        where = ["tenant_id = CAST(:t AS uuid)"]
        params: dict[str, Any] = {"t": tenant_id, "ps": page_size, "off": (page - 1) * page_size}
        if prefix:
            where.append("file_name LIKE :p"); params["p"] = f"{prefix}%"
        if status:
            where.append("status = :st"); params["st"] = status
        if source:
            where.append("source = :s"); params["s"] = source
        wsql = " AND ".join(where)
        total = (await session.execute(
            text(f"SELECT count(*) FROM storage_files WHERE {wsql}"), params
        )).scalar_one()
        rows = await session.execute(
            text(
                f"""SELECT id, file_name, content_type, size_bytes, backend, source,
                       status, owner_user_id, checksum_sha256, created_at
                FROM storage_files WHERE {wsql}
                ORDER BY created_at DESC LIMIT :ps OFFSET :off"""
            ),
            params,
        )
        items = [
            {
                "id": str(r[0]), "file_name": r[1], "content_type": r[2],
                "size_bytes": r[3], "backend": r[4], "source": r[5], "status": r[6],
                "owner_user_id": str(r[7]) if r[7] else None,
                "checksum_sha256": r[8],
                "created_at": r[9].isoformat() if r[9] else None,
            }
            for r in rows.fetchall()
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def list_upload_records(
        self,
        session: AsyncSession,
        tenant_id: str,
        *,
        file_name: str | None = None,
        uploader_user_id: str | None = None,
        source: str | None = None,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        where = ["tenant_id = CAST(:t AS uuid)"]
        params: dict[str, Any] = {"t": tenant_id, "ps": page_size, "off": (page - 1) * page_size}
        if file_name:
            where.append("file_name LIKE :fn"); params["fn"] = f"%{file_name}%"
        if uploader_user_id:
            where.append("uploader_user_id = CAST(:u AS uuid)"); params["u"] = uploader_user_id
        if source:
            where.append("source = :s"); params["s"] = source
        if status:
            where.append("status = :st"); params["st"] = status
        if start:
            try:
                params["start"] = parse_iso8601(start)
            except ValueError:
                raise HTTPException(status_code=400, detail="invalid start (ISO8601)")
            where.append("created_at >= :start")
        if end:
            try:
                params["end"] = parse_iso8601(end)
            except ValueError:
                raise HTTPException(status_code=400, detail="invalid end (ISO8601)")
            where.append("created_at <= :end")
        wsql = " AND ".join(where)
        total = (await session.execute(
            text(f"SELECT count(*) FROM storage_upload_records WHERE {wsql}"), params
        )).scalar_one()
        rows = await session.execute(
            text(
                f"""SELECT id, file_id, file_name, source, uploader_user_id, agent_id,
                       size_bytes, status, error_message, created_at
                FROM storage_upload_records WHERE {wsql}
                ORDER BY created_at DESC LIMIT :ps OFFSET :off"""
            ),
            params,
        )
        items = [
            {
                "id": str(r[0]),
                "file_id": str(r[1]) if r[1] else None,
                "file_name": r[2], "source": r[3],
                "uploader_user_id": str(r[4]) if r[4] else None,
                "agent_id": str(r[5]) if r[5] else None,
                "size_bytes": r[6], "status": r[7], "error_message": r[8],
                "created_at": r[9].isoformat() if r[9] else None,
            }
            for r in rows.fetchall()
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # ------------------------------------------------------------ 删除

    async def delete_file(
        self, session: AsyncSession, tenant_id: str, file_name: str
    ) -> dict[str, Any]:
        row = await self.get_file_row(session, tenant_id, file_name)
        if row is None:
            raise HTTPException(404, f"file not found: {file_name}")
        # 被 RAG 文档引用 → 禁删（DB_DESIGN §13.3：应用层 409）
        refs = (
            await session.execute(
                text(
                    """SELECT count(*) FROM rag_docs
                    WHERE file_id = CAST(:f AS uuid) AND deleted_at IS NULL"""
                ),
                {"f": row["id"]},
            )
        ).scalar_one()
        if refs:
            raise HTTPException(409, f"file referenced by {refs} rag_docs; delete them first")
        try:
            await asyncio.to_thread(self.backend(row["backend"]).delete, row["storage_key"])
        except StorageConfigError as exc:
            raise HTTPException(503, f"storage backend not configured: {exc}") from exc
        except StorageError as exc:
            raise HTTPException(502, f"storage backend error: {exc}") from exc
        await session.execute(
            text(
                """UPDATE storage_files SET status = 'deleted', deleted_at = now()
                WHERE id = CAST(:f AS uuid) AND tenant_id = CAST(:t AS uuid)"""
            ),
            {"f": row["id"], "t": tenant_id},
        )
        await session.commit()
        return {"ok": True, "file_name": file_name, "file_id": row["id"]}


_service: StorageService | None = None


def get_storage_service() -> StorageService:
    global _service
    if _service is None:
        _service = StorageService()
    return _service
