"""StorageBackend 抽象接口（STORE-01..04 后端抽象层）。

统一语义：
- key = 后端内定位键（local=相对路径 `<tenant8>/<file_name>`；gcs/oss=bucket 内 object key）
- put/get 以 bytes 为单位（自测/闭环规模足够；大文件流式优化留迭代，见 DEV_REPORT_S02）
- 实现为同步 SDK 调用，由 StorageService 通过线程池调度（不阻塞事件循环）
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class StorageError(Exception):
    """存储操作失败（物理文件缺失、SDK 运行时错误等）。"""


class StorageConfigError(StorageError):
    """后端配置不完整（缺 bucket/endpoint/凭证路径等）——返回明确配置错误而非崩溃。"""


class StorageBackend(ABC):
    """后端策略接口。name 与 storage_files.backend 枚举一致：local / gcs / oss。"""

    name: str = "abstract"

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str | None) -> str:
        """写入对象，返回实际存储 key。key 冲突（同名覆盖由服务层控制，不在后端做）。"""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """读取对象内容；不存在抛 StorageError。"""

    @abstractmethod
    def delete(self, key: str) -> None:
        """删除对象；不存在时静默（幂等）。"""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """对象是否存在。"""

    def describe(self) -> dict:
        """配置摘要（不含凭证，用于 /api/storage/backends 展示）。"""
        return {"name": self.name, "configured": True}
