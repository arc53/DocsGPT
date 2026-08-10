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
