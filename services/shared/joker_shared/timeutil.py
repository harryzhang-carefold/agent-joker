"""时间参数解析（BUG-03 修复）：ISO8601 字符串 → UTC aware datetime。

支持带 Z 后缀（2020-01-01T00:00:00Z）、带 offset（+08:00）、裸 UTC（无时区
后缀按 UTC 解释）三种常见形态。解析失败抛 ValueError（由调用方转 400）。
"""
from __future__ import annotations

from datetime import datetime, timezone


def parse_iso8601(value: str) -> datetime:
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
