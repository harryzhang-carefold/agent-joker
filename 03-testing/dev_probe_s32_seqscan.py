"""S32: 验证无 HNSW 索引的 3584 维向量表上，检索 SQL（retrieval.py 同构）走顺序扫描且结果正确。
在 pg 内建临时表（session 结束自动清理），插入 3 条 3584 维向量（第 1 条与查询最相似），
跑与 retrieval.py:190-193 完全相同的 SQL，EXPLAIN 确认 Seq Scan，结果确认 top-1 = 第 1 条。
"""
import asyncio
import random
import asyncpg

random.seed(42)


async def main():
    import os
    dsn = os.environ.get("DB_DSN", "").replace("+asyncpg", "")
    if not dsn:
        raise SystemExit("FATAL: no DB_DSN in container env")
    conn = await asyncpg.connect(dsn)
    # 3584 维：vec1 与 qvec 几乎相同（应排第一），vec2/vec3 随机
    def mk(first=0.0):
        vals = [round(first + random.random() * 0.01, 5) for _ in range(3584)]
        return "[" + ",".join(str(v) for v in vals) + "]"

    qv = mk(0.983)
    v1 = mk(0.983)
    v2 = mk(0.0)
    v3 = mk(0.5)

    await conn.execute("CREATE TEMP TABLE t32seqscan (i int, embedding vector(3584))")
    await conn.execute(
        "INSERT INTO t32seqscan VALUES (1, $1), (2, $2), (3, $3)", v1, v2, v3
    )

    # 与 services/shared/joker_shared/rag/retrieval.py 同构的检索 SQL
    sql = (
        "SELECT i, (1 - (v.embedding <=> CAST($1 AS vector)))::float8 AS sim "
        "FROM t32seqscan v ORDER BY v.embedding <=> CAST($1 AS vector) LIMIT 3"
    )
    rows = await conn.fetch(sql, qv)
    print("retrieval SQL result (no HNSW index, 3584 dim):")
    for r in rows:
        print(f"  i={r[0]} sim={r[1]:.6f}")

    plan = await conn.fetch("EXPLAIN (COSTS OFF) " + sql, qv)
    print("EXPLAIN plan:")
    for r in plan:
        print("  " + r[0])

    top1 = rows[0][0]
    seqscan = any("Seq Scan" in r[0] for r in plan)
    print(f"\nRESULT top1={top1} (expect 1) seqscan={seqscan} (expect True)")
    print(f"PASS={'PASS' if top1 == 1 and seqscan else 'FAIL'}")
    await conn.close()


asyncio.run(main())
