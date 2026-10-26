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


def test_markdown_html_cleanup_keeps_comparisons() -> None:
    tups = MarkdownParser().markdown_to_tups("# Compare\nIf x < 10 and y > 5 then stop.\n")
    assert tups == [("Compare", "If x < 10 and y > 5 then stop.\n\n")]


def test_markdown_html_cleanup_keeps_generics() -> None:
    content = "# Types\nUse List<String>, Map<K, V> or Optional<T>; List<Object> and Array<Map> too.\n"
    text = MarkdownParser().markdown_to_tups(content)[0][1]
    for kept in ("List<String>", "Map<K, V>", "Optional<T>", "List<Object>", "Array<Map>"):
        assert kept in text


def test_markdown_html_cleanup_removes_real_tags() -> None:
    content = '# Note\n<div class="note">Keep <b>bold</b> and line<br/>break <img src="a.png" alt="x"></div>\n'
    text = MarkdownParser().markdown_to_tups(content)[0][1]
    assert text == "Keep bold and linebreak \n\n"


def test_markdown_html_cleanup_removes_comments() -> None:
    content = "# C\nbefore <!-- a\nmulti-line comment with <b>tags</b> --> after\n"
    text = MarkdownParser().markdown_to_tups(content)[0][1]
    assert text == "before  after\n\n"


def test_markdown_html_cleanup_removes_uppercase_tags() -> None:
    content = '# Note\n<DIV class="note">Keep <B>bold</B> and line<BR/>break <IMG SRC="a.png"></DIV>\n'
    text = MarkdownParser().markdown_to_tups(content)[0][1]
    assert text == "Keep bold and linebreak \n\n"


def test_markdown_html_cleanup_keeps_generics_with_trailing_space() -> None:
    content = "# Types\nUse List<Object > and Array<Map > here.\n"
    text = MarkdownParser().markdown_to_tups(content)[0][1]
    assert "List<Object >" in text
    assert "Array<Map >" in text


def test_markdown_html_cleanup_ignores_tags_inside_comments() -> None:
    content = "# C\nkeep List<Map> <!-- </Map> --> here\n"
    text = MarkdownParser().markdown_to_tups(content)[0][1]
    assert text == "keep List<Map>  here\n\n"


def test_markdown_html_cleanup_removes_nested_bare_tags() -> None:
    content = "# Nest\n<DIV><B>bold</B></DIV> and <P>a <EM>b <B>c</B></EM> d</P>\n"
    text = MarkdownParser().markdown_to_tups(content)[0][1]
    assert text == "bold and a b c d\n\n"


def test_markdown_html_cleanup_keeps_generics_whatever_the_case() -> None:
    content = "# Types\nUse List<Object>, Array<Map> and Map<K, V> with x < 10 and y > 5.\n"
    text = MarkdownParser().markdown_to_tups(content)[0][1]
    for kept in ("List<Object>", "Array<Map>", "Map<K, V>", "x < 10", "y > 5"):
        assert kept in text


def test_markdown_html_cleanup_removes_inline_svg() -> None:
    content = (
        '# Icon\nIf x < 10 use List<int> <svg viewBox="0 0 24 24">\n'
        '<g><path d="M0 0h24v24H0z"/><circle cx="12" cy="12" r="4"/></g>\n'
        "</svg> and pass <path> here.\n"
    )
    text = MarkdownParser().markdown_to_tups(content)[0][1]
    assert text == "If x < 10 use List<int> \n\n and pass <path> here.\n\n"


def test_markdown_hash_lines_in_backtick_fence_are_not_headings():
    content = "# Install\n```bash\n# install dependencies\npip install -r requirements.txt\n```\nDone.\n"
    tups = MarkdownParser().markdown_to_tups(content)
    assert [h for h, _ in tups] == ["Install"]
    assert "# install dependencies\npip install -r requirements.txt\n```\nDone." in tups[0][1]


def test_markdown_hash_lines_in_tilde_fence_are_not_headings():
    content = "# Config\n~~~yaml\n# a comment\nkey: value\n~~~\n## Next\ntext\n"
    tups = MarkdownParser().markdown_to_tups(content)
    assert [h for h, _ in tups] == ["Config", "Next"]
    assert "# a comment\nkey: value" in tups[0][1]
    assert "text" in tups[1][1]


def test_markdown_fence_closes_only_on_matching_marker():
    # A shorter or different fence inside a longer one does not close it.
    content = "# Doc\n````md\n```\n~~~\n# still code\n````\n# After\nbody\n"
    tups = MarkdownParser().markdown_to_tups(content)
    assert [h for h, _ in tups] == ["Doc", "After"]
    assert "# still code" in tups[0][1]


def test_markdown_indented_fence_and_headings_after_it():
    content = "# A\n   ```\n# code\n   ```\n# B\nb text\n"
    tups = MarkdownParser().markdown_to_tups(content)
    assert [h for h, _ in tups] == ["A", "B"]
    assert "# code" in tups[0][1]


def test_markdown_fence_closes_with_crlf_line_endings():
    content = "# Install\r\n```bash\r\n# install dependencies\r\npip install x\r\n```\r\n# Usage\r\nrun it\r\n"
    tups = MarkdownParser().markdown_to_tups(content)
    assert [h.strip() for h, _ in tups] == ["Install", "Usage"]
    assert "# install dependencies" in tups[0][1]
    assert "run it" in tups[1][1]


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
