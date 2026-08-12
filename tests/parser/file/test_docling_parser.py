"""Comprehensive tests for application/parser/file/docling_parser.py

Covers: DoclingParser (init, _init_parser, _get_ocr_options, _export_content,
parse_file), subclass initialization, error handling.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# =====================================================================
# DoclingParser - Init
# =====================================================================


@pytest.mark.unit
class TestDoclingParserInit:

    def test_default_init(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser()
        assert parser.ocr_enabled is True
        assert parser.table_structure is True
        assert parser.export_format == "markdown"
        assert parser.use_rapidocr is True
        assert parser.ocr_languages == ["english"]
        assert parser.force_full_page_ocr is False
        assert parser._converter is None

    def test_custom_init(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(
            ocr_enabled=False,
            table_structure=False,
            export_format="text",
            use_rapidocr=False,
            ocr_languages=["german"],
            force_full_page_ocr=True,
        )
        assert parser.ocr_enabled is False
        assert parser.table_structure is False
        assert parser.export_format == "text"
        assert parser.use_rapidocr is False
        assert parser.ocr_languages == ["german"]
        assert parser.force_full_page_ocr is True


# =====================================================================
# Init Parser
# =====================================================================


@pytest.mark.unit
class TestDoclingParserInitParser:

    def test_init_parser_raises_without_docling(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser()

        with patch("importlib.util.find_spec", return_value=None):
            with pytest.raises(ImportError, match="docling is required"):
                parser._init_parser()

    def test_init_parser_success(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser()

        mock_converter = MagicMock()
        with patch("importlib.util.find_spec", return_value=MagicMock()), \
             patch.object(parser, "_create_converter", return_value=mock_converter):
            result = parser._init_parser()

            assert isinstance(result, dict)
            assert result["ocr_enabled"] is True
            assert result["table_structure"] is True
            assert parser._converter is mock_converter


# =====================================================================
# Get OCR Options
# =====================================================================


@pytest.mark.unit
class TestGetOCROptions:

    def test_returns_none_when_rapidocr_disabled(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(use_rapidocr=False)
        assert parser._get_ocr_options() is None

    def test_returns_options_when_available(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(use_rapidocr=True, ocr_languages=["english"])

        mock_options = MagicMock()
        with patch(
            "application.parser.file.docling_parser.DoclingParser._get_ocr_options",
            return_value=mock_options,
        ):
            result = parser._get_ocr_options()
            assert result is mock_options

    def test_returns_none_on_import_error(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(use_rapidocr=True)

        # Simulate the ImportError path
        original = parser._get_ocr_options

        def patched_get_ocr():
            try:
                raise ImportError("No RapidOcrOptions")
            except ImportError:
                return None

        parser._get_ocr_options = patched_get_ocr
        assert parser._get_ocr_options() is None
        parser._get_ocr_options = original


# =====================================================================
# Export Content
# =====================================================================


@pytest.mark.unit
class TestExportContent:

    def test_export_markdown(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(export_format="markdown")
        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "# Title\n\nContent here"
        mock_doc.texts = []

        result = parser._export_content(mock_doc)
        assert "# Title" in result
        mock_doc.export_to_markdown.assert_called_once()

    def test_export_html(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(export_format="html")
        mock_doc = MagicMock()
        mock_doc.export_to_html.return_value = "<h1>Title</h1>"
        mock_doc.texts = []

        result = parser._export_content(mock_doc)
        assert "<h1>" in result

    def test_export_text(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(export_format="text")
        mock_doc = MagicMock()
        mock_doc.export_to_text.return_value = "Plain text content"
        mock_doc.texts = []

        result = parser._export_content(mock_doc)
        assert "Plain text" in result

    def test_fallback_to_texts_on_minimal_content(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(export_format="markdown")
        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "<!-- image -->"

        text1 = MagicMock()
        text1.text = "OCR extracted text 1"
        text2 = MagicMock()
        text2.text = "OCR extracted text 2"
        mock_doc.texts = [text1, text2]

        result = parser._export_content(mock_doc)
        assert "OCR extracted text 1" in result
        assert "OCR extracted text 2" in result

    def test_no_fallback_for_substantial_content(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(export_format="markdown")
        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "A" * 100
        mock_doc.texts = []

        result = parser._export_content(mock_doc)
        assert result == "A" * 100

    def test_fallback_skipped_when_no_texts(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(export_format="markdown")
        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "short"
        mock_doc.texts = []

        result = parser._export_content(mock_doc)
        assert result == "short"

    def test_fallback_skips_empty_texts(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(export_format="markdown")
        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = ""

        empty_text = MagicMock()
        empty_text.text = ""
        mock_doc.texts = [empty_text]

        result = parser._export_content(mock_doc)
        assert result == ""


# =====================================================================
# Parse File
# =====================================================================


@pytest.mark.unit
class TestDoclingParserParseFile:

    def test_parse_file_success(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser()

        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "Parsed document content"
        mock_doc.texts = []
        mock_result.document = mock_doc
        mock_converter.convert.return_value = mock_result
        parser._converter = mock_converter

        result = parser.parse_file(Path("test.pdf"))
        assert "Parsed document content" in result

    def test_parse_file_inits_converter_on_first_call(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser()
        parser._converter = None

        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "content"
        mock_doc.texts = []
        mock_result.document = mock_doc
        mock_converter.convert.return_value = mock_result

        with patch.object(parser, "_init_parser") as mock_init:
            parser._converter = mock_converter
            mock_init.return_value = {}
            result = parser.parse_file(Path("test.pdf"))
            assert "content" in result

    def test_parse_file_error_ignore_raises_instead_of_returning_error_text(self):
        """A failed conversion must never become the document's text.

        Regression: ``errors="ignore"`` used to return
        ``"[Error parsing file with docling: ...]"``, which the attachment
        worker then stored as ``attachments.content`` and handed to the LLM
        as if it were the PDF. ``errors`` controls *decoding* leniency, not
        "substitute the traceback for the document".
        """
        from application.parser.file.base_parser import DocumentParseError
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser()
        mock_converter = MagicMock()
        mock_converter.convert.side_effect = Exception("Parse failed")
        parser._converter = mock_converter

        with pytest.raises(DocumentParseError) as excinfo:
            parser.parse_file(Path("bad.pdf"), errors="ignore")

        # The message identifies the file and preserves the cause for triage…
        assert "bad.pdf" in str(excinfo.value)
        assert "Parse failed" in str(excinfo.value)
        # …and the original exception is chained, not swallowed.
        assert isinstance(excinfo.value.__cause__, Exception)
        assert "Parse failed" in str(excinfo.value.__cause__)

    def test_parse_file_error_ignore_never_returns_a_string(self):
        """Belt-and-braces: no code path may hand back error text as content."""
        from application.parser.file.base_parser import DocumentParseError
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser()
        mock_converter = MagicMock()
        mock_converter.convert.side_effect = RuntimeError(
            "Conversion failed for: x.pdf with status: failure. Errors: "
            "InvalidCxxCompiler: No working C++ compiler found"
        )
        parser._converter = mock_converter

        try:
            result = parser.parse_file(Path("x.pdf"), errors="ignore")
        except DocumentParseError:
            return  # expected
        pytest.fail(
            f"parse_file returned {result!r} instead of raising; error text "
            "must not be usable as document content"
        )

    def test_parse_file_error_raise(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser()
        mock_converter = MagicMock()
        mock_converter.convert.side_effect = Exception("Parse failed")
        parser._converter = mock_converter

        with pytest.raises(Exception, match="Parse failed"):
            parser.parse_file(Path("bad.pdf"), errors="strict")


# =====================================================================
# Subclass Init
# =====================================================================


@pytest.mark.unit
class TestDoclingSubclasses:

    def test_pdf_parser_init(self):
        from application.parser.file.docling_parser import DoclingPDFParser

        parser = DoclingPDFParser()
        assert parser.ocr_enabled is True
        assert parser.export_format == "markdown"

    def test_pdf_parser_custom_ocr(self):
        from application.parser.file.docling_parser import DoclingPDFParser

        parser = DoclingPDFParser(ocr_enabled=False, force_full_page_ocr=True)
        assert parser.ocr_enabled is False
        assert parser.force_full_page_ocr is True

    def test_docx_parser_init(self):
        from application.parser.file.docling_parser import DoclingDocxParser

        parser = DoclingDocxParser()
        assert parser.export_format == "markdown"

    def test_pptx_parser_init(self):
        from application.parser.file.docling_parser import DoclingPPTXParser

        parser = DoclingPPTXParser()
        assert parser.export_format == "markdown"

    def test_xlsx_parser_init(self):
        from application.parser.file.docling_parser import DoclingXLSXParser

        parser = DoclingXLSXParser()
        assert parser.table_structure is True

    def test_html_parser_init(self):
        from application.parser.file.docling_parser import DoclingHTMLParser

        parser = DoclingHTMLParser()
        assert parser.export_format == "markdown"

    def test_image_parser_init(self):
        from application.parser.file.docling_parser import DoclingImageParser

        parser = DoclingImageParser()
        assert parser.ocr_enabled is True
        assert parser.force_full_page_ocr is True

    def test_image_parser_custom(self):
        from application.parser.file.docling_parser import DoclingImageParser

        parser = DoclingImageParser(ocr_enabled=False)
        assert parser.ocr_enabled is False

    def test_csv_parser_init(self):
        from application.parser.file.docling_parser import DoclingCSVParser

        parser = DoclingCSVParser()
        assert parser.table_structure is True

    def test_markdown_parser_init(self):
        from application.parser.file.docling_parser import DoclingMarkdownParser

        parser = DoclingMarkdownParser()
        assert parser.export_format == "markdown"

    def test_asciidoc_parser_init(self):
        from application.parser.file.docling_parser import DoclingAsciiDocParser

        parser = DoclingAsciiDocParser()
        assert parser.export_format == "markdown"

    def test_vtt_parser_init(self):
        from application.parser.file.docling_parser import DoclingVTTParser

        parser = DoclingVTTParser()
        assert parser.export_format == "markdown"

    def test_xml_parser_init(self):
        from application.parser.file.docling_parser import DoclingXMLParser

        parser = DoclingXMLParser()
        assert parser.export_format == "markdown"


# =====================================================================
# Coverage gap tests  (lines 148-153, 289)
# =====================================================================


@pytest.mark.unit
class TestDoclingParserGaps:
    def test_get_ocr_options_import_error_returns_none(self):
        """Cover lines 148-150: ImportError returns None."""
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(ocr_enabled=True, use_rapidocr=True)
        with patch.dict("sys.modules", {"docling.datamodel.pipeline_options": None}):
            # Force re-import to trigger ImportError
            with patch(
                "builtins.__import__", side_effect=ImportError("no module")
            ):
                result = parser._get_ocr_options()
                assert result is None

    def test_get_ocr_options_generic_error_returns_none(self):
        """Cover lines 151-153: generic Exception returns None."""
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser(ocr_enabled=True, use_rapidocr=True)
        with patch(
            "builtins.__import__",
            side_effect=RuntimeError("unexpected"),
        ):
            result = parser._get_ocr_options()
            assert result is None

    def test_csv_parser_init(self):
        """Cover line 289: DoclingCSVParser.__init__ calls super."""
        from application.parser.file.docling_parser import DoclingCSVParser

        parser = DoclingCSVParser()
        assert parser.export_format == "markdown"
        assert parser.ocr_enabled is True


# =====================================================================
# Pipeline memory caps
# =====================================================================


@pytest.mark.unit
class TestApplyPipelineCaps:
    """_apply_pipeline_caps bounds docling's threaded-pipeline buffering."""

    def test_caps_threaded_pipeline_knobs(self, monkeypatch):
        from application.core.settings import settings
        from application.parser.file.docling_parser import _apply_pipeline_caps

        monkeypatch.setattr(
            settings, "DOCLING_PIPELINE_QUEUE_MAX_SIZE", 2, raising=False
        )

        class Opts:
            # docling >= 2.94 threaded pipeline — all knobs present.
            queue_max_size = 100
            layout_batch_size = 4
            table_batch_size = 4
            ocr_batch_size = 4

        opts = Opts()
        _apply_pipeline_caps(opts)

        assert opts.queue_max_size == 2
        assert opts.layout_batch_size == 1
        assert opts.table_batch_size == 1
        assert opts.ocr_batch_size == 1

    def test_queue_size_is_settings_driven(self, monkeypatch):
        from application.core.settings import settings
        from application.parser.file.docling_parser import _apply_pipeline_caps

        monkeypatch.setattr(
            settings, "DOCLING_PIPELINE_QUEUE_MAX_SIZE", 6, raising=False
        )

        class Opts:
            queue_max_size = 100

        opts = Opts()
        _apply_pipeline_caps(opts)
        assert opts.queue_max_size == 6

    def test_misconfigured_zero_floors_to_one(self, monkeypatch):
        """A 0 queue depth could deadlock the threaded pipeline — floor it."""
        from application.core.settings import settings
        from application.parser.file.docling_parser import _apply_pipeline_caps

        monkeypatch.setattr(
            settings, "DOCLING_PIPELINE_QUEUE_MAX_SIZE", 0, raising=False
        )

        class Opts:
            queue_max_size = 100

        opts = Opts()
        _apply_pipeline_caps(opts)
        assert opts.queue_max_size == 1

    def test_noop_on_docling_without_threaded_pipeline(self):
        """Builds predating the threaded pipeline lack the knobs — the cap
        must be a silent no-op, not an AttributeError."""
        from application.parser.file.docling_parser import _apply_pipeline_caps

        class LegacyOpts:
            __slots__ = ("do_ocr", "do_table_structure")

            def __init__(self):
                self.do_ocr = False
                self.do_table_structure = True

        opts = LegacyOpts()
        _apply_pipeline_caps(opts)  # must not raise

        assert not hasattr(opts, "queue_max_size")
        assert not hasattr(opts, "layout_batch_size")


# =====================================================================
# Tabular size gate (CSV / XLSX)
# =====================================================================


@pytest.mark.unit
class TestDoclingTabularSizeGate:
    """Oversized tabular files must bypass docling.

    Docling materializes a ``TableCell`` object per cell (measured ~11 KB of
    RSS per 4-cell CSV row), so a multi-MB CSV balloons the worker by tens of
    GB. Above ``DOCLING_TABULAR_MAX_BYTES`` the docling tabular parsers must
    delegate to the lightweight parsers in ``tabular_parser``.
    """

    def _write_csv(self, tmp_path: Path, rows: int = 50) -> Path:
        path = tmp_path / "data.csv"
        path.write_text("\n".join(f"{i},{i * 2}" for i in range(rows)) + "\n")
        return path

    def test_oversized_csv_delegates_to_plain_csv_parser(self, tmp_path, monkeypatch):
        from application.core.settings import settings
        from application.parser.file.docling_parser import DoclingCSVParser, DoclingParser

        monkeypatch.setattr(settings, "DOCLING_TABULAR_MAX_BYTES", 64)
        docling_parse = MagicMock(name="docling_parse")
        monkeypatch.setattr(DoclingParser, "parse_file", docling_parse)

        path = self._write_csv(tmp_path)
        assert path.stat().st_size > 64

        out = DoclingCSVParser().parse_file(path)

        docling_parse.assert_not_called()
        # Plain ``CSVParser`` output: rows joined with ", ", newline-separated.
        assert out.startswith("0, 0\n1, 2\n")

    def test_small_csv_still_uses_docling(self, tmp_path, monkeypatch):
        from application.core.settings import settings
        from application.parser.file.docling_parser import DoclingCSVParser, DoclingParser

        monkeypatch.setattr(settings, "DOCLING_TABULAR_MAX_BYTES", 10_000_000)
        docling_parse = MagicMock(name="docling_parse", return_value="DOCLING")
        monkeypatch.setattr(DoclingParser, "parse_file", docling_parse)

        out = DoclingCSVParser().parse_file(self._write_csv(tmp_path))

        assert out == "DOCLING"
        docling_parse.assert_called_once()

    def test_gate_disabled_when_max_bytes_is_zero(self, tmp_path, monkeypatch):
        from application.core.settings import settings
        from application.parser.file.docling_parser import DoclingCSVParser, DoclingParser

        monkeypatch.setattr(settings, "DOCLING_TABULAR_MAX_BYTES", 0)
        docling_parse = MagicMock(name="docling_parse", return_value="DOCLING")
        monkeypatch.setattr(DoclingParser, "parse_file", docling_parse)

        out = DoclingCSVParser().parse_file(self._write_csv(tmp_path, rows=5000))

        assert out == "DOCLING"
        docling_parse.assert_called_once()

    def test_oversized_xlsx_delegates_to_excel_parser(self, tmp_path, monkeypatch):
        from application.core.settings import settings
        from application.parser.file.docling_parser import DoclingParser, DoclingXLSXParser
        from application.parser.file.tabular_parser import ExcelParser

        monkeypatch.setattr(settings, "DOCLING_TABULAR_MAX_BYTES", 64)
        docling_parse = MagicMock(name="docling_parse")
        monkeypatch.setattr(DoclingParser, "parse_file", docling_parse)
        excel_parse = MagicMock(name="excel_parse", return_value="PLAIN-XLSX")
        monkeypatch.setattr(ExcelParser, "parse_file", excel_parse)

        path = tmp_path / "big.xlsx"
        path.write_bytes(b"x" * 200)

        out = DoclingXLSXParser().parse_file(path)

        assert out == "PLAIN-XLSX"
        docling_parse.assert_not_called()
        excel_parse.assert_called_once()

    def test_small_xlsx_still_uses_docling(self, tmp_path, monkeypatch):
        from application.core.settings import settings
        from application.parser.file.docling_parser import DoclingParser, DoclingXLSXParser

        monkeypatch.setattr(settings, "DOCLING_TABULAR_MAX_BYTES", 10_000_000)
        docling_parse = MagicMock(name="docling_parse", return_value="DOCLING")
        monkeypatch.setattr(DoclingParser, "parse_file", docling_parse)

        path = tmp_path / "small.xlsx"
        path.write_bytes(b"x" * 200)

        assert DoclingXLSXParser().parse_file(path) == "DOCLING"
        docling_parse.assert_called_once()


# =====================================================================
# Tabular content-size gate — XLSX compression must not defeat it
# =====================================================================


def _make_xlsx(path: Path, rows: int) -> None:
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    for i in range(rows):
        ws.append([i, i * 2, i % 7, i % 13, i * 3])
    wb.save(str(path))


@pytest.mark.unit
class TestTabularContentSize:
    """XLSX is zip-compressed, so the gate must measure inner-uncompressed
    size, not on-disk bytes — otherwise a small-on-disk / many-cell xlsx
    (2.44 GB in docling) slips under a byte gate."""

    def test_xlsx_content_size_is_inner_not_ondisk(self, tmp_path):
        from application.parser.file.docling_parser import _tabular_content_size

        path = tmp_path / "data.xlsx"
        _make_xlsx(path, rows=5000)
        on_disk = path.stat().st_size
        inner = _tabular_content_size(path)
        # Repetitive numeric data compresses hard: inner XML >> zip on disk.
        assert inner > on_disk

    def test_csv_content_size_is_ondisk(self, tmp_path):
        from application.parser.file.docling_parser import _tabular_content_size

        path = tmp_path / "data.csv"
        path.write_text("a,b\n1,2\n3,4\n")
        assert _tabular_content_size(path) == path.stat().st_size

    def test_compressed_xlsx_over_inner_gate_delegates(self, tmp_path, monkeypatch):
        """The regression: on-disk < threshold < inner-uncompressed must gate."""
        from application.core.settings import settings
        from application.parser.file.docling_parser import (
            DoclingParser,
            DoclingXLSXParser,
            _tabular_content_size,
        )
        from application.parser.file.tabular_parser import ExcelParser

        path = tmp_path / "wide.xlsx"
        _make_xlsx(path, rows=5000)
        on_disk = path.stat().st_size
        inner = _tabular_content_size(path)
        assert inner > on_disk, "premise: compression hides cell count"

        # A byte gate between the two would have sent this to docling; the
        # inner-size gate must catch it.
        monkeypatch.setattr(
            settings, "DOCLING_TABULAR_MAX_BYTES", (on_disk + inner) // 2
        )
        docling_parse = MagicMock(name="docling_parse")
        monkeypatch.setattr(DoclingParser, "parse_file", docling_parse)
        excel_parse = MagicMock(name="excel_parse", return_value="PLAIN")
        monkeypatch.setattr(ExcelParser, "parse_file", excel_parse)

        out = DoclingXLSXParser().parse_file(path)

        assert out == "PLAIN"
        docling_parse.assert_not_called()
        excel_parse.assert_called_once()


# =====================================================================
# Markup gate (HTML / VTT) — truncate oversized element-dense markup
# =====================================================================


@pytest.mark.unit
class TestDoclingMarkupGate:
    def _write(self, tmp_path: Path, name: str, nbytes: int) -> Path:
        path = tmp_path / name
        # newline-terminated lines so the line-boundary trim has something to cut
        path.write_text(("x" * 63 + "\n") * (nbytes // 64 + 1))
        return path

    @pytest.mark.parametrize("name", ["big.html", "big.vtt"])
    def test_oversized_markup_parses_truncated_copy(self, tmp_path, monkeypatch, name):
        from application.core.settings import settings
        from application.parser.file import docling_parser as dp

        monkeypatch.setattr(settings, "DOCLING_MARKUP_MAX_BYTES", 512)
        path = self._write(tmp_path, name, 4096)
        assert path.stat().st_size > 512

        seen = {}

        def fake_parse(self_parser, file, errors="ignore"):
            p = str(file)
            seen["path"] = p
            seen["size"] = os.path.getsize(p)
            return "PARSED"

        monkeypatch.setattr(dp.DoclingParser, "parse_file", fake_parse)

        cls = dp.DoclingHTMLParser if name.endswith(".html") else dp.DoclingVTTParser
        out = cls().parse_file(path)

        assert out == "PARSED"
        assert seen["path"] != str(path), "must parse a temp copy, not the original"
        assert seen["size"] <= 512, "temp copy must be truncated to the cap"
        assert not os.path.exists(seen["path"]), "temp copy must be cleaned up"
        assert path.stat().st_size > 512, "original must be untouched"

    def test_small_markup_parses_original(self, tmp_path, monkeypatch):
        from application.core.settings import settings
        from application.parser.file import docling_parser as dp

        monkeypatch.setattr(settings, "DOCLING_MARKUP_MAX_BYTES", 10_000_000)
        path = self._write(tmp_path, "small.html", 1024)
        seen = {}

        def fake_parse(self_parser, file, errors="ignore"):
            seen["path"] = str(file)
            return "PARSED"

        monkeypatch.setattr(dp.DoclingParser, "parse_file", fake_parse)
        out = dp.DoclingHTMLParser().parse_file(path)

        assert out == "PARSED"
        assert seen["path"] == str(path)

    def test_markup_gate_disabled_when_zero(self, tmp_path, monkeypatch):
        from application.core.settings import settings
        from application.parser.file import docling_parser as dp

        monkeypatch.setattr(settings, "DOCLING_MARKUP_MAX_BYTES", 0)
        path = self._write(tmp_path, "big.vtt", 8192)
        seen = {}

        def fake_parse(self_parser, file, errors="ignore"):
            seen["path"] = str(file)
            return "PARSED"

        monkeypatch.setattr(dp.DoclingParser, "parse_file", fake_parse)
        dp.DoclingVTTParser().parse_file(path)

        assert seen["path"] == str(path), "disabled gate must parse the original"


# =====================================================================
# Gate seam: the oversized path through the REAL lightweight parser
# =====================================================================


@pytest.mark.unit
class TestTabularGateSeam:
    """Exercise the gate and the lightweight parser together.

    Every test in ``TestDoclingTabularSizeGate`` monkeypatches
    ``ExcelParser.parse_file`` away, so the seam between the size gate and
    the real fallback had zero coverage — which is how a crash on blank
    cells reached production and silently destroyed an upload.
    """

    def _write_xlsx_with_hole(self, path: Path) -> Path:
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([f"col{i}" for i in range(14)])
        ws.append(list(range(14)))
        holed = list(range(14))
        holed[11] = None
        ws.append(holed)
        wb.save(path)
        return path

    def test_oversized_xlsx_with_blank_cells_parses_end_to_end(
        self, tmp_path, monkeypatch
    ):
        """The real incident, end to end: gate trips, blanks do not crash."""
        from application.core.settings import settings
        from application.parser.file.docling_parser import (
            DoclingParser,
            DoclingXLSXParser,
        )

        monkeypatch.setattr(settings, "DOCLING_TABULAR_MAX_BYTES", 64)
        docling_parse = MagicMock(name="docling_parse")
        monkeypatch.setattr(DoclingParser, "parse_file", docling_parse)

        path = self._write_xlsx_with_hole(tmp_path / "focus.xlsx")

        out = DoclingXLSXParser().parse_file(path)

        docling_parse.assert_not_called()
        assert isinstance(out, str) and out
        assert "nan" not in out

    def test_lightweight_failure_becomes_document_parse_error(
        self, tmp_path, monkeypatch
    ):
        """A fallback crash must be non-retryable and batch-skippable.

        ``DocumentParseError`` is listed in ``dont_autoretry_for`` on both
        ``ingest`` and ``store_attachment``, and is the only exception
        ``SimpleDirectoryReader.load_data`` skips rather than propagating.
        """
        from application.core.settings import settings
        from application.parser.file.base_parser import DocumentParseError
        from application.parser.file.docling_parser import (
            DoclingParser,
            DoclingXLSXParser,
        )
        from application.parser.file.tabular_parser import ExcelParser

        monkeypatch.setattr(settings, "DOCLING_TABULAR_MAX_BYTES", 64)
        monkeypatch.setattr(DoclingParser, "parse_file", MagicMock())
        monkeypatch.setattr(
            ExcelParser,
            "parse_file",
            MagicMock(side_effect=TypeError("sequence item 11")),
        )

        path = self._write_xlsx_with_hole(tmp_path / "boom.xlsx")

        with pytest.raises(DocumentParseError):
            DoclingXLSXParser().parse_file(path)

    def test_oversized_csv_failure_becomes_document_parse_error(
        self, tmp_path, monkeypatch
    ):
        from application.core.settings import settings
        from application.parser.file.base_parser import DocumentParseError
        from application.parser.file.docling_parser import (
            DoclingCSVParser,
            DoclingParser,
        )
        from application.parser.file.tabular_parser import CSVParser

        monkeypatch.setattr(settings, "DOCLING_TABULAR_MAX_BYTES", 8)
        monkeypatch.setattr(DoclingParser, "parse_file", MagicMock())
        monkeypatch.setattr(
            CSVParser, "parse_file", MagicMock(side_effect=ValueError("bad"))
        )

        path = tmp_path / "data.csv"
        path.write_text("a,b\n1,2\n" * 20)

        with pytest.raises(DocumentParseError):
            DoclingCSVParser().parse_file(path)


# =====================================================================
# torch.compile inference setting
# =====================================================================


@pytest.mark.unit
class TestApplyInferenceSettings:
    """_apply_inference_settings governs docling's torch.compile of its models.

    docling >= 2.92 compiles its layout/OCR models with torch.compile by
    default, which hard-fails TorchInductor's Metal codegen on Apple Silicon
    and buys nothing for one-shot parses.
    """

    def test_disables_torch_compile_by_default(self, monkeypatch):
        from application.parser.file.docling_parser import _apply_inference_settings

        class Inference:
            compile_torch_models = True

        class DoclingSettings:
            inference = Inference()

        docling_settings = DoclingSettings()
        monkeypatch.setattr(
            "docling.datamodel.settings.settings", docling_settings, raising=False
        )

        _apply_inference_settings()

        assert docling_settings.inference.compile_torch_models is False

    def test_opt_in_reenables_torch_compile(self, monkeypatch):
        from application.core.settings import settings
        from application.parser.file.docling_parser import _apply_inference_settings

        monkeypatch.setattr(
            settings, "DOCLING_COMPILE_TORCH_MODELS", True, raising=False
        )

        class Inference:
            compile_torch_models = False

        class DoclingSettings:
            inference = Inference()

        docling_settings = DoclingSettings()
        monkeypatch.setattr(
            "docling.datamodel.settings.settings", docling_settings, raising=False
        )

        _apply_inference_settings()

        assert docling_settings.inference.compile_torch_models is True

    def test_noop_on_docling_without_inference_settings(self, monkeypatch):
        """Builds predating the inference settings must be a silent no-op."""
        from application.parser.file.docling_parser import _apply_inference_settings

        class DoclingSettings:
            pass

        monkeypatch.setattr(
            "docling.datamodel.settings.settings", DoclingSettings(), raising=False
        )

        _apply_inference_settings()  # must not raise

    def test_create_converter_applies_inference_settings(self, monkeypatch):
        """The cap is worthless unless the converter path actually calls it."""
        from application.parser.file.docling_parser import DoclingParser

        called = []
        monkeypatch.setattr(
            "application.parser.file.docling_parser._apply_inference_settings",
            lambda: called.append(True),
        )
        monkeypatch.setattr(
            "docling.document_converter.DocumentConverter",
            MagicMock(),
        )

        DoclingParser(ocr_enabled=False)._create_converter()

        assert called == [True]

    def test_inference_settings_applied_before_options_are_built(self, monkeypatch):
        """Ordering is load-bearing, not incidental.

        ``compile_model`` is a ``default_factory`` that reads docling's global
        at *option construction* time, so flipping the global after building
        ``PdfPipelineOptions`` is silently ignored. Pin the order.
        """
        import docling.datamodel.pipeline_options as dpo

        from application.parser.file.docling_parser import DoclingParser

        events = []
        monkeypatch.setattr(
            "application.parser.file.docling_parser._apply_inference_settings",
            lambda: events.append("settings"),
        )

        real_options = dpo.PdfPipelineOptions

        def _tracking_options(*args, **kwargs):
            events.append("options")
            return real_options(*args, **kwargs)

        monkeypatch.setattr(dpo, "PdfPipelineOptions", _tracking_options)
        monkeypatch.setattr("docling.document_converter.DocumentConverter", MagicMock())

        DoclingParser(ocr_enabled=False)._create_converter()

        assert events == ["settings", "options"], (
            "torch.compile must be disabled before PdfPipelineOptions is "
            f"constructed, got {events}"
        )
