"""MCP 注册/同步/管理共享库（S06，MCP-01/02/03，DECISION-010/011）。"""
from joker_shared.mcp.registry import (
    MCPRegistryService,
    get_mcp_registry,
)
from joker_shared.mcp.client import list_remote_tools, MCPProbeError
from joker_shared.mcp.platform_tools import PLATFORM_TOOLS, PLATFORM_TOOL_SCOPES

__all__ = [
    "MCPRegistryService",
    "get_mcp_registry",
    "list_remote_tools",
    "MCPProbeError",
    "PLATFORM_TOOLS",
    "PLATFORM_TOOL_SCOPES",
]
