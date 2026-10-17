"""The flattener keeps blocks apart without cutting sentences up."""

import time

import pytest
from bs4 import BeautifulSoup

from docsgpt.parser.html_text import html_to_text


def _text(html: str) -> str:
    return html_to_text(BeautifulSoup(html, "html.parser"))


def test_a_sentence_survives_its_inline_markup():
    """`get_text("\\n")` breaks this into five lines."""
    assert _text('<p>Hello <b>world</b>! See <a href="#">this</a>.</p>') == "Hello world! See this."


def test_blocks_are_kept_apart():
    html = "<h1>Quarterly Report</h1><p>Revenue rose.</p><ul><li>one</li><li>two</li></ul>"

    assert _text(html) == "Quarterly Report\nRevenue rose.\none\ntwo"


def test_the_title_reads_as_its_own_line():
    html = "<html><head><title>Test Page</title></head><body><p>Body text</p></body></html>"

    assert _text(html) == "Test Page\nBody text"


def test_a_line_break_element_becomes_a_line_break():
    assert _text("<p>line one<br>line two</p>") == "line one\nline two"


def test_script_and_style_contents_stay_out():
    html = "<p>x</p><script>var a = 1;</script><style>.a{color:red}</style><p>y</p>"

    assert _text(html) == "x\ny"


def test_empty_blocks_leave_no_blank_lines():
    assert _text("<div></div><p>only this</p><div>   </div>") == "only this"


def test_a_pre_block_keeps_its_indentation_and_blank_lines():
    """In a <pre> the whitespace is the content, so it is not normalised."""
    html = "<p>Run this:</p><pre>  if ready:\n    run()\n\n  done()</pre><p>after</p>"

    assert _text(html) == "Run this:\n  if ready:\n    run()\n\n  done()\nafter"


def test_a_pre_block_keeps_the_markup_inside_it_flat():
    html = "<pre><code>def f():\n    return 1</code></pre>"

    assert _text(html) == "def f():\n    return 1"


def test_text_before_a_block_keeps_its_own_line():
    """Only block ends were marked, so ``x<p>y</p>z`` read as ``xy``."""
    assert _text("x<p>y</p>z") == "x\ny\nz"


def test_a_line_break_inside_a_pre_block_is_kept():
    assert _text("<pre>a<br>  b</pre>") == "a\n  b"


def test_the_parsed_tree_is_left_unchanged():
    soup = BeautifulSoup("<p>one<br>two</p><pre>  x</pre><div>three</div>", "html.parser")
    before = str(soup)

    html_to_text(soup)

    assert str(soup) == before


def test_many_line_breaks_flatten_in_linear_time():
    """Replacing each <br> in place quadruples with every doubling: 20,000 of
    them took over 6 s, so 50,000 would take about 40 s. One pass takes a few
    hundredths of a second, so 5 s leaves a wide margin either way."""
    soup = BeautifulSoup("<div>" + "x<br>" * 50_000 + "</div>", "html.parser")

    started = time.perf_counter()
    lines = html_to_text(soup).split("\n")
    elapsed = time.perf_counter() - started

    assert elapsed < 5
    assert len(lines) == 50_000
    assert set(lines) == {"x"}


def test_adjacent_links_are_kept_apart():
    """A navigation bar or a tag list puts its links side by side with nothing between them."""
    assert _text("<nav><a>Home</a><a>Docs</a></nav>") == "Home Docs"


def test_adjacent_spans_are_kept_apart():
    assert _text("<p><span>Alice</span><span>CTO</span></p>") == "Alice CTO"


def test_text_between_elements_is_joined_as_written():
    """Only an element that touches another element gets a space; text is joined as it stands."""
    assert _text("<p><b>x</b>y<b>z</b></p>") == "xyz"


def test_a_comment_between_two_elements_does_not_join_them():
    assert _text("<p><a>x</a><!-- note --><a>y</a></p>") == "x y"


def test_source_line_breaks_inside_a_paragraph_collapse():
    assert _text("<p>Hello\n    world,\n  again</p>") == "Hello world, again"


def test_an_image_between_words_leaves_one_space():
    assert _text('<p>Hello <img src="x.png"> world</p>') == "Hello world"


def test_a_non_breaking_space_is_kept():
    assert _text("<p>10&#160;km</p>") == "10\xa0km"


def test_adjacent_elements_inside_a_pre_block_stay_joined():
    assert _text("<pre><span>a</span><span>b</span></pre>") == "ab"


@pytest.mark.parametrize("tag", ["form", "menu", "dialog", "center", "search", "thead", "tbody", "tfoot"])
def test_these_elements_start_their_own_line(tag):
    assert _text(f"before<{tag}>inside</{tag}>after") == "before\ninside\nafter"
