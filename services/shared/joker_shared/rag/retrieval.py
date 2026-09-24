"""RAG 检索核心（S05，RAG-06/07/08/09 + D-A official 两级判定 + D-B 内部检索留痕）。

设计要点（DB_DESIGN §4.4 / ARCH §2.2 / DECISION-006/022/023）：
- 向量召回（D-C）：检索只走**该 KB 自己的**独立向量表 `rag_chunks_vec_<kb_id>`，
  不跨库 join；多库 = 逐库召回后应用层合并。每个库用**自己的建库快照 embedding
  模型**向量化查询（RAG-06；换模型=全库重算，D-C，维度随库，不能跨库共用向量）。
- rerank 可选（RAG-07）：任一库配置了 active reranker 且未显式关闭 → 对合并候选
  重排；阈值语义（DECISION-006）：有 rerank 作用于 **rerank 分数**、无 rerank
  作用于**余弦相似度**（两情况阈值均生效）。reranker 不可用 → 降级纯向量（记日志）。
- topK + 阈值（RAG-08）：库级默认（top_k_default/score_threshold）+ 单次检索级覆盖
  （未传回落库级；多库默认取各库最大值=最严格，调用方可显式传覆盖）；
  每库召回 N = recall_top_n 或 max(3*topK, 20)。
- 反向定位（RAG-09）：返回 chunk_id/chunk_index + pos（原文坐标 JSONB，
  页/节/字符偏移/表格行列，供 RAG-11 切分对比与引用定位）。
- official 两级判定（D-A / DECISION-022）：`rag_docs.tag=official` 优先，
  NULL 继承库级 `rag_knowledge_bases.tag=official` → is_official 布尔
  （供 S09 AGENT-05 引用来源判定）。
- 留痕（D-B / DECISION-023）：内部检索落 trace `rag` 事件（自动建会话，
  不产生 tool_call 事件；S09 SAR 直调路径同样经此端点）。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared import trace as _trace
from joker_shared.llm import get_llm_service
from joker_shared.rag.service import vec_table

log = logging.getLogger("joker.rag.search")


# ---------------------------------------------------------------- official 两级判定（D-A）

def resolve_official(doc_tag: str | None, kb_tag: str | None) -> bool:
    """D-A / DECISION-022：文档级 tag=official 优先；NULL 继承库级 tag=official。"""
    if doc_tag is not None:
        return doc_tag == "official"
    return kb_tag == "official"


# ---------------------------------------------------------------- 内部校验（D-B）

async def check_agent_kb_grants(
    session: AsyncSession, tenant_id: str, agent_id: str, kb_ids: list[str]
) -> None:
    """"(agent_id, kb_id) 勾选校验（D-B / DECISION-023，ARCH §4.2）：
    全部 KB 必须已在 agent_knowledge_bases 勾选（deleted_at IS NULL），否则 403。"""
    if not kb_ids:
        return
    r = await session.execute(
        text(
            "SELECT knowledge_base_id FROM agent_knowledge_bases "
            "WHERE agent_id = CAST(:a AS uuid) AND deleted_at IS NULL AND knowledge_base_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"a": agent_id, "ids": kb_ids},
    )
    granted = {str(x[0]) for x in r.fetchall()}
    missing = [k for k in kb_ids if k not in granted]
    if missing:
        raise HTTPException(
            403,
            f"agent {agent_id} not granted kb access: {missing} (agent_knowledge_bases check, D-B)",
        )


# ---------------------------------------------------------------- trace 留痕（D-B；S09 统一 TraceService）

async def ensure_trace_session(
    session: AsyncSession, tenant_id: str, agent_id: str, user_id: str | None
) -> str | None:
    """取/建 trace_sessions（委托 S09 统一 TraceService；写失败不阻断检索）。"""
    return await _trace.ensure_trace_session(session, tenant_id, agent_id, user_id)


async def write_rag_event(
    session: AsyncSession,
    tenant_id: str,
    agent_id: str,
    user_id: str | None,
    session_id: str | None,
    payload: dict,
    rag_kb_id: str | None,
    status: str = "ok",
    latency_ms: int | None = None,
) -> None:
    """落 trace rag 事件（D-B 非拦截范围留痕；payload 脱敏；写失败不阻断主流程）。"""
    await _trace.write_event(
        session,
        tenant_id=tenant_id,
        trace_session_id=session_id,
        user_id=user_id,
        event_type="rag",
        payload=payload,
        rag_kb_id=rag_kb_id,
        status=status,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------- 检索核心

def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


async def search_kbs(
    session: AsyncSession,
    tenant_id: str,
    kb_ids: list[str],
    query: str,
    top_k: int | None = None,
    score_threshold: float | None = None,
    use_rerank: bool = True,
) -> dict:
    """多库 RAG 检索（D-C：逐库查各自向量表，应用层合并；RAG-06/07/08/09 语义）。

    返回 {items:[{chunk_id, content, kb_id, doc_id, doc_file_name, chunk_index, pos,
    tag, is_official, score, parent_content?}], total, top_k, threshold, reranked}。
    """
    if not kb_ids:
        raise HTTPException(422, "kb_ids is required (non-empty)")
    if not (query or "").strip():
        raise HTTPException(422, "query is required")
    kb_ids = list(dict.fromkeys(kb_ids))  # 去重保序

    # ---------- 库配置（租户行级；deleted 404 / 非 active 409）
    kbs: list[dict] = []
    for kb_id in kb_ids:
        r = await session.execute(
            text(
                "SELECT id, status, embedding_model_id, embedding_dim, reranker_model_id, "
                "top_k_default, score_threshold, recall_top_n, tag "
                "FROM rag_knowledge_bases WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"
            ),
            {"id": kb_id, "t": tenant_id},
        )
        row = r.first()
        if row is None:
            raise HTTPException(404, f"kb not found: {kb_id}")
        if row[1] != "active":
            raise HTTPException(409, f"kb not active (status={row[1]}): {kb_id}")
        kbs.append({
            "id": str(row[0]),
            "embedding_model_id": str(row[2]),
            "embedding_dim": int(row[3]),
            "reranker_model_id": str(row[4]) if row[4] else None,
            "top_k_default": int(row[5]),
            "score_threshold": float(row[6]),
            "recall_top_n": int(row[7]) if row[7] else None,
        })

    # ---------- RAG-08：单次覆盖，未传回落库级默认（多库默认取最严格=最大阈值）
    eff_top_k = int(top_k) if top_k else max(kb["top_k_default"] for kb in kbs)
    if eff_top_k <= 0:
        raise HTTPException(422, "top_k must be >= 1")
    eff_threshold = float(score_threshold) if score_threshold is not None else max(
        kb["score_threshold"] for kb in kbs
    )
    # RAG-07：有 active reranker 且未显式关闭 → 启用 rerank 精排
    eff_rerank = bool(use_rerank) and any(kb["reranker_model_id"] for kb in kbs)
    reranker_id = next((kb["reranker_model_id"] for kb in kbs if kb["reranker_model_id"]), None)

    llm = get_llm_service()

    # ---------- 逐库：查询向量化（该库自己的 embedding 模型）+ 向量召回（D-C 只走本库表）
    candidates: list[dict] = []
    for kb in kbs:
        recall_n = kb["recall_top_n"] or max(eff_top_k * 3, 20)
        tname = vec_table(kb["id"])
        exists = (await session.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": tname})).scalar_one()
        if not exists:
            log.warning("vec table missing for kb=%s (%s); skip", kb["id"], tname)
            continue
        qvec = (await llm.embed_texts(session, kb["embedding_model_id"], [query]))[0]
        if len(qvec) != kb["embedding_dim"]:
            raise HTTPException(
                500, f"query embedding dim mismatch: got {len(qvec)} want {kb['embedding_dim']} (kb={kb['id']})"
            )
        qv = _vec_literal(qvec)
        rows = await session.execute(
            text(
                # pgvector `<=>` 返回余弦**距离**（0=相同，2=相反）；余弦**相似度** = 1 - 距离
                f"SELECT v.chunk_id, (1 - (v.embedding <=> CAST(:qv AS vector)))::float8 AS sim "
                f"FROM {tname} v WHERE v.knowledge_base_id = CAST(:kb AS uuid) "
                f"ORDER BY v.embedding <=> CAST(:qv AS vector) LIMIT :n"
            ),
            {"qv": qv, "kb": kb["id"], "n": recall_n},
        )
        hits = rows.fetchall()
        if not hits:
            continue
        chunk_ids = [str(h[0]) for h in hits]
        sim_by_id = {str(h[0]): float(h[1]) for h in hits}
        meta = await session.execute(
            text(
                "SELECT c.id, c.doc_id, c.content, c.chunk_index, c.pos, c.parent_id, "
                "d.file_name, d.tag AS doc_tag, k.tag AS kb_tag, p.content AS parent_content "
                "FROM rag_chunks c "
                "JOIN rag_docs d ON d.id = c.doc_id AND d.deleted_at IS NULL "
                "JOIN rag_knowledge_bases k ON k.id = c.knowledge_base_id "
                "LEFT JOIN rag_chunks p ON p.id = c.parent_id "
                "WHERE c.knowledge_base_id = CAST(:kb AS uuid) AND c.deleted_at IS NULL "
                "AND c.id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"kb": kb["id"], "ids": chunk_ids},
        )
        for m in meta.fetchall():
            pos = m[4]
            if isinstance(pos, str):
                try:
                    pos = json.loads(pos)
                except ValueError:
                    pos = None
            candidates.append({
                "chunk_id": str(m[0]),
                "doc_id": str(m[1]),
                "content": m[2],
                "chunk_index": int(m[3]),
                "pos": pos,
                "parent_content": m[9],
                "kb_id": kb["id"],
                "doc_file_name": m[6],
                "doc_tag": m[7],
                "kb_tag": m[8],
                "score": sim_by_id.get(str(m[0]), 0.0),
            })

    if not candidates:
        return {
            "items": [], "total": 0, "top_k": eff_top_k,
            "threshold": eff_threshold, "reranked": False,
        }

    # ---------- rerank（RAG-07 可选；端点不可用 → 降级纯向量，记日志不阻断）
    reranked = False
    if eff_rerank and reranker_id and len(candidates) > 1:
        try:
            results = await llm.rerank(
                session, reranker_id, query, [c["content"] for c in candidates]
            )
            by_idx = {int(r["index"]): float(r["score"]) for r in results}
            for i, c in enumerate(candidates):
                c["score"] = by_idx.get(i, 0.0)
            candidates.sort(key=lambda x: x["score"], reverse=True)
            reranked = True
        except HTTPException as exc:
            log.warning("rerank unavailable (%s); fallback to vector similarity", exc.detail)

    # ---------- 阈值过滤（DECISION-006：有 rerank 作用 rerank 分、无则余弦相似度）+ topK
    kept = [c for c in candidates if c["score"] >= eff_threshold]
    kept = sorted(kept, key=lambda x: x["score"], reverse=True)[:eff_top_k]

    # ---------- 组装出参（RAG-09 chunk 索引+pos 反向定位 / D-A official 两级判定）
    items = []
    for c in kept:
        items.append({
            "chunk_id": c["chunk_id"],
            "content": c["content"],
            "kb_id": c["kb_id"],
            "doc_id": c["doc_id"],
            "doc_file_name": c["doc_file_name"],
            "chunk_index": c["chunk_index"],
            "pos": c["pos"],
            "tag": c["doc_tag"],
            "is_official": resolve_official(c["doc_tag"], c["kb_tag"]),
            "score": round(float(c["score"]), 6),
            "parent_content": c["parent_content"],
        })
    return {
        "items": items,
        "total": len(items),
        "top_k": eff_top_k,
        "threshold": eff_threshold,
        "reranked": reranked,
    }


async def search_with_trace(
    session: AsyncSession,
    tenant_id: str,
    agent_id: str | None,
    user_id: str | None,
    kb_ids: list[str],
    query: str,
    top_k: int | None = None,
    score_threshold: float | None = None,
    use_rerank: bool = True,
) -> dict:
    """内部检索入口封装（D-B / DECISION-023）：
    (agent_id,kb_id) 勾选校验（403）+ 检索 + rag trace 事件留痕（不产生 tool_call）。"""
    t0 = time.monotonic()
    try:
        if agent_id:
            await check_agent_kb_grants(session, tenant_id, agent_id, kb_ids)
        result = await search_kbs(
            session, tenant_id, kb_ids, query, top_k, score_threshold, use_rerank=use_rerank
        )
    except HTTPException as exc:
        # D-B 留痕：403（未勾选 KB）= denied、其余异常 = error（trace_events.status 语义）
        if agent_id:
            tsid = await ensure_trace_session(session, tenant_id, agent_id, user_id)
            await write_rag_event(
                session, tenant_id, agent_id, user_id, tsid,
                {"query": query, "kb_ids": kb_ids, "error": True, "error_detail": str(exc.detail)},
                kb_ids[0] if kb_ids else None,
                status="denied" if exc.status_code == 403 else "error",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        raise
    result["agent_id"] = agent_id
    if agent_id:
        tsid = await ensure_trace_session(session, tenant_id, agent_id, user_id)
        await write_rag_event(
            session, tenant_id, agent_id, user_id, tsid,
            {
                "query": query,
                "kb_ids": kb_ids,
                "top_k": result["top_k"],
                "threshold": result["threshold"],
                "reranked": result["reranked"],
                "hits": [
                    {"chunk_id": it["chunk_id"], "kb_id": it["kb_id"],
                     "score": it["score"], "is_official": it["is_official"]}
                    for it in result["items"]
                ],
            },
            kb_ids[0] if kb_ids else None,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    return result
