"""Tabular parser.

Contains parsers for tabular data files.

"""
import datetime
from pathlib import Path
from typing import Any, Dict, List, Union

from application.parser.file.base_parser import BaseParser


def cell_to_text(value: Any) -> str:
    """Render one spreadsheet/CSV cell as text that is always safe to join.

    ``Series.astype(str)`` cannot be trusted for this. Up to pandas 2.x it
    rendered missing values as the string ``"nan"``; pandas 3.0 *preserves*
    them, so ``.tolist()`` hands back Python ``float`` NaNs and ``str.join``
    raises ``TypeError: sequence item N: expected str instance, float found``.
    A single blank cell anywhere in a sheet was therefore enough to destroy
    an entire upload.

    Missing values (blank cells, ``NaT``, Excel error values, and formulas
    with no cached result) become the empty string. Dates and times are
    rendered ISO-8601 rather than pandas' repr. Integral floats drop the
    ``.0`` that pandas adds when a blank upcasts an integer column — an ID
    column with one gap otherwise turns every id into ``1001.0``. NUL bytes
    are stripped here because they crash the downstream Postgres text write.

    Args:
        value: A single cell value, of any type pandas or openpyxl may yield.

    Returns:
        str: The cell rendered as text; ``""`` for missing values.
    """
    if value is None:
        return ""
    # NaN is the only float that is not equal to itself. Checked before the
    # pandas call because it is by far the common case and needs no import.
    if isinstance(value, float) and value != value:
        return ""
    try:
        import pandas as pd

        # Raises on array-like cells, which are legitimate values, not NA.
        if pd.isna(value):
            return ""
    except (ImportError, TypeError, ValueError):
        pass
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value)
    return text.replace("\x00", "") if "\x00" in text else text


def _row_to_texts(row: Any) -> List[str]:
    """Render a pandas row as a list of join-safe strings."""
    return [cell_to_text(v) for v in row.tolist()]


class CSVParser(BaseParser):
    """CSV parser.

    Args:
        concat_rows (bool): whether to concatenate all rows into one document.
            If set to False, a Document will be created for each row.
            True by default.

    """

    def __init__(self, *args: Any, concat_rows: bool = True, **kwargs: Any) -> None:
        """Init params."""
        super().__init__(*args, **kwargs)
        self._concat_rows = concat_rows

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse file.

        Returns:
            Union[str, List[str]]: a string or a List of strings.

        """
        try:
            import csv
        except ImportError:
            raise ValueError("csv module is required to read CSV files.")
        text_list = []
        with open(file, "r") as fp:
            csv_reader = csv.reader(fp)
            for row in csv_reader:
                text_list.append(", ".join(row))
        if self._concat_rows:
            return "\n".join(text_list)
        else:
            return text_list


class PandasCSVParser(BaseParser):
    r"""Pandas-based CSV parser.

    Parses CSVs using the separator detection from Pandas `read_csv`function.
    If special parameters are required, use the `pandas_config` dict.

    Args:
        concat_rows (bool): whether to concatenate all rows into one document.
            If set to False, a Document will be created for each row.
            True by default.

        col_joiner (str): Separator to use for joining cols per row.
            Set to ", " by default.

        row_joiner (str): Separator to use for joining each row.
            Only used when `concat_rows=True`.
            Set to "\n" by default.

        pandas_config (dict): Options for the `pandas.read_csv` function call.
            Refer to https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html
            for more information.
            Set to empty dict by default, this means pandas will try to figure
            out the separators, table head, etc. on its own.
            
        header_period (int): Controls how headers are included in output:
            - 0: Headers only at the beginning
            - 1: Headers in every row
            - N > 1: Headers every N rows
            
        header_prefix (str): Prefix for header rows. Default is "HEADERS: ".
    """

    def __init__(
            self,
            *args: Any,
            concat_rows: bool = True,
            col_joiner: str = ", ",
            row_joiner: str = "\n",
            pandas_config: dict = {},
            header_period: int = 20,
            header_prefix: str = "HEADERS: ",
            **kwargs: Any
    ) -> None:
        """Init params."""
        super().__init__(*args, **kwargs)
        self._concat_rows = concat_rows
        self._col_joiner = col_joiner
        self._row_joiner = row_joiner
        self._pandas_config = pandas_config
        self._header_period = header_period
        self._header_prefix = header_prefix

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse file."""
        try:
            import pandas as pd
        except ImportError:
            raise ValueError("pandas module is required to read CSV files.")

        df = pd.read_csv(file, **self._pandas_config)
        headers = [cell_to_text(h) for h in df.columns.tolist()]
        header_row = f"{self._header_prefix}{self._col_joiner.join(headers)}"

        if not self._concat_rows:
            return df.apply(
                lambda row: (self._col_joiner).join(_row_to_texts(row)), axis=1
            ).tolist()

        text_list = []
        if self._header_period != 1:
            text_list.append(header_row)

        for i, row in df.iterrows():
            if (self._header_period > 1 and i > 0 and i % self._header_period == 0):
                text_list.append(header_row)
            text_list.append(self._col_joiner.join(_row_to_texts(row)))
            if self._header_period == 1 and i < len(df) - 1:
                text_list.append(header_row)

        return self._row_joiner.join(text_list)


class ExcelParser(BaseParser):
    r"""Excel (.xlsx) parser.

    Parses Excel files using Pandas `read_excel` function.
    If special parameters are required, use the `pandas_config` dict.

    Args:
        concat_rows (bool): whether to concatenate all rows into one document.
            If set to False, a Document will be created for each row.
            True by default.

        col_joiner (str): Separator to use for joining cols per row.
            Set to ", " by default.

        row_joiner (str): Separator to use for joining each row.
            Only used when `concat_rows=True`.
            Set to "\n" by default.

        pandas_config (dict): Options for the `pandas.read_excel` function call.
            Refer to https://pandas.pydata.org/docs/reference/api/pandas.read_excel.html
            for more information.
            Set to empty dict by default, this means pandas will try to figure
            out the table structure on its own.
            
        header_period (int): Controls how headers are included in output:
            - 0: Headers only at the beginning (default)
            - 1: Headers in every row
            - N > 1: Headers every N rows
            
        header_prefix (str): Prefix for header rows. Default is "HEADERS: ".
    """

    def __init__(
            self,
            *args: Any,
            concat_rows: bool = True,
            col_joiner: str = ", ",
            row_joiner: str = "\n",
            pandas_config: dict = {},
            header_period: int = 20,
            header_prefix: str = "HEADERS: ",
            **kwargs: Any
    ) -> None:
        """Init params."""
        super().__init__(*args, **kwargs)
        self._concat_rows = concat_rows
        self._col_joiner = col_joiner
        self._row_joiner = row_joiner
        self._pandas_config = pandas_config
        self._header_period = header_period
        self._header_prefix = header_prefix

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse file."""
        try:
            import pandas as pd
        except ImportError:
            raise ValueError("pandas module is required to read Excel files.")

        df = pd.read_excel(file, **self._pandas_config)
        headers = [cell_to_text(h) for h in df.columns.tolist()]
        header_row = f"{self._header_prefix}{self._col_joiner.join(headers)}"

        if not self._concat_rows:
            return df.apply(
                lambda row: (self._col_joiner).join(_row_to_texts(row)), axis=1
            ).tolist()

        text_list = []
        if self._header_period != 1:
            text_list.append(header_row)

        for i, row in df.iterrows():
            if (self._header_period > 1 and i > 0 and i % self._header_period == 0):
                text_list.append(header_row)
            text_list.append(self._col_joiner.join(_row_to_texts(row)))
            if self._header_period == 1 and i < len(df) - 1:
                text_list.append(header_row)
        return self._row_joiner.join(text_list)