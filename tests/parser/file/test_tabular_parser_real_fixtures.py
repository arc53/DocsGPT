"""Real-fixture tests for the tabular parsers.

The mock-based tests in ``test_tabular_parser.py`` stub pandas out entirely
(``MagicMock(astype=lambda _: MagicMock(tolist=lambda: ["value1", "value2"]))``),
so real pandas semantics were never exercised. That is why the pandas 3.0
change to ``Series.astype(str)`` — which now *preserves* missing values instead
of rendering them as the string ``"nan"`` — reached production as a
``TypeError: sequence item N: expected str instance, float found`` that
destroyed an entire spreadsheet upload.

These tests drive the parsers with real files.
"""

import datetime
from pathlib import Path

import pytest

from application.parser.file.tabular_parser import (
    ExcelParser,
    PandasCSVParser,
    cell_to_text,
)

openpyxl = pytest.importorskip("openpyxl")


def _write_xlsx(path: Path, rows: list[list], sheets: dict[str, list[list]] | None = None) -> Path:
    """Write ``rows`` to ``path`` as the first sheet, plus any extra ``sheets``."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    for name, extra_rows in (sheets or {}).items():
        extra = wb.create_sheet(title=name)
        for row in extra_rows:
            extra.append(row)
    wb.save(path)
    return path


def test_excel_blank_cell_in_row_does_not_crash(tmp_path):
    """A single blank cell must not destroy the whole document.

    Reproduces the production failure verbatim: a 14-column sheet whose
    second data row is blank at column index 11 raises
    ``sequence item 11: expected str instance, float found``.
    """
    headers = [f"col{i}" for i in range(14)]
    full_row = list(range(14))
    holed_row = list(range(14))
    holed_row[11] = None

    path = _write_xlsx(tmp_path / "focus.xlsx", [headers, full_row, holed_row])

    text = ExcelParser().parse_file(path)

    assert isinstance(text, str)
    assert "nan" not in text
    # The blank renders as an empty field between two joiners, not as a crash.
    assert ", , " in text


def test_excel_all_blank_row_does_not_crash(tmp_path):
    headers = ["a", "b", "c"]
    path = _write_xlsx(
        tmp_path / "blanks.xlsx", [headers, [1, 2, 3], [None, None, None]]
    )

    text = ExcelParser().parse_file(path)

    assert isinstance(text, str)
    assert "nan" not in text


def test_excel_mixed_types_render_readably(tmp_path):
    """Ints stay ints, dates are ISO, blanks are empty, nothing is ``nan``."""
    headers = ["id", "name", "ratio", "when", "flag", "blank"]
    path = _write_xlsx(
        tmp_path / "mixed.xlsx",
        [
            headers,
            [1001, "alpha", 1.5, datetime.datetime(2024, 1, 2, 3, 4), True, "x"],
            [1002, "beta", 2.25, datetime.datetime(2024, 5, 6, 7, 8), False, None],
        ],
    )

    text = ExcelParser().parse_file(path)

    assert "nan" not in text
    assert "NaT" not in text
    # A blank in the last column upcasts nothing: ids must not become 1001.0.
    assert "1001" in text and "1001.0" not in text
    assert "2024-01-02T03:04:00" in text


def test_excel_uncalculated_formula_cells_do_not_crash(tmp_path):
    """openpyxl never calculates formulas, so cached values are absent.

    Any workbook written by a non-Excel tool has all-NaN formula columns,
    which makes this a guaranteed crash on the pre-fix code.
    """
    path = _write_xlsx(
        tmp_path / "formulas.xlsx",
        [["a", "b", "total"], [1, 2, "=A2+B2"], [3, 4, "=A3+B3"]],
    )

    text = ExcelParser().parse_file(path)

    assert isinstance(text, str)
    assert "nan" not in text


def test_excel_error_values_do_not_crash(tmp_path):
    path = _write_xlsx(
        tmp_path / "errors.xlsx",
        [["a", "b"], [1, "#REF!"], [2, "#N/A"]],
    )

    text = ExcelParser().parse_file(path)

    assert isinstance(text, str)
    assert "nan" not in text


def test_excel_non_concat_rows_blank_cell_does_not_crash(tmp_path):
    """Covers the ``concat_rows=False`` branch, a separate join site."""
    path = _write_xlsx(
        tmp_path / "rows.xlsx", [["a", "b", "c"], [1, None, 3]]
    )

    rows = ExcelParser(concat_rows=False).parse_file(path)

    assert isinstance(rows, list)
    assert all(isinstance(r, str) for r in rows)
    assert not any("nan" in r for r in rows)


def test_nul_byte_in_cell_is_stripped(tmp_path):
    """NUL bytes crash the Postgres text write further downstream.

    openpyxl refuses to *write* a NUL into a worksheet
    (``IllegalCharacterError``), so the reachable route is CSV — plus the
    normalizer itself, which is what a hand-crafted or corrupt workbook
    would hit.
    """
    assert cell_to_text("di\x00rty") == "dirty"

    path = tmp_path / "nul.csv"
    path.write_bytes(b"a,b\nclean,di\x00rty\n")

    text = PandasCSVParser().parse_file(path)

    # pandas' C parser truncates the field at the NUL, so the tail is lost
    # before the normalizer sees it. What matters is that no NUL survives
    # into the text we hand to Postgres.
    assert "\x00" not in text
    assert "clean" in text


def test_pandas_csv_blank_cell_does_not_crash(tmp_path):
    path = tmp_path / "holed.csv"
    path.write_text("a,b,c\n1,,3\n4,5,6\n")

    text = PandasCSVParser().parse_file(path)

    assert isinstance(text, str)
    assert "nan" not in text


def test_pandas_csv_non_string_headers_do_not_crash(tmp_path):
    """``header=None`` yields integer column labels; the header join was never hardened."""
    path = tmp_path / "noheader.csv"
    path.write_text("1,2,3\n4,5,6\n")

    text = PandasCSVParser(pandas_config={"header": None}).parse_file(path)

    assert isinstance(text, str)
    assert text.startswith("HEADERS: ")


def test_pandas_csv_non_concat_rows_blank_cell_does_not_crash(tmp_path):
    path = tmp_path / "holed2.csv"
    path.write_text("a,b,c\n1,,3\n")

    rows = PandasCSVParser(concat_rows=False).parse_file(path)

    assert isinstance(rows, list)
    assert not any("nan" in r for r in rows)
