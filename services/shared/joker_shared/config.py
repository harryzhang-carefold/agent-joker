"""配置加载（pydantic-settings，.env 注入）。

对应 ARCHITECTURE §5.3 环境变量表。所有变量均有默认值，
.env.example 只提供变量名与占位（不含真实密钥，DECISION-012）。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 基础设施连接 ---
    DB_DSN: str = "postgresql+asyncpg://joker:joker@pg:5432/joker"
    REDIS_URL: str = "redis://redis:6379/0"

    # --- 认证（DECISION-002：HS256 单密钥，BFF 与 AuthService 共享） ---
    JWT_SECRET: str = "dev-only-jwt-secret-change-me"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 7

    # --- BFF→API 内部鉴权（DECISION-009） ---
    INTERNAL_HMAC_SECRET: str = "dev-only-hmac-secret-change-me"
    INTERNAL_HMAC_MAX_SKEW_SECONDS: int = 300

    # --- BFF 网关（S08） ---
    BFF_PLATFORM_API_BASE: str = "http://api:8001"   # PlatformMCPServer 代执行内部 API 的目标
    BFF_MCP_URL: str = "http://bff:8000/mcp"         # 平台内置 MCP server（PlatformMCPServer）端点（S06 注册行 url）
    BFF_PROXY_TIMEOUT: float = 120.0       # 路由转发/上游调用超时（秒）
    BFF_RL_CACHE_TTL: int = 10             # 限流阈值 Redis 镜像 TTL（秒；运行时调整 ≤10s 生效，DECISION-013）
    # BFF 侧 DB（限流配置 bff_rate_limit_configs + agent 解析 + trace 写点；S08 起 BFF 直连）
    BFF_DB_DSN: str = ""                   # 空=回退 DB_DSN
    BFF_MAX_TOOL_ROUNDS: int = 8           # 第三方 agent tool-calling 最大轮次（DECISION-008）

    # --- MCP 注册（S06，MCP-01/02/03，DECISION-010/011） ---
    MCP_PROBE_TIMEOUT_SECONDS: float = 10.0          # 注册/刷新时 tools/list 探测超时
    MCP_TOOL_CACHE_TTL: int = 600                    # 工具 schema Redis 缓存 TTL（10min，DB_DESIGN §11）

    # --- 存储（S01：配置文件可配置，后端切换=保留原后端访问） ---
    STORAGE_BACKEND: str = "local"          # local / gcs / oss
    STORAGE_LOCAL_PATH: str = "/data/storage"
    GCS_BUCKET: str = ""
    GCS_CREDENTIALS_PATH: str = ""
    OSS_ENDPOINT: str = ""
    OSS_BUCKET: str = ""
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""

    # --- 限流默认值（DECISION-013） ---
    BFF_RATE_LIMIT_TENANT_QPS: int = 50
    BFF_RATE_LIMIT_USER_QPS: int = 10
    BFF_RATE_LIMIT_LOGIN_IP_PER_MIN: int = 5
    BFF_ROUTES_FILE: str = ""              # 配置化路由表路径（BFF 切片使用）

    # --- Obsidian 沉淀（DECISION-019） ---
    OBSIDIAN_VAULT_PATH: str = "/data/obsidian-vault"

    # --- 保留策略（D-D / DECISION-025，用户裁定 2026-09-22） ---
    TRACE_RETENTION_DAYS: int = 90
    AUDIT_RETENTION_DAYS: int = 90
    # 定期清理任务检查间隔（小时）：每周期读当前保留天数 DROP 过期月分区（S09）
    RETENTION_CHECK_INTERVAL_HOURS: int = 1

    # --- LLM 节点（S03，LLM-01/02/03） ---
    # 端点配置化：.env 提供默认端点（供自测闭环）；CRUD 后即时生效。
    LLM_FALLBACK_ENDPOINT: str = ""          # 默认 chat 推理端点 base_url（OpenAI 兼容 /v1）
    LLM_FALLBACK_MODEL: str = ""             # 默认 chat 模型标识
    LLM_FALLBACK_API_KEY: str = ""           # 默认 chat API key（Fernet 加密落 DB，DECISION-012）
    LLM_FALLBACK_NAME: str = "platform-fallback-llm"
    # 本地 fallback embedding（确定性 n-gram 哈希，真实 embedding 端点不可用时闭环）
    LLM_LOCAL_FALLBACK_DIM: int = 256        # 向量维度（可配）
    LLM_LOCAL_FALLBACK_NGRAM: int = 3        # n-gram 大小
    LLM_PROBE_TIMEOUT_SECONDS: float = 15.0  # 连通性探测超时
    LLM_EMBEDDING_API_BASE: str = ""         # 默认 embedding 端点 base_url（可空）
    LLM_RERANKER_API_BASE: str = ""          # 默认 reranker 端点 base_url（可空）

    # --- 加密（DECISION-012：DB 凭证字段 Fernet 加密） ---
    FERNET_KEY: str = ""                   # 空=启动时生成随机（自测环境）

    # --- 自测种子（S01 验收用） ---
    SEED_TENANT_CODE: str = "acme"
    SEED_ADMIN_USERNAME: str = "admin"
    SEED_ADMIN_PASSWORD: str = "acme123"

    # --- 日志 ---
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
