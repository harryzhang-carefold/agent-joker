"""joker_shared — agent-joker 后端共享库（S01 骨架）。

模块：
- config：pydantic-settings 配置加载（.env 注入）
- db：SQLAlchemy 2.0 async（asyncpg）引擎 / 会话 / 租户行级过滤（DECISION-004）
- seed：启动种子（租户/角色/scope/用户 密码哈希补写）
- crypto：JWT 双令牌（DECISION-002）/ HMAC 内部签名（DECISION-009）/ bcrypt / Fernet
- redis_client：Redis 连接（黑名单/限流/缓存）
- audit：AuditLogService（BASE-06，异步写、失败不阻断）
"""

from joker_shared.config import settings

__all__ = ["settings"]
