"""``html_to_markdown_text`` keeps the word boundaries a page carries.

markdownify drops an inline element that holds nothing but whitespace, and takes the
whitespace with it, so two words are ingested as one. The file parser, the web extractor
and the web tool all convert through here, so one guard covers all three.
"""

import pytest

from docsgpt.parser.markdown_conversion import (
    MARKDOWNIFY_OPTIONS,
    html_to_markdown_text,
)


@pytest.mark.parametrize("tag", ["a", "b", "strong", "em", "i", "s", "del", "code", "sub", "sup"])
def test_whitespace_only_element_keeps_the_word_boundary(tag):
    attributes = ' href="https://example.com"' if tag == "a" else ""

    assert html_to_markdown_text(f"<p>Hello<{tag}{attributes}> </{tag}>world</p>").strip() == "Hello world"


def test_space_between_two_styled_runs_survives():
    """An editor that emits one element per styled run puts the space in its own element."""
    assert html_to_markdown_text("<p><b>First</b><b> </b><b>Last</b></p>").strip() == "**First** **Last**"


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>Hello <b> </b>world</p>", "Hello world"),
        ("<p>Hello<b> </b> world</p>", "Hello world"),
        ("<p>Hello<b>\n  </b>world</p>", "Hello world"),
    ],
)
def test_whitespace_only_element_becomes_one_space(html, expected):
    """A space next to the element is not doubled, and a line break inside it does not survive."""
    assert html_to_markdown_text(html).strip() == expected


def test_non_breaking_space_stays_itself():
    assert html_to_markdown_text("<p>Hello<b>&#160;</b>world</p>").strip() == "Hello world"


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>Hello <b>bold</b> world</p>", "Hello **bold** world"),
        ("<p>Hello <em>it</em> world</p>", "Hello *it* world"),
        ("<p>Hello <code>x</code> world</p>", "Hello `x` world"),
        ('<p>Hello <a href="https://example.com">link</a> world</p>', "Hello [link](https://example.com) world"),
        ("<p>Hello<b></b>world</p>", "Helloworld"),
    ],
)
def test_element_with_content_converts_as_before(html, expected):
    """The control: only an element with nothing but whitespace in it is passed through."""
    assert html_to_markdown_text(html).strip() == expected


def test_crawler_conventions_are_applied_and_overridable():
    """The ATX heading, the backslash line break and the inferred table header are the shape all three callers share."""
    assert MARKDOWNIFY_OPTIONS == {"heading_style": "ATX", "newline_style": "BACKSLASH", "table_infer_header": True}
    assert html_to_markdown_text("<h1>Title</h1>").strip() == "# Title"
    assert html_to_markdown_text("<p>a<br>b</p>").strip() == "a\\\nb"

    assert html_to_markdown_text("<h1>Title</h1>", heading_style="UNDERLINED").strip() == "Title\n====="


@pytest.mark.parametrize(
    "html, expected",
    [
        ("<pre>left<code>   </code>right</pre>", "left   right"),
        ("<pre>a<b>\t</b>b</pre>", "a\tb"),
        ("<pre>a<i>\n\n</i>b</pre>", "a\n\nb"),
    ],
    ids=["spaces", "tab", "newlines"],
)
def test_whitespace_inside_preformatted_text_stays_as_written(html, expected):
    """In <pre>, markdownify keeps whitespace as written, so it is not collapsed here."""
    assert html_to_markdown_text(html) == f"```\n{expected}\n```"


def test_the_file_parser_and_the_web_extractor_keep_the_word_boundary():
    from bs4 import BeautifulSoup

    from docsgpt.parser.file.html_parser import soup_to_markdown
    from docsgpt.parser.remote.page_content import extract_page

    sentence = "The quick brown fox jumps over the lazy dog and keeps running through the tall grass."
    html = f"<html><body><main><p>{sentence}</p><p>Hello<b> </b>world</p></main></body></html>"

    assert soup_to_markdown(BeautifulSoup(html, "html.parser")).endswith("Hello world")
    assert extract_page(html, "https://example.com/page").text.endswith("Hello world")
