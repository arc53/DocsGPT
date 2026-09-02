import pytest

from application.parser.file.html_parser import HTMLParser


HTML = (
    "<html><head><title>My Page</title></head>"
    "<body><h1>Heading</h1><p>Hello world.</p></body></html>"
)


@pytest.fixture
def html_file(tmp_path):
    path = tmp_path / "page.html"
    path.write_text(HTML)
    return path


def test_html_init_parser():
    parser = HTMLParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_html_parser_extracts_text(html_file):
    text = HTMLParser().parse_file(html_file)
    assert "Heading" in text
    assert "Hello world." in text


def test_html_parser_returns_plain_text(html_file):
    """bulk.py stringifies parser output, so it must not be a repr.

    The previous langchain BSHTMLLoader returned a Document whose ``str()`` is
    ``page_content='...' metadata={...}``, which leaked into indexed content.
    """
    text = HTMLParser().parse_file(html_file)
    assert isinstance(text, str)
    assert "page_content" not in str(text)
    assert "metadata=" not in str(text)


def test_html_parser_reports_title_metadata(html_file):
    assert HTMLParser().get_file_metadata(html_file) == {"title": "My Page"}


def test_html_parser_metadata_without_title(tmp_path):
    path = tmp_path / "no_title.html"
    path.write_text("<html><body><p>Just text.</p></body></html>")
    assert HTMLParser().get_file_metadata(path) == {}


def test_html_parser_metadata_unreadable_file(tmp_path):
    assert HTMLParser().get_file_metadata(tmp_path / "missing.html") == {}


# --- HTMLMarkdownParser: the anydoc engine's HTML path ---------------------------

from application.parser.file.html_parser import HTMLMarkdownParser, html_to_markdown  # noqa: E402

RICH_HTML = """<html><head><title>Doc Title</title>
<style>.x { color: red }</style><script>var secret = 1;</script></head>
<body>
<h1>Heading</h1>
<p>See <a href="../ref.html#anchor">the ref</a> for details.</p>
<table><tr><th>h1</th><th>h2</th></tr><tr><td>1</td><td>2</td></tr></table>
<pre><code>typing.__name__, typing.__spec__.name</code></pre>
</body></html>"""


@pytest.fixture
def rich_html_file(tmp_path):
    path = tmp_path / "rich.html"
    path.write_text(RICH_HTML)
    return path


def test_markdown_parser_keeps_structure(rich_html_file):
    out = HTMLMarkdownParser().parse_file(rich_html_file)

    assert isinstance(out, str)
    assert "# Heading" in out
    assert "[the ref](../ref.html#anchor)" in out  # links kept, hrefs verbatim
    assert "| h1 | h2 |" in out and "| 1 | 2 |" in out  # GFM table
    assert "typing.__name__, typing.__spec__.name" in out  # code byte-exact


def test_markdown_parser_drops_non_content(rich_html_file):
    out = HTMLMarkdownParser().parse_file(rich_html_file)

    assert "var secret" not in out
    assert "color: red" not in out
    assert "Doc Title" not in out  # title is metadata, not body text


def test_markdown_parser_reports_title_metadata(rich_html_file):
    assert HTMLMarkdownParser().get_file_metadata(rich_html_file) == {"title": "Doc Title"}


def test_markdown_parser_differs_from_plain_text_contract(rich_html_file):
    """``HTMLParser`` stays plain text (the ``fast`` engine's contract); only the new class emits Markdown."""
    plain = HTMLParser().parse_file(rich_html_file)
    assert "# Heading" not in plain
    assert "[the ref]" not in plain


def test_markdown_parser_handles_xhtml(tmp_path):
    path = tmp_path / "page.xhtml"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" '
        '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>X</title></head>'
        "<body><h2>Section</h2><p>Body &amp; entities.</p></body></html>"
    )
    out = HTMLMarkdownParser().parse_file(path)
    assert "## Section" in out
    assert "Body & entities." in out


def test_markdown_parser_init():
    parser = HTMLMarkdownParser()
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_html_to_markdown_collapses_blank_runs():
    out = html_to_markdown("<p>a</p><br/><br/><br/><br/><p>b</p>")
    assert "\n\n\n" not in out
    assert out.startswith("a") and out.endswith("b")


# --- HTMLMarkdownParser: input bounding and decoding ------------------------------


def test_markdown_parser_head_truncates_oversized_markup(tmp_path, monkeypatch):
    """Markup past MARKUP_MAX_BYTES is not parsed: the soup+markdownify tree costs
    ~50x the input, and the upload cap is 100 MB."""
    from application.core.settings import settings

    monkeypatch.setattr(settings, "MARKUP_MAX_BYTES", 600)
    path = tmp_path / "big.html"
    body = "".join(f"<p>para {i}</p>\n" for i in range(300))
    path.write_text("<html><head><title>Big</title></head><body>\n" + body + "</body></html>")
    assert path.stat().st_size > 600

    out = HTMLMarkdownParser().parse_file(path)

    assert "para 0" in out
    assert "para 299" not in out
    assert HTMLMarkdownParser().get_file_metadata(path) == {"title": "Big"}


def test_markdown_parser_gate_disabled_reads_everything(tmp_path, monkeypatch):
    from application.core.settings import settings

    monkeypatch.setattr(settings, "MARKUP_MAX_BYTES", 0)
    path = tmp_path / "big.html"
    body = "".join(f"<p>para {i}</p>\n" for i in range(300))
    path.write_text("<html><body>\n" + body + "</body></html>")

    out = HTMLMarkdownParser().parse_file(path)

    assert "para 299" in out


def test_markdown_parser_honours_declared_charset(tmp_path):
    """The file is handed to BeautifulSoup as bytes so ``<meta charset>`` wins
    over the process locale (docling did the same; the text parser does not)."""
    path = tmp_path / "cp1250.html"
    path.write_bytes(
        '<html><head><meta charset="windows-1250"><title>Plzeň</title></head>'
        "<body><p>Jiří z Plzně</p></body></html>".encode("cp1250")
    )

    assert "Jiří z Plzně" in HTMLMarkdownParser().parse_file(path)
    assert HTMLMarkdownParser().get_file_metadata(path) == {"title": "Plzeň"}


def test_markdown_parser_metadata_unreadable_file(tmp_path):
    assert HTMLMarkdownParser().get_file_metadata(tmp_path / "missing.html") == {}


def test_markdown_parser_cut_inside_utf8_char_does_not_mojibake_the_page(tmp_path, monkeypatch):
    """A byte cut mid-character makes strict UTF-8 fail; BeautifulSoup would then
    retry as windows-1252, which *succeeds* on umlauts and garbles everything."""
    from application.core.settings import settings

    path = tmp_path / "minified.html"
    body = "<p>Größe Übermaß schön für</p>" * 400  # no newlines: the cut is arbitrary
    path.write_bytes(
        ('<html><head><meta charset="utf-8"><title>Größe</title></head><body>' + body + "</body></html>")
        .encode("utf-8")
    )
    for cap in (2001, 2002, 2003):  # one of these lands inside a 2-byte sequence
        monkeypatch.setattr(settings, "MARKUP_MAX_BYTES", cap)
        out = HTMLMarkdownParser().parse_file(path)
        assert "Größe Übermaß schön für" in out, cap
        assert "Ã" not in out, cap


def test_trim_torn_utf8_tail():
    from application.parser.file.html_parser import _trim_torn_utf8_tail as trim

    e_acute, snowman, emoji = "é".encode(), "☃".encode(), "😀".encode()
    assert trim(b"abc") == b"abc"
    assert trim(b"abc" + e_acute) == b"abc" + e_acute  # complete 2-byte
    assert trim(b"abc" + e_acute[:1]) == b"abc"  # torn 2-byte
    assert trim(b"abc" + snowman[:2]) == b"abc"  # torn 3-byte
    assert trim(b"abc" + emoji[:3]) == b"abc"  # torn 4-byte
    assert trim(b"abc" + emoji) == b"abc" + emoji
    assert trim(b"") == b""
    assert trim(b"\xe8") == b""  # lone lead byte (also a cp1250 letter: at most one glyph lost)


def test_markdown_parser_metadata_reuses_last_parse(tmp_path, rich_html_file, monkeypatch):
    """The metadata call after parse_file must not build the soup again."""
    from application.parser.file import html_parser as mod

    parser = HTMLMarkdownParser()
    parser.parse_file(rich_html_file)
    calls = []
    monkeypatch.setattr(mod, "read_markup_head", lambda *a, **k: calls.append(a) or b"")
    assert parser.get_file_metadata(rich_html_file) == {"title": "Doc Title"}
    assert calls == []
    # A different file is read afresh.
    other = tmp_path / "other.html"
    other.write_text("<title>Other</title>")
    parser.get_file_metadata(other)
    assert len(calls) == 1


# --- second-pass fixes: XML prolog, data URIs, UTF-16 heads ---------------------


def test_xml_prolog_does_not_leak_into_markdown(tmp_path):
    from application.parser.file.html_parser import HTMLMarkdownParser

    path = tmp_path / "doc.xhtml"
    path.write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head>'
        b"<body><h1>Hi</h1><p>para</p><![CDATA[raw]]></body></html>"
    )
    text = HTMLMarkdownParser().parse_file(path)
    assert "xml version" not in text
    assert "raw" not in text
    assert text.startswith("# Hi")


def test_data_uris_are_stripped_from_images_and_links():
    payload = "data:image/png;base64," + "A" * 200_000
    html = (
        f'<p>before</p><img src="{payload}" alt="chart"><a href="{payload}">dl</a>'
        f'<img srcset="{payload} 1x" alt="x"><p>after</p>'
    )
    text = html_to_markdown(html)
    assert "AAAA" not in text
    assert "before" in text and "after" in text
    assert len(text) < 200


def test_utf16_head_keeps_an_even_byte_count(tmp_path, monkeypatch):
    from application.core.settings import settings
    from application.parser.file.html_parser import HTMLMarkdownParser, read_markup_head

    body = "".join(f"<p>Zeile {i} Über Größe</p>\n" for i in range(200))
    path = tmp_path / "wide.html"
    path.write_bytes(("<html><body>" + body + "</body></html>").encode("utf-16"))  # BOM-prefixed
    head = read_markup_head(path, 3001)
    assert len(head) % 2 == 0
    monkeypatch.setattr(settings, "MARKUP_MAX_BYTES", 3001)
    text = HTMLMarkdownParser().parse_file(path)
    assert "Zeile 0 Über Größe" in text
    assert "\x00" not in text
