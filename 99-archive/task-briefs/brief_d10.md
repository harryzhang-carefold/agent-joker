项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: 落实用户 2026-09-22 对两条风险项的正式裁定，修订 ARCHITECTURE.md + DB_DESIGN.md（并同步 DECISIONS.md/RISKS.md）。

【用户裁定 1（RISK-004 关闭）——向量维度不固定，按 embedding 模型维度】
原设计「全平台统一 1536 维存储 + 低于补零 + 高于拒绝 422」作废。新方案:
- 每个知识库使用所选 embedding 模型的真实维度
- 实现: 建库时按所选 embedding 模型维度动态建独立向量表（命名规范如 rag_chunks_vec_<kb_id>），或 pgvector 每库独立表; 具体实现方式你（开发）设计并写清，但必须满足: a) 不同 KB 可用不同维度; b) 检索只走该 KB 自己的向量表; c) KB 更换 embedding 模型后需全量重算向量（重建该库向量表）; d) rag_knowledge_bases.embedding_dim 记录该库实际维度（建库快照）; e) 模型维度变更/删除时的影响说明
- DB_DESIGN: rag_chunks 表的 embedding 字段说明改为「向量按库独立表存储（维度=该库 embedding 模型维度）」，补 rag_chunks_vec 表的表结构定义（含 kb 关联、HNSW 索引按实际维度），§13 索引清单同步
- ARCHITECTURE: 涉及 1536/补零/422 的表述全部替换为按模型维度方案; 建库流程/换模型流程补重算向量步骤
- 全文检索 "1536"、"补零" 清零（除历史说明外）

【用户裁定 2（RISK-005 关闭）——trace/审计日志保留策略可配置天数】
原设计「在线 90 天【推测】」作废。新方案:
- 保留天数可配置: 配置文件/环境变量（如 TRACE_RETENTION_DAYS / AUDIT_RETENTION_DAYS），默认 90 天（默认值标注为设计决定）
- 实现: 按月分区 + 定期任务按配置天数 DROP PARTITION/清理（已有设计沿用，参数化）
- DB_DESIGN L198 附近（api_audit_logs 保留策略）、L828（trace_events 保留策略）: 去掉【推测】，改为「保留天数可配置（环境变量 TRACE_RETENTION_DAYS / AUDIT_RETENTION_DAYS，默认 90 天）；月分区 + 过期 DROP PARTITION」
- ARCHITECTURE 涉及 90 天/保留策略处同步
- 全文检索 "90 天" 确认均为可配置表述

【同步管理文件】
- DECISIONS.md: 新增 D-C（向量维度按模型）、D-D（保留策略可配置），标注「用户裁定 2026-09-22」
- RISKS.md: RISK-004、RISK-005 状态改 CLOSED，处置栏写裁定内容+落点文档章节
- 文档头部修订记录追加一行（日期 + 依据用户裁定）

【要求】
- 自查: 全文无 "1536 统一"/"补零"/"90 天【推测】" 残留; rag_chunks_vec 表进入 §15 表清单总表（表数+1 需同步 §14/§15 计数）; 索引清单与字段表一致
- 完成后 kanban 标记完成，summary 列出修订条目数 + 裁定落点章节
- 只改 ARCHITECTURE.md、DB_DESIGN.md、DECISIONS.md、RISKS.md 四份文件
