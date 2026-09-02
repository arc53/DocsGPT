"""Tests for the anydoc parser (the default ``DOC_PARSER_ENGINE``).

Three behaviours matter and are asserted separately:

* a file anydoc converts comes back as Markdown, with ``last_engine`` set;
* a file it refuses (a scanned PDF, an unknown format) goes to the fallback
  parser when one is configured, and every failure surfaces as
  ``DocumentParseError`` — never as an empty document or a raw traceback;
* the suffix list the parser map is built from matches what the installed
  anydoc actually accepts.
"""

import importlib.machinery
import sys
import types

import pytest

from application.parser.file.base_parser import BaseParser, DocumentParseError

anydoc = pytest.importorskip("anydoc")

from application.parser.file.anydoc_parser import (  # noqa: E402 — after importorskip
    ANYDOC_SUFFIXES,
    AnydocParser,
    anydoc_available,
)


# Long enough to clear the scanned-PDF near-empty guard (_MIN_SCAN_FALLBACK_CHARS).
FALLBACK_TEXT = "fallback parser text output, long enough to clear the scanned-PDF guard."


class _RecordingFallback(BaseParser):
    """Stands in for docling / a legacy parser so delegation is observable."""

    def __init__(self, result=FALLBACK_TEXT):
        super().__init__(parser_config={})
        self.calls = []
        self._result = result

    def _init_parser(self):
        return {}

    def parse_file(self, file, errors="ignore"):
        self.calls.append(file)
        return self._result


class _ExplodingFallback(BaseParser):
    def _init_parser(self):
        return {}

    def parse_file(self, file, errors="ignore"):
        raise RuntimeError("fallback blew up")


def _scanned_pdf(path, pages=2):
    """A PDF with pages but no text layer: what a scan looks like to a parser."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def _fake_anydoc(monkeypatch, to_markdown):
    """Install a stub ``anydoc`` module whose ``to_markdown`` is ``to_markdown``."""
    fake = types.ModuleType("anydoc")
    fake.__spec__ = importlib.machinery.ModuleSpec("anydoc", None)

    class ConvertError(Exception):
        pass

    class UnsupportedError(ConvertError):
        pass

    class ResourceLimitError(ConvertError):
        pass

    fake.ConvertError = ConvertError
    fake.UnsupportedError = UnsupportedError
    fake.ResourceLimitError = ResourceLimitError
    fake.to_markdown = to_markdown
    monkeypatch.setitem(sys.modules, "anydoc", fake)
    return fake


# --- the suffix list is what anydoc really supports ---------------------------


def test_every_listed_suffix_is_an_anydoc_format():
    for suffix in ANYDOC_SUFFIXES:
        assert anydoc.format_from_extension(suffix) is not None, suffix


def test_epub_and_html_are_not_routed_to_anydoc():
    assert ".epub" not in ANYDOC_SUFFIXES
    assert ".html" not in ANYDOC_SUFFIXES


# --- successful conversion -----------------------------------------------------


def test_csv_converts_to_markdown_table(tmp_path):
    path = tmp_path / "items.csv"
    path.write_text("name,qty\nwidget,3\ngadget,5\n")
    parser = AnydocParser()
    parser.init_parser()

    out = parser.parse_file(path)

    assert isinstance(out, str)
    assert "widget" in out and "gadget" in out
    assert "|" in out  # rendered as a GFM table, not flat text
    assert parser.last_engine == "anydoc"


def test_xlsx_converts_with_cell_text(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "book.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["city", "population"])
    ws.append(["Ljubljana", 295000])
    wb.save(path)

    out = AnydocParser().parse_file(path)

    assert "Ljubljana" in out
    assert "295000" in out


def test_accepts_path_and_str(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("x,y\n1,2\n")
    assert AnydocParser().parse_file(str(path)) == AnydocParser().parse_file(path)


# --- refusal routes to the fallback --------------------------------------------


def test_scanned_pdf_delegates_to_fallback(tmp_path):
    path = _scanned_pdf(tmp_path / "scan.pdf")
    fallback = _RecordingFallback()
    parser = AnydocParser(fallback_parser=fallback)

    out = parser.parse_file(path)

    assert out == FALLBACK_TEXT
    assert fallback.calls == [path]
    assert parser.last_engine == "_RecordingFallback"


def test_fallback_last_engine_is_reported_when_it_has_one(tmp_path):
    path = _scanned_pdf(tmp_path / "scan.pdf")
    fallback = _RecordingFallback()
    fallback.last_engine = "pypdfium2"

    parser = AnydocParser(fallback_parser=fallback)
    parser.parse_file(path)

    assert parser.last_engine == "pypdfium2"


def test_scanned_pdf_without_fallback_is_document_parse_error(tmp_path):
    path = _scanned_pdf(tmp_path / "scan.pdf")
    parser = AnydocParser()

    with pytest.raises(DocumentParseError, match="scan.pdf"):
        parser.parse_file(path)
    assert parser.last_engine is None


def test_unknown_format_without_fallback_is_document_parse_error(tmp_path):
    path = tmp_path / "blob.xyz"
    path.write_bytes(b"hello")

    with pytest.raises(DocumentParseError, match="blob.xyz"):
        AnydocParser().parse_file(path)


def test_fallback_failure_is_document_parse_error(tmp_path):
    """A fallback that raises must not leak a bare exception (load_data skips only DocumentParseError)."""
    path = _scanned_pdf(tmp_path / "scan.pdf")

    with pytest.raises(DocumentParseError):
        AnydocParser(fallback_parser=_ExplodingFallback()).parse_file(path)


def test_fallback_document_parse_error_passes_through(tmp_path):
    class _Refusing(BaseParser):
        def _init_parser(self):
            return {}

        def parse_file(self, file, errors="ignore"):
            raise DocumentParseError("scan needs OCR")

    path = _scanned_pdf(tmp_path / "scan.pdf")
    with pytest.raises(DocumentParseError, match="scan needs OCR"):
        AnydocParser(fallback_parser=_Refusing()).parse_file(path)


def test_missing_file_is_document_parse_error(tmp_path):
    with pytest.raises(DocumentParseError, match="could not be read"):
        AnydocParser().parse_file(tmp_path / "missing.docx")


def test_empty_output_delegates(tmp_path, monkeypatch):
    """Whitespace-only output is treated as a failed conversion, not stored."""
    _fake_anydoc(monkeypatch, lambda path: "  \n\n ")
    fallback = _RecordingFallback("real text")
    path = tmp_path / "x.docx"
    path.write_bytes(b"irrelevant")

    out = AnydocParser(fallback_parser=fallback).parse_file(path)

    assert out == "real text"
    assert fallback.calls == [path]


def test_typed_convert_error_delegates(tmp_path, monkeypatch):
    fake = _fake_anydoc(monkeypatch, None)

    def _refuse(path):
        raise fake.UnsupportedError("PDF has no extractable text; OCR is required")

    fake.to_markdown = _refuse
    fallback = _RecordingFallback()
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4")

    assert AnydocParser(fallback_parser=fallback).parse_file(path) == FALLBACK_TEXT


def test_typed_convert_error_message_reaches_the_user(tmp_path, monkeypatch):
    fake = _fake_anydoc(monkeypatch, None)

    def _refuse(path):
        raise fake.UnsupportedError("PDF has no extractable text; OCR is required")

    fake.to_markdown = _refuse
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4")

    with pytest.raises(DocumentParseError, match="OCR is required"):
        AnydocParser().parse_file(path)


def test_resource_limit_is_terminal_even_with_fallback(tmp_path, monkeypatch):
    """anydoc refusing a file as too expensive must not hand it to a heavier
    engine that would then spend exactly what was refused."""
    fake = _fake_anydoc(monkeypatch, None)

    def _refuse(path):
        raise fake.ResourceLimitError(
            "resource limit exceeded (max_entry_bytes): word/document.xml declares 400400167 bytes"
        )

    fake.to_markdown = _refuse
    fallback = _RecordingFallback()
    parser = AnydocParser(fallback_parser=fallback)
    path = tmp_path / "bomb.docx"
    path.write_bytes(b"PK")

    with pytest.raises(DocumentParseError, match="max_entry_bytes"):
        parser.parse_file(path)
    assert fallback.calls == []
    assert parser.last_engine is None


def test_unexpected_exception_is_document_parse_error(tmp_path, monkeypatch):
    def _crash(path):
        raise RuntimeError("panic")

    _fake_anydoc(monkeypatch, _crash)
    path = tmp_path / "x.docx"
    path.write_bytes(b"irrelevant")

    with pytest.raises(DocumentParseError, match="x.docx"):
        AnydocParser().parse_file(path)


# --- init / availability --------------------------------------------------------


def test_init_parser_records_fallback():
    parser = AnydocParser(fallback_parser=_RecordingFallback())
    parser.init_parser()
    assert parser.parser_config == {"fallback_parser": "_RecordingFallback"}

    bare = AnydocParser()
    bare.init_parser()
    assert bare.parser_config == {"fallback_parser": None}


def test_init_parser_without_anydoc_raises_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "anydoc", None)
    assert not anydoc_available()
    with pytest.raises(ImportError, match="firecrawl-anydoc"):
        AnydocParser().init_parser()


def test_init_parser_imports_for_real_not_just_find_spec(monkeypatch):
    """A wheel whose native extension fails to load has a spec but no importable
    module; that must surface at init, not as a bare ImportError from parse_file
    mid-ingest (which load_data does not catch)."""
    import application.parser.file.anydoc_parser as mod

    monkeypatch.setattr(mod, "anydoc_available", lambda: True)
    monkeypatch.setitem(sys.modules, "anydoc", None)

    with pytest.raises(ImportError, match="firecrawl-anydoc"):
        AnydocParser().init_parser()


# --- PDF trust check + tableize wiring (PR 3) -----------------------------------

from pathlib import Path as _Path

FIXTURES = _Path(__file__).parent / "fixtures"
CID_PDF = FIXTURES / "nda_en_zh_cid_font.pdf"


# Long enough to clear the near-empty guard a trust-check re-parse must pass.
_REROUTE_TEXT = "docling reroute text, long enough to clear the near-empty reroute guard"


class _FakeDoclingFallback:
    """Registered as a DoclingParser subclass so ``_is_docling_backed`` is True."""

    def __new__(cls):
        from application.parser.file.docling_parser import DoclingParser

        class _Inner(DoclingParser):
            def __init__(self):
                self._parser_config = {}
                self.calls = []
                self.last_engine = None

            def parse_file(self, file, errors="ignore"):
                self.calls.append(file)
                return _REROUTE_TEXT

        return _Inner()


def test_trust_flagged_pdf_reroutes_to_docling_fallback():
    fallback = _FakeDoclingFallback()
    parser = AnydocParser(fallback_parser=fallback)

    out = parser.parse_file(CID_PDF)

    assert out == _REROUTE_TEXT
    assert fallback.calls == [CID_PDF]
    assert parser.last_engine == "_Inner"
    assert parser.get_file_metadata(CID_PDF) == {}  # rerouted, nothing to warn about


def test_trust_flagged_pdf_without_docling_keeps_output_and_warns():
    parser = AnydocParser(fallback_parser=_RecordingFallback())  # not docling-backed

    out = parser.parse_file(CID_PDF)

    assert "NON-DISCLOSURE" in out.upper() or len(out) > 50  # anydoc's own output kept
    meta = parser.get_file_metadata(CID_PDF)
    assert "parse_warnings" in meta
    assert any("ToUnicode" in w for w in meta["parse_warnings"])
    assert any("CJK" in w for w in meta["parse_warnings"])
    assert parser.last_engine == "anydoc"


def test_trust_check_disabled_stamps_nothing(monkeypatch):
    from application.parser.file import anydoc_parser as ap

    monkeypatch.setattr(ap.settings, "PDF_TRUST_CHECK", False)
    parser = AnydocParser()

    parser.parse_file(CID_PDF)

    assert parser.get_file_metadata(CID_PDF) == {}


def test_trust_reroute_failure_keeps_anydoc_output():
    fallback = _FakeDoclingFallback()

    def _boom(file, errors="ignore"):
        raise RuntimeError("docling exploded")

    fallback.parse_file = _boom
    parser = AnydocParser(fallback_parser=fallback)

    out = parser.parse_file(CID_PDF)

    assert "docling" not in out
    assert "parse_warnings" in parser.get_file_metadata(CID_PDF)
    assert parser.last_engine == "anydoc"


def test_trust_reroute_near_empty_keeps_anydoc_output():
    """A docling pipeline dropout ('' / '<!-- image -->') returns without
    raising; adopting it would swap anydoc's real text for an empty document."""
    fallback = _FakeDoclingFallback()
    fallback.parse_file = lambda file, errors="ignore": "<!-- image -->"
    parser = AnydocParser(fallback_parser=fallback)

    out = parser.parse_file(CID_PDF)

    assert "<!-- image -->" not in out
    assert "parse_warnings" in parser.get_file_metadata(CID_PDF)
    assert parser.last_engine == "anydoc"


def test_warnings_reset_between_files(tmp_path):
    parser = AnydocParser()
    parser.parse_file(CID_PDF)
    assert parser.get_file_metadata(CID_PDF) != {}

    clean = tmp_path / "clean.csv"
    clean.write_text("a,b\n1,2\n")
    parser.parse_file(clean)

    assert parser.get_file_metadata(clean) == {}
    assert parser.get_file_metadata(CID_PDF) == {}


def test_trust_check_errors_never_fail_the_parse(monkeypatch, tmp_path):
    def _explode(path, markdown):
        raise RuntimeError("scanner bug")

    import application.parser.file.pdf_trust as pt

    monkeypatch.setattr(pt, "verify_pdf_file", _explode)
    _fake_anydoc(monkeypatch, lambda path: "# converted fine")
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4 irrelevant")

    assert AnydocParser().parse_file(path) == "# converted fine"


def test_tableize_applied_when_enabled(monkeypatch, tmp_path):
    from application.parser.file import anydoc_parser as ap

    monkeypatch.setattr(ap.settings, "ANYDOC_TABLEIZE", True)
    monkeypatch.setattr(ap.settings, "PDF_TRUST_CHECK", False)
    _fake_anydoc(
        monkeypatch,
        lambda path: "Cash ..... 1,234 900\nDebt ..... 2,000 1,500\nEquity ..... 900 800",
    )
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4 irrelevant")

    out = AnydocParser().parse_file(path)

    assert "| Cash | 1,234 | 900 |" in out


def test_tableize_disabled_by_default(monkeypatch, tmp_path):
    from application.parser.file import anydoc_parser as ap

    monkeypatch.setattr(ap.settings, "PDF_TRUST_CHECK", False)
    flat = "Cash ..... 1,234 900\nDebt ..... 2,000 1,500\nEquity ..... 900 800"
    _fake_anydoc(monkeypatch, lambda path: flat)
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4 irrelevant")

    assert AnydocParser().parse_file(path) == flat


def test_tableize_never_touches_docling_reroute(monkeypatch):
    from application.parser.file import anydoc_parser as ap

    monkeypatch.setattr(ap.settings, "ANYDOC_TABLEIZE", True)
    fallback = _FakeDoclingFallback()
    parser = AnydocParser(fallback_parser=fallback)

    out = parser.parse_file(CID_PDF)

    assert out == _REROUTE_TEXT  # verbatim, not post-processed


# --- scanned-PDF near-empty guard (the OCR_ENGINE seam's loud-failure side) ------


def test_scanned_pdf_with_near_empty_fallback_fails_loudly_when_ocr_off(tmp_path):
    """A scan whose fallback (OCR off) extracts almost nothing must fail with
    an actionable message, not be stored as an empty document."""
    path = _scanned_pdf(tmp_path / "scan.pdf")
    fallback = _RecordingFallback(result="   ")
    fallback.ocr_enabled = False
    parser = AnydocParser(fallback_parser=fallback)

    with pytest.raises(DocumentParseError, match="OCR_ENABLED"):
        parser.parse_file(path)
    assert parser.last_engine is None


def test_scanned_pdf_with_near_empty_fallback_and_ocr_on_reports_it(tmp_path):
    path = _scanned_pdf(tmp_path / "scan.pdf")
    fallback = _RecordingFallback(result="x")
    fallback.ocr_enabled = True

    with pytest.raises(DocumentParseError, match="even with OCR enabled"):
        AnydocParser(fallback_parser=fallback).parse_file(path)


def test_scanned_pdf_with_substantial_fallback_output_passes(tmp_path):
    """docling extracting a text layer anydoc refused (the HK-bill case) must
    keep working — the guard only fires on near-empty results."""
    path = _scanned_pdf(tmp_path / "scan.pdf")
    out = AnydocParser(fallback_parser=_RecordingFallback()).parse_file(path)
    assert out == FALLBACK_TEXT


def test_non_scan_refusals_do_not_trigger_the_guard(tmp_path, monkeypatch):
    """Only the OCR-required refusal implies 'content exists but needs OCR';
    a malformed file with a short fallback result stays a successful parse."""
    fake = _fake_anydoc(monkeypatch, None)

    class MalformedError(fake.ConvertError):
        pass

    fake.MalformedError = MalformedError

    def _refuse(path):
        raise MalformedError("structurally unusable")

    fake.to_markdown = _refuse
    path = tmp_path / "x.docx"
    path.write_bytes(b"irrelevant")

    out = AnydocParser(fallback_parser=_RecordingFallback(result="tiny")).parse_file(path)
    assert out == "tiny"


# --- spreadsheets: a resource limit delegates, other formats stay terminal ----


def test_resource_limit_on_a_spreadsheet_delegates_to_the_tabular_fallback(tmp_path, monkeypatch):
    """anydoc refuses a 265k-row sheet on fixed limits that openpyxl/pandas
    read fine, so for tabular suffixes the limit is a reason to fall back."""
    fake = _fake_anydoc(monkeypatch, None)

    def _refuse(path):
        raise fake.ResourceLimitError("resource limit exceeded (max_xml_nodes): 2000000")

    fake.to_markdown = _refuse
    fallback = _RecordingFallback()
    parser = AnydocParser(fallback_parser=fallback)
    path = tmp_path / "big.xlsx"
    path.write_bytes(b"PK")

    assert parser.parse_file(path) == FALLBACK_TEXT
    assert fallback.calls == [path]
    assert parser.last_engine == "_RecordingFallback"


def test_resource_limit_on_a_spreadsheet_without_fallback_is_terminal(tmp_path, monkeypatch):
    fake = _fake_anydoc(monkeypatch, None)

    def _refuse(path):
        raise fake.ResourceLimitError("resource limit exceeded (max_entry_bytes)")

    fake.to_markdown = _refuse
    path = tmp_path / "big.xlsx"
    path.write_bytes(b"PK")

    with pytest.raises(DocumentParseError, match="max_entry_bytes"):
        AnydocParser().parse_file(path)


# --- mixed documents: one page's OCR failure costs that page only ------------


class _PerPageOcrFallback(BaseParser):
    ocr_enabled = True

    def __init__(self, failing_index):
        super().__init__()
        self.failing_index = failing_index
        self.requests = []

    def _init_parser(self):
        return {}

    def parse_file(self, file, errors="ignore"):
        return "unused"

    def ocr_pages(self, file, indices):
        self.requests.append(list(indices))
        if self.failing_index in indices:
            raise DocumentParseError("tesseract failed on this page")
        return {index: f"OCR TEXT PAGE {index + 1}" for index in indices}


def test_one_failing_page_does_not_drop_the_other_pages_ocr(tmp_path, monkeypatch):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("pypdf")
    _fake_anydoc(monkeypatch, lambda path: "Text pages read by anydoc.")
    fallback = _PerPageOcrFallback(failing_index=0)
    parser = AnydocParser(fallback_parser=fallback)
    path = _scanned_pdf(tmp_path / "mixed.pdf", pages=3)  # every page probes as scanned

    text = parser.parse_file(path)

    assert fallback.requests == [[0], [1], [2]]
    assert "OCR TEXT PAGE 1" not in text
    assert "OCR TEXT PAGE 2" in text and "OCR TEXT PAGE 3" in text
    assert text.startswith("Text pages read by anydoc.")
    # (The font-less blank-page fixture also earns a trust-check warning.)
    assert parser.get_file_metadata(path)["ocr_pages"] == 2
