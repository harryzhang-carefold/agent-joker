"""GCS 后端（Google Cloud Storage，STORE-02）。

凭证 = GCS_CREDENTIALS_PATH（service-account JSON 文件路径，compose 挂载）或
ADC（应用默认凭证）；bucket = GCS_BUCKET（DECISION-012：凭证走 env/挂载，不进 DB/日志）。

SDK 为可选依赖（google-cloud-storage，见 services/requirements-cloud.txt）：
未安装时构造即抛 StorageConfigError（→ API 503 明确配置错误，不崩溃）。
"""
from __future__ import annotations

from pathlib import Path

from joker_shared.config import settings
from joker_shared.storage.base import StorageBackend, StorageConfigError, StorageError


class GCSBackend(StorageBackend):
    name = "gcs"

    def __init__(
        self,
        bucket: str | None = None,
        credentials_path: str | None = None,
    ) -> None:
        self.bucket_name = bucket or settings.GCS_BUCKET
        self.credentials_path = credentials_path or settings.GCS_CREDENTIALS_PATH
        self._bucket = None
        self._client = self._init_client()

    def _init_client(self):
        if not self.bucket_name:
            raise StorageConfigError(
                "GCS backend not configured: set GCS_BUCKET in .env (DECISION-012)"
            )
        try:
            from google.cloud import storage  # type: ignore
        except ImportError as exc:
            raise StorageConfigError(
                "GCS backend not usable: python SDK 'google-cloud-storage' not installed "
                "(install from services/requirements-cloud.txt for cloud backends)"
            ) from exc
        if self.credentials_path:
            cp = Path(self.credentials_path)
            if not cp.is_file():
                raise StorageConfigError(
                    f"GCS credentials file not found: {self.credentials_path}"
                )
            import os

            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cp)
        client = storage.Client()
        self._client = client
        return client

    @property
    def bucket(self):
        if self._bucket is None:
            self._bucket = self._client.bucket(self.bucket_name)
        return self._bucket

    def put(self, key: str, data: bytes, content_type: str | None) -> str:
        try:
            blob = self.bucket.blob(key)
            blob.upload_from_string(data, content_type=content_type)
        except StorageConfigError:
            raise
        except Exception as exc:  # 云侧运行时错误 → 统一语义
            raise StorageError(f"gcs put failed: {exc}") from exc
        return key

    def get(self, key: str) -> bytes:
        try:
            blob = self.bucket.blob(key)
            if not blob.exists():
                raise StorageError(f"gcs object not found: {key!r}")
            return blob.download_as_bytes()
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"gcs get failed: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            blob = self.bucket.blob(key)
            if blob.exists():
                blob.delete()
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"gcs delete failed: {exc}") from exc

    def exists(self, key: str) -> bool:
        try:
            return self.bucket.blob(key).exists()
        except Exception:
            return False

    def describe(self) -> dict:
        return {
            "name": "gcs",
            "configured": True,
            "bucket": self.bucket_name,
            "credentials_path": self.credentials_path or "<ADC>",
        }
