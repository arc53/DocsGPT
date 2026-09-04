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


def _make_zip(entries: Dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.mark.unit
def test_zip_bomb_declared_size_over_cap_is_rejected(monkeypatch):
    # A tiny highly-compressible archive whose decompressed size exceeds the cap
    # must be rejected before any parser reads it (guards a zip-bomb OOM).
    monkeypatch.setattr(dr.settings, "DOCUMENT_MAX_DECOMPRESSED_BYTES", 1000, raising=False)
    data = _make_zip({"word/document.xml": b"A" * 50_000})
    assert len(data) < 1000  # the on-disk archive is well under the byte cap
    out = parse_document_bytes(data, "bomb.docx")
    assert "error" in out and "too much data" in out["error"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "suffix", [".docm", ".xlsm", ".xlsb", ".pptm", ".ppsx", ".ppsm", ".odt", ".ods", ".odp"]
)
def test_zip_bomb_guard_covers_every_anydoc_zip_format(monkeypatch, suffix):
    """Chat attachments have no extension whitelist, so every zip-packaged format
    the anydoc map routes must be gated the same way as .docx."""
    monkeypatch.setattr(dr.settings, "DOCUMENT_MAX_DECOMPRESSED_BYTES", 1000, raising=False)
    data = _make_zip({"content.xml": b"A" * 50_000})
    reason = dr._reject_zip_bomb(data, suffix)
    assert reason is not None and "too much data" in reason


@pytest.mark.unit
def test_zip_too_many_entries_is_rejected(monkeypatch):
    monkeypatch.setattr(dr.settings, "DOCUMENT_MAX_ARCHIVE_ENTRIES", 3, raising=False)
    data = _make_zip({f"f{i}.xml": b"x" for i in range(10)})
    out = parse_document_bytes(data, "many.xlsx")
    assert "error" in out and "too many entries" in out["error"]


@pytest.mark.unit
def test_reject_zip_bomb_ignores_non_zip_formats():
    # A non-zip extension (or a non-zip payload named .docx) is not gated here;
    # the format parser surfaces its own error downstream.
    assert dr._reject_zip_bomb(b"plain text", ".txt") is None
    assert dr._reject_zip_bomb(b"not a zip", ".docx") is None


@pytest.mark.unit
def test_reject_zip_bomb_path_matches_the_bytes_variant(tmp_path, monkeypatch):
    # The path-taking sibling (used by the attachment worker, which has a file
    # rather than bytes) must reach the same verdict as the bytes variant.
    monkeypatch.setattr(dr.settings, "DOCUMENT_MAX_DECOMPRESSED_BYTES", 1000, raising=False)
    data = _make_zip({"word/document.xml": b"A" * 50_000})
    path = tmp_path / "bomb.docx"
    path.write_bytes(data)

    reason = dr.reject_zip_bomb_path(str(path))

    assert reason is not None and "too much data" in reason
    assert reason == dr._reject_zip_bomb(data, ".docx")


@pytest.mark.unit
def test_reject_zip_bomb_path_allows_reasonable_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(dr.settings, "DOCUMENT_MAX_DECOMPRESSED_BYTES", 300 * 1024 * 1024, raising=False)
    monkeypatch.setattr(dr.settings, "DOCUMENT_MAX_ARCHIVE_ENTRIES", 10000, raising=False)
    path = tmp_path / "fine.docx"
    path.write_bytes(_make_zip({"word/document.xml": b"hello"}))

    assert dr.reject_zip_bomb_path(path) is None


@pytest.mark.unit
def test_reject_zip_bomb_path_ignores_non_container_and_corrupt_files(tmp_path, monkeypatch):
    monkeypatch.setattr(dr.settings, "DOCUMENT_MAX_DECOMPRESSED_BYTES", 1, raising=False)
    text = tmp_path / "notes.txt"
    text.write_bytes(b"x" * 5000)
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a real zip")

    # Non-container suffix is never inspected; a corrupt zip is left to the parser.
    assert dr.reject_zip_bomb_path(str(text)) is None
    assert dr.reject_zip_bomb_path(str(broken)) is None


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
def test_max_chars_does_not_truncate_parse_output():
    # max_chars now bounds only the VIEW (bound_parse_payload); parse returns the FULL text
    # so the persisted artifact is the complete parse.
    out = parse_document_bytes(("A" * 100).encode(), "note.txt", output="text", max_chars=10, include_tables=False)
    assert out["content"] == "A" * 100
    assert out["truncated"] is False


@pytest.mark.unit
def test_large_text_is_full_in_parse_output():
    # The default head+tail window moved to bound_parse_payload; parse keeps the full text.
    big = "A" * (dr._TEXT_MAX_BYTES * 3)
    out = parse_document_bytes(big.encode(), "note.txt", output="text", include_tables=False)
    assert out["content"] == big
    assert out["truncated"] is False


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
    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None, **kwargs: {".pdf": fake})
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

    # engine=auto resolves to the server default; this test is about the docling path.
    monkeypatch.setattr(dr.settings, "DOC_PARSER_ENGINE", "docling")

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

    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None, **kwargs: {".pdf": _FakeDoclingParser()})

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
    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None, **kwargs: {".pdf": fake})
    out = parse_document_bytes(b"%PDF", "doc.pdf", output="text", pages="2", engine="docling", include_tables=False)
    assert out["content"] == "page2"


@pytest.mark.unit
def test_page_ranges_are_bounded_before_materializing(monkeypatch):
    """Clamp hostile ranges to real pages while preserving selection semantics."""
    real_range = range
    range_calls: List[tuple[int, int]] = []

    def _guarded_range(start: int, stop: int) -> range:
        range_calls.append((start, stop))
        if stop - start > 100:
            raise AssertionError("attempted to materialize an unbounded page range")
        return real_range(start, stop)

    monkeypatch.setattr(dr, "range", _guarded_range, raising=False)

    selected = dr._selected_page_indices("1-1000000000,1-1000000000", total=3)

    assert selected == [0, 1, 2, 0, 1, 2]
    assert range_calls == [(0, 3), (0, 3)]


@pytest.mark.unit
def test_page_range_expansion_has_an_absolute_cap(monkeypatch):
    """An attacker-controlled page count cannot turn a range into millions of ints."""
    real_range = range
    range_calls: List[tuple[int, int]] = []

    def _guarded_range(start: int, stop: int) -> range:
        range_calls.append((start, stop))
        if stop - start > dr._MAX_PAGE_SELECTIONS:
            raise AssertionError("attempted to expand beyond the page-selection cap")
        return real_range(start, stop)

    monkeypatch.setattr(dr, "range", _guarded_range, raising=False)

    selected = dr._selected_page_indices("1-1000000000", total=25_000_000)

    assert len(selected) == dr._MAX_PAGE_SELECTIONS
    assert selected[0] == 0
    assert selected[-1] == dr._MAX_PAGE_SELECTIONS - 1
    assert range_calls == [(0, dr._MAX_PAGE_SELECTIONS)]


@pytest.mark.unit
def test_page_slicing_never_split_materializes_all_pages():
    """Form-feed slicing walks boundaries without allocating one string per page."""

    class _NoSplitText(str):
        def split(self, *_args, **_kwargs):
            raise AssertionError("page slicing must not call str.split")

    text = _NoSplitText("page1\fpage2\fpage3")

    assert dr._apply_pages(text, "3,1,3") == "page3\fpage1\fpage3"


@pytest.mark.unit
def test_duplicate_page_selection_cannot_amplify_source_text():
    """Repeated selectors remain bounded to the source text's resident size."""
    text = ("x" * 100) + "\fy"

    selected = dr._apply_pages(text, [1] * (dr._MAX_PAGE_SELECTIONS * 2))

    assert len(selected) <= len(text)


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
    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None, **kwargs: {".pdf": fake})

    out = parse_document_bytes(b"%PDF", "doc.pdf", output="text", engine="docling", include_tables=False)
    assert "error" in out and "parsing failed" in out["error"]
    assert seen and not seen[0].exists()


# ---------------------------------------------------------------------------
# ocr resolution
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_ocr_resolution(monkeypatch):
    monkeypatch.setattr(dr.settings, "OCR_ENABLED", True, raising=False)
    assert dr._resolve_ocr_enabled("off") is False
    assert dr._resolve_ocr_enabled("on") is True
    assert dr._resolve_ocr_enabled("auto") is True
    monkeypatch.setattr(dr.settings, "OCR_ENABLED", False, raising=False)
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


@pytest.mark.unit
def test_bound_parse_payload_max_chars_bounds_view_only():
    # max_chars caps the returned view; the parse itself is unaffected (see parse tests above).
    content = "A" * 100
    out = bound_parse_payload({"output": "text", "content": content}, max_chars=10)
    assert out["content"] == "A" * 10
    assert out["truncated"] is True


@pytest.mark.unit
def test_bound_parse_payload_default_window_when_no_max_chars():
    big = "A" * (dr._TEXT_MAX_BYTES * 3)
    out = bound_parse_payload({"output": "text", "content": big})
    assert "...[truncated" in out["content"]
    assert len(out["content"].encode("utf-8")) <= dr._TEXT_MAX_BYTES + 64
    assert out["truncated"] is True


@pytest.mark.unit
def test_bound_parse_payload_small_content_not_flagged():
    out = bound_parse_payload({"output": "text", "content": "hi"}, max_chars=10)
    assert out["content"] == "hi"
    assert out["truncated"] is False


# ---------------------------------------------------------------------------
# vanilla-converter fallback honors the torch.compile toggle
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_vanilla_converter_applies_inference_settings(monkeypatch, tmp_path):
    """The fallback builds its own DocumentConverter, so it must disable
    torch.compile itself — the configured-parser path can't do it for it."""
    import sys
    import types

    called = []
    monkeypatch.setattr(
        "application.parser.file.docling_parser._apply_inference_settings",
        lambda: called.append(True),
    )

    class _Doc:
        texts = []
        tables = []
        pages = {}

        def export_to_markdown(self):
            return "# md"

        def export_to_dict(self):
            return {"texts": []}

    class _Converter:
        def convert(self, *a, **k):
            assert called == [True], "converter built before torch.compile was disabled"
            return types.SimpleNamespace(document=_Doc())

    fake_docling = types.ModuleType("docling")
    fake_dc_module = types.ModuleType("docling.document_converter")
    fake_dc_module.DocumentConverter = _Converter
    fake_docling.document_converter = fake_dc_module
    monkeypatch.setitem(sys.modules, "docling", fake_docling)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_dc_module)

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")

    out = dr._docling_structured(path, ocr_enabled=False, include_tables=False, parser=None)

    assert out["markdown"] == "# md"
    assert called == [True]


# ---------------------------------------------------------------------------
# _docling_structured tables: blank cells must not leak NaN or mangle ints
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_structured_tables_render_blank_cells_as_strings(monkeypatch, tmp_path):
    """pandas 3 preserves missing values through ``astype(str)``, so a blank
    spreadsheet cell leaked a float NaN into the tables payload and a blank
    in an integer column mangled every id to ``1001.0``. Cells must come out
    as join-safe strings (same contract as the tabular parser's
    ``cell_to_text``)."""
    import sys
    import types

    import pandas as pd

    df = pd.DataFrame({"id": [1001, None, 1003], "name": ["a", "b", None]})

    class _Table:
        def export_to_dataframe(self):
            return df

    class _Doc:
        tables = [_Table()]
        pages = {"1": {}}

        def export_to_markdown(self):
            return "# md"

        def export_to_dict(self):
            return {"texts": [], "tables": [{}], "pages": {"1": {}}}

    class _Converter:
        def convert(self, *a, **k):
            return types.SimpleNamespace(document=_Doc())

    monkeypatch.setattr(
        "application.parser.file.docling_parser._apply_inference_settings",
        lambda: None,
    )
    fake_docling = types.ModuleType("docling")
    fake_dc_module = types.ModuleType("docling.document_converter")
    fake_dc_module.DocumentConverter = _Converter
    fake_docling.document_converter = fake_dc_module
    monkeypatch.setitem(sys.modules, "docling", fake_docling)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_dc_module)

    path = tmp_path / "doc.xlsx"
    path.write_bytes(b"stub")

    out = dr._docling_structured(path, ocr_enabled=False, include_tables=True, parser=None)

    [table] = out["tables"]
    cells = [c for row in table["rows"] for c in row]
    assert all(isinstance(c, str) for c in cells), f"non-string cells: {cells!r}"
    assert "1001" in cells and "1001.0" not in cells
    assert "" in cells  # blank cell renders as empty string, not "nan"/"None"


# ---------------------------------------------------------------------------
# engine=anydoc / auto: the default engine must never trigger a docling pass
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_anydoc_engine_is_accepted_and_passed_through(monkeypatch):
    fake = _FakeParser("anydoc text")
    seen = {}

    def _extractor(ocr_enabled=None, **kwargs):
        seen.update(kwargs)
        return {".pdf": fake}

    monkeypatch.setattr(dr, "get_default_file_extractor", _extractor)
    out = parse_document_bytes(b"%PDF-1.4", "doc.pdf", output="text", engine="anydoc", include_tables=False)
    assert out["content"] == "anydoc text"
    assert seen == {"engine": "anydoc"}


@pytest.mark.unit
def test_auto_engine_under_anydoc_skips_docling_table_pass(monkeypatch):
    """Default read (markdown, engine=auto, include_tables) must not run a docling conversion
    just to harvest tables when the configured engine is anydoc — that pass would cost more
    than the whole read and re-import the stack anydoc exists to avoid."""
    monkeypatch.setattr(dr.settings, "DOC_PARSER_ENGINE", "anydoc")
    fake = _FakeParser("# md body")
    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None, **kwargs: {".pdf": fake})

    def _boom(*args, **kwargs):
        raise AssertionError("docling conversion attempted under the anydoc engine")

    monkeypatch.setattr(dr, "_docling_structured", _boom)

    out = parse_document_bytes(b"%PDF-1.4", "doc.pdf")  # markdown, auto, include_tables=True

    assert out["content"] == "# md body"
    assert "tables" not in out


@pytest.mark.unit
def test_explicit_docling_engine_still_collects_tables(monkeypatch):
    monkeypatch.setattr(dr.settings, "DOC_PARSER_ENGINE", "anydoc")
    fake = _FakeParser("body")
    monkeypatch.setattr(dr, "get_default_file_extractor", lambda ocr_enabled=None, **kwargs: {".pdf": fake})
    monkeypatch.setattr(
        dr,
        "_docling_structured",
        lambda *a, **k: {"markdown": "body", "tables": [{"markdown": "| t |"}], "structured": {}, "page_count": 1},
    )

    out = parse_document_bytes(b"%PDF-1.4", "doc.pdf", engine="docling")

    assert out["tables"] == [{"markdown": "| t |"}]


@pytest.mark.unit
def test_structured_output_stays_docling_under_anydoc(monkeypatch):
    monkeypatch.setattr(dr.settings, "DOC_PARSER_ENGINE", "anydoc")
    calls = []

    def _fake_structured(path, *, ocr_enabled, include_tables, parser=None):
        calls.append(path)
        return {"markdown": "# s", "tables": [], "structured": {"texts": []}, "page_count": 1}

    monkeypatch.setattr(dr, "_docling_structured", _fake_structured)
    out = parse_document_bytes(b"%PDF-1.4", "doc.pdf", output="structured")
    assert out["output"] == "structured"
    assert len(calls) == 1


# --- second-pass routing fixes ---------------------------------------------------


def test_fast_engine_covers_the_whole_legacy_map():
    """`fast` must never fall through to the configured (anydoc/docling) map."""
    for suffix, name in {
        ".xhtml": "HTMLParser",
        ".pptx": "PPTXParser",
        ".epub": "EpubParser",
        ".rst": "RstParser",
        ".json": "JSONParser",
    }.items():
        assert type(dr._legacy_parser_for(suffix)).__name__ == name


@pytest.mark.parametrize("suffix", [".odt", ".doc", ".rtf", ".xls", ".ods", ".odp"])
def test_fast_engine_is_terminal_for_anydoc_only_suffixes(monkeypatch, suffix):
    """A suffix only anydoc reads has no legacy parser; `fast` must report that
    rather than silently running the configured engine the caller opted out of."""

    def _boom(*args, **kwargs):
        raise AssertionError("fast fell through to the configured engine map")

    monkeypatch.setattr(dr, "get_default_file_extractor", _boom)
    monkeypatch.setattr(dr, "_zip_bomb_reason", lambda *a, **k: None)

    assert dr._pick_parser(suffix, ocr_enabled=False, engine="fast") is None
    out = parse_document_bytes(b"\xd0\xcf\x11\xe0 bytes", f"doc{suffix}", output="text", engine="fast")
    assert "fast engine" in out["error"] and suffix in out["error"]


def test_fast_engine_still_falls_through_for_images_and_audio(monkeypatch):
    """Formats with no legacy parser and no anydoc alternative keep the configured map."""
    seen = []
    monkeypatch.setattr(dr, "get_default_file_extractor", lambda **kwargs: seen.append(kwargs) or {})
    for suffix in (".png", ".jpg", ".mp3", ".txt"):
        dr._pick_parser(suffix, ocr_enabled=True, engine="fast")
    assert len(seen) == 4


def test_tables_are_not_collected_when_the_pdf_parser_is_not_docling(monkeypatch):
    """Under OCR_BACKEND=native the docling engine hands PDFs to the native OCR
    parser; a vanilla DocumentConverter table pass would OCR the scan again."""

    from application.parser.file.ocr_parser import NativeOcrPdfParser

    native = NativeOcrPdfParser()
    native._parser_config = {}
    monkeypatch.setattr(native, "parse_file", lambda path, errors="ignore": "native text")

    calls = []
    monkeypatch.setattr(dr, "_pick_parser", lambda *a, **k: native)
    monkeypatch.setattr(dr, "_effective_engine", lambda engine: "docling")
    monkeypatch.setattr(dr, "_docling_structured", lambda *a, **k: calls.append(1) or {"tables": []})
    monkeypatch.setattr(dr, "_zip_bomb_reason", lambda *a, **k: None)

    out = parse_document_bytes(b"%PDF-1.4", "scan.pdf", engine="docling", include_tables=True)

    assert out["content"] == "native text"
    assert calls == []


def test_tables_survive_native_ocr_delegation_for_text_only_pdfs(monkeypatch):
    """OCR_BACKEND=native under the docling engine wraps a DoclingParser as the
    native parser's text_parser. A PDF with a text layer on every page is handed
    to that parser, so tables must ride that single conversion instead of being
    dropped by the scan exclusion."""

    from application.parser.file.docling_parser import DoclingParser
    from application.parser.file.ocr_parser import NativeOcrPdfParser

    class _Docling(DoclingParser):
        def __init__(self):
            super().__init__()
            self._parser_config = {"ready": True}

    docling = _Docling()
    native = NativeOcrPdfParser(text_parser=docling)
    native._parser_config = {}
    monkeypatch.setattr(native, "text_layer_delegate", lambda path: docling)
    monkeypatch.setattr(
        native, "parse_file", lambda path, errors="ignore": pytest.fail("native OCR ran on a text-only PDF")
    )

    calls = []

    def _fake_structured(path, *, ocr_enabled, include_tables, parser=None):
        calls.append(parser)
        return {"markdown": "# text pdf", "tables": [{"markdown": "| t |"}], "structured": {}, "page_count": 1}

    monkeypatch.setattr(dr, "_pick_parser", lambda *a, **k: native)
    monkeypatch.setattr(dr, "_effective_engine", lambda engine: "docling")
    monkeypatch.setattr(dr, "_docling_structured", _fake_structured)
    monkeypatch.setattr(dr, "_zip_bomb_reason", lambda *a, **k: None)

    out = parse_document_bytes(b"%PDF-1.4", "text.pdf", engine="docling", include_tables=True)

    assert out["content"] == "# text pdf"
    assert out["tables"] == [{"markdown": "| t |"}]
    assert calls == [docling]


def test_binary_office_suffix_without_anydoc_is_an_error_not_text(monkeypatch):
    monkeypatch.setattr(dr, "_pick_parser", lambda *a, **k: None)
    monkeypatch.setattr(dr, "_zip_bomb_reason", lambda *a, **k: None)

    out = parse_document_bytes(b"\xd0\xcf\x11\xe0 OLE bytes", "legacy.doc", output="text")

    assert "firecrawl-anydoc" in out["error"]
