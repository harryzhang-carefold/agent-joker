"""平台内置 MCP server（PlatformMCPServer）工具快照（S06，MCP-02 验收 4）。

平台工具（BFF /mcp 实装，S02/S05）注册为 `is_platform=true` 的 server 行 +
`source=platform` 的工具行（DB_DESIGN §5.1/5.2），与远端 server 的工具同表同语义
（禁用/删除/关联提示/缓存统一）。

工具定义与 BFF services/bff/app/platform_mcp.py 的 TOOLS 保持同步（同一来源事实：
DB_DESIGN §5.2 平台工具行 = upload_doc/query_doc/rag_search）。
"""
from __future__ import annotations

from typing import Any

# 平台工具 → 所需 scope（DB_DESIGN §5.2，供 ToolInterceptor ① scope 校验，S08 消费）
PLATFORM_TOOL_SCOPES: dict[str, list[str]] = {
    "upload_doc": ["storage:write"],
    "query_doc": ["storage:read"],
    "rag_search": ["rag:search"],
}

PLATFORM_TOOLS: list[dict[str, Any]] = [
    {
        "name": "upload_doc",
        "description": (
            "上传文档到平台存储（租户级）。入参 file_name + content（UTF-8 文本）；"
            "成功返回 file_id/file_name/size_bytes。同名文件 409。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_name": {"type": "string", "description": "文件名（含扩展名，租户内唯一）"},
                "content": {"type": "string", "description": "文件内容（UTF-8 文本）"},
                "source": {"type": "string", "description": "来源标记（默认 mcp:platform）"},
                "agent_id": {"type": "string", "description": "可选，关联 agent ID"},
                "access_token": {"type": "string", "description": "用户 Access Token（ToolInterceptor 强制注入）"},
            },
            "required": ["file_name", "content"],
        },
    },
    {
        "name": "query_doc",
        "description": (
            "按文件名/条件查询平台存储文件（仅本租户）。入参 file_name（精确，可选）或"
            " prefix/limit；返回文件列表（含 content——text 类文件直接内联，二进制返回元数据）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_name": {"type": "string", "description": "精确文件名（提供时忽略 prefix/limit）"},
                "prefix": {"type": "string", "description": "文件名前缀过滤"},
                "limit": {"type": "integer", "description": "返回条数上限（默认 20）"},
                "access_token": {"type": "string", "description": "用户 Access Token（ToolInterceptor 强制注入）"},
            },
            "required": [],
        },
    },
    {
        "name": "rag_search",
        "description": (
            "在指定知识库中做 RAG 检索，返回 chunk 内容 + 索引 + 原文档位置 + tag。"
            "入参 kb_ids[] + query + top_k（DECISION-006 阈值双语义；未勾选 KB 的 agent → 403）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kb_ids": {"type": "array", "items": {"type": "string"}, "description": "知识库 ID 列表（必选）"},
                "query": {"type": "string", "description": "检索文本（必选）"},
                "top_k": {"type": "integer", "description": "返回条数（默认 5）"},
                "score_threshold": {"type": "number", "description": "相似度阈值（DECISION-006）"},
                "agent_id": {"type": "string", "description": "可选，关联 agent ID（勾选校验）"},
                "access_token": {"type": "string", "description": "用户 Access Token（ToolInterceptor 强制注入）"},
            },
            "required": ["kb_ids", "query"],
        },
    },
]
