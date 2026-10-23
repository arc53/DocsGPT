from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from docsgpt.parser.file.markdown_parser import MarkdownParser
from docsgpt.parser import tokenization
from tests.parser.counter_fakes import spy_cl100k


class _Enc:
    def encode(self, s: str):
        return list(s)

    def encode_ordinary(self, s: str):
        return list(s)


@pytest.fixture(autouse=True)
def encoding(monkeypatch):
    return spy_cl100k(monkeypatch, inner=_Enc())


def test_markdown_init_parser():
    parser = MarkdownParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_markdown_parse_file_basic_structure():
    content = "# Title\npara1\npara2\n## Sub\ntext\n"
    parser = MarkdownParser()
    with patch("builtins.open", mock_open(read_data=content)):
        result = parser.parse_file(Path("doc.md"))
    assert isinstance(result, list) and len(result) >= 2

    assert "Title" in result[0]
    assert "para1" in result[0] and "para2" in result[0]
    assert "Sub" in result[1]
    assert "text" in result[1]


def test_markdown_removes_links_and_images_in_parse():
    content = "# T\nSee [link](http://x) and ![[img.png]] here.\n"
    parser = MarkdownParser()
    with patch("builtins.open", mock_open(read_data=content)):
        result = parser.parse_file(Path("doc.md"))
    joined = "\n".join(result)
    assert "(http://x)" not in joined
    assert "![[img.png]]" not in joined
    assert "link" in joined


def test_markdown_token_chunking_via_max_tokens():

    raw = "abcdefghij"  # 10 chars
    parser = MarkdownParser(max_tokens=4)
    with patch("builtins.open", mock_open(read_data=raw)):
        tups = parser.parse_tups(Path("doc.md"))
    assert len(tups) > 1
    for _hdr, chunk in tups:
        assert len(chunk) <= 4


def test_tups_chunk_append_small_text_golden():
    parser = MarkdownParser(max_tokens=4)
    assert parser.tups_chunk_append([], None, "ab\n") == [(None, "ab\n")]
    assert parser.tups_chunk_append([], None, "abcdefghij\n") == [
        (None, "abcd"),
        (None, "efgh"),
        (None, "ij\n"),
    ]
    assert parser.tups_chunk_append([("h", "x")], "# H", "abcde") == [("h", "x"), ("# H", "abcd"), ("# H", "e")]


_WINDOW = 64


def test_tups_chunk_append_counts_large_text_in_bounded_windows(encoding, monkeypatch):
    monkeypatch.setattr(tokenization, "_WINDOW_CHARS", _WINDOW, raising=False)
    text = "plain text line without any header\n" * 60
    assert MarkdownParser(max_tokens=10**6).tups_chunk_append([], None, text) == [(None, text)]
    assert max(encoding.encode_lengths) <= 2 * _WINDOW


def test_tups_chunk_append_windowed_count_still_chunks_over_budget(encoding, monkeypatch):
    monkeypatch.setattr(tokenization, "_WINDOW_CHARS", _WINDOW, raising=False)
    tups = MarkdownParser(max_tokens=300).tups_chunk_append([], None, "x" * 1000)
    assert [len(chunk) for _, chunk in tups] == [300, 300, 300, 100]
    assert max(encoding.encode_lengths) <= 2 * _WINDOW
