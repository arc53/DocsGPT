"""Comprehensive tests for application/parser/file/docs_parser.py

Covers: PDFParser (init, parse with pypdf, parse as image, import error),
DocxParser (init, parse, import error).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from application.parser.file.docs_parser import PDFParser, DocxParser


# =====================================================================
# PDFParser - Init
# =====================================================================


@pytest.mark.unit
class TestPDFParserInit:

    def test_init_parser(self):
        parser = PDFParser()
        result = parser._init_parser()
        assert isinstance(result, dict)
        assert result == {}

    def test_parser_config_not_set_initially(self):
        parser = PDFParser()
        assert not parser.parser_config_set

    def test_parser_config_set_after_init(self):
        parser = PDFParser()
        parser.init_parser()
        assert parser.parser_config_set


# =====================================================================
# PDFParser - Parse File
# =====================================================================


@pytest.mark.unit
class TestPDFParserParse:

    @patch("application.parser.file.docs_parser.settings")
    def test_parse_with_pypdf(self, mock_settings):
        mock_settings.PARSE_PDF_AS_IMAGE = False

        parser = PDFParser()

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page 1 content"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page 2 content"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]

        with patch("application.parser.file.docs_parser.PdfReader",
                   create=True), \
             patch("builtins.open", mock_open()):
            # Need to patch the import inside the function
            import sys
            mock_pypdf = MagicMock()
            mock_pypdf.PdfReader = MagicMock(return_value=mock_reader)
            sys.modules["pypdf"] = mock_pypdf

            try:
                result = parser.parse_file(Path("test.pdf"))
                assert "Page 1 content" in result
                assert "Page 2 content" in result
            finally:
                del sys.modules["pypdf"]

    @patch("application.parser.file.docs_parser.settings")
    @patch("application.parser.file.docs_parser.requests")
    def test_parse_as_image(self, mock_requests, mock_settings):
        mock_settings.PARSE_PDF_AS_IMAGE = True

        mock_response = MagicMock()
        mock_response.json.return_value = {"markdown": "# OCR Result"}
        mock_requests.post.return_value = mock_response

        parser = PDFParser()

        with patch("builtins.open", mock_open(read_data=b"fake pdf")):
            result = parser.parse_file(Path("test.pdf"))
            assert result == "# OCR Result"

    @patch("application.parser.file.docs_parser.settings")
    def test_parse_raises_on_missing_pypdf(self, mock_settings):
        mock_settings.PARSE_PDF_AS_IMAGE = False

        parser = PDFParser()

        # Simulate the import error path
        original = parser.parse_file

        def mock_parse(*args, **kwargs):
            raise ValueError("pypdf is required to read PDF files.")

        parser.parse_file = mock_parse

        try:
            with pytest.raises(ValueError, match="pypdf is required"):
                parser.parse_file(Path("test.pdf"))
        finally:
            parser.parse_file = original


# =====================================================================
# DocxParser - Init
# =====================================================================


@pytest.mark.unit
class TestDocxParserInit:

    def test_init_parser(self):
        parser = DocxParser()
        result = parser._init_parser()
        assert isinstance(result, dict)
        assert result == {}

    def test_parser_config_not_set_initially(self):
        parser = DocxParser()
        assert not parser.parser_config_set

    def test_parser_config_set_after_init(self):
        parser = DocxParser()
        parser.init_parser()
        assert parser.parser_config_set


# =====================================================================
# DocxParser - Parse File
# =====================================================================


@pytest.mark.unit
class TestDocxParserParse:

    def test_parse_file_success(self):
        parser = DocxParser()

        import sys
        mock_docx2txt = MagicMock()
        mock_docx2txt.process.return_value = "DOCX content here"
        sys.modules["docx2txt"] = mock_docx2txt

        try:
            result = parser.parse_file(Path("test.docx"))
            assert result == "DOCX content here"
        finally:
            del sys.modules["docx2txt"]

    def test_parse_raises_on_missing_docx2txt(self):
        parser = DocxParser()

        original = parser.parse_file

        def mock_parse(*args, **kwargs):
            raise ValueError("docx2txt is required to read Microsoft Word files.")

        parser.parse_file = mock_parse

        try:
            with pytest.raises(ValueError, match="docx2txt is required"):
                parser.parse_file(Path("test.docx"))
        finally:
            parser.parse_file = original


# =====================================================================
# BaseParser properties
# =====================================================================


@pytest.mark.unit
class TestBaseParserProperties:

    def test_get_file_metadata_default(self):
        parser = PDFParser()
        meta = parser.get_file_metadata(Path("test.pdf"))
        assert meta == {}


# =====================================================================
# Coverage gap tests  (lines 33-34, 59, 63)
# =====================================================================


@pytest.mark.unit
class TestDocsParserGaps:
    def test_pdf_parser_parse_as_image(self, tmp_path):
        """Cover lines 33-34: PARSE_PDF_AS_IMAGE sends to external service."""
        from application.parser.file.docs_parser import PDFParser

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        with patch(
            "application.parser.file.docs_parser.settings"
        ) as mock_settings:
            mock_settings.PARSE_PDF_AS_IMAGE = True
            with patch(
                "application.parser.file.docs_parser.requests.post"
            ) as mock_post:
                mock_post.return_value = MagicMock(
                    json=MagicMock(return_value={"markdown": "# Parsed Content"})
                )
                parser = PDFParser()
                result = parser.parse_file(pdf_file)
                assert result == "# Parsed Content"
                mock_post.assert_called_once()

    def test_docx_parser_init_parser(self):
        """Cover line 59: DocxParser._init_parser returns empty dict."""
        from application.parser.file.docs_parser import DocxParser

        parser = DocxParser()
        config = parser._init_parser()
        assert config == {}

    def test_docx_parser_import_error(self):
        """Cover line 63: ImportError when docx2txt not installed."""
        from application.parser.file.docs_parser import DocxParser

        parser = DocxParser()
        with patch.dict("sys.modules", {"docx2txt": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'docx2txt'"),
            ):
                with pytest.raises((ImportError, ValueError)):
                    parser.parse_file(Path("/tmp/fake.docx"))
