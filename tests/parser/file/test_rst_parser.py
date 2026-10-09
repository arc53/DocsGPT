import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

from docsgpt.parser.file.rst_parser import RstParser


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
    """Test removal of standard reStructuredText directive syntax."""
    parser = RstParser()
    content = "Text before\n.. note:: Important information\nText after"

    result = parser.remove_directives(content)

    assert result == "Text before\nImportant information\nText after"


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


def test_rst_to_tups_ignores_mismatched_underline_length():
    """A dash/equals run that doesn't match the length of the line above it
    is not a valid RST section header and should not be treated as one.

    Regression test: the header-detection guard previously included a
    self-comparison (``lines[i - 2] == lines[i - 2]``) that is always
    True, which silently disabled the length check it was meant to pair
    with. Any short divider line (e.g. a horizontal rule) following a
    longer line of prose was incorrectly promoted to a section header.
    """
    parser = RstParser()
    rst_content = (
        "Some regular paragraph text here that is fairly long.\n"
        "---\n"
        "More text continues after what might be mistaken for an underline.\n"
        "\n"
        "Real Header\n"
        "===========\n"
        "Real content under the real header.\n"
    )

    tups = parser.rst_to_tups(rst_content)

    headers = [header for header, _ in tups if header is not None]
    assert "Some regular paragraph text here that is fairly long." not in headers
    assert "Real Header" in headers

    combined_text = "\n".join(text for _, text in tups)
    assert "More text continues after what might be mistaken for an underline." in combined_text


def test_rst_to_tups_header_at_document_start():
    """A header on the very first line (i == 1) must still be detected;
    this exercises the lines[i - 2] index boundary directly. There must
    be no spurious (None, "") tuple ahead of it, since there is no real
    preamble in this document."""
    parser = RstParser()
    rst_content = "Title\n=====\nContent.\n"

    tups = parser.rst_to_tups(rst_content)

    headers = [header for header, _ in tups if header is not None]
    assert "Title" in headers
    assert (None, "") not in tups


def test_rst_to_tups_allows_underline_longer_than_title():
    """Per the RST spec, a section underline only needs to be at least
    as long as its title, not an exact-length match. An underline longer
    than its title is valid RST and must still be detected as a header.
    """
    parser = RstParser()
    rst_content = "Title\n=======\nContent.\n"

    tups = parser.rst_to_tups(rst_content)

    headers = [header for header, _ in tups if header is not None]
    assert "Title" in headers
    assert (None, "") not in tups


def test_rst_to_tups_preserves_preamble_before_first_header():
    """Text appearing before a document's first header must not be
    silently dropped.

    Regression test: the header-detection branch only saved accumulated
    text when current_header was already set, so preamble content ahead
    of the first header (current_header still None at that point) was
    discarded instead of being kept as a (None, preamble) tuple.
    """
    parser = RstParser()
    rst_content = (
        "This is preamble text that appears before any header.\n"
        "\n"
        "First Header\n"
        "============\n"
        "Content under the first header.\n"
    )

    tups = parser.rst_to_tups(rst_content)

    combined_text = "\n".join(text for _, text in tups)
    assert "This is preamble text that appears before any header." in combined_text

    headers = [header for header, _ in tups if header is not None]
    assert "First Header" in headers


def test_rst_to_tups_no_empty_chunk_when_file_starts_with_blank_line():
    """A file beginning with a blank line (or any whitespace-only text)
    before its first header must not produce a spurious (None, "") or
    (None, whitespace) chunk ahead of the real header.
    """
    parser = RstParser()
    rst_content = "\nTitle\n=====\nContent.\n"

    tups = parser.rst_to_tups(rst_content)

    assert tups[0][0] == "Title"
    for header, text in tups:
        if header is None:
            assert text.strip() != ""


def test_rst_to_tups_short_underline_at_least_4_chars_is_still_a_header():
    """docutils treats an underline shorter than its title as a valid
    section heading as long as the underline is still at least 4
    characters long -- it only emits a "Title underline too short"
    warning, it does not reject the heading. An underline below the
    4-character floor is the only case that is NOT treated as a header.
    """
    parser = RstParser()

    # Underline is shorter than the title but still >= 4 chars: docutils
    # still treats this as a heading.
    short_but_valid = "A Longer Title Than The Underline\n====\nContent.\n"
    tups = parser.rst_to_tups(short_but_valid)
    headers = [header for header, _ in tups if header is not None]
    assert "A Longer Title Than The Underline" in headers

    # Underline is both shorter than the title AND under 4 characters:
    # docutils does not treat this as a heading.
    too_short = "A Longer Title Than The Underline\n===\nContent.\n"
    tups = parser.rst_to_tups(too_short)
    headers = [header for header, _ in tups if header is not None]
    assert "A Longer Title Than The Underline" not in headers


def test_rst_to_tups_overline_title_at_document_start_no_adornment_chunk():
    """An overline-style title (====\\nTitle\\n====\\n) must not produce a
    spurious (None, "<overline>\\n") chunk ahead of the real title.

    Regression test: after stripping the title line from current_text,
    the overline line directly above it (itself matching the
    underline/overline pattern) remained in current_text. It passed the
    .strip() guard because it is not whitespace, so it leaked through as
    an extra adornment-only chunk.
    """
    parser = RstParser()
    rst_content = "=====\nTitle\n=====\nContent.\n"

    tups = parser.rst_to_tups(rst_content)

    headers = [header for header, _ in tups if header is not None]
    assert "Title" in headers
    assert (None, "=====\n") not in tups
    for header, text in tups:
        if header is None:
            assert text.strip() != ""


def test_rst_to_tups_overline_title_after_preamble_keeps_preamble_only():
    """An overline-style title appearing after real preamble text must
    keep that preamble, but still must not produce a separate
    adornment-only chunk for the overline itself, and the blank line
    directly above the overline must not be mistaken for an empty-titled
    heading.
    """
    parser = RstParser()
    rst_content = (
        "Some real preamble text here.\n"
        "\n"
        "=====\n"
        "Title\n"
        "=====\n"
        "Content.\n"
    )

    tups = parser.rst_to_tups(rst_content)

    combined_text = "\n".join(text for _, text in tups)
    assert "Some real preamble text here." in combined_text

    headers = [header for header, _ in tups if header is not None]
    assert "Title" in headers
    assert "" not in headers  # no empty-titled heading from the blank line above the overline

    assert (None, "=====\n") not in tups
    for header, text in tups:
        if header is None:
            assert text.strip() != ""


def test_rst_to_tups_keeps_divider_that_is_not_a_matching_overline():
    """Only an adornment line identical to the underline counts as an
    overline. A different divider directly above a title (here "----"
    above a "=====" underline) is ordinary preamble content and must not
    be stripped out of the preamble.
    """
    parser = RstParser()
    rst_content = "Intro\n\n----\nTitle\n=====\nContent\n"

    tups = parser.rst_to_tups(rst_content)

    headers = [header for header, _ in tups if header is not None]
    assert "Title" in headers
    preamble = "".join(text for header, text in tups if header is None)
    assert "Intro" in preamble
    assert "----" in preamble


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

.. note:: This is a note."""

    with patch("builtins.open", mock_open(read_data=content)):
        result = parser.parse_file(Path("test.rst"))

    joined_result = "\n".join(result)

    # All unwanted elements should be removed
    assert "http://example.com" not in joined_result  # hyperlinks removed
    assert ":doc:" not in joined_result  # interpreters removed
    assert ".. image::" not in joined_result  # images removed
    assert "+-----+" not in joined_result  # table excess removed
    assert ".. note::" not in joined_result
    assert "This is a note." in joined_result