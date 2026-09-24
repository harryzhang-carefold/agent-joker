项目根目录: /home/hermes/hermes-workspace/projects/agent-joker
任务: D10 完成后复核用户裁定 D-C/D-D 的落地（你云天明，测试视角）:
1. 读 02-development/ARCHITECTURE.md、02-development/DB_DESIGN.md、00-management/DECISIONS.md、00-management/RISKS.md
2. 验证 D-C（向量维度按模型）: 全文无 "1536 统一存储/补零/超维422拒绝" 残留; 每库独立向量表方案在 DB（rag_chunks_vec 表结构+HNSW索引+§13索引清单+§15表清单计数）与 ARCH（建库/换模型重算向量流程）均落地; embedding_dim 为建库快照
3. 验证 D-D（保留策略可配置）: 全文无 "90天【推测】" 残留; TRACE_RETENTION_DAYS/AUDIT_RETENTION_DAYS 可配置+默认90天 在 DB（api_audit_logs/trace_events 两处）与 ARCH 一致; RISKS RISK-004/005 = CLOSED
4. 交叉一致性: 表数计数、索引清单、ER图 与新增 rag_chunks_vec 表一致; 是否引入新不一致
5. 输出 04-analysis/REVISION_VERIFY_D10.md: 逐条验证 + 结论（PASS/残留清单）。只读复核，不修改被审文档
6. 完成后 kanban 标记完成，summary 给: 验证项数/通过数/残留数 + 结论
