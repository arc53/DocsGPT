import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

from application.parser.file.rst_parser import RstParser


@pytest.fixture
def rst_parser():
    return RstParser()


@pytest.fixture
def rst_parser_custom():
    return RstParser(
        remove_hyperlinks=False,
        remove_images=False,
        remove_table_excess=False,
        remove_interpreters=False,
        remove_directives=False,
        remove_whitespaces_excess=False,
        remove_characters_excess=False
    )


def test_rst_init_parser():
    parser = RstParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_rst_parser_initialization_with_custom_options():
    """Test RstParser initialization with custom options."""
    parser = RstParser(
        remove_hyperlinks=False,
        remove_images=False,
        remove_table_excess=False,
        remove_interpreters=False,
        remove_directives=False,
        remove_whitespaces_excess=False,
        remove_characters_excess=False
    )
    
    assert not parser._remove_hyperlinks
    assert not parser._remove_images
    assert not parser._remove_table_excess
    assert not parser._remove_interpreters
    assert not parser._remove_directives
    assert not parser._remove_whitespaces_excess
    assert not parser._remove_characters_excess


def test_rst_parser_default_initialization():
    """Test RstParser initialization with default options."""
    parser = RstParser()
    
    assert parser._remove_hyperlinks
    assert parser._remove_images
    assert parser._remove_table_excess
    assert parser._remove_interpreters
    assert parser._remove_directives
    assert parser._remove_whitespaces_excess
    assert parser._remove_characters_excess


def test_remove_hyperlinks():
    """Test hyperlink removal functionality."""
    parser = RstParser()
    content = "This is a `link text <http://example.com>`_ and more text."
    result = parser.remove_hyperlinks(content)
    assert result == "This is a link text and more text."


def test_remove_images():
    """Test image removal functionality."""
    parser = RstParser()
    content = "Some text\n.. image:: path/to/image.png\nMore text"
    result = parser.remove_images(content)
    assert result == "Some text\n\nMore text"


def test_remove_directives():
    """Test directive removal functionality."""
    parser = RstParser()
    content = "Text with `..note::` directive and more text"
    result = parser.remove_directives(content)
    # The regex pattern looks for `..something::` so it should remove `..note::`
    assert result == "Text with ` directive and more text"


def test_remove_interpreters():
    """Test interpreter removal functionality."""
    parser = RstParser()
    content = "Text with :doc: role and :ref: another role"
    result = parser.remove_interpreters(content)
    assert result == "Text with  role and  another role"


def test_remove_table_excess():
    """Test table separator removal functionality."""
    parser = RstParser()
    content = "Header\n+-----+-----+\n| A   | B   |\n+-----+-----+\nFooter"
    result = parser.remove_table_excess(content)
    assert "+-----+-----+" not in result
    assert "Header" in result
    assert "| A   | B   |" in result
    assert "Footer" in result


def test_chunk_by_token_count():
    """Test token-based chunking functionality."""
    parser = RstParser()
    text = "This is a long text that should be chunked into smaller pieces based on token count"
    chunks = parser.chunk_by_token_count(text, max_tokens=5)
    
    # Should create multiple chunks
    assert len(chunks) > 1
    
    # Each chunk should be reasonably sized (approximately 5 * 5 = 25 characters)
    for chunk in chunks:
        assert len(chunk) <= 30  # Allow some flexibility


def test_rst_to_tups_with_headers():
    """Test RST to tuples conversion with headers."""
    parser = RstParser()
    rst_content = """Introduction
============

This is the introduction text.

Chapter 1
=========

This is chapter 1 content.
More content here.

Chapter 2
=========

This is chapter 2 content."""
    
    tups = parser.rst_to_tups(rst_content)
    
    # Should have 3 tuples (intro, chapter 1, chapter 2)
    assert len(tups) >= 2
    
    # Check that headers are captured
    headers = [tup[0] for tup in tups if tup[0] is not None]
    assert "Introduction" in headers
    assert "Chapter 1" in headers
    assert "Chapter 2" in headers


def test_rst_to_tups_without_headers():
    """Test RST to tuples conversion without headers."""
    parser = RstParser()
    rst_content = "Just plain text without any headers or structure."
    
    tups = parser.rst_to_tups(rst_content)
    
    # Should have one tuple with None header
    assert len(tups) == 1
    assert tups[0][0] is None
    assert "Just plain text" in tups[0][1]


def test_parse_file_basic(rst_parser):
    """Test basic parse_file functionality."""
    content = """Title
=====

This is some content.

Subtitle
--------

More content here."""
    
    with patch("builtins.open", mock_open(read_data=content)):
        result = rst_parser.parse_file(Path("test.rst"))
    
    # Should return a list of strings
    assert isinstance(result, list)
    assert len(result) >= 1
    
    # Content should be processed and cleaned
    joined_result = "\n".join(result)
    assert "Title" in joined_result
    assert "content" in joined_result


def test_parse_file_with_hyperlinks(rst_parser_custom):
    """Test parse_file with hyperlinks when removal is disabled."""
    content = "Text with `link <http://example.com>`_ here."
    
    with patch("builtins.open", mock_open(read_data=content)):
        result = rst_parser_custom.parse_file(Path("test.rst"))
    
    joined_result = "\n".join(result)
    # Hyperlinks should be preserved when removal is disabled
    assert "http://example.com" in joined_result


def test_parse_tups_with_max_tokens():
    """Test parse_tups with token chunking."""
    parser = RstParser()
    content = """Header
======

This is a very long piece of content that should be chunked into smaller pieces when max_tokens is specified. It contains multiple sentences and should be split appropriately."""
    
    with patch("builtins.open", mock_open(read_data=content)):
        tups = parser.parse_tups(Path("test.rst"), max_tokens=10)
    
    # Should create multiple chunks due to token limit
    assert len(tups) > 1
    
    # Each tuple should have a header indicating chunk number
    chunk_headers = [tup[0] for tup in tups]
    assert any("Chunk" in str(header) for header in chunk_headers if header)


def test_parse_tups_without_max_tokens():
    """Test parse_tups without token chunking."""
    parser = RstParser()
    content = """Header
======

Content here."""
    
    with patch("builtins.open", mock_open(read_data=content)):
        tups = parser.parse_tups(Path("test.rst"), max_tokens=None)
    
    # Should not create additional chunks
    assert len(tups) >= 1
    
    # Headers should not contain "Chunk"
    chunk_headers = [tup[0] for tup in tups]
    assert not any("Chunk" in str(header) for header in chunk_headers if header)


def test_parse_file_empty_content():
    """Test parse_file with empty content."""
    parser = RstParser()
    
    with patch("builtins.open", mock_open(read_data="")):
        result = parser.parse_file(Path("empty.rst"))
    
    # Should handle empty content gracefully
    assert isinstance(result, list)


def test_all_cleaning_methods_applied():
    """Test that all cleaning methods are applied when enabled."""
    parser = RstParser()
    content = """Title
=====

Text with `link <http://example.com>`_ and :doc:`reference`.

.. image:: image.png

+-----+-----+
| A   | B   |
+-----+-----+

`..note::` This is a note."""

    with patch("builtins.open", mock_open(read_data=content)):
        result = parser.parse_file(Path("test.rst"))

    joined_result = "\n".join(result)

    # All unwanted elements should be removed
    assert "http://example.com" not in joined_result  # hyperlinks removed
    assert ":doc:" not in joined_result  # interpreters removed
    assert ".. image::" not in joined_result  # images removed
    assert "+-----+" not in joined_result  # table excess removed
    # The directive pattern looks for `..something::` so regular .. note:: won't be removed
    # but `..note::` will be removed
    assert "`..note::`" not in joined_result  # directives removed
