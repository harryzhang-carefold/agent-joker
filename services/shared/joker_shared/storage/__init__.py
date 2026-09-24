"""存储模块（S02）：StorageBackend 策略适配层 + StorageService 统一文件访问接口。

- 三实现：LocalFS（默认，volume /data/storage）/ GCS / Aliyun OSS（DECISION-012 凭证走 env 注入不进库）
- 后端切换：env STORAGE_BACKEND=local|gcs|oss（重启生效，DECISION-027）
- 行级分派：storage_files.backend 记录每文件实际落点，访问按行分派（STORE-03 验收 3，
  保留原后端访问、不迁移）
"""
from joker_shared.storage.base import (
    StorageBackend,
    StorageConfigError,
    StorageError,
)
from joker_shared.storage.local import LocalFSBackend
from joker_shared.storage.gcs import GCSBackend
from joker_shared.storage.oss import OSSBackend
from joker_shared.storage.service import StorageService, get_storage_service

__all__ = [
    "StorageBackend",
    "StorageConfigError",
    "StorageError",
    "LocalFSBackend",
    "GCSBackend",
    "OSSBackend",
    "StorageService",
    "get_storage_service",
]
