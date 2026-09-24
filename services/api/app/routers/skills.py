"""Skills 管理端点（S06，SKILL-01/02）。

scope 门禁（DB_DESIGN §10.2 内置 scope）：
- 写（创建/上传/更新/删除）需 `skills:manage`（缺失 → 403）
- 读（列表/详情）`skills:manage` 或 `mcp:tool` 均可？——否：skills 无独立读 scope，
  读用 `skills:manage`（管理面；对话界面由 S07 agent 配置消费，S08 起可放宽）。

租户隔离：全部数据端点强制 tenant_id = X-Auth-Tenant（跨租户 skill 404 不泄露存在性）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import auth_context, db_session, require_scope
from joker_shared.skills import get_skills_service

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _svc():
    return get_skills_service()


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "module": "skills", "phase": "S06-skills"}


@router.get("")
@router.get("/")
async def list_skills(
    status: str | None = Query(None, pattern="^(active|disabled)$"),
    source: str | None = Query(None, pattern="^(manual|upload)$"),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """本租户 skill 列表（SKILL-01 验收 1 可管理可见）。"""
    require_scope("skills:manage", auth=auth)
    return await _svc().list_skills(session, auth["tenant_id"], status, source)


@router.get("/{skill_id}")
async def get_skill(
    skill_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """skill 详情（含 files 清单；文本类 main 文件内容在 content 字段）。404（不存在/跨租户）。"""
    require_scope("skills:manage", auth=auth)
    d = await _svc().get_skill(session, skill_id, auth["tenant_id"])
    if d is None:
        raise HTTPException(404, f"skill not found: {skill_id}")
    return d


@router.post("", status_code=201)
@router.post("/", status_code=201)
async def create_skill(
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """手动添加 skill（SKILL-01 验收 1）：必选 name + content（prompt 文本），可选 description。

    同名 409；content 空 422。
    """
    require_scope("skills:manage", auth=auth)
    return await _svc().create_skill(session, auth["tenant_id"], auth["user_id"], body)


@router.post("/upload", status_code=201)
async def upload_skill(
    name: str = Form(...),
    description: str | None = Form(None),
    files: list[UploadFile] = File(...),
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """上传 skill 文件（SKILL-01 验收 2 / SKILL-02 验收 2）。

    multipart：`name` + `files[]`（第一个=main 入口文件，文本类内容同步进 content；
    其余=asset）。文件经 StorageService 落存储（source=skill，上传记录可查来源=skill）。
    """
    require_scope("skills:manage", auth=auth)
    parsed: list[tuple[str, bytes, str | None]] = []
    for f in files:
        data = await f.read()
        parsed.append((f.filename or "", data, f.content_type))
    return await _svc().upload_skill(
        session, auth["tenant_id"], auth["user_id"], name, parsed, description
    )


@router.put("/{skill_id}")
async def update_skill(
    skill_id: str,
    body: dict,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """更新 name/description/content/status；content 变更 → version+1（DB_DESIGN §6.1）。"""
    require_scope("skills:manage", auth=auth)
    return await _svc().update_skill(session, skill_id, auth["tenant_id"], auth["user_id"], body)


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    auth: dict = Depends(auth_context),
    session: AsyncSession = Depends(db_session),
):
    """删除 skill（SKILL-02 验收 3）：元数据软删 + skill_files 软删 + 存储文件物理删除。

    被 rag_docs 引用的文件跳过并在 files_skipped 中列出（不静默丢数据）。
    """
    require_scope("skills:manage", auth=auth)
    return await _svc().delete_skill(session, skill_id, auth["tenant_id"], auth["user_id"])
