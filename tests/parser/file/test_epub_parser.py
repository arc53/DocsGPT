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


def test_epub_parser_fast_ebook_import_error(epub_parser):
    """Test that ImportError is raised when fast-ebook is not available."""
    with patch.dict(sys.modules, {"fast_ebook": None}):
        with pytest.raises(ValueError, match="`fast-ebook` is required to read Epub files"):
            epub_parser.parse_file(Path("test.epub"))


def test_epub_parser_successful_parsing(epub_parser):
    """Test successful parsing of an epub file."""
    fake_fast_ebook = types.ModuleType("fast_ebook")
    fake_epub = types.ModuleType("fast_ebook.epub")
    fake_fast_ebook.epub = fake_epub

    mock_book = MagicMock()
    mock_book.to_markdown.return_value = "# Chapter 1\n\nContent 1\n\n# Chapter 2\n\nContent 2\n"

    fake_epub.read_epub = MagicMock(return_value=mock_book)

    with patch.dict(sys.modules, {
        "fast_ebook": fake_fast_ebook,
        "fast_ebook.epub": fake_epub,
    }):
        result = epub_parser.parse_file(Path("test.epub"))

    assert result == "# Chapter 1\n\nContent 1\n\n# Chapter 2\n\nContent 2\n"
    fake_epub.read_epub.assert_called_once_with(Path("test.epub"))


def test_epub_parser_empty_book(epub_parser):
    """Test parsing an epub file with no content."""
    fake_fast_ebook = types.ModuleType("fast_ebook")
    fake_epub = types.ModuleType("fast_ebook.epub")
    fake_fast_ebook.epub = fake_epub

    mock_book = MagicMock()
    mock_book.to_markdown.return_value = ""

    fake_epub.read_epub = MagicMock(return_value=mock_book)

    with patch.dict(sys.modules, {
        "fast_ebook": fake_fast_ebook,
        "fast_ebook.epub": fake_epub,
    }):
        result = epub_parser.parse_file(Path("empty.epub"))

    assert result == ""
