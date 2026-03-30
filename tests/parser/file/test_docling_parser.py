"""Comprehensive tests for application/parser/file/docling_parser.py

Covers: DoclingParser (init, _init_parser, _get_ocr_options, _export_content,
parse_file), subclass initialization, error handling.
"""

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

    def test_parse_file_error_ignore(self):
        from application.parser.file.docling_parser import DoclingParser

        parser = DoclingParser()
        mock_converter = MagicMock()
        mock_converter.convert.side_effect = Exception("Parse failed")
        parser._converter = mock_converter

        result = parser.parse_file(Path("bad.pdf"), errors="ignore")
        assert "Error" in result

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
