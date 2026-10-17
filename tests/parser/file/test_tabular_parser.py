import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

from docsgpt.parser.file.tabular_parser import CSVParser, PandasCSVParser, ExcelParser


@pytest.fixture
def csv_parser():
    return CSVParser()


@pytest.fixture
def pandas_csv_parser():
    return PandasCSVParser()


@pytest.fixture
def excel_parser():
    return ExcelParser()

def test_csv_init_parser():
    parser = CSVParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_pandas_csv_init_parser():
    parser = PandasCSVParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_excel_init_parser():
    parser = ExcelParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_csv_parser_concat_rows(csv_parser):
    mock_data = "col1,col2\nvalue1,value2\nvalue3,value4"

    with patch("builtins.open", mock_open(read_data=mock_data)):
        result = csv_parser.parse_file(Path("test.csv"))
        assert result == "col1, col2\nvalue1, value2\nvalue3, value4"


def test_csv_parser_separate_rows(csv_parser):
    csv_parser._concat_rows = False
    mock_data = "col1,col2\nvalue1,value2\nvalue3,value4"

    with patch("builtins.open", mock_open(read_data=mock_data)):
        result = csv_parser.parse_file(Path("test.csv"))
        assert result == ["col1, col2", "value1, value2", "value3, value4"]




def test_pandas_csv_parser_concat_rows(pandas_csv_parser):
    mock_df = MagicMock()
    mock_df.columns.tolist.return_value = ["col1", "col2"]
    mock_df.iterrows.return_value = [
        (0, MagicMock(tolist=lambda: ["value1", "value2"])),
        (1, MagicMock(tolist=lambda: ["value3", "value4"]))
    ]

    with patch("pandas.read_csv", return_value=mock_df):
        result = pandas_csv_parser.parse_file(Path("test.csv"))
        expected = "HEADERS: col1, col2\nvalue1, value2\nvalue3, value4"
        assert result == expected


def test_pandas_csv_parser_separate_rows(pandas_csv_parser):
    pandas_csv_parser._concat_rows = False
    mock_df = MagicMock()
    mock_df.apply.return_value.tolist.return_value = ["value1, value2", "value3, value4"]

    with patch("pandas.read_csv", return_value=mock_df):
        result = pandas_csv_parser.parse_file(Path("test.csv"))
        assert result == ["value1, value2", "value3, value4"]


def test_pandas_csv_parser_header_period(pandas_csv_parser):
    pandas_csv_parser._header_period = 2

    mock_df = MagicMock()
    mock_df.columns.tolist.return_value = ["col1", "col2"]
    mock_df.iterrows.return_value = [
        (0, MagicMock(tolist=lambda: ["value1", "value2"])),
        (1, MagicMock(tolist=lambda: ["value3", "value4"])),
        (2, MagicMock(tolist=lambda: ["value5", "value6"]))
    ]
    mock_df.__len__.return_value = 3

    with patch("pandas.read_csv", return_value=mock_df):
        result = pandas_csv_parser.parse_file(Path("test.csv"))
        expected = "HEADERS: col1, col2\nvalue1, value2\nvalue3, value4\nHEADERS: col1, col2\nvalue5, value6"
        assert result == expected


def test_excel_parser_concat_rows(excel_parser):
    mock_df = MagicMock()
    mock_df.columns.tolist.return_value = ["col1", "col2"]
    mock_df.iterrows.return_value = [
        (0, MagicMock(tolist=lambda: ["value1", "value2"])),
        (1, MagicMock(tolist=lambda: ["value3", "value4"]))
    ]

    with patch("pandas.read_excel", return_value=mock_df):
        result = excel_parser.parse_file(Path("test.xlsx"))
        expected = "HEADERS: col1, col2\nvalue1, value2\nvalue3, value4"
        assert result == expected


def test_excel_parser_separate_rows(excel_parser):
    excel_parser._concat_rows = False
    mock_df = MagicMock()
    mock_df.apply.return_value.tolist.return_value = ["value1, value2", "value3, value4"]

    with patch("pandas.read_excel", return_value=mock_df):
        result = excel_parser.parse_file(Path("test.xlsx"))
        assert result == ["value1, value2", "value3, value4"]


def test_excel_parser_header_period(excel_parser):
    excel_parser._header_period = 1

    mock_df = MagicMock()
    mock_df.columns.tolist.return_value = ["col1", "col2"]
    mock_df.iterrows.return_value = [
        (0, MagicMock(tolist=lambda: ["value1", "value2"])),
        (1, MagicMock(tolist=lambda: ["value3", "value4"]))
    ]
    mock_df.__len__.return_value = 2

    with patch("pandas.read_excel", return_value=mock_df):
        result = excel_parser.parse_file(Path("test.xlsx"))
        expected = "value1, value2\nHEADERS: col1, col2\nvalue3, value4"
        assert result == expected

def test_csv_parser_import_error(csv_parser):
    import sys
    with patch.dict(sys.modules, {"csv": None}):
        with pytest.raises(ValueError, match="csv module is required to read CSV files"):
            csv_parser.parse_file(Path("test.csv"))


def test_pandas_csv_parser_import_error(pandas_csv_parser):
    import sys
    with patch.dict(sys.modules, {"pandas": None}):
        with pytest.raises(ValueError, match="pandas module is required to read CSV files"):
            pandas_csv_parser.parse_file(Path("test.csv"))


def test_pandas_csv_parser_header_period_zero(pandas_csv_parser):
    pandas_csv_parser._header_period = 0
    mock_df = MagicMock()
    mock_df.columns.tolist.return_value = ["c1", "c2"]
    mock_df.iterrows.return_value = [
        (0, MagicMock(tolist=lambda: ["v1", "v2"])),
        (1, MagicMock(tolist=lambda: ["v3", "v4"])),
    ]
    with patch("pandas.read_csv", return_value=mock_df):
        result = pandas_csv_parser.parse_file(Path("f.csv"))
    assert result == "HEADERS: c1, c2\nv1, v2\nv3, v4"


def test_pandas_csv_parser_header_period_one(pandas_csv_parser):
    pandas_csv_parser._header_period = 1
    mock_df = MagicMock()
    mock_df.columns.tolist.return_value = ["a", "b"]
    mock_df.iterrows.return_value = [
        (0, MagicMock(tolist=lambda: ["x", "y"])),
        (1, MagicMock(tolist=lambda: ["m", "n"])),
    ]
    mock_df.__len__.return_value = 2
    with patch("pandas.read_csv", return_value=mock_df):
        result = pandas_csv_parser.parse_file(Path("f.csv"))
    assert result == "x, y\nHEADERS: a, b\nm, n"


def test_pandas_csv_parser_passes_pandas_config():
    parser = PandasCSVParser(pandas_config={"sep": ";", "header": 0})
    mock_df = MagicMock()
    with patch("pandas.read_csv", return_value=mock_df) as mock_read:
        parser.parse_file(Path("conf.csv"))
        kwargs = mock_read.call_args.kwargs
        assert kwargs.get("sep") == ";"
        assert kwargs.get("header") == 0


def test_excel_parser_custom_joiners_and_prefix(excel_parser):
    excel_parser._col_joiner = " | "
    excel_parser._row_joiner = " || "
    excel_parser._header_prefix = "COLUMNS: "
    mock_df = MagicMock()
    mock_df.columns.tolist.return_value = ["A", "B"]
    mock_df.iterrows.return_value = [
        (0, MagicMock(tolist=lambda: ["x", "y"])),
    ]
    with patch("pandas.read_excel", return_value=mock_df):
        result = excel_parser.parse_file(Path("t.xlsx"))
    assert result == "COLUMNS: A | B || x | y"

def test_excel_parser_import_error(excel_parser):
    import sys
    with patch.dict(sys.modules, {"pandas": None}):
        with pytest.raises(ValueError, match="pandas module is required to read Excel files"):
            excel_parser.parse_file(Path("test.xlsx"))

def test_excel_numeric_headers_do_not_crash(tmp_path):
    """Regression: a headerless/numeric xlsx gives integer column labels, and
    ``", ".join(headers)`` used to raise TypeError. The XLSX size-gate delegates
    to this parser, so it must handle numeric headers."""
    from openpyxl import Workbook

    from docsgpt.parser.file.tabular_parser import ExcelParser

    wb = Workbook()
    ws = wb.active
    for i in range(5):
        ws.append([i, i * 2, i * 3])
    path = tmp_path / "numeric.xlsx"
    wb.save(str(path))

    out = ExcelParser().parse_file(path)

    assert isinstance(out, str)
    assert len(out) > 0


LITERAL_NA_VALUES = ["N/A", "NA", "n/a", "NULL", "None", "NaN", "nan"]


@pytest.mark.parametrize("value", LITERAL_NA_VALUES)
def test_pandas_csv_keeps_a_literal_na_value(tmp_path, value):
    """pandas reads these strings as missing values, so the cell arrived blank.

    "N/A" is how a person writes "not applicable" and "NULL" is what a database
    export writes; either way the cell says something and the text lost it.
    """
    path = tmp_path / "status.csv"
    path.write_text(f"Code,Status\nA1,{value}\nA2,ok\n")

    text = PandasCSVParser().parse_file(path)

    assert f"A1, {value}" in text


@pytest.mark.parametrize("value", LITERAL_NA_VALUES)
def test_excel_keeps_a_literal_na_value(tmp_path, value):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Code", "Status"])
    sheet.append(["A1", value])
    sheet.append(["A2", "ok"])
    path = tmp_path / "status.xlsx"
    workbook.save(path)

    text = ExcelParser().parse_file(path)

    assert f"A1, {value}" in text


def test_a_genuinely_empty_cell_is_still_empty(tmp_path):
    """The control: keeping the literal strings must not make a blank visible."""
    path = tmp_path / "gap.csv"
    path.write_text("Code,Status,Units\nA1,,12\nA2,ok,7\n")

    text = PandasCSVParser().parse_file(path)

    assert "A1, , 12" in text


def test_a_whole_number_next_to_a_gap_keeps_its_form(tmp_path):
    """A blank used to upcast the column to float and write 12 as 12.0."""
    path = tmp_path / "gap.csv"
    path.write_text("Code,Units\nA1,12\nA2,\n")

    text = PandasCSVParser().parse_file(path)

    assert "A1, 12" in text
    assert "12.0" not in text


def test_the_caller_can_ask_for_the_default_na_list(tmp_path):
    path = tmp_path / "status.csv"
    path.write_text("Code,Status\nA1,N/A\nA2,ok\n")

    text = PandasCSVParser(pandas_config={"keep_default_na": True}).parse_file(path)

    assert text.splitlines()[1] == "A1, "

