# agent-joker — 生产部署指南（PROD_DEPLOY）

> 适用：单机 Docker Compose 生产部署（ARCHITECTURE §5.2 拓扑）。
> 与自测环境（README.md）的差异在 §7 逐项列明。自测口径 = 闭环可演示；**生产口径 = 安全 + 可恢复 + 真实 LLM**。

## 1. 服务器要求

| 项 | 最低 | 建议 |
|---|---|---|
| OS | Linux x86_64（Debian 12+/Ubuntu 22.04+ 已验证 13） | 同左 |
| Docker | Engine 24+ 与 Compose v2（`docker compose version` 必须能跑） | 29.x |
| CPU | 4 核 | 8 核 |
| 内存 | 6 GB（容器限额合计 ~3.6G + 构建期 node22 峰值） | 16 GB |
| 磁盘 | 30 GB（镜像 ~8G + 数据卷增长 + 日志） | 100 GB SSD |
| 网络 | 可出公网（拉镜像/调 LLM）；8080 入口需对外可达 | 前置 LB/反代 + TLS |

端口规划（宿主）：
- `8080` → webconsole（唯一业务入口：前端 + /api + /v1 + /mcp）
- `8000` → bff 直连（**生产建议防火墙关闭**，仅保留 8080）
- `9100/9200/9301` → mock 资产（**生产不启动**，无 `--profile mocks` 即不存在）
- pg(5432)/redis(6379) 默认不发布宿主端口（仅容器网络）

## 2. 必须填写的配置（.env 硬性项）

不填 = 起不来 / 不能登录 / 数据不可恢复。生成方式一并给出：

```bash
# 生成随机值
openssl rand -hex 32   # JWT_SECRET / INTERNAL_HMAC_SECRET
openssl rand -hex 16   # PG_PASSWORD
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_KEY
```

| 变量 | 必须 | 要求 | 说明 |
|---|---|---|---|
| `JWT_SECRET` | ✅ | 64 位 hex，随机 | BFF 签发/校验 access token；**一经填写不得更改**（改=全体用户掉线） |
| `INTERNAL_HMAC_SECRET` | ✅ | 64 位 hex，随机，**必须 ≠ JWT_SECRET** | BFF→API 内部签名（DECISION-009） |
| `PG_PASSWORD` | ✅ | 随机 | PostgreSQL 密码；**不得与默认值 joker 相同** |
| `FERNET_KEY` | ✅ | Fernet key（44 字符 base64） | DB 加密凭证字段（LLM key、OSS key、MCP auth 等）的对称密钥。**留空=每次启动随机生成，重启后已存加密字段全部解不开（不可恢复）**。生产必须固定；该 key 丢失=DB 中所有加密凭证作废，必须重新录入 |
| `SEED_ADMIN_PASSWORD` | ✅ | ≥12 位，含大小写+数字+符号 | 初始 admin 密码。种子仅在首启（空库）执行，之后改密码走管理台 |
| `SEED_ADMIN_USERNAME` | 建议 | 默认 admin | 建议改非 admin 名 |
| `SEED_TENANT_CODE` | 建议 | 默认 acme | 首租户编码，建议用公司域名前缀 |
| `SEED_PLATFORM_ADMIN_USERNAME` | 建议 | 默认 platform | 平台管理员用户名（system 租户）：**平台管理员 = tenant_code=system + SEED_PLATFORM_ADMIN_USERNAME（默认 platform）**，密码=SEED_ADMIN_PASSWORD；「租户管理」菜单/`/api/tenants` 仅该身份可用 |

## 3. 强烈建议填写（真实能力开关）

| 变量 | 建议值 | 说明 |
|---|---|---|
| `LLM_FALLBACK_ENDPOINT` | 你的 OpenAI 兼容端点 `http(s)://host:port/v1` | 不填 = agent 对话只有 mock/本地 fallback，**无真实推理**。注意可达性：LLM 若在**本机**，容器内必须写 `http://host.docker.internal:端口/v1`（compose 已配 host-gateway）；在内网其他机器写内网 IP；公网直接写 |
| `LLM_FALLBACK_MODEL` | 模型名，如 `vllm-qwen3.8-27b` | 与端点配套 |
| `LLM_FALLBACK_API_KEY` | 真实 key | 运行时 Fernet 加密落 DB，.env 只是种子来源（DECISION-012） |

> 有独立的 embedding / vision 模型端点时，部署后在管理台「LLM 节点」里注册（不用 .env），RAG 上传时按库选择。本地 fallback embedding（256 维 n-gram）仅作兜底，**生产检索质量依赖真实 embedding 模型**。

## 4. 按需配置

### 4.1 文件存储（默认 local，开箱可用）
```
STORAGE_BACKEND=local
STORAGE_LOCAL_PATH=/data/storage     # 容器内固定路径，挂 named volume，无需改
```
用云存储（重启容器生效，既有文件保留原后端访问——DECISION-027，不自动迁移）：
- GCS：`STORAGE_BACKEND=gcs` + `GCS_BUCKET` + `GCS_CREDENTIALS_PATH`（容器内挂载的 service-account json 路径）
- 阿里云 OSS：`STORAGE_BACKEND=oss` + `OSS_ENDPOINT` + `OSS_BUCKET` + `OSS_ACCESS_KEY_ID` + `OSS_ACCESS_KEY_SECRET`（建议用最小权限 RAM 子账号）

### 4.2 保留策略（D-D 可配置，默认 90 天）
```
TRACE_RETENTION_DAYS=90        # trace 事件
AUDIT_RETENTION_DAYS=90        # 接口操作日志/上传记录
RETENTION_CHECK_INTERVAL_HOURS=1
```
实现为月分区 + 定期 DROP PARTITION，改天数重启即按新值清理。

### 4.3 限流（DECISION-013，按业务量调整）
```
BFF_RATE_LIMIT_TENANT_QPS=50        # 每租户 QPS
BFF_RATE_LIMIT_USER_QPS=10          # 每用户 QPS
BFF_RATE_LIMIT_LOGIN_IP_PER_MIN=5   # 登录接口每 IP 每分钟
BFF_PROXY_TIMEOUT=120               # 代理超时（长文档解析/流式对话）
BFF_RL_CACHE_TTL=10
```

### 4.4 其他
```
LOG_LEVEL=INFO          # 生产固定 INFO；排障临时调 DEBUG 后改回
OBSIDIAN_VAULT_PATH=/data/obsidian-vault   # 容器内固定，挂 named volume
BFF_PLATFORM_API_BASE=http://api:8001      # 容器网络内地址，勿改
```

## 5. 生产 .env 模板

```ini
# ===== 硬性必须 =====
PG_PASSWORD=<openssl rand -hex 16>
DB_DSN=postgresql+asyncpg://joker:${PG_PASSWORD}@pg:5432/joker
REDIS_URL=redis://redis:6379/0
JWT_SECRET=<openssl rand -hex 32>
INTERNAL_HMAC_SECRET=<openssl rand -hex 32，不同于 JWT_SECRET>
FERNET_KEY=<Fernet.generate_key() 固定值>
SEED_TENANT_CODE=<公司前缀>
SEED_ADMIN_USERNAME=<非admin的超管名>
SEED_ADMIN_PASSWORD=<≥12位强密码>
SEED_PLATFORM_ADMIN_USERNAME=<平台管理员名，默认 platform，租户 system>

# ===== 真实 LLM（强烈建议） =====
LLM_FALLBACK_ENDPOINT=<OpenAI兼容/v1端点；本机服务用 http://host.docker.internal:port/v1>
LLM_FALLBACK_MODEL=<模型名>
LLM_FALLBACK_API_KEY=<key>

# ===== 存储（默认 local 即可） =====
STORAGE_BACKEND=local

# ===== 保留策略 =====
TRACE_RETENTION_DAYS=90
AUDIT_RETENTION_DAYS=90
RETENTION_CHECK_INTERVAL_HOURS=1

# ===== 限流（按需） =====
BFF_RATE_LIMIT_TENANT_QPS=50
BFF_RATE_LIMIT_USER_QPS=10
BFF_RATE_LIMIT_LOGIN_IP_PER_MIN=5

LOG_LEVEL=INFO
```

## 6. 启动 / 验证 / 日常运维

```bash
# 首次部署
git clone https://github.com/harryzhang-carefold/agent-joker.git
cd agent-joker/deploy
cp .env.example .env    # 按 §2~§5 填写（.env 切勿提交 git / 备份时加密）
docker compose up -d --build          # 生产不加 --profile mocks
docker compose ps                     # 等 pg/redis/bff/api/webconsole 全部 healthy

# 验证
curl -sf http://127.0.0.1:8080/healthz && echo OK        # webconsole
curl -sf http://127.0.0.1:8000/healthz && echo OK        # bff（若已关 8000 则走容器内验证）
# 浏览器 http://<host>:8080 → 超管登录 → 依次抽查 9 模块
```

**备份（每周 cron 建议）**：
```bash
docker exec joker-pg pg_dump -U joker joker | gzip > backup/joker_$(date +%F).sql.gz
docker run --rm -v agent-joker_storage:/data -v $PWD/backup:/b alpine tar czf /b/storage_$(date +%F).tar.gz -C /data .
docker run --rm -v agent-joker_obsidian:/data -v $PWD/backup:/b alpine tar czf /b/obsidian_$(date +%F).tar.gz -C /data .
```
（volume 名以 `docker volume ls | grep agent-joker` 为准；**FERNET_KEY 与 .env 需离线加密保管**——没有它恢复的库无法解密凭证字段。）

**升级**：`git pull` → `docker compose up -d --build`（数据卷保留，滚动替换容器）。跨大版本前先备份。

**日志**：`docker compose logs -f --tail=200 api bff`；trace/审计检索走管理台「链路追踪/审计日志」。

## 7. 生产与自测环境差异清单

| 项 | 自测（README） | 生产 |
|---|---|---|
| mocks profile（mock-llm/mcp/tp-agent） | `--profile mocks` 启动，闭环兜底 | **不启动**；LLM/MCP/第三方 agent 全部接真实端点 |
| SEED_ADMIN_PASSWORD | acme123 | ≥12 位强密码 |
| FERNET_KEY | 可留空 | **必须固定** |
| JWT/HMAC/PG 密钥 | 随机即可 | 随机 + 离线保管 + 永不变更（JWT/HMAC） |
| 8000 端口 | 开放便于调试 | **防火墙关闭**，仅 8080 对外 |
| TLS | 无（http） | 前置 Nginx/云 LB 做 TLS 终结，反代到 8080；平台自身不开 443 |
| LLM 端点 | mock-llm 兜底 | 真实端点 + 真实 embedding 模型（管理台注册） |
| 备份 | 不需要 | §6 每周备份 + .env/FERNET_KEY 离线保管 |
| 监控 | 无 | 建议：容器 healthcheck 告警 + `docker compose logs` 采集 + 磁盘/pg 体积监控（trace 月分区按月增长） |

## 8. 安全 checklist

- [ ] .env 权限 `600`，不在 git/镜像内（Dockerfile 不 COPY .env）
- [ ] JWT_SECRET / INTERNAL_HMAC_SECRET / FERNET_KEY 三值互不相同且离线备份
- [ ] 8000/5432/6379 不对公网暴露
- [ ] 8080 前置 TLS + 建议加 IP 白名单/限流（云 LB 层）
- [ ] 登录接口限流 `BFF_RATE_LIMIT_LOGIN_IP_PER_MIN` 已按暴露面调整
- [ ] 云存储用最小权限凭证（GCS SA 仅限该 bucket；OSS 最小 RAM 策略）
- [ ] 定期轮换：SEED 超管密码（管理台改）、LLM/OSS key（管理台「LLM 节点/存储」改，Fernet 自动重加密）
- [ ] 保留策略天数与实际合规要求核对（trace/audit 默认 90 天）
