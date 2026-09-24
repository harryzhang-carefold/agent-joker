"""RAGService（S04，RAG-01/02/03/04/05/11 + 建库/向量化流水线）。

设计要点（DB_DESIGN §4 / ARCH §2.2 / DECISION-021/024）：
- 建库（RAG-01）：选 embedding 模型 → 固化 embedding_dim（建库快照）→
  动态建该库独立向量表 rag_chunks_vec_<kb_id>（HNSW 按实际维度 N，D-C）。
- 上传（RAG-02）：6 类文档经 StorageService 落盘（source=kb，上传记录留痕）→
  rag_docs 行（status=uploaded）→ 进程内任务队列（DECISION-021，worker 单并发串行）。
- 流水线：uploaded→parsing→splitting→embedded→ready / failed（状态机驱动，
  每步独立 commit，崩溃后重放从断点继续）。
- 解析（RAG-03）：pymupdf/python-docx/openpyxl/直读（DECISION-005）；
  图片/扫描页/内嵌图 → supports_vision 的 LLM endpoint 视觉解析；
  视觉不可用 → 降级（占位块 + rag_doc_images skipped + 日志，不阻断）。
- 切分（RAG-04）：5 策略工厂（fixed/parent_child/semantic/structured_tree/table），
  库级默认 + 文档级覆盖，重切分 = 删旧 chunk + 重建向量。
- 向量化：chunk embedding 批量写入该库独立向量表（D-C：检索只走本库表）。
- 原文查看 + chunk 编辑（RAG-05）：原文经 StorageService 取回；
  编辑 chunk → 重算向量写本库向量表 + edited_at 留痕。
- 切分对比（RAG-11，ARCH §2.2.1）：chunk 列表 / chunk→pos / 位置→chunk 反查。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared.config import settings
from joker_shared.llm import get_llm_service
from joker_shared.rag.parser import DOC_TYPE_BY_EXT, ParsedBlock, SUPPORTED_TYPES, parse_document
from joker_shared.rag.splitter import DEFAULT_PARAMS, STRATEGIES, split_blocks, effective_strategy
from joker_shared.storage.service import get_storage_service

log = logging.getLogger("joker.rag")

KB_STATUSES = ("active", "reindexing", "disabled")
DOC_STATUSES = ("uploaded", "parsing", "splitting", "embedded", "ready", "failed", "reindexing")
_EMBED_BATCH = 32  # EmbeddingNode 批量（ARCH §2.2【推测】默认 32）

# ---------------------------------------------------------------- 进程内任务队列（DECISION-021）

class TaskQueue:
    """进程内文档任务队列：worker 单并发串行处理（闭环规模；预留 Redis 兜底 key）。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._running_docs: set[str] = set()

    async def enqueue(self, doc_id: str) -> None:
        await self._queue.put(doc_id)

    async def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._loop(), name="rag-doc-worker")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()

    async def _loop(self) -> None:
        from joker_shared.db import get_session

        while True:
            item = await self._queue.get()
            doc_id = item.split(":", 1)[1] if item.startswith("resplit:") else item
            if doc_id in self._running_docs:
                continue
            self._running_docs.add(doc_id)
            try:
                async for session in get_session():
                    try:
                        await process_document(session, doc_id)
                    except Exception as exc:
                        # 流水线失败 → 状态落 failed（带错误摘要），不静默卡死
                        log.exception("rag doc worker failed item=%s", item)
                        await session.execute(
                            text("UPDATE rag_docs SET status = 'failed', error_message = :e WHERE id = CAST(:id AS uuid)"),
                            {"e": f"{type(exc).__name__}: {exc}", "id": doc_id},
                        )
                        await session.commit()
                    break
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("rag doc worker session-level failure item=%s", item)
            finally:
                self._running_docs.discard(doc_id)


_task_queue = TaskQueue()


def get_task_queue() -> TaskQueue:
    return _task_queue


# ---------------------------------------------------------------- 向量表辅助

def vec_table(kb_id: str) -> str:
    """每库独立向量表名（D-C / DECISION-024）：rag_chunks_vec_<kb_id 去连字符>。"""
    return f"rag_chunks_vec_{kb_id.replace('-', '')}"


def _vec_literal(vec: list[float]) -> str:
    """pgvector 向量字面量 '[0.1,0.2,...]'（参数化绑定：::vector 在 named param 后失效，
    故字面量拼进 SQL —— 值仅含数字/逗号/方括号/负号/点，无注入面）。"""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


# ---------------------------------------------------------------- KB CRUD（RAG-01）

async def _kb_row(session: AsyncSession, tenant_id: str, kb_id: str) -> Any:
    r = await session.execute(
        text("SELECT * FROM rag_knowledge_bases WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"),
        {"id": kb_id, "t": tenant_id},
    )
    return r.first()


async def _kb_dict(row: Any) -> dict:
    d = dict(row._mapping)
    for k in ("id", "tenant_id", "embedding_model_id", "reranker_model_id", "created_by", "updated_by"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if isinstance(d.get("split_params_default"), str):
        try:
            d["split_params_default"] = json.loads(d["split_params_default"])
        except ValueError:
            d["split_params_default"] = None
    if d.get("score_threshold") is not None:
        d["score_threshold"] = float(d["score_threshold"])
    return d


async def list_kbs(session: AsyncSession, tenant_id: str, status: str | None = None, page: int = 1, page_size: int = 50) -> dict:
    where = ["tenant_id = CAST(:t AS uuid)", "deleted_at IS NULL"]
    params: dict[str, Any] = {"t": tenant_id, "ps": page_size, "off": (page - 1) * page_size}
    if status:
        where.append("status = :st"); params["st"] = status
    w = " AND ".join(where)
    total = (await session.execute(text(f"SELECT count(*) FROM rag_knowledge_bases WHERE {w}"), params)).scalar_one()
    rows = await session.execute(
        text(f"SELECT * FROM rag_knowledge_bases WHERE {w} ORDER BY created_at LIMIT :ps OFFSET :off"), params
    )
    items = []
    for r in rows.fetchall():
        d = await _kb_dict(r)
        # D-C 每库独立向量表信息（API_NOTES 列表契约：vec_table/vec_table_exists）
        d["vec_table"] = vec_table(d["id"])
        d["vec_table_exists"] = await _table_exists(session, d["vec_table"])
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def create_kb(
    session: AsyncSession, tenant_id: str, user_id: str | None, d: dict
) -> dict:
    """建库：校验 embedding 模型（active）→ 固化 embedding_dim（D-C 快照）→
    动态建独立向量表 rag_chunks_vec_<kb_id>（HNSW 按实际维度）。"""
    name = (d.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    emb_id = d.get("embedding_model_id")
    if not emb_id:
        raise HTTPException(422, "embedding_model_id is required (RAG-01 验收 2)")
    emb = (
        await session.execute(
            text("SELECT id, name, dimensions, status FROM llm_embedding_models WHERE id = CAST(:id AS uuid)"),
            {"id": emb_id},
        )
    ).first()
    if emb is None:
        raise HTTPException(404, f"embedding model not found: {emb_id}")
    if emb[3] != "active":
        raise HTTPException(409, f"embedding model disabled: {emb[1]}")

    if d.get("reranker_model_id"):
        rr = (
            await session.execute(
                text("SELECT id, status FROM llm_reranker_models WHERE id = CAST(:id AS uuid)"),
                {"id": d["reranker_model_id"]},
            )
        ).first()
        if rr is None:
            raise HTTPException(404, f"reranker model not found: {d['reranker_model_id']}")
    strategy = d.get("split_strategy_default") or "fixed"
    if strategy not in STRATEGIES:
        raise HTTPException(422, f"split_strategy_default must be one of {list(STRATEGIES)}")

    dup = (
        await session.execute(
            text("SELECT 1 FROM rag_knowledge_bases WHERE tenant_id = CAST(:t AS uuid) AND name = :n AND deleted_at IS NULL"),
            {"t": tenant_id, "n": name},
        )
    ).first()
    if dup:
        raise HTTPException(409, f"kb name already exists: {name}")

    kb_id = str(uuid.uuid4())
    dim = int(emb[2])
    # 先建向量表（失败不留半截库行）
    tname = (
        await session.execute(text("SELECT create_rag_chunks_vec(CAST(:id AS uuid), :dim)"), {"id": kb_id, "dim": dim})
    ).scalar_one()
    await session.execute(
        text(
            """INSERT INTO rag_knowledge_bases
            (id, tenant_id, name, description, tag, embedding_model_id, embedding_dim, reranker_model_id,
             top_k_default, score_threshold, recall_top_n, split_strategy_default, split_params_default,
             status, created_by, updated_by)
            VALUES (CAST(:id AS uuid), CAST(:t AS uuid), :n, :desc, :tag, CAST(:emb AS uuid), :dim,
                    CAST(:rr AS uuid), :tk, CAST(:th AS numeric(4,3)), :rn, :ss, :sp, 'active',
                    CAST(:u AS uuid), CAST(:u AS uuid))"""
        ),
        {
            "id": kb_id, "t": tenant_id, "n": name, "desc": d.get("description"),
            "tag": d.get("tag"), "emb": emb_id, "dim": dim,
            "rr": d.get("reranker_model_id"),
            "tk": int(d.get("top_k_default") or 5),
            "th": float(d.get("score_threshold") or 0.3),
            "rn": d.get("recall_top_n"), "ss": strategy,
            "sp": json.dumps(d.get("split_params_default") or DEFAULT_PARAMS.get(strategy, {})),
            "u": user_id,
        },
    )
    await session.commit()
    log.info("kb created %s (%s) dim=%s vec_table=%s", name, kb_id, dim, tname)
    return await get_kb(session, tenant_id, kb_id)


async def get_kb(session: AsyncSession, tenant_id: str, kb_id: str) -> dict | None:
    row = await _kb_row(session, tenant_id, kb_id)
    if row is None or row._mapping.get("deleted_at") is not None:
        return None
    d = await _kb_dict(row)
    d["vec_table"] = vec_table(kb_id)
    d["vec_table_exists"] = await _table_exists(session, vec_table(kb_id))
    return d


async def _table_exists(session: AsyncSession, name: str) -> bool:
    r = await session.execute(
        text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}
    )
    return bool(r.scalar_one())


async def update_kb(session: AsyncSession, tenant_id: str, user_id: str | None, kb_id: str, d: dict) -> dict:
    row = await _kb_row(session, tenant_id, kb_id)
    if row is None or row._mapping.get("deleted_at") is not None:
        raise HTTPException(404, f"kb not found: {kb_id}")
    sets, params = [], {"id": kb_id, "t": tenant_id, "ub": user_id}
    for col in ("name", "description", "tag", "top_k_default", "recall_top_n", "split_strategy_default"):
        if col in d:
            sets.append(f"{col} = :{col}"); params[col] = d[col]
    if "score_threshold" in d:
        sets.append("score_threshold = :th"); params["th"] = float(d["score_threshold"])
    if "split_params_default" in d:
        sets.append("split_params_default = :sp"); params["sp"] = json.dumps(d["split_params_default"] or {})
    if "status" in d:
        if d["status"] not in KB_STATUSES:
            raise HTTPException(422, f"status must be one of {list(KB_STATUSES)}")
        sets.append("status = :st"); params["st"] = d["status"]
    if not sets:
        raise HTTPException(400, "no fields to update")
    if "name" in d and d["name"] != row._mapping["name"]:
        dup = (
            await session.execute(
                text("SELECT 1 FROM rag_knowledge_bases WHERE tenant_id = CAST(:t AS uuid) AND name = :n AND id <> CAST(:id AS uuid) AND deleted_at IS NULL"),
                {"t": tenant_id, "n": d["name"], "id": kb_id},
            )
        ).first()
        if dup:
            raise HTTPException(409, f"kb name already exists: {d['name']}")
    sets.append("updated_by = :ub")
    await session.execute(text(f"UPDATE rag_knowledge_bases SET {', '.join(sets)} WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"), params)
    await session.commit()
    return await get_kb(session, tenant_id, kb_id)


async def delete_kb(session: AsyncSession, tenant_id: str, kb_id: str) -> dict:
    """删除库 = 级联删文档/chunk + DROP 向量表（RAG-01 验收 5；D-C）。

    软删库行（deleted_at）；文档/chunk 由库软删联动（应用层）；向量表 DROP
    （库已不可检索，物理释放）。
    """
    row = await _kb_row(session, tenant_id, kb_id)
    if row is None or row._mapping.get("deleted_at") is not None:
        raise HTTPException(404, f"kb not found: {kb_id}")
    # 级联软删文档（chunk 随 doc 级联；向量随 chunk FK 级联，但 DROP 表更快更干净）
    await session.execute(
        text(
            "UPDATE rag_docs SET deleted_at = now() WHERE knowledge_base_id = CAST(:id AS uuid) "
            "AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"
        ),
        {"id": kb_id, "t": tenant_id},
    )
    await session.execute(
        text(
            "UPDATE rag_knowledge_bases SET deleted_at = now(), doc_count = 0 "
            "WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"
        ),
        {"id": kb_id, "t": tenant_id},
    )
    await session.commit()
    # DROP 向量表（库级独立表，D-C；FK CASCADE 会先删 chunk 行，此处直接 DROP）
    tname = vec_table(kb_id)
    await session.execute(text(f"DROP TABLE IF EXISTS {tname}"))
    await session.commit()
    log.info("kb deleted %s; vec table %s dropped", kb_id, tname)
    return {"ok": True, "deleted": kb_id}


async def reindex_kb(session: AsyncSession, tenant_id: str, user_id: str | None, kb_id: str, new_emb_id: str) -> dict:
    """换 embedding 模型 = 全库重算向量（D-C 流程 c）：
    ① 建新维度影子表 → ② 全量重嵌入（status=reindexing，期间检索走旧表）
    → ③ 切换 embedding_dim + 表引用（rename 交换）→ ④ DROP 旧表。

    闭环实现：后台任务队列驱动（逐文档重切分+重嵌入到新表），完成后切换。
    """
    row = await _kb_row(session, tenant_id, kb_id)
    if row is None or row._mapping.get("deleted_at") is not None:
        raise HTTPException(404, f"kb not found: {kb_id}")
    if row._mapping["status"] == "reindexing":
        raise HTTPException(409, "kb is already reindexing")
    emb = (
        await session.execute(
            text("SELECT id, name, dimensions, status FROM llm_embedding_models WHERE id = CAST(:id AS uuid)"),
            {"id": new_emb_id},
        )
    ).first()
    if emb is None:
        raise HTTPException(404, f"embedding model not found: {new_emb_id}")
    if emb[3] != "active":
        raise HTTPException(409, f"embedding model disabled: {emb[1]}")
    new_dim = int(emb[2])
    old_tname = vec_table(kb_id)
    shadow = f"{old_tname}_reindex"
    # ① 影子表（新维度）
    await session.execute(text(f"DROP TABLE IF EXISTS {shadow}"))
    await session.execute(
        text(
            f"CREATE TABLE {shadow} (chunk_id UUID PRIMARY KEY REFERENCES rag_chunks(id) ON DELETE CASCADE, "
            f"knowledge_base_id UUID NOT NULL REFERENCES rag_knowledge_bases(id) ON DELETE CASCADE, "
            f"embedding vector({new_dim}) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            f"updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    )
    await session.execute(
        text(f"CREATE INDEX ON {shadow} USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)")
    )
    # ② 状态切 reindexing + 记录目标
    await session.execute(
        text(
            "UPDATE rag_knowledge_bases SET status = 'reindexing', embedding_model_id = CAST(:e AS uuid), "
            "updated_by = CAST(:u AS uuid) WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"
        ),
        {"e": new_emb_id, "u": user_id, "id": kb_id, "t": tenant_id},
    )
    await session.commit()
    # ③ 逐文档重切分 + 重嵌入（旧 chunk 保留 → 检索期间仍走旧表）
    docs = (
        await session.execute(
            text(
                "SELECT id FROM rag_docs WHERE knowledge_base_id = CAST(:id AS uuid) "
                "AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"
            ),
            {"id": kb_id, "t": tenant_id},
        )
    ).fetchall()
    await _enqueue_reindex(session, kb_id, [str(d[0]) for d in docs], shadow, new_dim, new_emb_id, tenant_id, user_id)
    return {"ok": True, "kb_id": kb_id, "status": "reindexing", "shadow_table": shadow, "new_dim": new_dim}


# ---------------------------------------------------------------- 文档（RAG-02）

async def upload_doc(
    session: AsyncSession,
    tenant_id: str,
    user_id: str | None,
    kb_id: str,
    file_name: str,
    data: bytes,
    content_type: str | None,
    tag: str | None = None,
    split_strategy: str | None = None,
    split_params: dict | None = None,
) -> dict:
    """上传文档到知识库：StorageService 落盘（source=kb）→ rag_docs 行 → 入队解析流水线。

    422：非支持类型 / .doc 旧格式（提示转 .docx）/ 空文件。
    """
    kb = await get_kb(session, tenant_id, kb_id)
    if kb is None:
        raise HTTPException(404, f"kb not found: {kb_id}")
    if kb["status"] != "active":
        raise HTTPException(409, f"kb not active (status={kb['status']})")

    ext = ("." + file_name.rsplit(".", 1)[-1].lower()) if "." in file_name else ""
    doc_type = DOC_TYPE_BY_EXT.get(ext)
    if doc_type is None:
        if ext == ".doc":
            raise HTTPException(422, ".doc 旧格式不支持（仅 .docx）：请转换为 .docx 后重新上传")
        raise HTTPException(422, f"unsupported file type: {ext or '(none)'} (supported: {', '.join(sorted(SUPPORTED_TYPES))})")

    storage = get_storage_service()
    try:
        info = await storage.upload(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            file_name=file_name,
            data=data,
            content_type=content_type,
            source="kb",  # RAG-02 验收 4：上传记录 source=知识库
        )
    except HTTPException as exc:
        # 同名 409 → 语义化为文档级错误
        if exc.status_code == 409:
            raise HTTPException(409, f"file_name already exists in storage: {file_name}") from exc
        raise

    doc_id = str(uuid.uuid4())
    if split_strategy and split_strategy not in STRATEGIES:
        raise HTTPException(422, f"split_strategy must be one of {list(STRATEGIES)}")
    await session.execute(
        text(
            """INSERT INTO rag_docs
            (id, tenant_id, knowledge_base_id, file_id, file_name, tag, doc_type, status,
             split_strategy, split_params, created_by, updated_by)
            VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:kb AS uuid), CAST(:f AS uuid), :fn,
                    :tag, :dt, 'uploaded', :ss, :sp, CAST(:u AS uuid), CAST(:u AS uuid))"""
        ),
        {
            "id": doc_id, "t": tenant_id, "kb": kb_id, "f": info["id"],
            "fn": file_name, "tag": tag, "dt": doc_type,
            "ss": split_strategy, "sp": json.dumps(split_params) if split_params else None,
            "u": user_id,
        },
    )
    await session.execute(
        text("UPDATE rag_knowledge_bases SET doc_count = doc_count + 1 WHERE id = CAST(:id AS uuid)"),
        {"id": kb_id},
    )
    await session.commit()
    await get_task_queue().enqueue(doc_id)
    log.info("doc uploaded %s → kb %s (%s)", file_name, kb_id, doc_id)
    return await get_doc(session, tenant_id, kb_id, doc_id)


async def _doc_row(session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str) -> Any:
    r = await session.execute(
        text(
            "SELECT d.*, k.name AS kb_name FROM rag_docs d "
            "JOIN rag_knowledge_bases k ON k.id = d.knowledge_base_id "
            "WHERE d.id = CAST(:id AS uuid) AND d.tenant_id = CAST(:t AS uuid) "
            "AND d.knowledge_base_id = CAST(:kb AS uuid)"
        ),
        {"id": doc_id, "t": tenant_id, "kb": kb_id},
    )
    return r.first()


def _doc_dict(row: Any) -> dict:
    d = dict(row._mapping)
    for k in ("id", "tenant_id", "knowledge_base_id", "file_id", "created_by", "updated_by"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if isinstance(d.get("split_params"), str):
        try:
            d["split_params"] = json.loads(d["split_params"])
        except ValueError:
            d["split_params"] = None
    for ts in ("created_at", "updated_at", "deleted_at"):
        if d.get(ts) is not None:
            d[ts] = d[ts].isoformat()
    d.pop("kb_name", None) or d.update({"kb_name": row._mapping.get("kb_name")})
    return d


async def get_doc(session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str) -> dict | None:
    row = await _doc_row(session, tenant_id, kb_id, doc_id)
    if row is None or row._mapping.get("deleted_at") is not None:
        return None
    d = _doc_dict(row)
    d["kb_name"] = row._mapping.get("kb_name")
    return d


async def list_docs(
    session: AsyncSession, tenant_id: str, kb_id: str,
    status: str | None = None, page: int = 1, page_size: int = 50,
) -> dict:
    kb = await get_kb(session, tenant_id, kb_id)
    if kb is None:
        raise HTTPException(404, f"kb not found: {kb_id}")
    where = [
        "d.tenant_id = CAST(:t AS uuid)", "d.knowledge_base_id = CAST(:kb AS uuid)", "d.deleted_at IS NULL"
    ]
    params: dict[str, Any] = {"t": tenant_id, "kb": kb_id, "ps": page_size, "off": (page - 1) * page_size}
    if status:
        where.append("d.status = :st"); params["st"] = status
    w = " AND ".join(where)
    total = (await session.execute(text(f"SELECT count(*) FROM rag_docs d WHERE {w}"), params)).scalar_one()
    rows = await session.execute(
        text(f"SELECT d.* FROM rag_docs d WHERE {w} ORDER BY d.created_at LIMIT :ps OFFSET :off"),
        params,
    )
    items = [_doc_dict(r) for r in rows.fetchall()]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def delete_doc(session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str) -> dict:
    """删除文档：级联物理删 chunk（向量随 FK CASCADE 同删，DB_DESIGN §13.3）
    + 库 doc_count 维护。原文件保留在存储（rag_docs 软删后解除引用，可再删文件）。"""
    row = await _doc_row(session, tenant_id, kb_id, doc_id)
    if row is None or row._mapping.get("deleted_at") is not None:
        raise HTTPException(404, f"doc not found: {doc_id}")
    # chunk 物理删（向量行 FK ON DELETE CASCADE 同删 —— 设计：删除级联删文档/chunk/向量）
    await session.execute(
        text("DELETE FROM rag_chunks WHERE doc_id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"),
        {"id": doc_id, "t": tenant_id},
    )
    await session.execute(
        text("UPDATE rag_docs SET deleted_at = now() WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"),
        {"id": doc_id, "t": tenant_id},
    )
    await session.execute(
        text("UPDATE rag_knowledge_bases SET doc_count = GREATEST(doc_count - 1, 0) WHERE id = CAST(:kb AS uuid)"),
        {"kb": kb_id},
    )
    await session.commit()
    _parsed_cache.pop(doc_id, None)
    return {"ok": True, "deleted": doc_id}


async def doc_file_bytes(session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str) -> tuple[dict, bytes]:
    """原文档二进制（RAG-05 验收 1 / RAG-11 左栏渲染源，经 StorageService → 后端透明）。"""
    doc = await get_doc(session, tenant_id, kb_id, doc_id)
    if doc is None:
        raise HTTPException(404, f"doc not found: {doc_id}")
    row, data = await get_storage_service().download(session, tenant_id, doc["file_name"])
    return doc, data


# ---------------------------------------------------------------- chunk（RAG-05 / RAG-11）

def _chunk_dict(row: Any) -> dict:
    d = dict(row._mapping)
    for k in ("id", "tenant_id", "doc_id", "knowledge_base_id", "parent_id", "created_by", "updated_by"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    if isinstance(d.get("pos"), str):
        try:
            d["pos"] = json.loads(d["pos"])
        except ValueError:
            d["pos"] = None
    for ts in ("edited_at", "created_at", "updated_at"):
        if d.get(ts) is not None:
            d[ts] = d[ts].isoformat()
    if d.get("last_score") is not None:
        d["last_score"] = float(d["last_score"])
    return d


async def list_chunks(
    session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str,
    page: int = 1, page_size: int = 100,
) -> dict:
    """chunk 列表（右栏；RAG-05 验收 3 / RAG-11 接口 2）：按 chunk_index 升序。"""
    doc = await get_doc(session, tenant_id, kb_id, doc_id)
    if doc is None:
        raise HTTPException(404, f"doc not found: {doc_id}")
    where = [
        "c.tenant_id = CAST(:t AS uuid)", "c.doc_id = CAST(:d AS uuid)", "c.deleted_at IS NULL"
    ]
    params: dict[str, Any] = {"t": tenant_id, "d": doc_id, "ps": page_size, "off": (page - 1) * page_size}
    w = " AND ".join(where)
    total = (await session.execute(text(f"SELECT count(*) FROM rag_chunks c WHERE {w}"), params)).scalar_one()
    rows = await session.execute(
        text(f"SELECT c.* FROM rag_chunks c WHERE {w} ORDER BY c.chunk_index LIMIT :ps OFFSET :off"), params
    )
    items = [_chunk_dict(r) for r in rows.fetchall()]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def chunk_location(session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str, chunk_id: str) -> dict:
    """chunk → 原文位置映射（RAG-11 接口 3：右→左联动）。"""
    r = await session.execute(
        text(
            "SELECT c.pos FROM rag_chunks c WHERE c.id = CAST(:cid AS uuid) AND c.doc_id = CAST(:d AS uuid) "
            "AND c.tenant_id = CAST(:t AS uuid) AND c.deleted_at IS NULL"
        ),
        {"cid": chunk_id, "d": doc_id, "t": tenant_id},
    )
    row = r.first()
    if row is None:
        raise HTTPException(404, f"chunk not found: {chunk_id}")
    pos = row[0]
    if isinstance(pos, str):
        pos = json.loads(pos)
    return {"pos": pos or {}, "chunk_id": chunk_id}


async def chunks_by_location(
    session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str, pos: dict
) -> dict:
    """原文位置 → chunk 反查（RAG-11 接口 4：左→右联动）。

    包含判定（ARCH §2.2.1）：
    - 文本类（page + char 区间）：同页（或同节）且 [char_start, char_end] 包含请求位置
    - 表格类：sheet + 行/列区间相交
    - 图片类：page 相等
    重叠切分可能多命中；primary_chunk_id = chunk_index 最小者。
    """
    doc = await get_doc(session, tenant_id, kb_id, doc_id)
    if doc is None:
        raise HTTPException(404, f"doc not found: {doc_id}")
    rows = await session.execute(
        text(
            "SELECT id, chunk_index, pos FROM rag_chunks "
            "WHERE doc_id = CAST(:d AS uuid) AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL "
            "ORDER BY chunk_index"
        ),
        {"d": doc_id, "t": tenant_id},
    )
    items: list[dict] = []
    req_page = pos.get("page")
    req_cs, req_ce = pos.get("char_start"), pos.get("char_end")
    req_tr = pos.get("table_row") or {}
    req_sp = tuple(pos.get("section_path") or ())
    for r in rows.fetchall():
        cpos = r[2]
        if isinstance(cpos, str):
            cpos = json.loads(cpos) or {}
        hit = False
        if req_tr:  # 表格：sheet + 行列区间相交
            ctr = cpos.get("table_row") or {}
            if (
                ctr.get("sheet") == req_tr.get("sheet")
                and ctr.get("table") == req_tr.get("table")
                and (ctr.get("row_start") or 1) <= (req_tr.get("row_end") or 0)
                and (ctr.get("row_end") or 0) >= (req_tr.get("row_start") or 1)
            ):
                hit = True
        elif req_cs is not None and req_ce is not None:
            # 文本类：页/节匹配 + 字符区间包含
            page_ok = req_page is None or cpos.get("page") is None or cpos.get("page") == req_page
            sp_ok = (
                not req_sp
                or not cpos.get("section_path")
                or tuple(cpos.get("section_path") or ()) == req_sp
            )
            cs, ce = cpos.get("char_start"), cpos.get("char_end")
            if page_ok and sp_ok and cs is not None and ce is not None:
                hit = cs <= req_cs and ce >= req_ce
        elif req_page is not None:
            hit = cpos.get("page") == req_page
        if hit:
            items.append({"chunk_id": str(r[0]), "chunk_index": int(r[1])})
    items.sort(key=lambda x: x["chunk_index"])
    return {"items": items, "primary_chunk_id": items[0]["chunk_id"] if items else None}


async def edit_chunk(
    session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str, chunk_id: str,
    content: str, user_id: str | None,
) -> dict:
    """编辑 chunk 文本（RAG-05 验收 2/4）：更新 content + 重算向量写本库向量表 +
    edited_at/updated_by 留痕。"""
    if content is None or not str(content).strip():
        raise HTTPException(422, "content must be non-empty")
    r = await session.execute(
        text(
            "SELECT id, content FROM rag_chunks WHERE id = CAST(:cid AS uuid) AND doc_id = CAST(:d AS uuid) "
            "AND tenant_id = CAST(:t AS uuid) AND deleted_at IS NULL"
        ),
        {"cid": chunk_id, "d": doc_id, "t": tenant_id},
    )
    row = r.first()
    if row is None:
        raise HTTPException(404, f"chunk not found: {chunk_id}")
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    await session.execute(
        text(
            "UPDATE rag_chunks SET content = :c, content_sha256 = :s, edited_at = now(), "
            "updated_by = CAST(:u AS uuid) WHERE id = CAST(:cid AS uuid)"
        ),
        {"c": content, "s": sha, "u": user_id, "cid": chunk_id},
    )
    # 重算向量写本库向量表（D-C：检索只走本库表）
    kb = await get_kb(session, tenant_id, kb_id)
    vecs = await get_llm_service().embed_texts(session, kb["embedding_model_id"], [content])
    tname = vec_table(kb_id)
    await session.execute(
        text(f"INSERT INTO {tname} (chunk_id, knowledge_base_id, embedding) "
             "VALUES (CAST(:cid AS uuid), CAST(:kb AS uuid), CAST(:v AS vector)) "
             "ON CONFLICT (chunk_id) DO UPDATE SET embedding = EXCLUDED.embedding"),
        {"cid": chunk_id, "kb": kb_id, "v": _vec_literal(vecs[0])},
    )
    await session.commit()
    log.info("chunk edited %s (kb %s) re-embedded", chunk_id, kb_id)
    row2 = (
        await session.execute(text("SELECT * FROM rag_chunks WHERE id = CAST(:cid AS uuid)"), {"cid": chunk_id})
    ).first()
    return _chunk_dict(row2)


async def resplit_doc(
    session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str,
    split_strategy: str | None, split_params: dict | None, user_id: str | None,
) -> dict:
    """重切分（RAG-04 验收 2）：删旧 chunk（+向量）→ 按新策略重新 解析→切分→向量化。

    解析产物（图片/视觉记录）保留（重新解析成本高且视觉记录可追溯）；
    重切分仅重跑 split + embed 阶段。文档状态 → splitting（完成后 ready）。
    """
    doc = await get_doc(session, tenant_id, kb_id, doc_id)
    if doc is None:
        raise HTTPException(404, f"doc not found: {doc_id}")
    if doc["status"] not in ("ready", "embedded", "failed"):
        raise HTTPException(409, f"doc not ready for resplit (status={doc['status']})")
    if split_strategy and split_strategy not in STRATEGIES:
        raise HTTPException(422, f"split_strategy must be one of {list(STRATEGIES)}")
    # 持久化文档级覆盖（RAG-04：策略可在文档级配置并重新切分）
    sets = ["updated_by = CAST(:u AS uuid)", "status = 'splitting'", "error_message = NULL"]
    params: dict[str, Any] = {"id": doc_id, "t": tenant_id, "u": user_id}
    if split_strategy is not None:
        sets.append("split_strategy = :ss"); params["ss"] = split_strategy
    if split_params is not None:
        sets.append("split_params = :sp"); params["sp"] = json.dumps(split_params)
    await session.execute(text(f"UPDATE rag_docs SET {', '.join(sets)} WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"), params)
    await session.commit()
    await _enqueue_resplit(doc_id)
    return await get_doc(session, tenant_id, kb_id, doc_id)


# ---------------------------------------------------------------- 流水线（DECISION-021 状态机）

# 解析产物进程内缓存（doc_id → blocks）：重切分复用，避免二次解析/视觉调用。
# 崩溃后缓存丢失 → splitting 阶段重新解析（视觉记录追加、行为一致，幂等）。
_parsed_cache: dict[str, list[dict]] = {}


async def _set_doc_status(session: AsyncSession, doc_id: str, status: str, error: str | None = None) -> None:
    if error is not None:
        await session.execute(
            text("UPDATE rag_docs SET status = :st, error_message = :e WHERE id = CAST(:id AS uuid)"),
            {"st": status, "e": error, "id": doc_id},
        )
    else:
        await session.execute(
            text("UPDATE rag_docs SET status = :st, error_message = NULL WHERE id = CAST(:id AS uuid)"),
            {"st": status, "id": doc_id},
        )
    await session.commit()


async def process_document(session: AsyncSession, doc_id: str) -> None:
    """文档流水线：uploaded→parsing→splitting→embedded→ready / failed。

    断点续做：每阶段读当前状态，从断点继续（崩溃恢复）。
    """
    row = (
        await session.execute(
            text(
                "SELECT d.id, d.tenant_id, d.knowledge_base_id, d.file_id, d.file_name, d.doc_type, d.status, "
                "d.split_strategy, d.split_params, k.id AS kb, k.embedding_model_id, k.embedding_dim, "
                "k.split_strategy_default, k.split_params_default "
                "FROM rag_docs d JOIN rag_knowledge_bases k ON k.id = d.knowledge_base_id "
                "WHERE d.id = CAST(:id AS uuid)"
            ),
            {"id": doc_id},
        )
    ).first()
    if row is None:
        log.warning("pipeline: doc not found %s", doc_id)
        return
    m = row._mapping
    status = m["status"]
    if status in ("ready", "embedded"):
        # embedded 但没 ready（向量化完成未标记）→ 补标记
        if status == "embedded":
            await _set_doc_status(session, doc_id, "ready")
        return
    if status == "failed":
        # 允许手动重试：重入队时重置（由 retry_doc 处理；此处直接失败态跳过）
        return

    tenant_id, kb_id = str(m["tenant_id"]), str(m["kb"])
    doc_type = m["doc_type"]

    # ---------- parsing ----------
    if status in ("uploaded", "parsing"):
        if status == "uploaded":
            await _set_doc_status(session, doc_id, "parsing")
        _parsed_cache.pop(doc_id, None)  # 重试/新上传：不用旧缓存
        # 取原文（StorageService，source 无关）
        row2 = (
            await session.execute(
                text("SELECT file_name, backend FROM storage_files WHERE id = CAST(:f AS uuid)"),
                {"f": str(m["file_id"])},
            )
        ).first()
        if row2 is None:
            await _set_doc_status(session, doc_id, "failed", "source file missing in storage")
            return
        file_row, data = await get_storage_service().download(session, tenant_id, row2[0])
        parsed = await parse_document(
            session, tenant_id=tenant_id, user_id=None, doc_id=doc_id, doc_type=doc_type, data=data
        )
        # 持久化解析产物（JSON；重切分时复用，避免二次解析/视觉调用）
        blocks_payload = [
            {"kind": b.kind, "text": b.text, "pos": b.pos, "is_table": b.is_table} for b in parsed.blocks
        ]
        await session.execute(
            text(
                "UPDATE rag_docs SET parse_method = :pm, page_count = :pc "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"pm": parsed.parse_method, "pc": parsed.page_count, "id": doc_id},
        )
        await _save_parsed_blocks(session, doc_id, blocks_payload)
        await session.commit()
        status = "splitting"
        await _set_doc_status(session, doc_id, "splitting")

    # ---------- splitting ----------
    if status in ("splitting", "embedded"):
        blocks = await _load_parsed_blocks(session, doc_id)
        if not blocks:
            # 缓存丢失（进程重启）→ 重新解析（视觉记录追加，行为一致）
            row3 = (
                await session.execute(
                    text("SELECT file_name FROM storage_files WHERE id = CAST(:f AS uuid)"),
                    {"f": str(m["file_id"])},
                )
            ).first()
            file_row3, data3 = await get_storage_service().download(session, tenant_id, row3[0])
            reparsed = await parse_document(
                session, tenant_id=tenant_id, user_id=None, doc_id=doc_id, doc_type=doc_type, data=data3
            )
            blocks = [
                ParsedBlock(b.kind, b.text, b.pos, b.is_table) for b in reparsed.blocks
            ]
            _parsed_cache[doc_id] = [
                {"kind": b.kind, "text": b.text, "pos": b.pos, "is_table": b.is_table} for b in blocks
            ]
        if not blocks:
            await _set_doc_status(session, doc_id, "failed", "no parsed blocks (parse produced empty content)")
            return

        def _j(v):
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except ValueError:
                    return None
            return v

        strategy, params = effective_strategy(
            {"split_strategy": m["split_strategy"], "split_params": _j(m["split_params"])},
            {
                "split_strategy_default": m["split_strategy_default"],
                "split_params_default": _j(m["split_params_default"]),
            },
        )
        chunks = split_blocks(blocks, strategy, params)
        if not chunks:
            await _set_doc_status(session, doc_id, "failed", "splitting produced no chunks")
            return
        # 删旧 chunk（重切分场景；向量随 FK CASCADE 删除）
        await session.execute(
            text("DELETE FROM rag_chunks WHERE doc_id = CAST(:id AS uuid)"), {"id": doc_id}
        )
        # 写 chunk（splitter 输出顺序保证：每个 parent_key 组首个 = 父块，其余 = 子块）
        parent_ids: dict[str, str] = {}
        for c in chunks:
            if c.parent_key and c.parent_key not in parent_ids:
                cid = str(uuid.uuid4())
                await _insert_chunk(session, tenant_id, kb_id, doc_id, c, strategy, user_id=None, cid=cid)
                parent_ids[c.parent_key] = cid
        seen_parents: set[str] = set()
        for c in chunks:
            if c.parent_key and c.parent_key in parent_ids and c.parent_key not in seen_parents:
                seen_parents.add(c.parent_key)
                continue  # 组内首个 = 父块（已在第一遍写入）
            pid = parent_ids.get(c.parent_key) if c.parent_key else None
            await _insert_chunk(session, tenant_id, kb_id, doc_id, c, strategy, user_id=None, parent_id=pid)
        await session.execute(
            text("UPDATE rag_docs SET chunk_count = :n WHERE id = CAST(:id AS uuid)"),
            {"n": len(chunks), "id": doc_id},
        )
        await session.commit()
        status = "embedded"
        # ---------- embedded ----------
        kb_dim = int(m["embedding_dim"])
        kb = await get_kb(session, tenant_id, kb_id)
        all_chunks = (
            await session.execute(
                text(
                    "SELECT id, content FROM rag_chunks WHERE doc_id = CAST(:id AS uuid) AND deleted_at IS NULL ORDER BY chunk_index"
                ),
                {"id": doc_id},
            )
        ).fetchall()
        tname = vec_table(kb_id)
        if not await _table_exists(session, tname):
            # 向量表丢失（异常态）→ 按建库快照重建
            await session.execute(text("SELECT create_rag_chunks_vec(CAST(:id AS uuid), :dim)"), {"id": kb_id, "dim": kb_dim})
            await session.commit()
        texts = [r[1] for r in all_chunks]
        for i in range(0, len(texts), _EMBED_BATCH):
            batch = texts[i : i + _EMBED_BATCH]
            vecs = await get_llm_service().embed_texts(session, str(kb["embedding_model_id"]), batch)
            for cid, vec in zip([str(r[0]) for r in all_chunks[i : i + _EMBED_BATCH]], vecs):
                if len(vec) != kb_dim:
                    raise HTTPException(500, f"embedding dim mismatch: got {len(vec)} want {kb_dim} (kb={kb_id})")
                await session.execute(
                    text(f"INSERT INTO {tname} (chunk_id, knowledge_base_id, embedding) "
                         "VALUES (CAST(:cid AS uuid), CAST(:kb AS uuid), CAST(:v AS vector)) "
                         "ON CONFLICT (chunk_id) DO UPDATE SET embedding = EXCLUDED.embedding"),
                    {"cid": str(cid), "kb": kb_id, "v": _vec_literal(vec)},
                )
            await session.commit()
        await _set_doc_status(session, doc_id, "ready")
        log.info("doc ready %s: %s chunks (strategy=%s, dim=%s)", doc_id, len(chunks), strategy, kb_dim)
        return


async def _insert_chunk(
    session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str,
    c: Any, strategy: str, user_id: str | None, cid: str | None = None, parent_id: str | None = None,
) -> str:
    cid = cid or str(uuid.uuid4())
    # chunk_index 需文档内唯一 → 取当前最大 +1
    nxt = (
        await session.execute(
            text("SELECT COALESCE(MAX(chunk_index), -1) + 1 FROM rag_chunks WHERE doc_id = CAST(:d AS uuid)"),
            {"d": doc_id},
        )
    ).scalar_one()
    sha = hashlib.sha256(c.content.encode("utf-8")).hexdigest()
    await session.execute(
        text(
            """INSERT INTO rag_chunks
            (id, tenant_id, doc_id, knowledge_base_id, parent_id, chunk_index, content, content_sha256,
             pos, split_strategy, is_table, created_by, updated_by)
            VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:d AS uuid), CAST(:kb AS uuid),
                    CAST(:p AS uuid), :idx, :c, :s, CAST(:pos AS jsonb), :st, :it,
                    CAST(:u AS uuid), CAST(:u AS uuid))"""
        ),
        {
            "id": cid, "t": tenant_id, "d": doc_id, "kb": kb_id, "p": parent_id,
            "idx": nxt, "c": c.content, "s": sha, "pos": json.dumps(c.pos, ensure_ascii=False),
            "st": strategy, "it": c.is_table, "u": user_id,
        },
    )
    return cid


# ---------------------------------------------------------------- 解析产物持久化（重切分复用）

async def _save_parsed_blocks(session: AsyncSession, doc_id: str, blocks: list[dict]) -> None:
    """解析产物存进程内缓存（_parsed_cache）：
    - 重切分（resplit）直接复用，不二次解析/视觉调用；
    - 进程重启后缓存丢失 → splitting 阶段重新解析（视觉记录追加不删除，行为一致）。
    设计未给独立解析产物表（34 表定稿），闭环规模下进程内缓存足够。"""
    _parsed_cache[doc_id] = blocks


async def _load_parsed_blocks(session: AsyncSession, doc_id: str) -> list[dict]:
    from joker_shared.rag.parser import ParsedBlock

    if doc_id in _parsed_cache:
        raw = _parsed_cache[doc_id]
    else:
        return []
    return [ParsedBlock(b["kind"], b["text"], b.get("pos") or {}, b.get("is_table", False)) for b in raw]


# ---------------------------------------------------------------- 重切分队列 + reindex 任务

async def _enqueue_resplit(doc_id: str) -> None:
    await _task_queue.enqueue(f"resplit:{doc_id}")


async def _enqueue_reindex(
    session: AsyncSession, kb_id: str, doc_ids: list[str], shadow: str,
    new_dim: int, new_emb_id: str, tenant_id: str, user_id: str | None,
) -> None:
    """reindex 影子表重嵌入 + 切换（进程内串行，避免与文档流水线竞争同一库的向量表引用）。"""
    task = asyncio.create_task(_run_reindex(kb_id, doc_ids, shadow, new_dim, new_emb_id, tenant_id, user_id))
    _reindex_tasks.append(task)


_reindex_tasks: list[asyncio.Task] = []


async def _run_reindex(
    kb_id: str, doc_ids: list[str], shadow: str, new_dim: int,
    new_emb_id: str, tenant_id: str, user_id: str | None,
) -> None:
    from joker_shared.db import get_session

    try:
        async for session in get_session():
            tname = vec_table(kb_id)
            # 逐文档：取 chunk → 新模型嵌入 → 写影子表
            for doc_id in doc_ids:
                chunks = (
                    await session.execute(
                        text(
                            "SELECT id, content FROM rag_chunks WHERE doc_id = CAST(:d AS uuid) AND deleted_at IS NULL"
                        ),
                        {"d": doc_id},
                    )
                ).fetchall()
                if not chunks:
                    continue
                texts = [r[1] for r in chunks]
                for i in range(0, len(texts), _EMBED_BATCH):
                    vecs = await get_llm_service().embed_texts(session, new_emb_id, texts[i : i + _EMBED_BATCH])
                    for cid, vec in zip([str(r[0]) for r in chunks[i : i + _EMBED_BATCH]], vecs):
                        await session.execute(
                            text(f"INSERT INTO {shadow} (chunk_id, knowledge_base_id, embedding) "
                                 "VALUES (CAST(:cid AS uuid), CAST(:kb AS uuid), CAST(:v AS vector))"),
                            {"cid": cid, "kb": kb_id, "v": _vec_literal(vec)},
                        )
                    await session.commit()
            # 切换：旧表 → _old，影子 → 正式，DROP 旧
            old_name = f"{tname}_old_{uuid.uuid4().hex[:8]}"
            await session.execute(text(f"ALTER TABLE {tname} RENAME TO {old_name}"))
            await session.execute(text(f"ALTER TABLE {shadow} RENAME TO {tname}"))
            await session.execute(text(f"DROP TABLE IF EXISTS {old_name}"))
            await session.execute(
                text(
                    "UPDATE rag_knowledge_bases SET status = 'active', embedding_dim = :dim, "
                    "updated_by = CAST(:u AS uuid) WHERE id = CAST(:id AS uuid) AND tenant_id = CAST(:t AS uuid)"
                ),
                {"dim": new_dim, "u": user_id, "id": kb_id, "t": tenant_id},
            )
            await session.commit()
            log.info("reindex done kb=%s: shadow %s → %s (dim=%s)", kb_id, shadow, tname, new_dim)
            return
    except Exception:
        log.exception("reindex failed kb=%s (status stays reindexing; manual cleanup)", kb_id)
        async for session in get_session():
            await session.execute(
                text("UPDATE rag_knowledge_bases SET status = 'active' WHERE id = CAST(:id AS uuid)"),
                {"id": kb_id},
            )
            await session.commit()
            return


# ---------------------------------------------------------------- 重试

async def retry_doc(session: AsyncSession, tenant_id: str, kb_id: str, doc_id: str) -> dict:
    """failed 文档重试：状态回 uploaded → 重新入队（从 parsing 重跑）。"""
    doc = await get_doc(session, tenant_id, kb_id, doc_id)
    if doc is None:
        raise HTTPException(404, f"doc not found: {doc_id}")
    if doc["status"] != "failed":
        raise HTTPException(409, f"only failed docs can be retried (status={doc['status']})")
    await _set_doc_status(session, doc_id, "uploaded")
    await get_task_queue().enqueue(doc_id)
    return await get_doc(session, tenant_id, kb_id, doc_id)
