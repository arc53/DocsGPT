"""The text parsers must read files as UTF-8, whatever the platform default is."""
import builtins
from pathlib import Path
from typing import Any

import pytest

from docsgpt import utils
from docsgpt.parser.file.markdown_parser import MarkdownParser
from docsgpt.parser.file.rst_parser import RstParser
from docsgpt.parser.file.tabular_parser import CSVParser

TEXT = "Caf\u00e9 \u2014 \u65e5\u672c\u8a9e \u201csmart quotes\u201d"


class _Enc:
    """Tokenizer stub that treats every character as one token."""

    def encode(self, s: str) -> list[str]:
        """Encode a string into one token per character.

        Args:
            s: The text to encode.

        Returns:
            A list with one entry per character.
        """
        return list(s)

    def encode_ordinary(self, s: str) -> list[str]:
        """Encode a string the same way as ``encode``.

        Args:
            s: The text to encode.

        Returns:
            A list with one entry per character.
        """
        return list(s)


@pytest.fixture(autouse=True)
def _legacy_default_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make open() default to cp1252, as it does on Windows, and stub the tokenizer.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(utils, "get_encoding", lambda: _Enc())
    real_open = builtins.open

    def fake_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        """Open a file, defaulting text mode to cp1252 when no encoding is given.

        Args:
            file: The path or descriptor to open.
            mode: The open mode.
            *args: Extra positional arguments for ``open``.
            **kwargs: Extra keyword arguments for ``open``.

        Returns:
            The opened file object.
        """
        if "b" not in mode and "encoding" not in kwargs and not args[1:2]:
            kwargs["encoding"] = "cp1252"
            kwargs.setdefault("errors", "replace")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)


def _joined(result: str | list[str]) -> str:
    """Join a parser result into one string.

    Args:
        result: A string or a list of strings returned by a parser.

    Returns:
        The result as a single string.
    """
    return " ".join(result) if isinstance(result, list) else result


def test_markdown_parser_reads_utf_8(tmp_path: Path) -> None:
    """MarkdownParser keeps UTF-8 text intact under a cp1252 default."""
    path = tmp_path / "doc.md"
    path.write_text(f"# Title\n\n{TEXT}\n", encoding="utf-8")
    assert TEXT in _joined(MarkdownParser().parse_file(path))


def test_rst_parser_reads_utf_8(tmp_path: Path) -> None:
    """RstParser keeps UTF-8 text intact under a cp1252 default."""
    path = tmp_path / "doc.rst"
    path.write_text(f"Title\n=====\n\n{TEXT}\n", encoding="utf-8")
    assert TEXT in _joined(RstParser().parse_file(path))


def test_csv_parser_reads_utf_8(tmp_path: Path) -> None:
    """CSVParser keeps UTF-8 text intact under a cp1252 default."""
    path = tmp_path / "data.csv"
    path.write_text(f"name,note\nx,{TEXT}\n", encoding="utf-8")
    assert TEXT in _joined(CSVParser().parse_file(path))
