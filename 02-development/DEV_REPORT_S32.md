# DEV_REPORT S32 — 修复 BUG-19（3584 维建库 500，HNSW 2000 维硬上限降级）+ 自测证据

- 任务卡：t_892ebfc3（S32，zhangbeihai）
- 上游：2026-09-28 用户真实 UI 报「新增知识库保存报错」，主 agent 本地复现 + 定因（卡 body 已含根因）
- 事实源：`03-testing/BUGS.md`（BUG-19 段）、卡 body 根因、`00-management/PIPELINE.md` BUG-19 轮
- 本轮范围：**只修 BUG-19 相关代码 + 证据/报告文件**，不做无关重构；**不 push**（终审后随 S34 轮一次推）
- 部署：api/bff 镜像 s29→s32 重建，8 容器全 healthy（`docker compose ps` 核验）

## 一、修改文件清单

| 文件 | 改动 |
|---|---|
| `services/shared/joker_shared/db/init_schema.sql` | `create_rag_chunks_vec`：HNSW 索引包进 `IF p_dim <= 2000 THEN ... END IF`（>2000 维不建索引） |
| `services/shared/joker_shared/rag/service.py` | ① `create_kb`：建向量表失败 → 回滚 + 清半截向量表 + 可读 500（剥 `<class '...'>:` 前缀/`[SQL:...]`/`[parameters:...]`、截 160 字符）；② `reindex_kb`：影子表同规则 `if new_dim <= 2000` 才建 HNSW |
| `deploy/docker-compose.yml` | api/bff 镜像标签 s29→s32 |

## 二、根因 / 决策 / 改动

### 根因
`rag/service.py` 建 KB 调 `create_rag_chunks_vec`（`init_schema.sql`），对每库向量表**无条件** `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`。pgvector HNSW 索引硬性上限 **2000 维**（PG 错误 `column cannot have more than 2000 dimensions for hnsw index`），`s26-gte-qwen2-real`（3584 维）超限 → 建表失败 → 建库 500。

### 决策（DECISION，记于此，不入 DECISIONS.md——该文件由褚岩在终审轮统一收录，与 S29 先例一致）
**>2000 维不建 HNSW，检索走顺序扫描**（`ORDER BY embedding <=> q`）。
- 理由：① pgvector HNSW 2000 维是硬上限，无参数可绕；② 替代方案 ivfflat 虽支持高维，但需训练（lists）、空表/小表下性能劣于顺序扫描、批量写入后需 REINDEX，复杂度不划算；③ 单 KB 文档量级（chunk 数千~数万）下 3584 维顺序扫描检索延迟可接受；④ 检索 SQL（`retrieval.py`）本来就只写 `embedding <=> q` 排序，不依赖索引，**天然兼容、零改动**——只改建表分支即可。
- 影响面：`<=2000` 维行为与现状**完全一致**（HNSW 照建），仅 `>2000` 维路径变化；`reindex_kb` 换模型重算向量同规则（否则 256 维库换 3584 维模型会在影子表再撞上限）。
- 错误处理：建向量表失败（未来若有其他超限/DB 错误）返回**可读 500**，不向前端 toast 泄漏 traceback/SQL/参数（满足卡验收 3）。

### 改动逐条
1. `init_schema.sql create_rag_chunks_vec`：
   ```sql
   IF p_dim <= 2000 THEN
     EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_embedding ON %I USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)', ...);
   END IF;
   ```
2. `rag/service.py reindex_kb`：影子表建表后 `if new_dim <= 2000:` 才 `CREATE INDEX ... hnsw`。
3. `rag/service.py create_kb`：`create_rag_chunks_vec` 调用包 try/except → `session.rollback()` + `DROP TABLE IF EXISTS <vec_table>` + 可读 500（首行错误 + 剥前缀 + 截 160 字符 + 「若维度超过 2000 将不建 HNSW 索引（顺序扫描检索）」提示）。

## 三、自测证据汇总（QA_STANDARD 第 1 层，真实 HTTP urllib 原始响应，经 webconsole:8080→BFF→API，无 in-page fetch）

### 3.1 主自测：`03-testing/dev_probe_s32_bug19.log`（脚本 `dev_probe_s32_bug19_final.py`）— **12/12 PASS**

| # | 检查 | 结果 |
|---|---|---|
| A | 3584 维建库（**真实模型行 `s26-gte-qwen2-real`**，修复前 = 500） | **201** ✅ |
| B | 256 维建库（HNSW 分支对照） | 201 ✅ |
| B2 | 注册 3584 维 local provider（`local://fallback`，确定性向量） | 201 ✅ |
| E2 | 用 local 3584 模型建库 | 201 ✅ |
| C | `pg_indexes` 核验：3584 维库（real+local）**无 HNSW 索引**；256 维库**有 1 个 hnsw 索引** | ✅ |
| D1 | 256 库上传 .txt | 201 ✅ |
| D2 | 256 文档流水线 → `status=ready`，chunk_count=2 | ✅ |
| D3 | 256 检索 → 200，hits=2，唯一 marker 命中 | ✅ |
| E3 | 3584 库上传 .txt | 201 ✅ |
| E4 | 3584 文档流水线 → `status=ready`，chunk_count=2 | ✅ |
| E5 | 3584 检索 → 200，hits=2，唯一 marker 命中（score 0.652/0.613，top1 正确） | ✅ |
| F | 清理 3 个测试 KB | 200×3 ✅ |

（F 中 local 3584 embedding 模型 DELETE 返回 409：既有行为——KB 软删除但模型引用检查未过滤 `deleted_at`，属「禁用而非删除」语义，非本轮引入，不阻塞。）

### 3.2 顺序扫描专项：`03-testing/dev_probe_s32_bug19_seqscan.log`（脚本 `dev_probe_s32_seqscan.py`）— **PASS**
临时 3584 维表（无 HNSW 索引）插入 3 条向量，跑 `retrieval.py` 同款检索 SQL：
- 结果排序正确（top1 sim=0.999991 > 0.999980 > 0.865365）
- `EXPLAIN` 计划 = **Seq Scan**（`Sort Key: (embedding <=> q)`，非 Index Scan）→ 证明无索引路径正确且引擎确走顺序扫描。

### 3.3 外部 3584 端点状态记录：`03-testing/dev_probe_s32_bug19_endpoint.log`
自测期间 `34.64.61.208:4000`（DB 行 `s26-gte-qwen2-real` 指向的真实 3584 端点）经历三种状态：
1. 06:41 端点侧故障：HTTP 全断连（`RemoteDisconnected`），joker-api 容器与宿主**均复现**（TCP 4000 可达但 HTTP 丢弃请求）；
2. 06:49 恢复但 `/v1/embeddings` 对 DB 配置的 `model='gte-qwen2'` 返回 **404**；
3. 07:05+ 最终复测：`/v1/models` 显示端点**实际服务 `gte-Qwen2-1.5B-instruct`（真实 embedding 验证 = 1536 维）**，与 DB 行 `gte-qwen2`（3584 维）**模型漂移**（端点侧 vLLM 换了模型）。

**结论**：3584 维真实外部端点当前不可用（端点侧环境态，非平台代码缺陷）。3584 维文档流水线（上传→向量化→检索）用**本地 3584 维 provider** 完成闭环（E3-E5 全 PASS）——建库/索引/检索的维度逻辑与端点无关，3584 维真实端点链路待端点恢复后由 **S33 复测**（已登记 RISK-019）。

## 四、部署
- `deploy/docker-compose.yml`：api/bff 镜像 `agent-joker-{api,bff}:s29` → `:s32`。
- 重建后 `docker compose ps`：8 容器全 **healthy**（joker-api / joker-bff / joker-pg / joker-redis / joker-webconsole / 3×mock）。
- 启动方式不变：`cd deploy && docker compose up -d --build`。
- 数据库 schema 函数 `create_rag_chunks_vec` 已由 api 容器 entrypoint 在启动时按新 `init_schema.sql` 幂等重建（函数体内已含 `p_dim <= 2000` 分支，psql `\sf` 核验）。

## 五、已知问题 / 遗留
1. **RISK-019（新增）**：外部 3584 端点 `34.64.61.208:4000` 模型漂移（现服务 1536 维 `gte-Qwen2-1.5B-instruct`，DB 行仍指 `gte-qwen2` 3584 维）——端点侧环境态，需端点方恢复 3584 模型或用户更新 DB 行配置；S33 复测时若端点仍未恢复，3584 维真实端点链路以 local provider 闭环证据为准 + 记录端点状态。
2. **3584 维无 HNSW = 顺序扫描**：单 KB 文档量极大时检索延迟上升（当前量级可接受）；若后续需要，可评估 ivfflat（>2000 维可用）或按 KB 拆分。
3. `delete_embedding_model` 对「仅被软删除 KB 引用」的模型返回 409（既有行为，未过滤 `deleted_at`）——非本轮引入，未改动。
4. 本卡**不 push**：代码 + 证据随 S34（chuyan 终审）一次推送。
