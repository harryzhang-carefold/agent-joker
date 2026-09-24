"""RAG 文档解析（S04，RAG-03；DECISION-005）。

按 doc_type 分派解析器，产出「内容流」（块序列）：
- txt          → 直读（单块全文）
- docx         → python-docx（段落/表格按文档顺序；标题层级 → section_path）
- xlsx         → openpyxl（每个 sheet 的表格 → Markdown 表格块，含行列范围）
- pdf          → pymupdf（页文本层；页无文本 → 扫描页标记；内嵌图片抽取）
- png/jpg      → 整图（视觉块）

视觉分支（RAG-03）：图片/扫描页/内嵌图 → 调 supports_vision=true 的 LLM endpoint
生成文字化内容；**视觉不可用 → 降级**（块记 [图片未解析: ...]，rag_doc_images 记
skipped，RISK 记录，不阻断流水线）。

同步解析库调用经 asyncio.to_thread（不阻塞事件循环，与 S02 StorageService 一致）。
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from joker_shared.config import settings
from joker_shared.crypto import decrypt_secret

log = logging.getLogger("joker.rag.parser")

SUPPORTED_TYPES = ("txt", "docx", "xlsx", "pdf", "png", "jpg")

DOC_TYPE_BY_EXT = {
    ".txt": "txt",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
}

VISION_PROMPT = (
    "请完整转录这张图片中的全部内容（文字、公式、图表内容）。"
    "公式用 LaTeX 或清晰的文字形式表达；图表请描述其结构与关键数据。"
    "只输出转录/描述内容本身，不要额外说明。"
)
PROMPT_VERSION = "v1"


@dataclass
class ParsedBlock:
    """内容流中的一块（切分的最小输入单元）。

    pos 语义（ARCH §2.2.1 坐标结构）：
    - pdf 文本: page=页码(1起), char_start/char_end=该页文本层内偏移
    - pdf 扫描: page=页码, char_start/char_end=视觉文字化内容流内偏移（页级粒度）
    - docx:    section_path=章节标题路径, char_start/char_end=节内偏移
    - txt:     char_start/char_end=全文偏移
    - xlsx:    table_row={sheet, table, row_start, row_end, col_start?, col_end?}
    - png/jpg: page=1（整图）
    """

    kind: str  # text / scanned_page / image / table
    text: str
    pos: dict[str, Any] = field(default_factory=dict)
    is_table: bool = False


@dataclass
class ParseResult:
    blocks: list[ParsedBlock]
    page_count: int
    parse_method: str  # text / vision / mixed
    images: list[dict]  # 待视觉解析项（含 image bytes，落库前消费）


# ---------------------------------------------------------------- 各类型解析（同步，跑在 to_thread 里）

def _parse_txt(data: bytes) -> ParseResult:
    text = data.decode("utf-8", errors="replace")
    blocks = [ParsedBlock("text", text, {"char_start": 0, "char_end": len(text)})]
    return ParseResult(blocks, 1, "text", [])


def _parse_docx(data: bytes) -> ParseResult:
    from docx import Document
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))

    def iter_block_items(parent):
        from docx.oxml.ns import qn

        for child in parent.element.body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, parent)
            elif child.tag == qn("w:tbl"):
                yield DocxTable(child, parent)

    blocks: list[ParsedBlock] = []
    # 章节路径：heading 1..N 维护栈
    heading_stack: list[tuple[int, str]] = []
    section_char_offset: dict[tuple, int] = {}  # section_path -> 已输出字符数
    cur_section: tuple = ()
    cur_section_len = 0

    for item in iter_block_items(doc):
        if isinstance(item, Paragraph):
            style = (item.style.name or "").lower() if item.style is not None else ""
            text = item.text
            if style.startswith("heading"):
                try:
                    level = int(style.split()[-1])
                except ValueError:
                    level = 1
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                if text.strip():
                    heading_stack.append((level, text.strip()))
                cur_section = tuple(h for _, h in heading_stack)
                cur_section_len = 0
                continue
            if not text.strip():
                continue
            pos = {
                "section_path": list(cur_section),
                "char_start": cur_section_len,
                "char_end": cur_section_len + len(text),
            }
            cur_section_len += len(text)
            blocks.append(ParsedBlock("text", text, pos))
        else:  # 表格
            rows = []
            for r in item.rows:
                rows.append([c.text.strip() for c in r.cells])
            if not rows:
                continue
            md = _rows_to_markdown(rows)
            pos = {
                "section_path": list(cur_section),
                "table_row": {
                    "sheet": "docx",
                    "table": len([b for b in blocks if b.is_table]) + 1,
                    "row_start": 1,
                    "row_end": len(rows),
                },
            }
            blocks.append(ParsedBlock("table", md, pos, is_table=True))
    if not blocks:
        raise ValueError("docx 无有效内容（空文档或仅样式）")
    return ParseResult(blocks, 1, "text", [])


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join([" --- "] * width) + "|"]
    for r in rows[1:]:
        out.append("| " + " | ".join(x.replace("\n", " ") for x in r) + " |")
    return "\n".join(out)


def _parse_xlsx(data: bytes) -> ParseResult:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    blocks: list[ParsedBlock] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            if all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
                continue
            rows.append(["" if v is None else str(v) for v in row])
        if not rows:
            continue
        table_no = len([b for b in blocks if b.is_table]) + 1
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        md = _rows_to_markdown(rows)
        pos = {
            "table_row": {
                "sheet": sheet_name,
                "table": table_no,
                "row_start": 1,
                "row_end": len(rows),
                "col_start": 1,
                "col_end": width,
            }
        }
        blocks.append(ParsedBlock("table", md, pos, is_table=True))
    if not blocks:
        raise ValueError("xlsx 无有效内容（所有 sheet 为空）")
    return ParseResult(blocks, 1, "text", [])


def _parse_pdf(data: bytes) -> ParseResult:
    import fitz  # pymupdf

    doc = fitz.open(stream=data, filetype="pdf")
    blocks: list[ParsedBlock] = []
    images: list[dict] = []
    for page_no in range(doc.page_count):
        page = doc[page_no]
        page_text = page.get_text("text") or ""
        if page_text.strip():
            blocks.append(
                ParsedBlock(
                    "text",
                    page_text,
                    {"page": page_no + 1, "char_start": 0, "char_end": len(page_text)},
                )
            )
        else:
            # 扫描页（无文本层）→ 视觉分支
            pix = page.get_pixmap(dpi=150)
            images.append(
                {
                    "source_type": "scanned_page",
                    "page_no": page_no + 1,
                    "data": pix.tobytes("png"),
                }
            )
        # 内嵌图片抽取（pymupdf）
        try:
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    ext = doc.extract_image(xref)
                except Exception:
                    continue
                if not ext:
                    continue
                raw = ext.get("image") or b""
                if not raw:
                    continue
                mime = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
                        "gif": "image/gif", "bmp": "image/bmp"}.get(ext.get("ext", ""), "image/png")
                images.append(
                    {
                        "source_type": "inline_image",
                        "page_no": page_no + 1,
                        "data": raw,
                        "mime": mime,
                        "name": f"page{page_no + 1}_img{xref}",
                    }
                )
        except Exception:
            log.warning("pdf inline image extraction failed (page=%s)", page_no + 1, exc_info=True)
    if not blocks and not images:
        raise ValueError("pdf 无文本层且无可解析页")
    return ParseResult(blocks, doc.page_count, "text", images)


def _parse_image(data: bytes, mime: str) -> ParseResult:
    return ParseResult(
        [],
        1,
        "vision",
        [
            {
                "source_type": "image_doc",
                "page_no": 1,
                "data": data,
                "mime": mime,
                "name": "whole-image",
            }
        ],
    )


# ---------------------------------------------------------------- 视觉解析（RAG-03）

async def _find_vision_endpoint(session: AsyncSession) -> dict | None:
    """取一个 active 且 supports_vision=true 的 endpoint；无 → None（降级）。"""
    r = await session.execute(
        text(
            "SELECT id, name, base_url, model, api_key_enc, auth_scheme, timeout_seconds "
            "FROM llm_endpoints WHERE status = 'active' AND supports_vision = true "
            "ORDER BY created_at LIMIT 1"
        )
    )
    row = r.first()
    if row is None:
        return None
    return dict(row._mapping)


async def _vision_describe(
    session: AsyncSession, endpoint: dict, data: bytes, mime: str, token_hint: str
) -> tuple[str, dict | None, str | None]:
    """调视觉 endpoint（OpenAI 兼容 chat/completions + image_url data URI）。

    返回 (文字化内容 or None, token_usage, error)。失败不抛（降级语义由调用方决定）。
    """
    b64 = base64.b64encode(data).decode("ascii")
    body = {
        "model": endpoint["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 2048,
        "temperature": 0,
    }
    headers = {}
    if endpoint.get("api_key_enc"):
        key = decrypt_secret(endpoint["api_key_enc"])
        headers["Authorization"] = f"Bearer {key}"
    base = (endpoint.get("base_url") or "").rstrip("/")
    timeout = min(float(endpoint.get("timeout_seconds") or 120), 120)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{base}/chat/completions", json=body, headers=headers)
        if r.status_code != 200:
            return None, None, f"HTTP {r.status_code}: {r.text[:200]}"
        d = r.json()
        content = (d.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        usage = d.get("usage") or {}
        token_usage = {"prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens")}
        return content, token_usage, None
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}"


async def _record_image_rows(
    session: AsyncSession,
    tenant_id: str,
    doc_id: str,
    user_id: str | None,
    images: list[dict],
    kb_embed_dim: int,
) -> list[tuple[dict, str | None, str | None]]:
    """视觉解析执行 + rag_doc_images 记录（逐图可追溯，DB_DESIGN §4.5）。

    返回 [(image_meta, vision_text or None, endpoint_id or None), ...]——
    顺序与 images 一致，供调用方合并进内容流。
    """
    endpoint = await _find_vision_endpoint(session)
    out: list[tuple[dict, str | None, str | None]] = []
    for img in images:
        img_id = str(uuid.uuid4())
        # 图片落盘走 StorageService（source=kb；RESTRICT 禁删保护）
        from joker_shared.storage.service import get_storage_service

        ext = "png" if (img.get("mime") or "").endswith("png") else ("jpg" if (img.get("mime") or "").endswith("jpeg") else "bin")
        name = f"rag_{doc_id[:8]}_{img['source_type']}_{img_id[:8]}.{ext}"
        try:
            file_info = await get_storage_service().upload(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                file_name=name,
                data=img["data"],
                content_type=img.get("mime") or "application/octet-stream",
                source="kb",
            )
            image_file_id = file_info["id"]
        except HTTPException as exc:
            # 图片落盘失败（配额/同名）→ 该图跳过（不阻断文档流水线）
            await session.execute(
                text(
                    "INSERT INTO rag_doc_images (id, tenant_id, doc_id, image_file_id, source_type, page_no, status, error_message, created_by, updated_by) "
                    "VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:d AS uuid), CAST(:f AS uuid), :st, :pn, 'skipped', :e, CAST(:u AS uuid), CAST(:u AS uuid))"
                ),
                {
                    "id": img_id, "t": tenant_id, "d": doc_id,
                    "f": str(uuid.uuid4()), "st": img["source_type"],
                    "pn": img.get("page_no"), "e": f"image storage failed: {exc.detail}",
                    "u": user_id,
                },
            )
            await session.commit()
            out.append((img, None, None))
            continue

        if endpoint is None:
            # 视觉不可用 → 降级跳过（DECISION-005 降级路径；RISK 记录，不阻断）
            log.warning("vision unavailable; image %s skipped (degrade path)", img["source_type"])
            await session.execute(
                text(
                    "INSERT INTO rag_doc_images (id, tenant_id, doc_id, image_file_id, source_type, page_no, prompt_version, status, error_message, created_by, updated_by) "
                    "VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:d AS uuid), CAST(:f AS uuid), :st, :pn, :pv, 'skipped', :e, CAST(:u AS uuid), CAST(:u AS uuid))"
                ),
                {
                    "id": img_id, "t": tenant_id, "d": doc_id, "f": image_file_id,
                    "st": img["source_type"], "pn": img.get("page_no"),
                    "pv": PROMPT_VERSION,
                    "e": "no supports_vision endpoint available (degrade path, RISK)",
                    "u": user_id,
                },
            )
            await session.commit()
            out.append((img, None, None))
            continue

        content, token_usage, err = await _vision_describe(
            session, endpoint, img["data"], img.get("mime") or "image/png", ""
        )
        if content is None:
            await session.execute(
                text(
                    "INSERT INTO rag_doc_images (id, tenant_id, doc_id, image_file_id, source_type, page_no, vision_endpoint_id, prompt_version, status, error_message, created_by, updated_by) "
                    "VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:d AS uuid), CAST(:f AS uuid), :st, :pn, CAST(:ve AS uuid), :pv, 'failed', :e, CAST(:u AS uuid), CAST(:u AS uuid))"
                ),
                {
                    "id": img_id, "t": tenant_id, "d": doc_id, "f": image_file_id,
                    "st": img["source_type"], "pn": img.get("page_no"),
                    "ve": endpoint["id"], "pv": PROMPT_VERSION, "e": err, "u": user_id,
                },
            )
            await session.commit()
            out.append((img, None, endpoint["id"]))
            continue

        await session.execute(
            text(
                "INSERT INTO rag_doc_images (id, tenant_id, doc_id, image_file_id, source_type, page_no, vision_endpoint_id, prompt_version, status, vision_text, token_usage, created_by, updated_by) "
                "VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:d AS uuid), CAST(:f AS uuid), :st, :pn, CAST(:ve AS uuid), :pv, 'done', :vt, :tu, CAST(:u AS uuid), CAST(:u AS uuid))"
            ),
            {
                "id": img_id, "t": tenant_id, "d": doc_id, "f": image_file_id,
                "st": img["source_type"], "pn": img.get("page_no"),
                "ve": endpoint["id"], "pv": PROMPT_VERSION,
                "vt": content, "tu": _jsonb(token_usage), "u": user_id,
            },
        )
        await session.commit()
        out.append((img, content, endpoint["id"]))
    return out


def _jsonb(obj) -> str:
    import json

    return json.dumps(obj)


# ---------------------------------------------------------------- 入口

async def parse_document(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: str | None,
    doc_id: str,
    doc_type: str,
    data: bytes,
) -> ParseResult:
    """解析 + 视觉分支执行。返回含视觉文字的 ParseResult（blocks 已合并图文，按文档顺序）。

    视觉不可用 → 降级路径（记 skipped/failed + 日志，不阻断，DECISION-005）。
    """
    if doc_type not in SUPPORTED_TYPES:
        raise HTTPException(422, f"unsupported doc_type: {doc_type} (supported: {', '.join(SUPPORTED_TYPES)})")

    if doc_type == "txt":
        result = await asyncio.to_thread(_parse_txt, data)
    elif doc_type == "docx":
        result = await asyncio.to_thread(_parse_docx, data)
    elif doc_type == "xlsx":
        result = await asyncio.to_thread(_parse_xlsx, data)
    elif doc_type == "pdf":
        result = await asyncio.to_thread(_parse_pdf, data)
    else:
        mime = "image/png" if doc_type == "png" else "image/jpeg"
        result = await asyncio.to_thread(_parse_image, data, mime)

    # 视觉分支（图片/扫描页/内嵌图）
    if result.images:
        had_text = any(b.kind == "text" and b.text.strip() for b in result.blocks)
        vision = await _record_image_rows(session, tenant_id, doc_id, user_id, result.images, 0)
        merged = _merge_vision_blocks(result.blocks, vision)
        result.blocks = merged
        vision_ok = any(v is not None for _, v, _ in vision)
        # parse_method 反映内容实际来源：
        #  文本+视觉成功 → mixed；仅视觉成功 → vision；仅文本（视觉全降级）→ text；
        #  纯图文档（无文本层）无论视觉成败 → vision（视觉型文档，降级细节记 rag_doc_images.status）
        if had_text and vision_ok:
            result.parse_method = "mixed"
        elif vision_ok:
            result.parse_method = "vision"
        elif had_text:
            result.parse_method = "text"
        else:
            result.parse_method = "vision"

    # 整图文档/纯扫描：视觉失败（全部 None）且无文本块 → 降级占位块（文档不失败，RISK）
    if not result.blocks:
        result.blocks = [
            ParsedBlock(
                "image",
                "[图片未解析：视觉能力不可用，内容缺失（RISK：视觉降级）]",
                {"page": 1},
            )
        ]
        result.parse_method = "vision"
    return result


def _merge_vision_blocks(
    blocks: list[ParsedBlock],
    vision: list[tuple[dict, str | None, str | None]],
) -> list[ParsedBlock]:
    """图文按文档顺序合并为内容流（FLOW_DIAGRAMS：图文合并为内容流）。

    视觉文字以独立块插入到对应页/文档位置：
    - scanned_page: 插入到该页文本块之前（页级）
    - inline_image: 插入到该页文本块之后（页内）
    - image_doc:    整图 → 单块
    视觉失败/跳过 → 插入占位块 [图片未解析: <类型> p<n>]（保证 chunk 覆盖全部来源）。
    """
    out: list[ParsedBlock] = []
    by_page: dict[int, list] = {}
    for meta, vtext, _ep in vision:
        pn = meta.get("page_no") or 1
        by_page.setdefault(pn, []).append((meta, vtext))

    for b in blocks:
        out.append(b)
        pn = b.pos.get("page")
        for meta, vtext in by_page.get(pn, []):
            if vtext:
                out.append(ParsedBlock("image", vtext, {"page": pn, "char_start": 0, "char_end": len(vtext)}))
            else:
                placeholder = f"[图片未解析: {meta['source_type']} p{pn}（视觉不可用，降级路径）]"
                out.append(ParsedBlock("image", placeholder, {"page": pn}))
    # 无文本块的页（纯扫描页）
    pages_with_text = {b.pos.get("page") for b in blocks if b.pos.get("page")}
    for pn, items in by_page.items():
        if pn not in pages_with_text:
            for meta, vtext in items:
                if vtext:
                    out.append(ParsedBlock("image", vtext, {"page": pn, "char_start": 0, "char_end": len(vtext)}))
                else:
                    placeholder = f"[图片未解析: {meta['source_type']} p{pn}（视觉不可用，降级路径）]"
                    out.append(ParsedBlock("image", placeholder, {"page": pn}))
    return out
