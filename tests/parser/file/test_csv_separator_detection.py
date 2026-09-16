"""A .csv file is not always comma separated.

Excel writes the list separator of the machine's locale -- a semicolon across
most of Europe -- and a tab separated export is routinely saved as .csv.
``pandas.read_csv`` defaults to a comma, so those files were read as a single
column holding the whole row, separators and all.
"""

from pathlib import Path

import pytest

from docsgpt.parser.file.tabular_parser import (
    CSVParser,
    PandasCSVParser,
    detect_separator,
)

ROWS = ["Name;Region;Units", "Widget;EU;12", "Gadget;US;7"]
EXPECTED = "HEADERS: Name, Region, Units\nWidget, EU, 12\nGadget, US, 7"


def _write(tmp_path: Path, text: str, name: str = "table.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("separator", [",", ";", "\t", "|"])
def test_pandas_parser_reads_the_separator_the_file_was_written_with(tmp_path: Path, separator: str) -> None:
    text = "\n".join(row.replace(";", separator) for row in ROWS) + "\n"

    assert PandasCSVParser().parse_file(_write(tmp_path, text)) == EXPECTED


def test_pandas_parser_keeps_an_explicit_separator(tmp_path: Path) -> None:
    """A separator given in pandas_config is used as given, with no detection."""
    text = "\n".join(ROWS) + "\n"

    parser = PandasCSVParser(pandas_config={"sep": ";"})

    assert parser.parse_file(_write(tmp_path, text)) == EXPECTED


def test_pandas_parser_leaves_a_single_column_file_alone(tmp_path: Path) -> None:
    """Guard: a separator that does not line up across the rows is not one.

    This is also why pandas' own sniffing (``sep=None, engine="python"``) is not
    used: it splits the header ``Note`` on the ``t`` inside it.
    """
    text = "Note\na; b\nc; d\n"

    result = PandasCSVParser().parse_file(_write(tmp_path, text))

    assert result == "HEADERS: Note\na; b\nc; d"


def test_plain_parser_reads_a_semicolon_file(tmp_path: Path) -> None:
    text = "\n".join(ROWS) + "\n"

    result = CSVParser().parse_file(_write(tmp_path, text))

    assert result == "Name, Region, Units\nWidget, EU, 12\nGadget, US, 7"


def test_plain_parser_leaves_a_comma_file_alone(tmp_path: Path) -> None:
    text = "col1,col2\nvalue1,value2\nvalue3,value4\n"

    result = CSVParser().parse_file(_write(tmp_path, text))

    assert result == "col1, col2\nvalue1, value2\nvalue3, value4"


@pytest.mark.parametrize(
    "sample, expected",
    [
        ("a,b,c\n1,2,3\n", ","),
        ("a;b;c\n1;2;3\n", ";"),
        ("a\tb\tc\n1\t2\t3\n", "\t"),
        ("a|b|c\n1|2|3\n", "|"),
        # A separator inside a quoted field is not a separator.
        ('Name,Note\nWidget,"a; b"\nGadget,"c; d"\n', ","),
        # Rows that do not line up leave the default in place.
        ("Note\na; b\nc; d\n", ","),
        ("name,value\nAlice,1\nBob,2,extra\n", ","),
        ("", ","),
    ],
)
def test_detect_separator(sample: str, expected: str) -> None:
    assert detect_separator(sample) == expected


def test_detect_separator_never_raises_on_an_unreadable_file(tmp_path: Path) -> None:
    from docsgpt.parser.file.tabular_parser import detect_file_separator

    assert detect_file_separator(tmp_path / "missing.csv") == ","
