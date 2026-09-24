"""Agent 模块（S07，AGENT-01..11）。

- service：AgentService（agent 元数据 CRUD + 四要素勾选 + 会话/消息管理）
- memory：三层记忆（Redis 短期 + PG 长期 + Obsidian 沉淀，DECISION-019）
- citations：引用来源规则（DECISION-017 / D-A official 两级判定）
- tools_factory：InterceptorTool 工厂（DECISION-015 进程内拦截，S07 占位拦截器）
- runtime：SimpleAgentRuntime（LangChain tool-calling loop，DECISION-007）
- third_party：第三方 agent URL 代理 + tool_calls 意图拦截（DECISION-008）
"""
from joker_shared.agents.service import AgentService, get_agent_service

__all__ = ["AgentService", "get_agent_service"]
