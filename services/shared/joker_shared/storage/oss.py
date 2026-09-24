"""Aliyun OSS 后端（阿里云对象存储，STORE-02）。

凭证 = OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET + OSS_ENDPOINT / OSS_BUCKET
（DECISION-012：env 注入，不进 DB/日志）。

SDK 为可选依赖（oss2，见 services/requirements-cloud.txt）：
未安装时构造即抛 StorageConfigError（→ API 503 明确配置错误，不崩溃）。
"""
from __future__ import annotations

from joker_shared.config import settings
from joker_shared.storage.base import StorageBackend, StorageConfigError, StorageError


class OSSBackend(StorageBackend):
    name = "oss"

    def __init__(
        self,
        endpoint: str | None = None,
        bucket: str | None = None,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
    ) -> None:
        self.endpoint = endpoint or settings.OSS_ENDPOINT
        self.bucket_name = bucket or settings.OSS_BUCKET
        self.access_key_id = access_key_id or settings.OSS_ACCESS_KEY_ID
        self.access_key_secret = access_key_secret or settings.OSS_ACCESS_KEY_SECRET
        self._bucket = None
        self._init_bucket()

    def _init_bucket(self) -> None:
        missing = [
            n
            for n, v in (
                ("OSS_ENDPOINT", self.endpoint),
                ("OSS_BUCKET", self.bucket_name),
                ("OSS_ACCESS_KEY_ID", self.access_key_id),
                ("OSS_ACCESS_KEY_SECRET", self.access_key_secret),
            )
            if not v
        ]
        if missing:
            raise StorageConfigError(
                "OSS backend not configured: missing env " + ", ".join(missing)
            )
        try:
            import oss2  # type: ignore
        except ImportError as exc:
            raise StorageConfigError(
                "OSS backend not usable: python SDK 'oss2' not installed "
                "(install from services/requirements-cloud.txt for cloud backends)"
            ) from exc
        auth = oss2.Auth(self.access_key_id, self.access_key_secret)
        self._bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)

    def put(self, key: str, data: bytes, content_type: str | None) -> str:
        try:
            headers = {"Content-Type": content_type} if content_type else None
            self._bucket.put_object(key, data, headers=headers)
        except StorageConfigError:
            raise
        except Exception as exc:
            raise StorageError(f"oss put failed: {exc}") from exc
        return key

    def get(self, key: str) -> bytes:
        try:
            return self._bucket.get_object(key).read()
        except StorageConfigError:
            raise
        except Exception as exc:
            raise StorageError(f"oss get failed: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            self._bucket.delete_object(key)
        except StorageConfigError:
            raise
        except Exception as exc:
            raise StorageError(f"oss delete failed: {exc}") from exc

    def exists(self, key: str) -> bool:
        try:
            return self._bucket.object_exists(key)
        except Exception:
            return False

    def describe(self) -> dict:
        return {
            "name": "oss",
            "configured": True,
            "endpoint": self.endpoint,
            "bucket": self.bucket_name,
        }
