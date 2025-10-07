import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import types

from application.parser.file.epub_parser import EpubParser


@pytest.fixture
def epub_parser():
    return EpubParser()


def test_epub_init_parser():
    parser = EpubParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_epub_parser_ebooklib_import_error(epub_parser):
    """Test that ImportError is raised when ebooklib is not available."""
    with patch.dict(sys.modules, {"ebooklib": None}):
        with pytest.raises(ValueError, match="`EbookLib` is required to read Epub files"):
            epub_parser.parse_file(Path("test.epub"))


def test_epub_parser_html2text_import_error(epub_parser):
    """Test that ImportError is raised when html2text is not available."""
    fake_ebooklib = types.ModuleType("ebooklib")
    fake_epub = types.ModuleType("ebooklib.epub")
    fake_ebooklib.epub = fake_epub
    
    with patch.dict(sys.modules, {"ebooklib": fake_ebooklib, "ebooklib.epub": fake_epub}):
        with patch.dict(sys.modules, {"html2text": None}):
            with pytest.raises(ValueError, match="`html2text` is required to parse Epub files"):
                epub_parser.parse_file(Path("test.epub"))


def test_epub_parser_successful_parsing(epub_parser):
    """Test successful parsing of an epub file."""

    fake_ebooklib = types.ModuleType("ebooklib")
    fake_epub = types.ModuleType("ebooklib.epub")
    fake_html2text = types.ModuleType("html2text")
    
    # Mock ebooklib constants
    fake_ebooklib.ITEM_DOCUMENT = "document"
    fake_ebooklib.epub = fake_epub
    
    mock_item1 = MagicMock()
    mock_item1.get_type.return_value = "document"
    mock_item1.get_content.return_value = b"<h1>Chapter 1</h1><p>Content 1</p>"
    
    mock_item2 = MagicMock()
    mock_item2.get_type.return_value = "document"
    mock_item2.get_content.return_value = b"<h1>Chapter 2</h1><p>Content 2</p>"
    
    mock_item3 = MagicMock()
    mock_item3.get_type.return_value = "other"  # Should be ignored
    mock_item3.get_content.return_value = b"<p>Other content</p>"
    
    mock_book = MagicMock()
    mock_book.get_items.return_value = [mock_item1, mock_item2, mock_item3]
    
    fake_epub.read_epub = MagicMock(return_value=mock_book)
    
    def mock_html2text_func(html_content):
        if "Chapter 1" in html_content:
            return "# Chapter 1\n\nContent 1\n"
        elif "Chapter 2" in html_content:
            return "# Chapter 2\n\nContent 2\n"
        return "Other content\n"
    
    fake_html2text.html2text = mock_html2text_func
    
    with patch.dict(sys.modules, {
        "ebooklib": fake_ebooklib,
        "ebooklib.epub": fake_epub,
        "html2text": fake_html2text
    }):
        result = epub_parser.parse_file(Path("test.epub"))
    
    expected_result = "# Chapter 1\n\nContent 1\n\n# Chapter 2\n\nContent 2\n"
    assert result == expected_result
    
    # Verify epub.read_epub was called with correct parameters
    fake_epub.read_epub.assert_called_once_with(Path("test.epub"), options={"ignore_ncx": True})


def test_epub_parser_empty_book(epub_parser):
    """Test parsing an epub file with no document items."""
    # Create mock modules
    fake_ebooklib = types.ModuleType("ebooklib")
    fake_epub = types.ModuleType("ebooklib.epub")
    fake_html2text = types.ModuleType("html2text")
    
    fake_ebooklib.ITEM_DOCUMENT = "document"
    fake_ebooklib.epub = fake_epub
    
    # Create mock book with no document items
    mock_book = MagicMock()
    mock_book.get_items.return_value = []
    
    fake_epub.read_epub = MagicMock(return_value=mock_book)
    fake_html2text.html2text = MagicMock()
    
    with patch.dict(sys.modules, {
        "ebooklib": fake_ebooklib,
        "ebooklib.epub": fake_epub,
        "html2text": fake_html2text
    }):
        result = epub_parser.parse_file(Path("empty.epub"))
    assert result == ""

    fake_html2text.html2text.assert_not_called()


def test_epub_parser_non_document_items_ignored(epub_parser):
    """Test that non-document items are ignored during parsing."""
    fake_ebooklib = types.ModuleType("ebooklib")
    fake_epub = types.ModuleType("ebooklib.epub")
    fake_html2text = types.ModuleType("html2text")
    
    fake_ebooklib.ITEM_DOCUMENT = "document"
    fake_ebooklib.epub = fake_epub
    
    mock_doc_item = MagicMock()
    mock_doc_item.get_type.return_value = "document"
    mock_doc_item.get_content.return_value = b"<p>Document content</p>"
    
    mock_other_item = MagicMock()
    mock_other_item.get_type.return_value = "image"  # Not a document
    
    mock_book = MagicMock()
    mock_book.get_items.return_value = [mock_other_item, mock_doc_item]
    
    fake_epub.read_epub = MagicMock(return_value=mock_book)
    fake_html2text.html2text = MagicMock(return_value="Document content\n")
    
    with patch.dict(sys.modules, {
        "ebooklib": fake_ebooklib,
        "ebooklib.epub": fake_epub,
        "html2text": fake_html2text
    }):
        result = epub_parser.parse_file(Path("test.epub"))
    
    assert result == "Document content\n"
    
    fake_html2text.html2text.assert_called_once_with("<p>Document content</p>")
