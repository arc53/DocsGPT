from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

class _Enc:
    def encode(self, s: str):
        return list(s)

@pytest.fixture(autouse=True)
def _patch_tokenizer(monkeypatch):
    import application.parser.file.markdown_parser as mdp
    monkeypatch.setattr(mdp.tiktoken, "get_encoding", lambda _: _Enc())

from application.parser.file.markdown_parser import MarkdownParser

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

