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


class _RecordingFallback(BaseParser):
    """Stands in for docling / a legacy parser so delegation is observable."""

    def __init__(self, result="fallback text"):
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

    assert out == "fallback text"
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

    assert AnydocParser(fallback_parser=fallback).parse_file(path) == "fallback text"


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
