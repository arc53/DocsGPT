"""Legacy and OpenDocument workbooks (.xls, .xlsb, .ods) through ``ExcelParser``.

pandas picks the reader from the file's bytes: ``xlrd`` for .xls, ``pyxlsb`` for
.xlsb and ``odfpy`` for .ods, with ``calamine`` as the fallback for the first
two. Only ``openpyxl`` used to be installed, so a legacy workbook raised a bare
``ImportError`` that failed a whole connector sync and was retried three times.

``fixtures/legacy.{xls,xlsb,ods}`` hold :data:`ROWS`. They were written once,
outside the test dependencies: the .xls with xlwt, the .ods with odfpy, and the
.xlsb as BIFF12 records (workbook, one sheet, inline strings).
"""

import shutil
import sys
from pathlib import Path

import pytest

from docsgpt.parser.file.anydoc_parser import _TABULAR_SUFFIXES
from docsgpt.parser.file.base_parser import DocumentParseError
from docsgpt.parser.file.tabular_parser import ExcelParser, PandasCSVParser

openpyxl = pytest.importorskip("openpyxl")

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY_SUFFIXES = (".xls", ".xlsb", ".ods")

ROWS = [
    ["id", "name", "ratio", "note"],
    [1, "alpha", 0.5, "N/A"],
    [2, "beta", None, "two words"],
    [3, "gamma, delta", 2.25, None],
]


def _write_xlsx(path: Path) -> Path:
    """Write :data:`ROWS` as an OOXML workbook (also valid under an .xlsm name)."""
    wb = openpyxl.Workbook()
    for row in ROWS:
        wb.active.append(row)
    wb.save(path)
    return path


def _write_csv(path: Path) -> Path:
    """Write :data:`ROWS` as CSV, quoting the field that holds a comma."""
    lines = []
    for row in ROWS:
        cells = ["" if v is None else str(v) for v in row]
        lines.append(",".join(f'"{c}"' if "," in c else c for c in cells))
    path.write_text("\n".join(lines) + "\n")
    return path


def _fixture(suffix: str, tmp_path: Path) -> Path:
    """A file of ``suffix`` holding :data:`ROWS`."""
    if suffix == ".csv":
        return _write_csv(tmp_path / "rows.csv")
    if suffix in (".xlsx", ".xlsm"):
        return _write_xlsx(tmp_path / f"rows{suffix}")
    return FIXTURES / f"legacy{suffix}"


@pytest.fixture
def xlsx_text(tmp_path):
    """What ``ExcelParser`` makes of the .xlsx twin of the fixtures."""
    return ExcelParser().parse_file(_write_xlsx(tmp_path / "twin.xlsx"))


@pytest.fixture
def no_calamine(monkeypatch):
    """Make ``import python_calamine`` fail, as on an install without it."""
    monkeypatch.setitem(sys.modules, "python_calamine", None)


@pytest.mark.unit
@pytest.mark.parametrize("suffix", LEGACY_SUFFIXES)
def test_a_legacy_workbook_reads_like_its_xlsx_twin(suffix, xlsx_text):
    assert ExcelParser().parse_file(FIXTURES / f"legacy{suffix}") == xlsx_text


@pytest.mark.unit
@pytest.mark.parametrize("suffix", LEGACY_SUFFIXES)
def test_rows_mode_matches_the_xlsx_twin(suffix, tmp_path):
    twin = ExcelParser(concat_rows=False).parse_file(_write_xlsx(tmp_path / "twin.xlsx"))

    assert ExcelParser(concat_rows=False).parse_file(FIXTURES / f"legacy{suffix}") == twin


@pytest.mark.unit
@pytest.mark.parametrize("suffix", (".xls", ".xlsb"))
def test_legacy_bytes_under_an_xlsx_name_still_read(suffix, tmp_path, xlsx_text):
    """anydoc hands a ``.xlsx`` it cannot convert to ``ExcelParser``, and pandas goes by the bytes.

    A legacy workbook saved or downloaded under an .xlsx name takes that route.
    """
    misnamed = tmp_path / "report.xlsx"
    shutil.copy(FIXTURES / f"legacy{suffix}", misnamed)

    assert ExcelParser().parse_file(misnamed) == xlsx_text


@pytest.mark.unit
def test_an_explicit_engine_in_pandas_config_is_kept(monkeypatch):
    import pandas as pd

    seen = {}
    real_read_excel = pd.read_excel

    def _spy(file, **kwargs):
        seen.update(kwargs)
        return real_read_excel(file, **{**kwargs, "engine": "calamine"})

    monkeypatch.setattr(pd, "read_excel", _spy)

    ExcelParser(pandas_config={"engine": "my-engine"}).parse_file(FIXTURES / "legacy.xls")

    assert seen["engine"] == "my-engine"


@pytest.mark.unit
def test_xlsx_stays_on_its_default_engine(monkeypatch, tmp_path):
    """Only the legacy formats move to calamine, so .xlsx output does not change."""
    import pandas as pd

    seen = {}
    real_read_excel = pd.read_excel

    def _spy(file, **kwargs):
        seen.update(kwargs)
        return real_read_excel(file, **kwargs)

    monkeypatch.setattr(pd, "read_excel", _spy)

    ExcelParser().parse_file(_write_xlsx(tmp_path / "twin.xlsx"))

    assert "engine" not in seen


@pytest.mark.unit
@pytest.mark.parametrize("suffix", LEGACY_SUFFIXES)
def test_a_missing_reader_is_a_parse_error(suffix, no_calamine):
    """Deterministic for the install, so it must be the type ingest skips and Celery does not retry."""
    with pytest.raises(DocumentParseError, match=f"legacy{suffix}.*python-calamine"):
        ExcelParser().parse_file(FIXTURES / f"legacy{suffix}")


@pytest.mark.unit
def test_every_tabular_suffix_has_a_fixture_here():
    """A suffix added to ``_TABULAR_SUFFIXES`` needs a case in :func:`_fixture` (and a reader)."""
    covered = {".csv", ".xlsx", ".xlsm", *LEGACY_SUFFIXES}
    assert set(_TABULAR_SUFFIXES) <= covered


@pytest.mark.unit
@pytest.mark.parametrize("suffix", sorted(_TABULAR_SUFFIXES))
def test_every_tabular_suffix_has_an_installed_reader(suffix, tmp_path):
    """anydoc hands these to the tabular parsers; each must have its reader installed.

    Parsing a real file is the check: it fails on a missing reader the same way
    an ingest would.
    """
    parser = PandasCSVParser() if suffix == ".csv" else ExcelParser()

    text = parser.parse_file(_fixture(suffix, tmp_path))

    assert "gamma, delta" in text and "two words" in text
