"""引用来源规则（AGENT-05/11，DECISION-017 + D-A / DECISION-022）。

判定三态（DECISION-017）：
1. official 判定命中（D-A 两级：文档级 tag=official 优先，NULL 继承库级 tag=official）
   → 强制附 RAG 来源（无论 show_citations）。
2. 用户明确要求（show_citations=true 显式开关，或 LLM 意图判定兜底，如「给我出处」）
   → 附来源。
3. 两者都无 → 不附来源。

出参：`[{doc_id, doc_name, kb_id, kb_tag, chunk_id, chunk_index, pos, is_official,
   score, url}]`——url 为原文查看页定位 URL（RAG-09 反向定位，供前端跳转）。

简易 agent：由运行时自行判定并附加（本模块）。
第三方 agent：平台把完整引用信息（含 is_official / show_citations 提示）提供给 agent，
提供方决定是否显示（AGENT-11：平台侧信息完整性可验证）。
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("joker.citations")

# 原文查看页定位 URL（RAG-09；前端 /kb/{kb_id}/docs/{doc_id}?chunk=...）
DOC_BASE_URL = "/api/rag/kbs/{kb_id}/docs/{doc_id}"


def _citation_url(kb_id: str, doc_id: str, chunk_index: int | None, pos: Any) -> str:
    """拼定位 URL：优先 chunk 索引；pos 含 page 时带 page。"""
    base = DOC_BASE_URL.format(kb_id=kb_id, doc_id=doc_id)
    parts = []
    if chunk_index is not None:
        parts.append(f"chunk={chunk_index}")
    if isinstance(pos, dict) and pos.get("page") is not None:
        parts.append(f"page={pos['page']}")
    if parts:
        return f"{base}?{'&'.join(parts)}"
    return base


def build_citations(items: list[dict], force: bool = False, show: bool = False) -> list[dict]:
    """从 RAG 检索 items 构造引用列表。

    force=True（official 命中）→ 返回全部 official items（或全部 items 当无法区分）。
    show=True（用户明确要求）→ 返回全部 items。
    两者都 False → []。
    """
    if not items:
        return []
    if force:
        # official 判定命中的文档优先（is_official=True）；若无 official 标记则全量
        officials = [it for it in items if it.get("is_official")]
        picked = officials if officials else items
    elif show:
        picked = items
    else:
        return []

    out = []
    for it in picked:
        out.append({
            "doc_id": it.get("doc_id"),
            "doc_name": it.get("doc_file_name"),
            "kb_id": it.get("kb_id"),
            "kb_tag": it.get("kb_tag"),
            "chunk_id": it.get("chunk_id"),
            "chunk_index": it.get("chunk_index"),
            "pos": it.get("pos"),
            "is_official": it.get("is_official"),
            "score": it.get("score"),
            "url": _citation_url(
                it.get("kb_id") or "", it.get("doc_id") or "",
                it.get("chunk_index"), it.get("pos"),
            ),
        })
    return out


def render_citations_markdown(citations: list[dict]) -> str:
    """回复末尾的来源 markdown（AGENT-05 验收 1「每条可点击跳转」）。"""
    if not citations:
        return ""
    lines = ["\n---\n**来源（RAG 引用）：**"]
    for i, c in enumerate(citations, 1):
        doc = c.get("doc_name") or "未知文档"
        pos = ""
        if isinstance(c.get("pos"), dict):
            if c["pos"].get("page") is not None:
                pos = f" §第{c['pos']['page']}页"
            elif c["pos"].get("section_path"):
                pos = f" §{' / '.join(str(x) for x in c['pos']['section_path'])}"
            elif c["pos"].get("table_row"):
                tr = c["pos"]["table_row"]
                pos = f" §表格{tr.get('sheet', '')} 行{tr.get('row_start', '')}-{tr.get('row_end', '')}"
        official = "（官方）" if c.get("is_official") else ""
        url = c.get("url") or ""
        if url:
            lines.append(f"{i}. [{doc}{pos}{official}]({url})")
        else:
            lines.append(f"{i}. {doc}{pos}{official}")
    return "\n".join(lines)


# ============================================================ LLM 意图判定兜底（DECISION-017）


_INTENT_PATTERNS = (
    "引用", "来源", "出处", "根据", "依据", "哪篇", "哪个文档", "参考资料",
    "cite", "citation", "source", "reference", "where does", "出处", "佐证",
)


def llm_intent_fallback_requires_citation(user_message: str, show_citations: bool | None) -> bool:
    """未显式指定 show_citations 时，判断用户消息是否要求引用（DECISION-017 兜底）。

    两层：
    1. 显式参数 show_citations=True → True（确定性，验收可测）。
    2. 自然语言意图（轻量关键词匹配，闭环可演示；真实 LLM 意图判定由运行时可选增强）。
    """
    if show_citations is True:
        return True
    if show_citations is False:
        return False  # 显式关闭 → 不再走兜底（确定性优先）
    msg = (user_message or "").lower()
    return any(p in msg for p in _INTENT_PATTERNS)
