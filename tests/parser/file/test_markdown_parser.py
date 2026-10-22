from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from docsgpt.parser.file.markdown_parser import MarkdownParser
from docsgpt import utils


class _Enc:
    def encode(self, s: str):
        return list(s)

    def encode_ordinary(self, s: str):
        return list(s)


@pytest.fixture(autouse=True)
def _patch_tokenizer(monkeypatch):
    monkeypatch.setattr(utils, "get_encoding", lambda: _Enc())

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


def test_markdown_to_tups_keeps_later_header_after_consecutive_headers():
    # Two headers back-to-back with no body between them: every header
    # must survive, and the body that follows belongs to the LAST one.
    # The pre-fix code's ``continue`` short-circuited both the append
    # and the current_header update, so ``# H2`` was silently dropped
    # and the body was attributed to ``# H1``.
    raw = "# H1\n# H2\nbody\n"
    parser = MarkdownParser()
    tups = parser.markdown_to_tups(raw)
    assert tups == [("H2", "body\n\n")]


def test_markdown_to_tups_keeps_only_last_header_when_several_chain():
    # Three headers in a row collapse to the last one; nothing before it
    # should re-appear in the output.
    raw = "# H1\n## H2\n### H3\nbody\n"
    parser = MarkdownParser()
    tups = parser.markdown_to_tups(raw)
    assert tups == [("H3", "body\n\n")]


def test_markdown_parse_file_preserves_consecutive_headers_via_end_to_end():
    # End-to-end through parse_file: a markdown file with two
    # consecutive headers followed by a paragraph must produce output
    # that mentions the LAST header (H2), not body — the regression
    # symptom was that ``# H1''\" survived and ``body''\" joined it,
    # because the bug lived inside markdown_to_tups.
    content = "# H1\n# H2\nbody\n"
    parser = MarkdownParser()
    with patch("builtins.open", mock_open(read_data=content)):
        result = parser.parse_file(Path("doc.md"))
    joined = "\n".join(result)
    assert "H2" in joined
    assert "body" in joined
    assert "H1" not in joined
