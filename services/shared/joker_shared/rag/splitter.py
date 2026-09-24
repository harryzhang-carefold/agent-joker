"""切分引擎（S04，RAG-04；DECISION-020：5 策略工厂，LangChain text-splitters 基础 + 自研）。

策略（库级默认 + 文档级覆盖，参数可配，支持重切分）：
- fixed           定长（默认 chunk_size=500 字 / overlap=50）
- parent_child    父子（父:子 ≈ 1:4，默认父 2000 / 子 500）
- semantic        语义（相似度断点阈值 0.25：相邻句向量余弦 < 阈值 → 断点）
- structured_tree 结构化-文档树（按 section_path 标题层级自研：每个节 = 父，节内按定长子块）
- table           表格（整表 = chunk，is_table=true；非表格块走定长）

输入 = parser.ParsedBlock 内容流（带 pos）；输出 = chunk 序列（content + pos 映射）。
pos 映射规则（ARCH §2.2.1）：块内子切分按字符偏移映射回块坐标（pdf 页内偏移 /
docx 节内偏移 / txt 全文偏移）；表格块 pos=table_row 原样携带。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from joker_shared.rag.parser import ParsedBlock

log = logging.getLogger("joker.rag.splitter")

STRATEGIES = ("fixed", "parent_child", "semantic", "structured_tree", "table")

# 各策略缺省参数（RAG-04 验收 4「缺省值在文档中明确」；与 DECISION-020 一致）
DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "fixed": {"chunk_size": 500, "overlap": 50},
    "parent_child": {"parent_size": 2000, "child_size": 500, "overlap": 50},
    "semantic": {"threshold": 0.25, "chunk_size": 500},
    "structured_tree": {"chunk_size": 500, "overlap": 50},
    "table": {"max_table_chars": 4000, "row_group": 50},
}


@dataclass
class ChunkOut:
    content: str
    pos: dict[str, Any] = field(default_factory=dict)
    is_table: bool = False
    parent_key: str | None = None  # parent_child/structured_tree 内部关联（service 层转 parent_id）


# ---------------------------------------------------------------- 通用工具

def _resolve_params(strategy: str, params: dict | None) -> dict[str, Any]:
    p = dict(DEFAULT_PARAMS[strategy])
    for k, v in (params or {}).items():
        if k in p and v is not None:
            p[k] = v
    return p


def _char_pos(block: ParsedBlock, s: int, e: int) -> dict[str, Any]:
    """块内字符偏移 [s,e) → 块坐标 pos（保持原键结构，char 偏移相加）。"""
    pos = dict(block.pos)
    if "char_start" in pos:
        pos["char_start"] = int(pos["char_start"]) + s
        pos["char_end"] = int(pos["char_end"] if pos.get("char_end") is not None else int(pos.get("char_start", 0))) + e
    else:
        # 页级/整图/表格块：无字符偏移 → 原 pos（页级粒度）
        pass
    return pos


def _block_table_pos(block: ParsedBlock, row_offset: int = 0, rows: int = 0, cols: int = 0) -> dict[str, Any]:
    pos = dict(block.pos)
    tr = dict(pos.get("table_row") or {})
    if row_offset:
        tr["row_start"] = int(tr.get("row_start") or 1) + row_offset
        tr["row_end"] = tr["row_start"] - 1 + rows
    if cols and not tr.get("col_end"):
        tr["col_start"] = int(tr.get("col_start") or 1)
        tr["col_end"] = tr["col_start"] - 1 + cols
    pos["table_row"] = tr
    return pos


def _table_rows(content: str) -> list[str]:
    """Markdown 表格 → 行列表（| 开头）。"""
    return [ln for ln in content.splitlines() if ln.strip().startswith("|")]


# ---------------------------------------------------------------- 各策略

def _split_fixed(blocks: list[ParsedBlock], p: dict[str, Any]) -> list[ChunkOut]:
    """定长切分：表格块整块 = chunk；文本块按 chunk_size/overlap 切（pos 按字符偏移精确映射）。"""
    chunks: list[ChunkOut] = []
    for b in blocks:
        if b.is_table:
            chunks.append(ChunkOut(b.text, _block_table_pos(b), True))
            continue
        text = b.text
        size, ov = int(p["chunk_size"]), int(p["overlap"])
        if not text.strip():
            continue
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            seg = text[start:end]
            if seg.strip():
                chunks.append(ChunkOut(seg, _char_pos(b, start, end - start)))
            if end == len(text):
                break
            start = end - ov
    return chunks


def _split_parent_child(blocks: list[ParsedBlock], p: dict[str, Any]) -> list[ChunkOut]:
    """父块 = 连续子块按 parent_size 聚合；子块 = 块内定长（child_size）。

    返回顺序：先全部父块（parent_key=None, pos=聚合区间），再全部子块
    （parent_key=父序号）。service 层据此建 parent_id 引用。
    """
    parent_size, child_size, ov = int(p["parent_size"]), int(p["child_size"]), int(p["overlap"])
    # 1) 子块（携带块内偏移 + 父聚合用的「全文流坐标」）
    children: list[dict] = []  # {content, pos, block_idx, s, e, table?}
    for bi, b in enumerate(blocks):
        if b.is_table:
            children.append({"content": b.text, "pos": _block_table_pos(b), "table": True,
                             "bi": bi, "s": 0, "e": len(b.text)})
            continue
        start = 0
        while start < len(b.text):
            end = min(start + child_size, len(b.text))
            seg = b.text[start:end]
            if seg.strip():
                children.append({"content": seg, "pos": _char_pos(b, start, end - start),
                                 "table": False, "bi": bi, "s": start, "e": end})
            if end == len(b.text):
                break
            start = end - ov

    # 2) 按 child_size 累计聚合父块（跨块按内容流顺序；表格子块独占进父块）
    out: list[ChunkOut] = []
    parents: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0
    for c in children:
        if cur and cur_len + len(c["content"]) > parent_size:
            parents.append(cur)
            cur, cur_len = [], 0
        cur.append(c)
        cur_len += len(c["content"])
    if cur:
        parents.append(cur)

    # 输出顺序保证：每个父组先出父块（组内 index 0）再出子块（index ≥ 1）——
    # service 层按「组内首个 = 父」建 parent_id 引用（不靠内容长度启发式）。
    for pi, grp in enumerate(parents, 1):
        first, last = grp[0], grp[-1]
        if first["table"] or last["table"] or len({c["bi"] for c in grp}) > 1:
            ppos = dict(first["pos"])
        else:
            ppos = _char_pos(blocks[first["bi"]], first["s"], last["e"] - first["s"])
        content = "\n\n".join(c["content"] for c in grp)
        out.append(ChunkOut(content, ppos, False, parent_key=f"p{pi}"))
    for pi, grp in enumerate(parents, 1):
        for c in grp:
            out.append(ChunkOut(c["content"], c["pos"], c["table"], parent_key=f"p{pi}"))
    return out


def _split_semantic(blocks: list[ParsedBlock], p: dict[str, Any]) -> list[ChunkOut]:
    """语义切分：句子级；相邻句 n-gram 向量余弦相似度 < threshold(0.25) → 断点；
    段内累计到 chunk_size 强制断。纯 Python（确定性，无外部依赖）。"""
    threshold = float(p["threshold"])
    chunk_size = int(p["chunk_size"])
    out: list[ChunkOut] = []
    for b in blocks:
        if b.is_table:
            out.append(ChunkOut(b.text, _block_table_pos(b), True))
            continue
        sents = _sentences(b.text)
        if not sents:
            if b.text.strip():
                out.append(ChunkOut(b.text.strip(), _char_pos(b, 0, len(b.text))))
            continue
        # 句子 → 向量（本地 n-gram 确定性向量，与 fallback embedding 同算法）
        vecs = [_ngram_vec(s) for s in sents]
        # 断点：句间相似度 < threshold 或 累计长度 > chunk_size
        segments: list[list[int]] = []
        cur: list[int] = [0]
        cur_len = len(sents[0])
        for i in range(1, len(sents)):
            sim = _cosine(vecs[i - 1], vecs[i])
            if sim < threshold or cur_len + len(sents[i]) > chunk_size:
                segments.append(cur)
                cur, cur_len = [i], len(sents[i])
            else:
                cur.append(i)
                cur_len += len(sents[i])
        segments.append(cur)

        # 句子在块内偏移（按原文本顺序累计）
        offsets: list[tuple[int, int]] = []
        pos0 = 0
        for s in sents:
            idx = b.text.find(s, pos0)
            if idx < 0:
                idx = pos0
            offsets.append((idx, idx + len(s)))
            pos0 = idx + len(s)
        for seg in segments:
            s0, s1 = offsets[seg[0]][0], offsets[seg[-1]][1]
            content = b.text[s0:s1].strip()
            if content:
                out.append(ChunkOut(content, _char_pos(b, s0, s1 - s0)))
    return out


def _sentences(text: str) -> list[str]:
    import re

    parts = re.split(r"(?<=[。！？；.!?;])\s*", text)
    return [p.strip() for p in parts if p.strip()]


_GRAM: dict[str, int] = {}


def _ngram_vec(s: str, n: int = 3, dim: int = 128) -> list[float]:
    import re as _re

    norm = _re.sub(r"\s+", " ", s.strip().lower())
    grams = [norm[i : i + n] for i in range(max(len(norm) - n + 1, 0))] or ([norm] if norm else [])
    vec = [0.0] * dim
    for g in grams:
        h = _fnv1a64(g)
        vec[h % dim] += 1.0 if (h >> 61) & 1 else -1.0
    sq = math.sqrt(sum(v * v for v in vec))
    return [v / sq for v in vec] if sq else vec


def _fnv1a64(s: str) -> int:
    h = 0xCBF29CE484222325
    for byte in s.encode("utf-8"):
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _split_structured_tree(blocks: list[ParsedBlock], p: dict[str, Any]) -> list[ChunkOut]:
    """结构化-文档树：按 section_path 层级分节（docx）；每节 = 父块（标题+节内容），
    节内按定长（chunk_size）出子块（parent_key=节序号）。非结构化块（txt/pdf/xlsx）
    整块为父 + 定长子块（无标题层级，树=单根）。"""
    chunk_size, ov = int(p["chunk_size"]), int(p["overlap"])
    # 按 section_path 分组（保持顺序）
    groups: list[tuple[tuple, list[int]]] = []
    for i, b in enumerate(blocks):
        key = tuple(b.pos.get("section_path") or ())
        if groups and groups[-1][0] == key:
            groups[-1][1].append(i)
        else:
            groups.append((key, [i]))

    out: list[ChunkOut] = []
    for gi, (key, idxs) in enumerate(groups, 1):
        grp = [blocks[i] for i in idxs]
        # 父块：节标题（section_path 末级）+ 全节文本（子块可定位回节内）
        title = key[-1] if key else "(root)"
        full = "\n\n".join(b.text for b in grp if b.text.strip())
        if not full:
            continue
        first = grp[0]
        ppos = dict(first.pos)
        ppos["section_path"] = list(key)
        out.append(ChunkOut(f"## {title}\n{full}", ppos, False, parent_key=f"s{gi}"))
        # 子块：定长（带节路径 + 块内偏移）
        for b in grp:
            if b.is_table:
                out.append(ChunkOut(b.text, _block_table_pos(b), True, parent_key=f"s{gi}"))
                continue
            start = 0
            while start < len(b.text):
                end = min(start + chunk_size, len(b.text))
                seg = b.text[start:end]
                if seg.strip():
                    cpos = _char_pos(b, start, end - start)
                    cpos["section_path"] = list(key)
                    out.append(ChunkOut(seg, cpos, False, parent_key=f"s{gi}"))
                if end == len(b.text):
                    break
                start = end - ov
    return out


def _split_table(blocks: list[ParsedBlock], p: dict[str, Any]) -> list[ChunkOut]:
    """表格策略：表格块整表 = chunk（is_table=true；超大表按行组切）；
    非表格块按定长（保证全文档覆盖）。"""
    max_table = int(p["max_table_chars"])
    row_group = int(p["row_group"])
    out: list[ChunkOut] = []
    for b in blocks:
        if not b.is_table:
            out.extend(_split_fixed([b], {"chunk_size": 500, "overlap": 50}))
            continue
        if len(b.text) <= max_table:
            out.append(ChunkOut(b.text, _block_table_pos(b), True))
            continue
        # 超大表：按行组切（表头随行重复，保证每个 chunk 自含表头）
        rows = _table_rows(b.text)
        header = rows[:2]  # 表头行 + 分隔行
        body = rows[2:]
        tr = dict(b.pos.get("table_row") or {})
        base_row = int(tr.get("row_start") or 1)
        for i in range(0, len(body), row_group):
            grp = body[i : i + row_group]
            md = "\n".join(header + grp)
            out.append(ChunkOut(md, _block_table_pos(b, row_offset=i, rows=len(grp)), True))
    return out


# ---------------------------------------------------------------- 工厂

def split_blocks(
    blocks: list[ParsedBlock],
    strategy: str,
    params: dict | None = None,
) -> list[ChunkOut]:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown split strategy: {strategy} (supported: {', '.join(STRATEGIES)})")
    p = _resolve_params(strategy, params)
    fn = {
        "fixed": _split_fixed,
        "parent_child": _split_parent_child,
        "semantic": _split_semantic,
        "structured_tree": _split_structured_tree,
        "table": _split_table,
    }[strategy]
    out = fn(blocks, p)
    out = [c for c in out if c.content and c.content.strip()]
    if not out and any(b.text.strip() for b in blocks):
        # 兜底：全部空白块 → 单块（不产生空文档）
        txt = "\n\n".join(b.text for b in blocks if b.text.strip())
        out = [ChunkOut(txt, dict(blocks[0].pos))]
    return out


def effective_strategy(doc: dict, kb: dict) -> tuple[str, dict | None]:
    """文档级覆盖优先，否则库默认（RAG-04 验收 2）。"""
    s = doc.get("split_strategy") or kb.get("split_strategy_default") or "fixed"
    params = doc.get("split_params") if doc.get("split_params") is not None else (kb.get("split_params_default") or None)
    return s, params
