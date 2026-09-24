-- =====================================================================
-- agent-joker 初始 schema（S01 后端骨架，2026-09-23，章北海）
-- 来源：02-development/DB_DESIGN.md（34 张表，全字段，TASK-D12 定稿）
-- 幂等：可重复执行（CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
--       种子数据 ON CONFLICT DO NOTHING）。
-- 分区表：trace_events / api_audit_logs 按月分区（DECISION-025 / D-D）；
--         初始建 3 个月分区（当前月 ± 1），后续由平台任务按保留天数 DROP/ADD。
-- 动态表：rag_chunks_vec_<kb_id> 每知识库一张独立向量表（D-C / DECISION-024），
--         由函数 create_rag_chunks_vec(kb_id uuid, dim integer) 建库时动态创建，
--         见文件末尾「动态向量表」小节。
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector（pgvector/pgvector:pg16 自带）
CREATE EXTENSION IF NOT EXISTS pgcrypto;        -- gen_random_uuid()（种子数据用；应用层 ID 由 Python uuid7 生成）

-- 触发器函数：updated_at 自动更新（幂等）
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- §1 基础（8 张：tenants / users / roles / scopes / role_scopes /
--               user_roles / auth_refresh_tokens / api_audit_logs）
-- =====================================================================

CREATE TABLE IF NOT EXISTS tenants (
  id                UUID PRIMARY KEY,
  name              TEXT NOT NULL,
  code              TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'active',        -- active / disabled
  plan              TEXT NOT NULL DEFAULT 'free',          -- free / pro（预留）
  storage_quota_mb  INTEGER NOT NULL DEFAULT 1024,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        UUID,                                   -- 逻辑外键 users.id（可空，循环引用）
  updated_by        UUID
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_tenants_name') THEN
    ALTER TABLE tenants ADD CONSTRAINT uq_tenants_name UNIQUE (name);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_tenants_code') THEN
    ALTER TABLE tenants ADD CONSTRAINT uq_tenants_code UNIQUE (code);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants (status);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_tenants_updated') THEN CREATE TRIGGER trg_tenants_updated BEFORE UPDATE ON tenants FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS users (
  id                 UUID PRIMARY KEY,
  tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  username           TEXT NOT NULL,
  email              TEXT,
  password_hash      TEXT NOT NULL,                         -- bcrypt
  display_name       TEXT,
  status             TEXT NOT NULL DEFAULT 'active',        -- active / disabled
  is_platform_admin  BOOLEAN NOT NULL DEFAULT false,
  last_login_at      TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by         UUID,
  updated_by         UUID,
  deleted_at         TIMESTAMPTZ
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_users_tenant_username') THEN
    ALTER TABLE users ADD CONSTRAINT uq_users_tenant_username UNIQUE (tenant_id, username);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_users_tenant_email') THEN
    ALTER TABLE users ADD CONSTRAINT uq_users_tenant_email UNIQUE (tenant_id, email);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_tenant ON users (tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_status ON users (status);
CREATE INDEX IF NOT EXISTS idx_users_platform_admin ON users (is_platform_admin);
CREATE INDEX IF NOT EXISTS idx_users_deleted ON users (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_users_updated') THEN CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS roles (
  id           UUID PRIMARY KEY,
  tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  description  TEXT,
  is_builtin   BOOLEAN NOT NULL DEFAULT false,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by   UUID,
  updated_by   UUID,
  deleted_at   TIMESTAMPTZ
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_roles_tenant_name') THEN
    ALTER TABLE roles ADD CONSTRAINT uq_roles_tenant_name UNIQUE (tenant_id, name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_roles_tenant ON roles (tenant_id);
CREATE INDEX IF NOT EXISTS idx_roles_builtin ON roles (is_builtin);
CREATE INDEX IF NOT EXISTS idx_roles_deleted ON roles (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_roles_updated') THEN CREATE TRIGGER trg_roles_updated BEFORE UPDATE ON roles FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS scopes (
  id           UUID PRIMARY KEY,
  tenant_id    UUID,                                        -- NULL = 平台级 scope
  code         TEXT NOT NULL,
  description  TEXT,
  category     TEXT NOT NULL DEFAULT 'function',            -- function / resource / tool
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by   UUID,
  updated_by   UUID
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_scopes_tenant_code') THEN
    ALTER TABLE scopes ADD CONSTRAINT uq_scopes_tenant_code UNIQUE (tenant_id, code);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_scopes_platform_code ON scopes (code) WHERE tenant_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_scopes_tenant ON scopes (tenant_id);
CREATE INDEX IF NOT EXISTS idx_scopes_category ON scopes (category);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_scopes_updated') THEN CREATE TRIGGER trg_scopes_updated BEFORE UPDATE ON scopes FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS role_scopes (
  role_id     UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  scope_id    UUID NOT NULL REFERENCES scopes(id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by  UUID,
  PRIMARY KEY (role_id, scope_id)
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id     UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by  UUID,
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
  id            UUID PRIMARY KEY,                            -- = jti
  tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash    TEXT NOT NULL,                               -- SHA-256（不落明文）
  device_info   JSONB,
  expires_at    TIMESTAMPTZ NOT NULL,                        -- 签发时 now + 7d
  revoked_at    TIMESTAMPTZ,
  replaced_by   UUID REFERENCES auth_refresh_tokens(id),     -- 轮换后继 jti（可空）
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by    UUID,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_refresh_token_hash') THEN
    ALTER TABLE auth_refresh_tokens ADD CONSTRAINT uq_refresh_token_hash UNIQUE (token_hash);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_refresh_tenant ON auth_refresh_tokens (tenant_id);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON auth_refresh_tokens (user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_expires ON auth_refresh_tokens (expires_at);   -- 清理任务（跨租户运维索引，例外）
CREATE INDEX IF NOT EXISTS idx_refresh_revoked ON auth_refresh_tokens (revoked_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_refresh_updated') THEN CREATE TRIGGER trg_refresh_updated BEFORE UPDATE ON auth_refresh_tokens FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- api_audit_logs：按月分区（保留天数可配置 AUDIT_RETENTION_DAYS，默认 90，D-D / DECISION-025）
CREATE TABLE IF NOT EXISTS api_audit_logs (
  id              UUID NOT NULL,
  tenant_id       UUID,                                       -- 匿名请求（登录失败）= NULL
  user_id         UUID,
  method          TEXT NOT NULL,
  path            TEXT NOT NULL,
  query_digest    TEXT,
  request_digest  TEXT,                                       -- 截断 2KB + 脱敏
  status_code     INTEGER NOT NULL,
  latency_ms      INTEGER,
  client_ip       TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by      UUID,
  updated_by      UUID,
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_time  ON api_audit_logs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user_time    ON api_audit_logs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_path_time    ON api_audit_logs (path, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_status_time  ON api_audit_logs (status_code, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_ip_time      ON api_audit_logs (client_ip, created_at DESC);

-- =====================================================================
-- §2 存储（2 张：storage_files / storage_upload_records）
-- =====================================================================

CREATE TABLE IF NOT EXISTS storage_files (
  id                UUID PRIMARY KEY,
  tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  file_name         TEXT NOT NULL,
  content_type      TEXT,
  size_bytes        BIGINT,
  backend           TEXT NOT NULL DEFAULT 'local',           -- local / gcs / oss（行级记录实际落点，STORE-03）
  storage_key       TEXT,
  checksum_sha256   TEXT,
  source            TEXT,                                     -- api / mcp / agent / kb / skill
  status            TEXT NOT NULL DEFAULT 'ready',           -- ready / failed / deleted
  owner_user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        UUID,
  updated_by        UUID,
  deleted_at        TIMESTAMPTZ
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_files_tenant_name') THEN
    ALTER TABLE storage_files ADD CONSTRAINT uq_files_tenant_name UNIQUE (tenant_id, file_name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_files_tenant_time ON storage_files (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_backend     ON storage_files (backend);
CREATE INDEX IF NOT EXISTS idx_files_status      ON storage_files (status);
CREATE INDEX IF NOT EXISTS idx_files_deleted     ON storage_files (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_files_updated') THEN CREATE TRIGGER trg_files_updated BEFORE UPDATE ON storage_files FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS storage_upload_records (
  id               UUID PRIMARY KEY,
  tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  file_id          UUID REFERENCES storage_files(id) ON DELETE SET NULL,
  file_name        TEXT NOT NULL,
  source           TEXT NOT NULL,                            -- api / mcp:platform / mcp:<server> / agent / kb / skill
  uploader_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  agent_id         UUID,                                     -- 逻辑外键 agents.id（可空）
  size_bytes       BIGINT,
  status           TEXT NOT NULL,                            -- success / failed / rejected
  error_message    TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by       UUID,
  updated_by       UUID
);
CREATE INDEX IF NOT EXISTS idx_uprec_tenant_time ON storage_upload_records (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_uprec_file        ON storage_upload_records (file_id);
CREATE INDEX IF NOT EXISTS idx_uprec_source      ON storage_upload_records (source);
CREATE INDEX IF NOT EXISTS idx_uprec_status      ON storage_upload_records (status);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_uprec_updated') THEN CREATE TRIGGER trg_uprec_updated BEFORE UPDATE ON storage_upload_records FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- =====================================================================
-- §3 LLM 节点（3 张：llm_endpoints / llm_embedding_models / llm_reranker_models）
-- 平台级共享（tenant_id 仅审计归属，不做行级过滤，ARCH §9-13）
-- =====================================================================

CREATE TABLE IF NOT EXISTS llm_endpoints (
  id               UUID PRIMARY KEY,
  tenant_id        UUID,                                     -- 审计归属（NULL=平台预置）
  name             TEXT NOT NULL,
  base_url         TEXT NOT NULL,
  model            TEXT NOT NULL,
  api_key_enc      TEXT,                                     -- Fernet 加密（DECISION-012）
  auth_scheme      TEXT NOT NULL DEFAULT 'bearer',           -- bearer / api_key_header / none
  supports_vision  BOOLEAN NOT NULL DEFAULT false,
  default_params   JSONB,
  timeout_seconds  INTEGER NOT NULL DEFAULT 120,
  status           TEXT NOT NULL DEFAULT 'active',           -- active / disabled
  last_test_at     TIMESTAMPTZ,
  last_test_result TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by       UUID,
  updated_by       UUID
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_endpoints_name') THEN
    ALTER TABLE llm_endpoints ADD CONSTRAINT uq_endpoints_name UNIQUE (name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_endpoints_tenant  ON llm_endpoints (tenant_id);
CREATE INDEX IF NOT EXISTS idx_endpoints_vision  ON llm_endpoints (supports_vision);
CREATE INDEX IF NOT EXISTS idx_endpoints_status  ON llm_endpoints (status);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_endpoints_updated') THEN CREATE TRIGGER trg_endpoints_updated BEFORE UPDATE ON llm_endpoints FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS llm_embedding_models (
  id          UUID PRIMARY KEY,
  tenant_id   UUID,
  name        TEXT NOT NULL,
  provider    TEXT NOT NULL DEFAULT 'api',                   -- api / local
  base_url    TEXT NOT NULL,
  model       TEXT NOT NULL,
  api_key_enc TEXT,
  dimensions  INTEGER NOT NULL,                              -- 建库时锁定（D-C）
  batch_size  INTEGER NOT NULL DEFAULT 32,
  status      TEXT NOT NULL DEFAULT 'active',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by  UUID,
  updated_by  UUID
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_emb_name') THEN
    ALTER TABLE llm_embedding_models ADD CONSTRAINT uq_emb_name UNIQUE (name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_emb_tenant ON llm_embedding_models (tenant_id);
CREATE INDEX IF NOT EXISTS idx_emb_status ON llm_embedding_models (status);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_emb_updated') THEN CREATE TRIGGER trg_emb_updated BEFORE UPDATE ON llm_embedding_models FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS llm_reranker_models (
  id              UUID PRIMARY KEY,
  tenant_id       UUID,
  name            TEXT NOT NULL,
  base_url        TEXT NOT NULL,
  model           TEXT NOT NULL,
  api_key_enc     TEXT,
  max_candidates  INTEGER NOT NULL DEFAULT 100,
  status          TEXT NOT NULL DEFAULT 'active',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by      UUID,
  updated_by      UUID
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_rerank_name') THEN
    ALTER TABLE llm_reranker_models ADD CONSTRAINT uq_rerank_name UNIQUE (name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_rerank_tenant ON llm_reranker_models (tenant_id);
CREATE INDEX IF NOT EXISTS idx_rerank_status ON llm_reranker_models (status);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_rerank_updated') THEN CREATE TRIGGER trg_rerank_updated BEFORE UPDATE ON llm_reranker_models FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- =====================================================================
-- §4 RAG（5 张：rag_knowledge_bases / rag_docs / rag_chunks /
--             rag_doc_images + 动态向量表 rag_chunks_vec_<kb_id>）
-- =====================================================================

CREATE TABLE IF NOT EXISTS rag_knowledge_bases (
  id                     UUID PRIMARY KEY,
  tenant_id              UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name                   TEXT NOT NULL,
  description            TEXT,
  tag                    TEXT,                               -- 库级 tag（official 默认，D-A）
  embedding_model_id     UUID NOT NULL REFERENCES llm_embedding_models(id),
  embedding_dim          INTEGER NOT NULL,                   -- 建库快照（D-C）
  reranker_model_id      UUID REFERENCES llm_reranker_models(id),
  top_k_default          INTEGER NOT NULL DEFAULT 5,
  score_threshold        NUMERIC(4,3) NOT NULL DEFAULT 0.300,
  recall_top_n           INTEGER,
  split_strategy_default TEXT NOT NULL DEFAULT 'fixed',      -- fixed/parent_child/semantic/structured_tree/table
  split_params_default   JSONB,
  status                 TEXT NOT NULL DEFAULT 'active',     -- active / reindexing / disabled
  doc_count              INTEGER NOT NULL DEFAULT 0,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by             UUID,
  updated_by             UUID,
  deleted_at             TIMESTAMPTZ
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_kb_tenant_name') THEN
    ALTER TABLE rag_knowledge_bases ADD CONSTRAINT uq_kb_tenant_name UNIQUE (tenant_id, name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_kb_tenant  ON rag_knowledge_bases (tenant_id);
CREATE INDEX IF NOT EXISTS idx_kb_tag     ON rag_knowledge_bases (tag);
CREATE INDEX IF NOT EXISTS idx_kb_status  ON rag_knowledge_bases (status);
CREATE INDEX IF NOT EXISTS idx_kb_deleted ON rag_knowledge_bases (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_kb_updated') THEN CREATE TRIGGER trg_kb_updated BEFORE UPDATE ON rag_knowledge_bases FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS rag_docs (
  id                  UUID PRIMARY KEY,
  tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  knowledge_base_id   UUID NOT NULL REFERENCES rag_knowledge_bases(id) ON DELETE CASCADE,
  file_id             UUID NOT NULL REFERENCES storage_files(id),   -- 被引用的文件禁删（RESTRICT 语义见 §13.3：应用层 409）
  file_name           TEXT NOT NULL,
  tag                 TEXT,                                      -- 文档级 tag（D-A：NULL 继承库级）
  doc_type            TEXT NOT NULL,                             -- txt/docx/xlsx/pdf/png/jpg（.doc 422 拒绝）
  status              TEXT NOT NULL DEFAULT 'uploaded',          -- uploaded→parsing→splitting→embedded→ready/failed/reindexing
  error_message       TEXT,
  parse_method        TEXT,                                      -- text / vision / mixed
  page_count          INTEGER,
  split_strategy      TEXT,                                      -- 文档级覆盖（NULL=库默认）
  split_params        JSONB,
  chunk_count         INTEGER NOT NULL DEFAULT 0,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by          UUID,
  updated_by          UUID,
  deleted_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_docs_kb     ON rag_docs (tenant_id, knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_docs_status ON rag_docs (status);
CREATE INDEX IF NOT EXISTS idx_docs_tag    ON rag_docs (tenant_id, knowledge_base_id, tag);
CREATE INDEX IF NOT EXISTS idx_docs_deleted ON rag_docs (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_docs_updated') THEN CREATE TRIGGER trg_docs_updated BEFORE UPDATE ON rag_docs FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS rag_chunks (
  id                UUID PRIMARY KEY,
  tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  doc_id            UUID NOT NULL REFERENCES rag_docs(id) ON DELETE CASCADE,
  knowledge_base_id UUID NOT NULL REFERENCES rag_knowledge_bases(id) ON DELETE CASCADE,
  parent_id         UUID REFERENCES rag_chunks(id) ON DELETE SET NULL,
  chunk_index       INTEGER NOT NULL,                            -- 文档内从 0 递增
  content           TEXT NOT NULL,
  content_sha256    TEXT,
  pos               JSONB,                                       -- {page, section_path, char_start, char_end, table_row}
  split_strategy    TEXT,
  is_table          BOOLEAN NOT NULL DEFAULT false,
  -- 向量不入本表：按库独立表存储（D-C / DECISION-024）→ rag_chunks_vec_<kb_id>
  last_score        NUMERIC(4,3),
  edited_at         TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        UUID,
  updated_by        UUID,
  deleted_at        TIMESTAMPTZ
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_chunks_doc_index') THEN
    ALTER TABLE rag_chunks ADD CONSTRAINT uq_chunks_doc_index UNIQUE (doc_id, chunk_index);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_chunks_doc    ON rag_chunks (tenant_id, doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_deleted ON rag_chunks (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_chunks_updated') THEN CREATE TRIGGER trg_chunks_updated BEFORE UPDATE ON rag_chunks FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- 动态向量表：每知识库一张 rag_chunks_vec_<kb_id>（维度 = 该库 embedding 模型维度）
-- 由下面的函数在「建库」时调用（S02 RAG 切片实现建库流程时接入）。
CREATE TABLE IF NOT EXISTS rag_doc_images (
  id                UUID PRIMARY KEY,
  tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  doc_id            UUID NOT NULL REFERENCES rag_docs(id) ON DELETE CASCADE,
  image_file_id     UUID NOT NULL REFERENCES storage_files(id) ON DELETE RESTRICT,  -- 被引用文件禁删（shiqiang N2）
  source_type       TEXT NOT NULL,                               -- image_doc / scanned_page / inline_image
  page_no           INTEGER,
  vision_endpoint_id UUID REFERENCES llm_endpoints(id) ON DELETE SET NULL,
  prompt_version    TEXT,
  status            TEXT NOT NULL DEFAULT 'pending',             -- pending / done / failed / skipped
  vision_text       TEXT,
  token_usage       JSONB,
  error_message     TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        UUID,
  updated_by        UUID
);
CREATE INDEX IF NOT EXISTS idx_images_doc        ON rag_doc_images (doc_id);
CREATE INDEX IF NOT EXISTS idx_images_source_type ON rag_doc_images (source_type);
CREATE INDEX IF NOT EXISTS idx_images_status     ON rag_doc_images (status);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_images_updated') THEN CREATE TRIGGER trg_images_updated BEFORE UPDATE ON rag_doc_images FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- =====================================================================
-- §5 MCP（2 张：mcp_servers / mcp_tools）
-- =====================================================================

CREATE TABLE IF NOT EXISTS mcp_servers (
  id               UUID PRIMARY KEY,
  tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name             TEXT NOT NULL,
  url              TEXT NOT NULL,
  transport        TEXT NOT NULL DEFAULT 'streamable_http',     -- streamable_http / sse
  is_platform      BOOLEAN NOT NULL DEFAULT false,              -- true = PlatformMCPServer（不可删）
  auth_headers_enc TEXT,                                        -- Fernet 加密机器凭证
  status           TEXT NOT NULL DEFAULT 'unreachable',         -- online / offline / unreachable / disabled
  last_sync_at     TIMESTAMPTZ,
  last_error       TEXT,
  tool_count       INTEGER NOT NULL DEFAULT 0,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by       UUID,
  updated_by       UUID,
  deleted_at       TIMESTAMPTZ
);
-- S07 修复：软删语义下全量 UNIQUE(tenant_id,name) 会让「软删后重新注册同名」撞
-- 残留行（500 IntegrityError）→ 改为部分唯一索引（deleted_at IS NULL），
-- 约束名沿用 uq_mcp_servers_tenant_name（报错文案兼容）。
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_mcp_servers_tenant_name') THEN
    ALTER TABLE mcp_servers DROP CONSTRAINT uq_mcp_servers_tenant_name;
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_servers_tenant_name
  ON mcp_servers (tenant_id, name) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_servers_tenant  ON mcp_servers (tenant_id);
CREATE INDEX IF NOT EXISTS idx_mcp_servers_platform ON mcp_servers (is_platform);
CREATE INDEX IF NOT EXISTS idx_mcp_servers_status  ON mcp_servers (status);
CREATE INDEX IF NOT EXISTS idx_mcp_servers_deleted ON mcp_servers (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_mcp_servers_updated') THEN CREATE TRIGGER trg_mcp_servers_updated BEFORE UPDATE ON mcp_servers FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS mcp_tools (
  id              UUID PRIMARY KEY,
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  server_id       UUID NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  description     TEXT,
  input_schema    JSONB,
  source          TEXT NOT NULL DEFAULT 'remote',               -- remote / platform
  required_scopes JSONB NOT NULL DEFAULT '["mcp:tool"]',
  enabled         BOOLEAN NOT NULL DEFAULT true,
  removed_remote  BOOLEAN NOT NULL DEFAULT false,
  last_sync_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by      UUID,
  updated_by      UUID,
  deleted_at      TIMESTAMPTZ
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_mcp_tools_server_name') THEN
    ALTER TABLE mcp_tools ADD CONSTRAINT uq_mcp_tools_server_name UNIQUE (server_id, name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_mcp_tools_server  ON mcp_tools (tenant_id, server_id);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_enabled ON mcp_tools (enabled);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_source  ON mcp_tools (source);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_removed ON mcp_tools (removed_remote);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_deleted ON mcp_tools (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_mcp_tools_updated') THEN CREATE TRIGGER trg_mcp_tools_updated BEFORE UPDATE ON mcp_tools FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- =====================================================================
-- §6 Skills（2 张：skills / skill_files）
-- =====================================================================

CREATE TABLE IF NOT EXISTS skills (
  id          UUID PRIMARY KEY,
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  description TEXT,
  content     TEXT,
  source      TEXT NOT NULL DEFAULT 'manual',                   -- manual / upload
  version     INTEGER NOT NULL DEFAULT 1,
  status      TEXT NOT NULL DEFAULT 'active',
  file_count  INTEGER NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by  UUID,
  updated_by  UUID,
  deleted_at  TIMESTAMPTZ
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_skills_tenant_name') THEN
    ALTER TABLE skills ADD CONSTRAINT uq_skills_tenant_name UNIQUE (tenant_id, name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_skills_tenant  ON skills (tenant_id);
CREATE INDEX IF NOT EXISTS idx_skills_source  ON skills (source);
CREATE INDEX IF NOT EXISTS idx_skills_status  ON skills (status);
CREATE INDEX IF NOT EXISTS idx_skills_deleted ON skills (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_skills_updated') THEN CREATE TRIGGER trg_skills_updated BEFORE UPDATE ON skills FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS skill_files (
  id         UUID NOT NULL,
  tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  skill_id   UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  file_id    UUID NOT NULL REFERENCES storage_files(id) ON DELETE CASCADE,
  file_name  TEXT NOT NULL,
  role       TEXT NOT NULL DEFAULT 'main',                      -- main / asset
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by UUID,
  updated_by UUID,
  deleted_at TIMESTAMPTZ,
  PRIMARY KEY (skill_id, file_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_files_skill  ON skill_files (skill_id);
CREATE INDEX IF NOT EXISTS idx_skill_files_role   ON skill_files (role);
CREATE INDEX IF NOT EXISTS idx_skill_files_deleted ON skill_files (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_skill_files_updated') THEN CREATE TRIGGER trg_skill_files_updated BEFORE UPDATE ON skill_files FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- =====================================================================
-- §7 Agent（9 张：agents + 4 勾选表 + agent_sessions / agent_messages /
--              agent_memories / agent_obsidian_notes）
-- =====================================================================

CREATE TABLE IF NOT EXISTS agents (
  id                       UUID PRIMARY KEY,
  tenant_id                UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name                     TEXT NOT NULL,                        -- 租户内唯一；= OpenAI model 标识（DECISION-016）
  description              TEXT,
  type                     TEXT NOT NULL DEFAULT 'simple',       -- simple / third_party
  system_prompt            TEXT,
  model_params             JSONB,
  max_tool_rounds          INTEGER NOT NULL DEFAULT 8,
  show_citations_default   BOOLEAN NOT NULL DEFAULT false,
  third_party_url          TEXT,
  third_party_transport    TEXT,
  third_party_auth_enc     TEXT,
  third_party_session_param TEXT,
  status                   TEXT NOT NULL DEFAULT 'active',
  session_count            INTEGER NOT NULL DEFAULT 0,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by               UUID,
  updated_by               UUID,
  deleted_at               TIMESTAMPTZ
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_agents_tenant_name') THEN
    ALTER TABLE agents ADD CONSTRAINT uq_agents_tenant_name UNIQUE (tenant_id, name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_agents_tenant  ON agents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_agents_type    ON agents (type);
CREATE INDEX IF NOT EXISTS idx_agents_status  ON agents (status);
CREATE INDEX IF NOT EXISTS idx_agents_deleted ON agents (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_agents_updated') THEN CREATE TRIGGER trg_agents_updated BEFORE UPDATE ON agents FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS agent_llm_endpoints (
  agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  llm_endpoint_id UUID NOT NULL REFERENCES llm_endpoints(id) ON DELETE CASCADE,
  priority        INTEGER NOT NULL DEFAULT 1,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by      UUID,
  deleted_at      TIMESTAMPTZ,
  PRIMARY KEY (agent_id, llm_endpoint_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_agent_llm_single ON agent_llm_endpoints (agent_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_agent_llm_deleted ON agent_llm_endpoints (agent_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS agent_knowledge_bases (
  agent_id           UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  knowledge_base_id  UUID NOT NULL REFERENCES rag_knowledge_bases(id) ON DELETE CASCADE,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by         UUID,
  deleted_at         TIMESTAMPTZ,
  PRIMARY KEY (agent_id, knowledge_base_id)
);
CREATE INDEX IF NOT EXISTS idx_agent_kb_deleted ON agent_knowledge_bases (knowledge_base_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS agent_mcp_tools (
  agent_id      UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  mcp_tool_id   UUID NOT NULL REFERENCES mcp_tools(id) ON DELETE CASCADE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by    UUID,
  deleted_at    TIMESTAMPTZ,
  PRIMARY KEY (agent_id, mcp_tool_id)
);
CREATE INDEX IF NOT EXISTS idx_agent_tools_tool ON agent_mcp_tools (mcp_tool_id) WHERE deleted_at IS NULL;  -- MCP-03 关联检测主索引

CREATE TABLE IF NOT EXISTS agent_skills (
  agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  skill_id    UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by  UUID,
  deleted_at  TIMESTAMPTZ,
  PRIMARY KEY (agent_id, skill_id)
);
CREATE INDEX IF NOT EXISTS idx_agent_skill_deleted ON agent_skills (skill_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS agent_sessions (
  id                  UUID PRIMARY KEY,
  tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  agent_id            UUID NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
  user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title               TEXT,
  status              TEXT NOT NULL DEFAULT 'active',            -- active / closed
  message_count       INTEGER NOT NULL DEFAULT 0,
  total_tokens        INTEGER NOT NULL DEFAULT 0,
  last_message_at     TIMESTAMPTZ,
  external_session_id TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by          UUID,
  updated_by          UUID,
  deleted_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sessions_agent   ON agent_sessions (tenant_id, agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON agent_sessions (tenant_id, user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status  ON agent_sessions (status);
CREATE INDEX IF NOT EXISTS idx_sessions_last_msg ON agent_sessions (last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_deleted ON agent_sessions (deleted_at);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_sessions_updated') THEN CREATE TRIGGER trg_sessions_updated BEFORE UPDATE ON agent_sessions FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS agent_messages (
  id            UUID PRIMARY KEY,
  tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  session_id    UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  role          TEXT NOT NULL,                                   -- user / assistant / tool / system
  content       TEXT,
  tool_calls    JSONB,
  tool_call_id  TEXT,
  citations     JSONB,
  file_ids      JSONB,
  token_usage   JSONB,
  status        TEXT NOT NULL DEFAULT 'pending',                 -- pending / done / failed
  error_message TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by    UUID,
  updated_by    UUID
);
CREATE INDEX IF NOT EXISTS idx_messages_session   ON agent_messages (tenant_id, session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_tool_call_id ON agent_messages (tool_call_id);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_messages_updated') THEN CREATE TRIGGER trg_messages_updated BEFORE UPDATE ON agent_messages FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS agent_memories (
  id                UUID PRIMARY KEY,
  tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  agent_id          UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  user_id           UUID REFERENCES users(id) ON DELETE SET NULL,   -- NULL = agent 级共享记忆
  memory_type       TEXT NOT NULL DEFAULT 'fact',                    -- fact / preference / summary / entity
  content           TEXT NOT NULL,
  source_session_id UUID,                                          -- 逻辑外键 agent_sessions.id（可空）
  importance        NUMERIC(2,1) NOT NULL DEFAULT 5.0,
  access_count      INTEGER NOT NULL DEFAULT 0,
  last_accessed_at  TIMESTAMPTZ,
  status            TEXT NOT NULL DEFAULT 'active',                 -- active / archived
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        UUID,
  updated_by        UUID
);
CREATE INDEX IF NOT EXISTS idx_memories_agent ON agent_memories (tenant_id, agent_id, user_id);
CREATE INDEX IF NOT EXISTS idx_memories_type  ON agent_memories (memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_status ON agent_memories (status);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_memories_updated') THEN CREATE TRIGGER trg_memories_updated BEFORE UPDATE ON agent_memories FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
CREATE TABLE IF NOT EXISTS agent_obsidian_notes (
  id                UUID PRIMARY KEY,
  tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  agent_id          UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  user_id           UUID REFERENCES users(id) ON DELETE SET NULL,
  file_path         TEXT NOT NULL,                                   -- vault/<tenant_code>/<agent_name>/<yyyy-mm>/<slug>.md
  title             TEXT,
  summary           TEXT,
  tags              JSONB,
  source_session_id UUID,
  rag_doc_id        UUID,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        UUID,
  updated_by        UUID
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_obs_notes_tenant_path') THEN
    ALTER TABLE agent_obsidian_notes ADD CONSTRAINT uq_obs_notes_tenant_path UNIQUE (tenant_id, file_path);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_obs_notes_agent ON agent_obsidian_notes (agent_id, created_at DESC);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_obs_notes_updated') THEN CREATE TRIGGER trg_obs_notes_updated BEFORE UPDATE ON agent_obsidian_notes FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- =====================================================================
-- §8 BFF（1 张：bff_rate_limit_configs）
-- =====================================================================

CREATE TABLE IF NOT EXISTS bff_rate_limit_configs (
  id             UUID PRIMARY KEY,
  tenant_id      UUID REFERENCES tenants(id) ON DELETE SET NULL,   -- NULL = 平台级默认
  dimension      TEXT NOT NULL,                                     -- tenant_qps / user_qps / login_ip_per_min / agent_chat_qps
  limit_value    INTEGER NOT NULL,
  window_seconds INTEGER NOT NULL DEFAULT 1,
  enabled        BOOLEAN NOT NULL DEFAULT true,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by     UUID,
  updated_by     UUID
);
-- (tenant_id, dimension) 唯一；NULL tenant = 全局行（部分唯一索引表达：非 NULL 行全唯一）
CREATE UNIQUE INDEX IF NOT EXISTS uk_bff_rl ON bff_rate_limit_configs (tenant_id, dimension) WHERE tenant_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uk_bff_rl_global ON bff_rate_limit_configs (dimension) WHERE tenant_id IS NULL;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_bff_rl_updated') THEN CREATE TRIGGER trg_bff_rl_updated BEFORE UPDATE ON bff_rate_limit_configs FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- =====================================================================
-- §9 Trace（2 张：trace_sessions / trace_events【月分区】）
-- =====================================================================

CREATE TABLE IF NOT EXISTS trace_sessions (
  id               UUID PRIMARY KEY,
  tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  session_id       UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  agent_id         UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  started_at       TIMESTAMPTZ NOT NULL,
  ended_at         TIMESTAMPTZ,
  event_count      INTEGER NOT NULL DEFAULT 0,
  tool_call_count  INTEGER NOT NULL DEFAULT 0,
  rag_call_count   INTEGER NOT NULL DEFAULT 0,
  file_event_count INTEGER NOT NULL DEFAULT 0,
  total_tokens     INTEGER NOT NULL DEFAULT 0,
  status           TEXT NOT NULL DEFAULT 'active',                 -- active / ended / failed
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by       UUID,
  updated_by       UUID
);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_trc_sessions_session') THEN
    ALTER TABLE trace_sessions ADD CONSTRAINT uq_trc_sessions_session UNIQUE (session_id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_trc_sessions_tenant ON trace_sessions (tenant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_trc_sessions_agent  ON trace_sessions (tenant_id, agent_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_trc_sessions_user   ON trace_sessions (tenant_id, user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_trc_sessions_time   ON trace_sessions (started_at DESC);   -- 运维例外（跨租户清理）
CREATE INDEX IF NOT EXISTS idx_trc_sessions_status ON trace_sessions (status);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_trc_sessions_updated') THEN CREATE TRIGGER trg_trc_sessions_updated BEFORE UPDATE ON trace_sessions FOR EACH ROW EXECUTE FUNCTION set_updated_at(); END IF; END $$;
-- trace_events：按月分区（保留天数可配置 TRACE_RETENTION_DAYS，默认 90，D-D / DECISION-025）
CREATE TABLE IF NOT EXISTS trace_events (
  id             UUID NOT NULL,
  tenant_id      UUID NOT NULL,
  session_id     UUID NOT NULL REFERENCES trace_sessions(id) ON DELETE CASCADE,
  event_type     TEXT NOT NULL,                                    -- message / file / tool_call / rag / system
  seq            INTEGER NOT NULL,
  payload        JSONB,
  payload_tsv    TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', payload::text)) STORED,
  tool_name      TEXT,
  tool_server_id UUID REFERENCES mcp_servers(id) ON DELETE SET NULL,
  rag_kb_id      UUID REFERENCES rag_knowledge_bases(id) ON DELETE SET NULL,
  file_id        UUID REFERENCES storage_files(id) ON DELETE SET NULL,
  message_id     UUID REFERENCES agent_messages(id) ON DELETE SET NULL,
  token_usage    JSONB,
  latency_ms     INTEGER,
  status         TEXT NOT NULL DEFAULT 'ok',                       -- ok / error / denied
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by     UUID,
  updated_by     UUID,
  PRIMARY KEY (id, created_at),
  UNIQUE (session_id, seq, created_at)                             -- 会话内保序（分区表唯一键须含分区键）
) PARTITION BY RANGE (created_at);

CREATE INDEX IF NOT EXISTS idx_trc_events_session   ON trace_events (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_trc_events_type      ON trace_events (tenant_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trc_events_tool      ON trace_events (tenant_id, tool_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trc_events_status    ON trace_events (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trc_events_payload_tsv ON trace_events USING GIN (payload_tsv);  -- 关键词全文检索（TRACE-02）

-- =====================================================================
-- 月度分区（trace_events / api_audit_logs）
-- 函数 ensure_monthly_partitions()：保证当前月 ± 1 的分区存在（幂等）。
-- 保留期清理：按 TRACE_RETENTION_DAYS / AUDIT_RETENTION_DAYS DROP 过期分区
--   （定期任务实现，S08 trace 切片负责；此处仅提供建分区函数与初始分区）。
-- =====================================================================

CREATE OR REPLACE FUNCTION ensure_monthly_partitions(
  p_table  TEXT,
  p_months int DEFAULT 3          -- 覆盖当前月向前 p_months-1 个月、向后 1 个月
) RETURNS void AS $$
DECLARE
  m      int;
  ym     date;
  pname  TEXT;
BEGIN
  FOR m IN 0..(p_months - 1) LOOP
    ym    := date_trunc('month', now() - (m || ' months')::interval);
    pname := p_table || '_' || to_char(ym, 'YYYY_MM');
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = pname) THEN
      EXECUTE format(
        'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
        pname, p_table, ym::text, (ym + interval '1 month')::text
      );
    END IF;
  END LOOP;
END;
$$ LANGUAGE plpgsql;

-- 初始分区：当前月 + 前 1 月 + 后 1 月（幂等，重复执行无副作用）
SELECT ensure_monthly_partitions('trace_events', 3);
SELECT ensure_monthly_partitions('api_audit_logs', 3);

-- =====================================================================
-- 动态向量表（D-C / DECISION-024，用户裁定 2026-09-22）
-- rag_chunks_vec_<kb_id>：每知识库一张独立向量表，维度 = 该库 embedding 模型维度。
-- 建库流程（S02 RAG 切片实现时调用）：
--   1) SELECT create_rag_chunks_vec('<kb_id>', <embedding 模型 dimensions>);
--      → 幂等创建 rag_chunks_vec_<kb_id>（vector(N) + HNSW 余弦索引）
--   2) 写 rag_knowledge_bases.embedding_dim = 该维度（建库快照）
--   3) 换 embedding 模型（全量重算，状态机 reindexing）：
--      a. 建影子表（临时维度）→ b. 全量重嵌入 → c. 切换 embedding_dim +
--      RENAME 影子表为目标名 → d. DROP 旧表
-- =====================================================================

CREATE OR REPLACE FUNCTION create_rag_chunks_vec(p_kb_id uuid, p_dim integer)
RETURNS TEXT AS $$
DECLARE
  tname TEXT;
BEGIN
  IF p_dim IS NULL OR p_dim <= 0 OR p_dim > 6000 THEN
    RAISE EXCEPTION 'invalid embedding dimension: %', p_dim;
  END IF;
  IF p_kb_id::text !~* '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' THEN
    RAISE EXCEPTION 'invalid kb_id: %', p_kb_id;
  END IF;
  tname := 'rag_chunks_vec_' || replace(p_kb_id::text, '-', '');   -- 32 位无连字符，合法标识符
  EXECUTE format(
    'CREATE TABLE IF NOT EXISTS %I (
       chunk_id          UUID PRIMARY KEY REFERENCES rag_chunks(id) ON DELETE CASCADE,
       knowledge_base_id UUID NOT NULL REFERENCES rag_knowledge_bases(id) ON DELETE CASCADE,
       embedding         vector(%s) NOT NULL,
       created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
       updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
     )',
    tname, p_dim
  );
  EXECUTE format(
    'CREATE INDEX IF NOT EXISTS idx_%s_embedding ON %I USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)',
    replace(p_kb_id::text, '-', ''), tname
  );
  -- 向量表 updated_at 触发器（命名按表名生成，幂等）
  EXECUTE format(
    'DROP TRIGGER IF EXISTS trg_%s_vec_updated ON %I',
    replace(p_kb_id::text, '-', ''), tname
  );
  EXECUTE format(
    'CREATE TRIGGER trg_%s_vec_updated BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
    replace(p_kb_id::text, '-', ''), tname
  );
  RETURN tname;
END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- 种子数据（DB_DESIGN §10.3，幂等 ON CONFLICT DO NOTHING）
--   系统租户 00000000-0000-0000-0000-000000000001 + 平台级内置 scope +
--   首个业务租户 acme（登录自测用，admin/acme123，bcrypt 见下）
-- =====================================================================

-- 系统租户
INSERT INTO tenants (id, name, code, status, plan, storage_quota_mb)
VALUES ('00000000-0000-0000-0000-000000000001', '系统', 'system', 'active', 'pro', 10240)
ON CONFLICT (code) DO NOTHING;

-- 平台级内置 scope（tenant_id = NULL，DECISION-004 / ARCH §4.6）
-- 幂等：固定 UUID（由 code 派生）+ 按 code 去重（重复执行不产生新行）
INSERT INTO scopes (id, tenant_id, code, description, category)
SELECT
  md5(code)::uuid,           -- 固定 UUID（由 code 的 md5 派生，重复执行不漂移）
  NULL, code, description, category
FROM (VALUES
  ('iam:manage',    '用户/角色/权限管理', 'function'),
  ('storage:manage','存储管理',           'function'),
  ('storage:read',  '文件读取',           'tool'),
  ('storage:write', '文件写入',           'tool'),
  ('kb:manage',     '知识库管理',         'function'),
  ('rag:search',    'RAG 检索',           'tool'),
  ('mcp:manage',    'MCP server 管理',    'function'),
  ('mcp:tool',      'MCP 工具调用',       'tool'),
  ('skills:manage', 'Skills 管理',        'function'),
  ('agents:manage', 'Agent 管理',         'function'),
  ('llm:manage',    'LLM 节点管理（平台级）', 'function'),
  ('trace:read',    'Trace 检索',         'function')
) AS v(code, description, category)
WHERE NOT EXISTS (SELECT 1 FROM scopes s WHERE s.code = v.code AND s.tenant_id IS NULL);

-- 首个业务租户（自测用；密码在 AuthService 启动种子中 bcrypt 处理，
-- 此处仅保证租户/角色/用户行存在——密码哈希由种子脚本写入，见 services/api 启动 seed）
INSERT INTO tenants (id, name, code, status, plan, storage_quota_mb)
VALUES ('00000000-0000-0000-0000-000000000002', 'Acme', 'acme', 'active', 'free', 1024)
ON CONFLICT (code) DO NOTHING;

-- 内置角色（每租户一份，is_builtin，DB_DESIGN §10.3）
INSERT INTO roles (id, tenant_id, name, description, is_builtin) VALUES
  ('00000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000001', 'admin',  '平台运营管理员', true),
  ('00000000-0000-0000-0000-000000000012', '00000000-0000-0000-0000-000000000001', 'member', '普通成员',       true),
  ('00000000-0000-0000-0000-000000000021', '00000000-0000-0000-0000-000000000002', 'admin',  '租户管理员',     true),
  ('00000000-0000-0000-0000-000000000022', '00000000-0000-0000-0000-000000000002', 'member', '普通成员',       true)
ON CONFLICT DO NOTHING;

-- 内置角色 → 平台级 scope 绑定（admin = 全部功能 + 工具 scope；member = 对话级）
INSERT INTO role_scopes (role_id, scope_id)
SELECT r.id, s.id FROM roles r JOIN scopes s
  ON (r.id = '00000000-0000-0000-0000-000000000011' AND s.tenant_id IS NULL)
   OR (r.id = '00000000-0000-0000-0000-000000000021' AND s.tenant_id IS NULL AND s.code IN
       ('iam:manage','storage:manage','storage:read','storage:write','kb:manage','rag:search',
        'mcp:manage','mcp:tool','skills:manage','agents:manage','trace:read'))
   OR (r.id = '00000000-0000-0000-0000-000000000012' AND s.tenant_id IS NULL AND s.code IN
       ('storage:read','storage:write','rag:search','mcp:tool'))
   OR (r.id = '00000000-0000-0000-0000-000000000022' AND s.tenant_id IS NULL AND s.code IN
       ('storage:read','storage:write','rag:search','mcp:tool'))
ON CONFLICT (role_id, scope_id) DO NOTHING;

-- 自测用户（acme 租户 admin；密码哈希由 API 启动种子补写——bcrypt 在 SQL 内不可生成）
INSERT INTO users (id, tenant_id, username, password_hash, display_name, status)
VALUES ('00000000-0000-0000-0000-000000000031', '00000000-0000-0000-0000-000000000002',
        'admin', '$2b$12$REPLACE_BY_BOOTSTRAP', 'Acme Admin', 'active')
ON CONFLICT (tenant_id, username) DO NOTHING;
INSERT INTO user_roles (user_id, role_id)
VALUES ('00000000-0000-0000-0000-000000000031', '00000000-0000-0000-0000-000000000021')
ON CONFLICT DO NOTHING;
