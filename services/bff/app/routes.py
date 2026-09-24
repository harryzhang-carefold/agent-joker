"""BFF 配置化路由（BFF-03，DECISION-014）：路径前缀 → 目标服务 + 路径模板。

- 启动加载 `BFF_ROUTES_FILE`（YAML）；文件缺省/未配置 → 内置默认路由表（见 _DEFAULT_ROUTES）。
- 热加载 API（POST /api/bff/routes/reload，平台级权限）：重新读文件并原子替换内存路由表，
  新增模块端点**无需改 BFF 代码**（BFF-03 验收 3）。
- 匹配：按前缀长度降序取最长匹配前缀；命中则按 `path_template` 重写转发路径，
  未命中 → 404（ARCH §4.1 ④）。
- 路由目标 = 服务 base（`target: platformapi` → BFF_PLATFORM_API_BASE）+ 前缀剥离/模板替换。

路由表结构（routes.yml）::

    routes:
      - prefix: /api/
        target: platformapi        # platformapi → BFF_PLATFORM_API_BASE
        strip_prefix: true         # 转发时剥离匹配前缀（默认保留，见下）
        path_template: ""          # 可选：转发路径模板，{path} = 匹配后的剩余路径
      - prefix: /v1/
        target: bff-local          # 特殊：BFF 本地处理（OpenAI 兼容 /mcp 不在此表）
"""
from __future__ import annotations

import copy
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from joker_shared.config import settings

log = logging.getLogger("joker.bff.routes")

# 内置默认路由表（routes.yml 未配置时的兜底；保证新增端点不改代码也可用）。
# 平台 API（/api/*、/internal/*）统一转发到 PlatformAPI；BFF 本地端点（/v1/*, /mcp, /healthz,
# /api/bff/*）由 BFF 自身处理（不进转发表）。
_DEFAULT_ROUTES: list[dict[str, Any]] = [
    {"prefix": "/api/", "target": "platformapi", "strip_prefix": False},
    {"prefix": "/internal/", "target": "platformapi", "strip_prefix": False},
]

# 特殊 target：BFF 本地处理（不进上游转发）
TARGET_LOCAL = "bff-local"


@dataclass
class Route:
    prefix: str
    target: str
    strip_prefix: bool = False
    path_template: str = ""

    def matches(self, path: str) -> bool:
        return path.startswith(self.prefix)

    def build_upstream_path(self, path: str) -> str:
        """匹配后剩余路径 + 模板替换 → 转发路径。"""
        rest = path[len(self.prefix):]
        if self.path_template:
            return self.path_template.replace("{path}", rest)
        if self.strip_prefix:
            return "/" + rest if rest else "/"
        return path  # 保留原路径（target base 不含前缀时直接用）


class RouteTable:
    """内存路由表（线程安全原子替换）。"""

    def __init__(self, routes: list[Route]) -> None:
        self._routes: list[Route] = list(routes)
        self._lock = threading.Lock()
        self._reorder()

    def _reorder(self) -> None:
        # 前缀长者优先（最长前缀匹配，避免 /api/ 吞掉 /api/bff/）
        self._routes.sort(key=lambda r: len(r.prefix), reverse=True)

    def get(self, path: str) -> Route | None:
        with self._lock:
            for r in self._routes:
                if r.matches(path):
                    return r
        return None

    def replace(self, routes: list[Route]) -> None:
        with self._lock:
            self._routes = list(routes)
            self._reorder()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"prefix": r.prefix, "target": r.target,
                 "strip_prefix": r.strip_prefix, "path_template": r.path_template}
                for r in self._routes
            ]


def _parse(raw: list[dict[str, Any]]) -> list[Route]:
    out: list[Route] = []
    for item in raw or []:
        prefix = str(item.get("prefix") or "").rstrip()
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        out.append(Route(
            prefix=prefix,
            target=str(item.get("target") or "platformapi"),
            strip_prefix=bool(item.get("strip_prefix", False)),
            path_template=str(item.get("path_template") or ""),
        ))
    return out


class Router:
    """配置化路由管理器（启动加载 + 热加载，DECISION-014）。"""

    def __init__(self) -> None:
        self.file: str = settings.BFF_ROUTES_FILE or ""
        self.table: RouteTable
        self.source: str = "default"
        self._load()

    def _load(self) -> None:
        if self.file and Path(self.file).exists():
            try:
                data = yaml.safe_load(Path(self.file).read_text(encoding="utf-8")) or {}
                routes = _parse(data.get("routes") or [])
                if routes:
                    self.table = RouteTable(routes)
                    self.source = self.file
                    log.info("routes loaded from %s (%d routes)", self.file, len(routes))
                    return
                log.warning("routes file %s empty; using default routes", self.file)
            except Exception as exc:
                log.exception("routes file %s parse failed; using default routes", self.file)
        self.table = RouteTable(copy.deepcopy(_DEFAULT_ROUTES))
        self.source = "default"

    def reload(self) -> dict[str, Any]:
        """热加载（平台级权限端点调用）：重读文件并原子替换。失败 → 保持旧表 + 报错。"""
        if not (self.file and Path(self.file).exists()):
            raise FileNotFoundError(f"routes file not found: {self.file or '(unset)'}")
        data = yaml.safe_load(Path(self.file).read_text(encoding="utf-8")) or {}
        routes = _parse(data.get("routes") or [])
        if not routes:
            raise ValueError("routes file has no valid routes")
        self.table.replace(routes)
        self.source = self.file
        log.info("routes hot-reloaded from %s (%d routes)", self.file, len(routes))
        return {"source": self.source, "count": len(routes), "routes": self.table.snapshot()}


_router: Router | None = None


def get_router() -> Router:
    global _router
    if _router is None:
        _router = Router()
    return _router
