"""routers 包。9 模块 router（ARCH §1.1）：
auth/iam/audit 在 S01 实装；storage(S02)/llm(S03)/rag(S04-05)/mcp(S06)/skills(S06)
已实装；agents(S07)/trace(S09) 已实装。
"""
from fastapi import APIRouter

router = APIRouter()


# ---- 实装模块 ----
from app.routers import (  # noqa: E402
    agents,
    auth,
    audit as audit_router,
    iam,
    llm,
    mcp as mcp_router,
    rag,
    skills as skills_router,
    storage,
    trace as trace_router,
)

router.include_router(auth.router)
router.include_router(iam.router)
router.include_router(audit_router.router)
router.include_router(agents.router)              # /api/agents（S07 agent 管理/对话/会话/记忆）
router.include_router(trace_router.router)        # /api/trace（S09 全链路 trace 检索，TRACE-02）
router.include_router(storage.router)            # /api/storage（管理面）
router.include_router(storage.internal_router)   # /internal/storage（机器凭证代执行面）
router.include_router(llm.router)                # /api/llm（S03 LLM 节点，平台级共享）
router.include_router(rag.router)                # /api/rag（S04 RAG 知识库/文档/chunk，租户级）
router.include_router(rag.internal_router)       # /internal/rag（S05 内部检索，D-B 机器凭证代执行）
router.include_router(mcp_router.router)         # /api/mcp（S06 MCP 注册/同步/工具管理）
router.include_router(skills_router.router)      # /api/skills（S06 Skills 管理）
