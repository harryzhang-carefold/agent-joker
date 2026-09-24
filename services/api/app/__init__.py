"""PlatformAPI — agent-joker 业务 API 单体（S01 骨架）。

FastAPI 应用工厂。9+1 模块 router（auth/iam/audit/storage/llm/rag/mcp/
skills/agents/trace，ARCH §1.1）。S01 实装：auth（登录/刷新/登出）+
iam（用户/角色/scope）+ audit（查询）；其余为 /healthz 占位（各切片实装）。
"""
