import json
from typing import Any, Dict, List, Union
from pathlib import Path

from docsgpt.parser.file.base_parser import BaseParser, DocumentParseError

class JSONParser(BaseParser):
    r"""JSON (.json) parser.

    Parses JSON files into a list of strings or a concatenated document.
    It handles JSON objects (dictionaries), arrays (lists), and scalar values.
    Objects and scalars are treated as one row; arrays retain their items as rows.

    Args:
        concat_rows (bool): Whether to concatenate all rows into one document.
            If set to False, a Document will be created for each item in the JSON.
            True by default.

        row_joiner (str): Separator to use for joining each row.
            Only used when `concat_rows=True`.
            Set to "\n" by default.

        json_config (dict): Options for parsing JSON. Can be used to specify options like
        custom decoding or formatting. Set to empty dict by default.

    """

    def __init__(
            self,
            *args: Any,
            concat_rows: bool = True,
            row_joiner: str = "\n",
            json_config: dict = {},
            **kwargs: Any
    ) -> None:
        """Init params."""
        super().__init__(*args, **kwargs)
        self._concat_rows = concat_rows
        self._row_joiner = row_joiner
        self._json_config = json_config

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, List[str]]:
        """Parse JSON file.

        Args:
            file (Path): Path to the .json file.
            errors (str): Error handling policy. Unused: JSON is read as strict
                UTF-8, and a file that is not valid UTF-8 is not valid JSON.

        Returns:
            Union[str, List[str]]: Concatenated rows if ``concat_rows`` is
            True, otherwise the parsed rows.

        Raises:
            DocumentParseError: When the file is not readable JSON. The raw
                ``JSONDecodeError``/``UnicodeDecodeError`` used to escape
                ``SimpleDirectoryReader.load_data``, which skips only
                ``DocumentParseError``, so one malformed file aborted the
                whole multi-file ingest; the attachment tasks autoretry every
                exception except ``DocumentParseError``, so a poison file
                also re-failed on every retry instead of failing once.
        """
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f, **self._json_config)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DocumentParseError(
                f"Failed to parse {Path(file).name}: not valid JSON ({exc})."
            ) from exc

        if not isinstance(data, list):
            data = [data]

        if self._concat_rows:
            return self._row_joiner.join([str(item) for item in data])
        else:
            return data
