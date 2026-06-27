"""In-process document parsing for the ``read_document`` tool, run on the Celery parsing worker.

``parse_document_bytes`` turns untrusted document bytes into a bounded, shaped
result (markdown/text/structured/chunks) using the BACKEND parsers (Docling by
default). It applies the same untrusted-content safeguards as uploads — an
extension whitelist, a byte cap, ``safe_filename`` staging into a temp file, and
temp cleanup — so a hostile filename or document is treated as inert data.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from application.core.settings import settings
from application.parser.file.bulk import get_default_file_extractor
from application.parser.file.constants import SUPPORTED_SOURCE_EXTENSIONS
from application.utils import safe_filename

logger = logging.getLogger(__name__)

# Cap the text returned to the LLM so a huge document can't flood context; the
# full result is still persisted as a ``data`` artifact. When the text exceeds
# the cap a head+tail window keeps both the document's beginning AND end (e.g.
# totals/signatures) within the byte budget.
_TEXT_MAX_BYTES = 8000
_MAX_TABLES_RETURNED = 20
_MAX_TABLE_ROWS = 50
_MAX_CELL_CHARS = 200
# Caps applied to the bounded view that rides back through the Redis result
# backend (the full result still lives in the persisted artifact).
_MAX_CHUNKS_RETURNED = 50

_VALID_OUTPUTS = ("markdown", "text", "structured", "chunks")
_VALID_OCR = ("auto", "on", "off")
_VALID_ENGINES = ("auto", "docling", "fast")


def truncate_text_head_tail(text: str, max_bytes: Optional[int] = None) -> str:
    """Bound text to a head+tail byte window so a large file can't flood context."""
    cap = int(max_bytes or _TEXT_MAX_BYTES)
    if cap <= 0:
        return text
    encoded = text.encode("utf-8")
    if len(encoded) <= cap:
        return text
    head = cap // 2
    tail = cap - head
    dropped = len(encoded) - head - tail
    head_text = encoded[:head].decode("utf-8", errors="ignore")
    tail_text = encoded[-tail:].decode("utf-8", errors="ignore")
    return f"{head_text}\n\n...[truncated {dropped} bytes]...\n\n{tail_text}"


def bound_parse_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Bound every shape of a parse payload so the Redis-backed result stays small.

    ``content`` is re-windowed and ``chunks`` is capped in count and per-chunk
    length. ``structured`` is left as-is: it rides back so json_schema validation
    in the tool can run against it, and it is already bounded by the input byte
    cap plus the table caps (``_compact_table`` / ``summary``); the full result is
    also persisted as a ``data`` artifact. The dict is mutated in place.
    """
    content = payload.get("content")
    if isinstance(content, str):
        payload["content"] = truncate_text_head_tail(content)

    chunks = payload.get("chunks")
    if isinstance(chunks, list):
        bounded = [
            truncate_text_head_tail(chunk) if isinstance(chunk, str) else chunk
            for chunk in chunks[:_MAX_CHUNKS_RETURNED]
        ]
        if len(chunks) > _MAX_CHUNKS_RETURNED:
            payload["chunks_truncated"] = True
            payload["total_chunks"] = len(chunks)
        payload["chunks"] = bounded

    return payload


def _max_input_bytes() -> int:
    """Return the size cap for a parsed document (its own setting, else the sandbox cap)."""
    explicit = int(getattr(settings, "DOCUMENT_PARSE_MAX_BYTES", 0) or 0)
    if explicit > 0:
        return explicit
    return int(getattr(settings, "SANDBOX_MAX_INPUT_BYTES", 25 * 1024 * 1024))


def _resolve_ocr_enabled(ocr: str) -> bool:
    """Resolve the OCR flag from the ``ocr`` arg and the deployment setting."""
    if ocr == "on":
        return True
    if ocr == "off":
        return False
    return bool(getattr(settings, "DOCLING_OCR_ENABLED", False))


def _pick_parser(suffix: str, *, ocr_enabled: bool, engine: str):
    """Select the parser for ``suffix`` honoring the requested engine; None when unsupported."""
    if engine == "fast":
        legacy = _legacy_parser_for(suffix)
        if legacy is not None:
            return legacy
    extractor = get_default_file_extractor(ocr_enabled=ocr_enabled)
    return extractor.get(suffix)


def _legacy_parser_for(suffix: str):
    """Return a non-Docling parser for ``suffix`` (the ``fast`` engine), or None."""
    from application.parser.file.docs_parser import DocxParser, PDFParser
    from application.parser.file.html_parser import HTMLParser
    from application.parser.file.markdown_parser import MarkdownParser
    from application.parser.file.tabular_parser import ExcelParser, PandasCSVParser

    legacy = {
        ".pdf": PDFParser,
        ".docx": DocxParser,
        ".csv": PandasCSVParser,
        ".xlsx": ExcelParser,
        ".html": HTMLParser,
        ".md": MarkdownParser,
        ".mdx": MarkdownParser,
    }
    cls = legacy.get(suffix)
    return cls() if cls is not None else None


def _parse_to_text(parser: Any, path: Path) -> str:
    """Run a parser and coerce its ``str | List[str]`` result to a single text blob."""
    if not parser.parser_config_set:
        parser.init_parser()
    parsed = parser.parse_file(path, errors="ignore")
    if isinstance(parsed, list):
        return "\n\n".join(str(part) for part in parsed)
    return str(parsed)


def _compact_table(table: Dict[str, Any]) -> Dict[str, Any]:
    """Bound a single table's rows and cell sizes so one giant table can't bloat context."""

    def _cell(value: Any) -> Any:
        if isinstance(value, str) and len(value) > _MAX_CELL_CHARS:
            return value[:_MAX_CELL_CHARS] + "...[truncated]"
        return value

    rows = table.get("rows")
    if not isinstance(rows, list):
        return table
    capped = [[_cell(c) for c in row] if isinstance(row, list) else _cell(row) for row in rows[:_MAX_TABLE_ROWS]]
    compact = dict(table)
    compact["rows"] = capped
    if len(rows) > _MAX_TABLE_ROWS:
        compact["rows_truncated"] = True
        compact["total_rows"] = len(rows)
    return compact


def _docling_structured(path: Path, *, ocr_enabled: bool, include_tables: bool) -> Dict[str, Any]:
    """Convert a document with Docling and return markdown + structured dict + bounded tables."""
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    doc = converter.convert(str(path)).document
    markdown = doc.export_to_markdown()
    structured = doc.export_to_dict()
    tables: List[Dict[str, Any]] = []
    if include_tables:
        for tbl in getattr(doc, "tables", []) or []:
            try:
                df = tbl.export_to_dataframe()
                tables.append({"columns": [str(c) for c in df.columns], "rows": df.astype(str).values.tolist()})
            except Exception:
                try:
                    tables.append({"markdown": tbl.export_to_markdown()})
                except Exception:
                    continue
            if len(tables) >= _MAX_TABLES_RETURNED:
                break
    page_count = len(getattr(doc, "pages", {}) or {})
    return {"markdown": markdown, "structured": structured, "tables": tables, "page_count": page_count}


def _structure_summary(structured: Any) -> Dict[str, int]:
    """Summarize the Docling structured dict by top-level element counts (keeps context compact)."""
    if not isinstance(structured, dict):
        return {}
    counts: Dict[str, int] = {}
    for key in ("texts", "tables", "pictures", "groups", "pages"):
        value = structured.get(key)
        if isinstance(value, (list, dict)):
            counts[key] = len(value)
    return counts


def _apply_pages(text: str, pages: Any) -> str:
    """Best-effort page-range slice on a page-delimited markdown blob (``\\f`` separated)."""
    if not pages:
        return text
    parts = text.split("\f")
    if len(parts) <= 1:
        return text
    selected = _selected_page_indices(pages, len(parts))
    if not selected:
        return text
    return "\f".join(parts[i] for i in selected if 0 <= i < len(parts))


def _selected_page_indices(pages: Any, total: int) -> List[int]:
    """Parse ``pages`` ("1-3", "2", [1,2]) into 0-based indices bounded by ``total``."""
    indices: List[int] = []
    tokens = pages if isinstance(pages, list) else str(pages).split(",")
    for token in tokens:
        token = str(token).strip()
        if "-" in token:
            try:
                lo, hi = (int(p) for p in token.split("-", 1))
            except ValueError:
                continue
            indices.extend(range(lo - 1, hi))
        else:
            try:
                indices.append(int(token) - 1)
            except ValueError:
                continue
    return [i for i in indices if 0 <= i < total]


def _to_chunks(text: str, max_chars: Optional[int]) -> List[str]:
    """Chunk parsed text via the ingestion chunker; bounded and JSON-safe for the result."""
    from application.parser.chunking_creator import ChunkerCreator
    from application.parser.schema.base import Document

    chunker = ChunkerCreator.create_chunker("classic_chunk")
    chunks = chunker.chunk([Document(text=text)])
    cap = int(max_chars or 0)
    out: List[str] = []
    for chunk in chunks:
        body = getattr(chunk, "text", str(chunk))
        out.append(body[:cap] if cap > 0 else body)
        if len(out) >= 200:
            break
    return out


def parse_document_bytes(
    data: bytes,
    filename: str,
    *,
    output: str = "markdown",
    ocr: str = "auto",
    pages: Any = None,
    engine: str = "auto",
    max_chars: Optional[int] = None,
    include_tables: bool = True,
) -> Dict[str, Any]:
    """Parse untrusted document bytes into a bounded shaped result; whitelist + size + cleanup guarded."""
    if output not in _VALID_OUTPUTS:
        return {"error": f"unsupported output '{output}'; expected one of {_VALID_OUTPUTS}."}
    if ocr not in _VALID_OCR:
        return {"error": f"unsupported ocr '{ocr}'; expected one of {_VALID_OCR}."}
    if engine not in _VALID_ENGINES:
        return {"error": f"unsupported engine '{engine}'; expected one of {_VALID_ENGINES}."}

    safe_name = safe_filename(filename) or "document"
    suffix = os.path.splitext(safe_name)[1].lower()
    if suffix not in SUPPORTED_SOURCE_EXTENSIONS:
        return {"error": f"unsupported file type '{suffix or filename}'."}

    cap = _max_input_bytes()
    if len(data) > cap:
        return {"error": f"input document is too large: {len(data)} bytes exceeds the {cap}-byte cap."}

    ocr_enabled = _resolve_ocr_enabled(ocr)
    tmp_dir = tempfile.mkdtemp(prefix="docparse-")
    tmp_path = Path(tmp_dir) / safe_name
    try:
        tmp_path.write_bytes(data)
        return _shape(tmp_path, suffix, output, ocr_enabled, engine, pages, max_chars, include_tables)
    except Exception as exc:
        logger.exception("parse_document_bytes: parsing failed")
        return {"error": f"parsing failed: {type(exc).__name__}: {exc}"}
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
            os.rmdir(tmp_dir)
        except OSError:
            logger.warning("parse_document_bytes: temp cleanup failed for %s", tmp_dir, exc_info=True)


def _shape(
    path: Path,
    suffix: str,
    output: str,
    ocr_enabled: bool,
    engine: str,
    pages: Any,
    max_chars: Optional[int],
    include_tables: bool,
) -> Dict[str, Any]:
    """Run the selected parser/engine and shape the result per ``output``; bounded throughout.

    ``output='structured'`` always uses Docling regardless of ``engine`` — the ``fast``
    engine is markdown/text only and cannot produce the structured dict.
    """
    if output == "structured":
        try:
            extracted = _docling_structured(path, ocr_enabled=ocr_enabled, include_tables=include_tables)
        except Exception as exc:
            return {"error": f"structured parsing requires Docling: {type(exc).__name__}: {exc}"}
        bounded, truncated = _bounded(extracted["markdown"], max_chars)
        return {
            "output": "structured",
            "content": bounded,
            "truncated": truncated,
            "tables": [_compact_table(t) for t in extracted["tables"]],
            "structured": extracted["structured"],
            "summary": _structure_summary(extracted["structured"]),
            "page_count": extracted["page_count"],
        }

    parser = _pick_parser(suffix, ocr_enabled=ocr_enabled, engine=engine)
    if parser is None:
        # A whitelisted extension with no dedicated parser (e.g. .txt) reads as plain
        # text, matching SimpleDirectoryReader's standard-read fallback.
        text = path.read_text(errors="ignore")
    else:
        text = _parse_to_text(parser, path)
    text = _apply_pages(text, pages)

    if output == "chunks":
        return {"output": "chunks", "chunks": _to_chunks(text, max_chars), "truncated": False}

    tables: List[Dict[str, Any]] = []
    if include_tables and engine != "fast":
        try:
            tables = [_compact_table(t) for t in _docling_structured(
                path, ocr_enabled=ocr_enabled, include_tables=True)["tables"]]
        except Exception:
            tables = []
    bounded, truncated = _bounded(text, max_chars)
    payload: Dict[str, Any] = {"output": output, "content": bounded, "truncated": truncated}
    if tables:
        payload["tables"] = tables
    return payload


def _bounded(text: str, max_chars: Optional[int]) -> tuple[str, bool]:
    """Bound text to ``max_chars`` (chars) or the default byte window; flag truncation."""
    if max_chars and int(max_chars) > 0:
        capped = text[: int(max_chars)]
        return capped, len(capped) < len(text)
    bounded = truncate_text_head_tail(text)
    return bounded, bounded != text
