"""Tests for the pypdfium2 text-layer PDF parser used on the attachment path.

Two behaviours matter here and are asserted separately:

* a PDF with a real text layer is read directly by pypdfium2, skipping docling
  entirely (this is the whole point — docling costs tens of seconds per file);
* a PDF with no text layer (a scan) is handed to the fallback parser rather
  than returning an empty document, so the scanned-PDF path is unchanged.

The extractor-wiring test is the guard that source ingestion keeps docling:
the fast path must only appear when a caller explicitly asks for it.
"""

import pytest

from application.parser.file.base_parser import BaseParser, DocumentParseError

pypdfium2 = pytest.importorskip("pypdfium2")


def _text_pdf(path, pages=3, text="The quick brown fox jumps over the lazy dog."):
    """Write a PDF that has a genuine text layer."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    for page in range(pages):
        # Several lines per page so the per-page character count clears the
        # probe threshold the way a real document does.
        for line in range(12):
            c.drawString(72, 720 - line * 18, f"page {page} line {line} {text}")
        c.showPage()
    c.save()
    return path


def _scanned_pdf(path, pages=3):
    """Write a PDF with pages but no text layer, i.e. what a scan looks like."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


class _RecordingFallback(BaseParser):
    """Stands in for the docling parser so delegation is observable."""

    def __init__(self):
        super().__init__(parser_config={})
        self.calls = []

    def _init_parser(self):
        return {}

    def parse_file(self, file, errors="ignore"):
        self.calls.append(file)
        return "FALLBACK OUTPUT"

    def get_file_metadata(self, file):
        return {"fallback_meta": True}


@pytest.fixture
def parser_cls():
    from application.parser.file.pdfium_parser import PdfiumTextParser

    return PdfiumTextParser


def test_text_layer_pdf_is_read_by_pypdfium2(tmp_path, parser_cls):
    pdf = _text_pdf(tmp_path / "text.pdf")
    fallback = _RecordingFallback()
    parser = parser_cls(fallback_parser=fallback)
    parser.init_parser()

    out = parser.parse_file(pdf)

    assert "quick brown fox" in out
    assert "page 2" in out, "every page should be extracted, not just the first"
    assert fallback.calls == [], "a text-layer PDF must not reach docling"
    assert parser.last_engine == "pypdfium2"


def test_scanned_pdf_delegates_to_fallback(tmp_path, parser_cls):
    pdf = _scanned_pdf(tmp_path / "scan.pdf")
    fallback = _RecordingFallback()
    parser = parser_cls(fallback_parser=fallback)
    parser.init_parser()

    out = parser.parse_file(pdf)

    assert out == "FALLBACK OUTPUT"
    assert fallback.calls == [pdf]
    assert parser.last_engine == "_RecordingFallback"


def test_scanned_pdf_without_fallback_raises(tmp_path, parser_cls):
    pdf = _scanned_pdf(tmp_path / "scan.pdf")
    parser = parser_cls(fallback_parser=None)
    parser.init_parser()

    with pytest.raises(DocumentParseError):
        parser.parse_file(pdf)


def test_unopenable_pdf_delegates_to_fallback(tmp_path, parser_cls):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"not a pdf at all")
    fallback = _RecordingFallback()
    parser = parser_cls(fallback_parser=fallback)
    parser.init_parser()

    assert parser.parse_file(pdf) == "FALLBACK OUTPUT"
    assert fallback.calls == [pdf]


def test_metadata_reports_engine_and_page_count(tmp_path, parser_cls):
    pdf = _text_pdf(tmp_path / "text.pdf", pages=4)
    parser = parser_cls(fallback_parser=_RecordingFallback())
    parser.init_parser()
    parser.parse_file(pdf)

    meta = parser.get_file_metadata(pdf)

    assert meta["parse_engine"] == "pypdfium2"
    assert meta["pdf_pages"] == 4


def test_fallback_metadata_is_passed_through(tmp_path, parser_cls):
    pdf = _scanned_pdf(tmp_path / "scan.pdf")
    parser = parser_cls(fallback_parser=_RecordingFallback())
    parser.init_parser()
    parser.parse_file(pdf)

    meta = parser.get_file_metadata(pdf)

    assert meta["fallback_meta"] is True
    assert meta["parse_engine"] == "_RecordingFallback"


def test_threshold_sends_sparse_text_to_fallback(tmp_path, parser_cls):
    """A PDF whose text layer is a stray character is a scan, not a document."""
    pdf = _text_pdf(tmp_path / "sparse.pdf", pages=2, text="")
    fallback = _RecordingFallback()
    parser = parser_cls(fallback_parser=fallback, min_median_chars=10_000)
    parser.init_parser()

    assert parser.parse_file(pdf) == "FALLBACK OUTPUT"


# --- extractor wiring: the guard that source ingestion keeps docling ---------
# (under the docling engine; the anydoc engine ignores the fast path, see below)


@pytest.fixture
def docling_engine(monkeypatch):
    from application.core.settings import settings

    monkeypatch.setattr(settings, "DOC_PARSER_ENGINE", "docling")


def test_extractor_defaults_to_docling_for_pdf(docling_engine):
    """Sources must be unaffected: no fast path unless explicitly requested."""
    from application.parser.file.bulk import get_default_file_extractor

    pdf_parser = get_default_file_extractor()[".pdf"]

    assert type(pdf_parser).__name__ == "DoclingPDFParser"


def test_extractor_uses_fast_path_when_requested(docling_engine):
    from application.parser.file.bulk import get_default_file_extractor
    from application.parser.file.pdfium_parser import PdfiumTextParser

    pdf_parser = get_default_file_extractor(pdf_text_fast_path=True)[".pdf"]

    assert isinstance(pdf_parser, PdfiumTextParser)
    assert type(pdf_parser.fallback_parser).__name__ == "DoclingPDFParser"


def test_anydoc_engine_ignores_fast_path(monkeypatch):
    """anydoc already reads the text layer in milliseconds and keeps structure."""
    pytest.importorskip("anydoc")
    from application.core.settings import settings
    from application.parser.file.bulk import get_default_file_extractor

    monkeypatch.setattr(settings, "DOC_PARSER_ENGINE", "anydoc")

    pdf_parser = get_default_file_extractor(pdf_text_fast_path=True)[".pdf"]

    assert type(pdf_parser).__name__ == "AnydocParser"


def test_fast_path_does_not_change_non_pdf_parsers(docling_engine):
    from application.parser.file.bulk import get_default_file_extractor

    plain = get_default_file_extractor()
    fast = get_default_file_extractor(pdf_text_fast_path=True)

    for suffix in (".docx", ".xlsx", ".csv", ".html"):
        assert type(fast[suffix]).__name__ == type(plain[suffix]).__name__
