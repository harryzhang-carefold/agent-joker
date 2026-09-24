"""LLMNodeService 端点（S03，LLM-01/02/03）。

平台级共享（DB_DESIGN §3 / ARCH §9-13）：
- 列表对全体租户可见（tenant_id 仅审计归属，不做行级过滤）
- 增/删/改/连通性测试需平台 scope `llm:manage`（缺失 → 403）
- api_key 响应只回 `api_key_set` 布尔；DB 只存 Fernet 密文；日志不记明文（DECISION-012）
- 节点配置化：无缓存，每次读库 → CRUD 后即时生效（RAG/Agent 用最新）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import auth_context, db_session, require_scope
from joker_shared.llm import get_llm_service

router = APIRouter(prefix="/api/llm", tags=["llm"])


def _svc():
    return get_llm_service()


def _require_llm_manage(auth: dict) -> None:
    require_scope("llm:manage", auth=auth)


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "module": "llm", "phase": "S03-llm"}


# ============================================================ endpoint（LLM-01）

@router.get("/endpoints")
async def list_endpoints(
    status: str | None = Query(None, pattern="^(active|disabled)$"),
    supports_vision: bool | None = Query(None),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """endpoint 列表（平台级共享，全租户可见；status / supports_vision 过滤）。"""
    return await _svc().list_endpoints(session, status=status, supports_vision=supports_vision)


@router.get("/endpoints/{node_id}")
async def get_endpoint(
    node_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    node = await _svc().get_endpoint(session, node_id)
    if node is None:
        raise HTTPException(404, f"endpoint not found: {node_id}")
    return node


@router.post("/endpoints", status_code=201)
async def create_endpoint(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """新增 endpoint。必选：name/base_url/model；可选：api_key（Fernet 加密落库）/
    auth_scheme(bearer|api_key_header|none) / supports_vision / default_params /
    timeout_seconds / status(active|disabled)。"""
    _require_llm_manage(auth)
    for f in ("name", "base_url", "model"):
        if not body.get(f):
            raise HTTPException(422, f"missing required field: {f}")
    if body.get("status") and body["status"] not in ("active", "disabled"):
        raise HTTPException(422, "status must be active|disabled")
    return await _svc().create_endpoint(session, auth["tenant_id"], auth["user_id"], body)


@router.put("/endpoints/{node_id}")
async def update_endpoint(
    node_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """更新 endpoint（部分字段；api_key 非空=替换，clear_api_key=true=清除）。"""
    _require_llm_manage(auth)
    return await _svc().update_endpoint(session, node_id, auth["user_id"], body)


@router.delete("/endpoints/{node_id}")
async def delete_endpoint(
    node_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除 endpoint；被 agent 勾选或视觉解析引用 → 409 + 引用清单（禁用代替硬删）。"""
    _require_llm_manage(auth)
    return await _svc().delete_endpoint(session, node_id)


@router.post("/endpoints/{node_id}/test")
async def test_endpoint(
    node_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """连通性测试（LLM-01 验收 3）：轻量 chat "ping" 调用。
    返回 {ok, latency_ms, summary}（可用/不可用+错误摘要），并写 last_test_*。"""
    _require_llm_manage(auth)
    return await _svc().probe_endpoint(session, node_id)


# ============================================================ embedding（LLM-02）

@router.get("/embeddings")
async def list_embeddings(
    status: str | None = Query(None, pattern="^(active|disabled)$"),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """embedding 模型列表（含本地 fallback 节点，provider=local）。"""
    return await _svc().list_embeddings(session, status=status)


@router.get("/embeddings/{node_id}")
async def get_embedding(
    node_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    node = await _svc().get_embedding(session, node_id)
    if node is None:
        raise HTTPException(404, f"embedding model not found: {node_id}")
    return node


@router.post("/embeddings", status_code=201)
async def create_embedding(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """新增 embedding 模型。必选：name/dimensions；可选：provider(api|local)/
    base_url/model/api_key/batch_size/status。"""
    _require_llm_manage(auth)
    for f in ("name", "dimensions"):
        if f not in body:
            raise HTTPException(422, f"missing required field: {f}")
    try:
        body["dimensions"] = int(body["dimensions"])
    except (TypeError, ValueError):
        raise HTTPException(422, "dimensions must be int") from None
    return await _svc().create_embedding(session, auth["tenant_id"], auth["user_id"], body)


@router.put("/embeddings/{node_id}")
async def update_embedding(
    node_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    _require_llm_manage(auth)
    return await _svc().update_embedding(session, node_id, auth["user_id"], body)


@router.delete("/embeddings/{node_id}")
async def delete_embedding(
    node_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除 embedding 模型；被知识库引用 → 409（禁用代替硬删）。"""
    _require_llm_manage(auth)
    return await _svc().delete_embedding(session, node_id)


@router.post("/embeddings/{node_id}/test")
async def test_embedding(
    node_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """连通性测试：本地节点走确定性实现（必 ok）；API 节点发短文本 /embeddings。"""
    _require_llm_manage(auth)
    return await _svc().probe_embedding(session, node_id)


# ============================================================ reranker（LLM-03）

@router.get("/rerankers")
async def list_rerankers(
    status: str | None = Query(None, pattern="^(active|disabled)$"),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    return await _svc().list_rerankers(session, status=status)


@router.get("/rerankers/{node_id}")
async def get_reranker(
    node_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    node = await _svc().get_reranker(session, node_id)
    if node is None:
        raise HTTPException(404, f"reranker model not found: {node_id}")
    return node


@router.post("/rerankers", status_code=201)
async def create_reranker(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """新增 reranker 模型。必选：name/base_url/model；可选：api_key/max_candidates/status。"""
    _require_llm_manage(auth)
    for f in ("name", "base_url", "model"):
        if not body.get(f):
            raise HTTPException(422, f"missing required field: {f}")
    return await _svc().create_reranker(session, auth["tenant_id"], auth["user_id"], body)


@router.put("/rerankers/{node_id}")
async def update_reranker(
    node_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    _require_llm_manage(auth)
    return await _svc().update_reranker(session, node_id, auth["user_id"], body)


@router.delete("/rerankers/{node_id}")
async def delete_reranker(
    node_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除 reranker 模型；被知识库引用 → 409（禁用代替硬删）。"""
    _require_llm_manage(auth)
    return await _svc().delete_reranker(session, node_id)


@router.post("/rerankers/{node_id}/test")
async def test_reranker(
    node_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """连通性测试：发短文本 /rerank（Jina 兼容契约）。"""
    _require_llm_manage(auth)
    return await _svc().probe_reranker(session, node_id)


# ============================================================ 本地 fallback embedding（确定性，闭环兜底）

@router.post("/embeddings/local/embed")
async def local_embed(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """本地确定性 fallback embedding 直测（自测闭环/调试用，无 scope 门禁——只信签名头）。
    体：{texts: str[], dim?: int} → {items: float[][]}（同文本必返回同向量）。"""
    from joker_shared.llm import local_fallback_embeddings

    texts = body.get("texts")
    if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
        raise HTTPException(422, "texts must be non-empty list[str]")
    dim = int(body.get("dim") or 0) or None
    vecs = local_fallback_embeddings(texts, dim)
    return {"items": vecs, "total": len(vecs), "dim": len(vecs[0])}
