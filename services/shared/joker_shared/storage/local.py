"""LocalFS 后端（默认）：文件落盘 STORAGE_LOCAL_PATH（compose volume /data/storage）。

key 布局（DB_DESIGN §2.1）：`<tenant_id 前 8 位>/<file_name>`。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

from joker_shared.config import settings
from joker_shared.storage.base import StorageBackend, StorageError


class LocalFSBackend(StorageBackend):
    name = "local"

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.STORAGE_LOCAL_PATH)

    def _path(self, key: str) -> Path:
        # 防路径穿越：key 内不允许 .. 与绝对路径
        if not key or key.startswith("/") or ".." in key:
            raise StorageError(f"invalid storage key: {key!r}")
        return self.root / key

    def put(self, key: str, data: bytes, content_type: str | None) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # 原子写：临时文件 + rename，避免半截文件
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".joker-tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return key

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not p.is_file():
            raise StorageError(f"local file not found: {key!r}")
        return p.read_bytes()

    def delete(self, key: str) -> None:
        p = self._path(key)
        try:
            p.unlink()
        except FileNotFoundError:
            pass

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def describe(self) -> dict:
        return {"name": "local", "configured": True, "root": str(self.root)}

    @staticmethod
    def checksum(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
