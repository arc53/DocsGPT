"""The text parsers must read files as UTF-8, whatever the platform default is."""
import builtins

import pytest

from docsgpt import utils
from docsgpt.parser.file.markdown_parser import MarkdownParser
from docsgpt.parser.file.rst_parser import RstParser
from docsgpt.parser.file.tabular_parser import CSVParser

TEXT = "Caf\u00e9 \u2014 \u65e5\u672c\u8a9e \u201csmart quotes\u201d"


class _Enc:
    def encode(self, s: str):
        return list(s)

    def encode_ordinary(self, s: str):
        return list(s)


@pytest.fixture(autouse=True)
def _legacy_default_encoding(monkeypatch):
    """Make open() default to cp1252, as it does on Windows, and stub the tokenizer."""
    monkeypatch.setattr(utils, "get_encoding", lambda: _Enc())
    real_open = builtins.open

    def fake_open(file, mode="r", *args, **kwargs):
        if "b" not in mode and "encoding" not in kwargs and not args[1:2]:
            kwargs["encoding"] = "cp1252"
            kwargs.setdefault("errors", "replace")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)


def _joined(result) -> str:
    return " ".join(result) if isinstance(result, list) else result


def test_markdown_parser_reads_utf_8(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(f"# Title\n\n{TEXT}\n", encoding="utf-8")
    assert TEXT in _joined(MarkdownParser().parse_file(path))


def test_rst_parser_reads_utf_8(tmp_path):
    path = tmp_path / "doc.rst"
    path.write_text(f"Title\n=====\n\n{TEXT}\n", encoding="utf-8")
    assert TEXT in _joined(RstParser().parse_file(path))


def test_csv_parser_reads_utf_8(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(f"name,note\nx,{TEXT}\n", encoding="utf-8")
    assert TEXT in _joined(CSVParser().parse_file(path))
