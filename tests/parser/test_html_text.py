"""The flattener keeps blocks apart without cutting sentences up."""

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
