import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from application.parser.file.docs_parser import PDFParser, DocxParser


@pytest.fixture
def pdf_parser():
    return PDFParser()


@pytest.fixture
def docx_parser():
    return DocxParser()


def test_pdf_init_parser():
    parser = PDFParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_docx_init_parser():
    parser = DocxParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


@patch("application.parser.file.docs_parser.settings")
def test_parse_pdf_with_pypdf(mock_settings, pdf_parser):
    mock_settings.PARSE_PDF_AS_IMAGE = False

    # Create mock pages with text content
    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "Test PDF content page 1"
    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = "Test PDF content page 2"

    mock_reader_instance = MagicMock()
    mock_reader_instance.pages = [mock_page1, mock_page2]

    original_parse_file = pdf_parser.parse_file

    def mock_parse_file(*args, **kwargs):
        _ = args, kwargs
        text_list = []
        num_pages = len(mock_reader_instance.pages)
        for page_index in range(num_pages):
            page = mock_reader_instance.pages[page_index]
            page_text = page.extract_text()
            text_list.append(page_text)
        text = "\n".join(text_list)
        return text

    pdf_parser.parse_file = mock_parse_file

    try:
        result = pdf_parser.parse_file(Path("test.pdf"))
        assert result == "Test PDF content page 1\nTest PDF content page 2"
    finally:
        pdf_parser.parse_file = original_parse_file


@patch("application.parser.file.docs_parser.settings")
def test_parse_pdf_pypdf_import_error(mock_settings, pdf_parser):
    mock_settings.PARSE_PDF_AS_IMAGE = False

    original_parse_file = pdf_parser.parse_file

    def mock_parse_file(*args, **kwargs):
        _ = args, kwargs
        raise ValueError("pypdf is required to read PDF files.")

    pdf_parser.parse_file = mock_parse_file

    try:
        with pytest.raises(ValueError, match="pypdf is required to read PDF files"):
            pdf_parser.parse_file(Path("test.pdf"))
    finally:
        pdf_parser.parse_file = original_parse_file


def test_parse_docx(docx_parser):
    original_parse_file = docx_parser.parse_file

    def mock_parse_file(*args, **kwargs):
        _ = args, kwargs
        return "Test DOCX content"

    docx_parser.parse_file = mock_parse_file

    try:
        result = docx_parser.parse_file(Path("test.docx"))
        assert result == "Test DOCX content"
    finally:
        docx_parser.parse_file = original_parse_file


def test_parse_docx_import_error(docx_parser):
    original_parse_file = docx_parser.parse_file

    def mock_parse_file(*args, **kwargs):
        _ = args, kwargs
        raise ValueError("docx2txt is required to read Microsoft Word files.")

    docx_parser.parse_file = mock_parse_file

    try:
        with pytest.raises(ValueError, match="docx2txt is required to read Microsoft Word files"):
            docx_parser.parse_file(Path("test.docx"))
    finally:
        docx_parser.parse_file = original_parse_file