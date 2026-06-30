"""Unit tests for parse_document_bytes: output shapes, whitelist/size guards, params, and cleanup.

Docling-heavy paths are stubbed or skipped; these cover the shaping and the
untrusted-content safeguards (extension whitelist, byte cap, temp cleanup).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

import application.parser.document_reader as dr
from application.parser.document_reader import (
    bound_parse_payload,
    parse_document_bytes,
    truncate_text_head_tail,
)


# ---------------------------------------------------------------------------
# Guards: whitelist + size cap
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_unknown_extension_is_rejected():
    out = parse_document_bytes(b"data", "evil.exe")
    assert "error" in out and "unsupported file type" in out["error"]


@pytest.mark.unit
def test_size_cap_rejects_oversize(monkeypatch):
    monkeypatch.setattr(dr.settings, "DOCUMENT_PARSE_MAX_BYTES", 8, raising=False)
    out = parse_document_bytes(b"P" * 64, "note.txt", output="text")
    assert "error" in out and "too large" in out["error"]


@pytest.mark.unit
def test_bad_output_ocr_engine_rejected():
    assert "unsupported output" in parse_document_bytes(b"x", "a.txt", output="nope")["error"]
    assert "unsupported ocr" in parse_document_bytes(b"x", "a.txt", ocr="maybe")["error"]
    assert "unsupported engine" in parse_document_bytes(b"x", "a.txt", engine="ghost")["error"]


# ---------------------------------------------------------------------------
# Plain-text path: .txt has no dedicated parser -> standard read
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_text_output_for_plain_text():
    out = parse_document_bytes(b"hello world\n", "note.txt", output="text", include_tables=False)
    assert out["output"] == "text"
    assert out["content"] == "hello world\n"
    assert out["truncated"] is False


@pytest.mark.unit
def test_markdown_output_default():
    out = parse_document_bytes(b"# Title\n", "note.txt", include_tables=False)
    assert out["output"] == "markdown"
    assert "# Title" in out["content"]


@pytest.mark.unit
def test_max_chars_truncates_and_flags():
    out = parse_document_bytes(("A" * 100).encode(), "note.txt", output="text", max_chars=10, include_tables=False)
    assert out["truncated"] is True
    assert len(out["content"]) == 10


@pytest.mark.unit
def test_default_window_truncates_large_text():
    big = ("A" * (dr._TEXT_MAX_BYTES * 3)).encode()
    out = parse_document_bytes(big, "note.txt", output="text", include_tables=False)
    assert out["truncated"] is True
    assert "...[truncated" in out["content"]
    assert len(out["content"].encode("utf-8")) <= dr._TEXT_MAX_BYTES + 64


# ---------------------------------------------------------------------------
# chunks output
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_chunks_output_returns_list():
    out = parse_document_bytes(b"para one.\n\npara two.\n", "note.txt", output="chunks", include_tables=False)
    assert out["output"] == "chunks"
    assert isinstance(out["chunks"], list)
    assert all(isinstance(c, str) for c in out["chunks"])


# ---------------------------------------------------------------------------
# engine selection: a mapped parser is chosen and run with the right text shape
# ---------------------------------------------------------------------------
class _FakeParser:
    """Records that it was used and returns a fixed string or list of strings."""

    def __init__(self, result):
        self._result = result
        self.parser_config_set = True
        self.inited = False

    def init_parser(self):
        self.inited = True

    def parse_file(self, file: Path, errors: str = "ignore"):
        return self._result


@pytest.mark.unit
def test_engine_picks_parser_and_coerces_list(monkeypatch):
    fake = _FakeParser(["chunk A", "chunk B"])
    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None: {".pdf": fake})
    out = parse_document_bytes(b"%PDF-1.4", "doc.pdf", output="text", engine="docling", include_tables=False)
    assert out["content"] == "chunk A\n\nchunk B"


@pytest.mark.unit
def test_fast_engine_uses_legacy_parser(monkeypatch):
    fake = _FakeParser("legacy text")
    monkeypatch.setattr(dr, "_legacy_parser_for", lambda suffix: fake)
    out = parse_document_bytes(b"%PDF-1.4", "doc.pdf", output="text", engine="fast", include_tables=False)
    assert out["content"] == "legacy text"


# ---------------------------------------------------------------------------
# single Docling conversion: the default markdown+tables path must not re-convert
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_default_markdown_with_tables_converts_docling_once(monkeypatch):
    """Default read (markdown, engine=auto, include_tables) converts the doc with Docling once.

    A Docling-backed parser already converts the whole document to produce its text;
    collecting tables must reuse that single conversion instead of re-running
    DocumentConverter. Counts conversions across both sites to prove no double pass.
    """
    import sys
    import types

    from application.parser.file.docling_parser import DoclingParser

    counter = {"instances": 0, "converts": 0}

    class _FakeTable:
        def export_to_dataframe(self):
            raise RuntimeError("no dataframe")  # force the markdown fallback path

        def export_to_markdown(self):
            return "| h |\n| - |\n| v |"

    class _FakeDoc:
        tables = [_FakeTable()]
        pages = {"1": {}}

        def export_to_markdown(self):
            return "# single-pass content"

        def export_to_dict(self):
            return {"texts": [{}], "tables": [{}], "pages": {"1": {}}}

    class _FakeResult:
        document = _FakeDoc()

    class _CountingConverter:
        def __init__(self, *args, **kwargs):
            counter["instances"] += 1

        def convert(self, *args, **kwargs):
            counter["converts"] += 1
            return _FakeResult()

    fake_docling = types.ModuleType("docling")
    fake_dc_module = types.ModuleType("docling.document_converter")
    fake_dc_module.DocumentConverter = _CountingConverter
    fake_docling.document_converter = fake_dc_module
    monkeypatch.setitem(sys.modules, "docling", fake_docling)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_dc_module)

    class _FakeDoclingParser(DoclingParser):
        """Docling-backed parser exposing its configured converter + export for reuse.

        The collapse path converts ONCE via ``self._converter`` and exports content via
        ``_export_content`` (the configured pipeline/OCR), so both content and tables
        come from a single conversion.
        """

        def __init__(self):
            super().__init__()
            self._parser_config = {"ready": True}  # makes parser_config_set True
            self._converter = _CountingConverter()  # single configured conversion

        def _export_content(self, document):
            return "# single-pass content"

        def parse_file(self, file, errors="ignore"):
            # Only reached if the collapse path fails; the test asserts it doesn't.
            return "# parse-file content"

    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None: {".pdf": _FakeDoclingParser()})

    # Defaults: output=markdown, engine=auto, include_tables=True -> the double-parse path.
    out = parse_document_bytes(b"%PDF-1.4", "doc.pdf")

    assert out["output"] == "markdown"
    # Content comes from the CONFIGURED parser's export (matches the legacy single
    # parse), not a vanilla converter; the collapse path was taken, not the fallback.
    assert "single-pass content" in out["content"]
    assert "parse-file content" not in out["content"]
    assert out["tables"] == [{"markdown": "| h |\n| - |\n| v |"}]
    assert counter["converts"] == 1  # was 2 before the fix (content pass + tables pass)
    assert counter["instances"] == 1


# ---------------------------------------------------------------------------
# pages: page-range slice on a form-feed delimited blob
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_pages_slices_form_feed_blob(monkeypatch):
    fake = _FakeParser("page1\fpage2\fpage3")
    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None: {".pdf": fake})
    out = parse_document_bytes(b"%PDF", "doc.pdf", output="text", pages="2", engine="docling", include_tables=False)
    assert out["content"] == "page2"


# ---------------------------------------------------------------------------
# structured output (Docling stubbed)
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_structured_output_shapes_via_docling(monkeypatch):
    def _fake_structured(path, *, ocr_enabled, include_tables):
        return {
            "markdown": "# Statement",
            "structured": {"texts": [{}], "tables": [{}], "pages": {"1": {}}},
            "tables": [{"columns": ["a"], "rows": [["1"]]}],
            "page_count": 1,
        }

    monkeypatch.setattr(dr, "_docling_structured", _fake_structured)
    out = parse_document_bytes(b"%PDF", "doc.pdf", output="structured")
    assert out["output"] == "structured"
    assert out["content"].startswith("# Statement")
    assert out["structured"]["texts"]
    assert out["summary"] == {"texts": 1, "tables": 1, "pages": 1}
    assert out["page_count"] == 1
    assert out["tables"] == [{"columns": ["a"], "rows": [["1"]]}]


@pytest.mark.unit
def test_structured_output_missing_docling_is_clean_error(monkeypatch):
    def _boom(path, *, ocr_enabled, include_tables):
        raise ImportError("No module named 'docling'")

    monkeypatch.setattr(dr, "_docling_structured", _boom)
    out = parse_document_bytes(b"%PDF", "doc.pdf", output="structured")
    assert "error" in out and "structured parsing requires Docling" in out["error"]


# ---------------------------------------------------------------------------
# table bounding
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_table_rows_and_cells_are_bounded():
    big_cell = "y" * (dr._MAX_CELL_CHARS * 3)
    table: Dict[str, Any] = {"columns": ["a", "b"], "rows": [[str(i), big_cell] for i in range(dr._MAX_TABLE_ROWS * 4)]}
    compact = dr._compact_table(table)
    assert len(compact["rows"]) == dr._MAX_TABLE_ROWS
    assert compact["rows_truncated"] is True
    assert compact["total_rows"] == dr._MAX_TABLE_ROWS * 4
    assert compact["rows"][0][1].endswith("...[truncated]")


# ---------------------------------------------------------------------------
# temp cleanup: the staged temp file is removed even on parser failure
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_temp_file_cleaned_up_on_success(monkeypatch):
    seen: List[Path] = []

    real_mkdtemp = dr.tempfile.mkdtemp

    def _tracking_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        seen.append(Path(d))
        return d

    monkeypatch.setattr(dr.tempfile, "mkdtemp", _tracking_mkdtemp)
    parse_document_bytes(b"hi", "note.txt", output="text", include_tables=False)
    assert seen and not seen[0].exists()


@pytest.mark.unit
def test_temp_file_cleaned_up_on_parser_error(monkeypatch):
    seen: List[Path] = []
    real_mkdtemp = dr.tempfile.mkdtemp

    def _tracking_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        seen.append(Path(d))
        return d

    monkeypatch.setattr(dr.tempfile, "mkdtemp", _tracking_mkdtemp)

    fake = _FakeParser("x")
    fake.parse_file = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None: {".pdf": fake})

    out = parse_document_bytes(b"%PDF", "doc.pdf", output="text", engine="docling", include_tables=False)
    assert "error" in out and "parsing failed" in out["error"]
    assert seen and not seen[0].exists()


# ---------------------------------------------------------------------------
# ocr resolution
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_ocr_resolution(monkeypatch):
    monkeypatch.setattr(dr.settings, "DOCLING_OCR_ENABLED", True, raising=False)
    assert dr._resolve_ocr_enabled("off") is False
    assert dr._resolve_ocr_enabled("on") is True
    assert dr._resolve_ocr_enabled("auto") is True
    monkeypatch.setattr(dr.settings, "DOCLING_OCR_ENABLED", False, raising=False)
    assert dr._resolve_ocr_enabled("auto") is False


@pytest.mark.unit
def test_truncate_head_tail_keeps_both_ends():
    text = "HEAD" + ("x" * 200) + "TAIL"
    out = truncate_text_head_tail(text, 40)
    assert "HEAD" in out and "TAIL" in out and "...[truncated" in out


# ---------------------------------------------------------------------------
# bound_parse_payload: every shape stays bounded for the Redis result backend
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_bound_parse_payload_bounds_content_and_chunks():
    huge = "Z" * (dr._TEXT_MAX_BYTES * 3)
    chunks = [huge for _ in range(dr._MAX_CHUNKS_RETURNED * 2)]
    out = bound_parse_payload({"output": "chunks", "content": huge, "chunks": chunks})
    assert len(out["content"].encode("utf-8")) <= dr._TEXT_MAX_BYTES + 64
    assert len(out["chunks"]) == dr._MAX_CHUNKS_RETURNED
    assert out["chunks_truncated"] is True
    assert out["total_chunks"] == dr._MAX_CHUNKS_RETURNED * 2
    assert all("...[truncated" in c for c in out["chunks"])


@pytest.mark.unit
def test_bound_parse_payload_keeps_structured_for_validation():
    structured = {"texts": [{}], "tables": [{}]}
    out = bound_parse_payload({"output": "structured", "content": "# ok", "structured": structured})
    # structured must survive so the tool's json_schema validation can run on it.
    assert out["structured"] == structured
