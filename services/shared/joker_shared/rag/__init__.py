"""RAG 模块（S04 解析/切分/服务；S05 检索核心）。"""
from joker_shared.rag.parser import ParseResult, ParsedBlock, parse_document
from joker_shared.rag.splitter import DEFAULT_PARAMS, STRATEGIES, split_blocks
from joker_shared.rag.retrieval import (
    check_agent_kb_grants,
    resolve_official,
    search_kbs,
    search_with_trace,
)

__all__ = [
    "ParseResult",
    "ParsedBlock",
    "parse_document",
    "DEFAULT_PARAMS",
    "STRATEGIES",
    "split_blocks",
    "search_kbs",
    "search_with_trace",
    "resolve_official",
    "check_agent_kb_grants",
]
