import json
from typing import Any, Dict, List, Union
from pathlib import Path

from application.parser.file.base_parser import BaseParser

class JSONParser(BaseParser):
    r"""JSON (.json) parser.

    Parses JSON files into a list of strings or a concatenated document.
    It handles both JSON objects (dictionaries) and arrays (lists).

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
        """Parse JSON file."""
        
        with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f, **self._json_config)

        if isinstance(data, dict):
            data = [data]

        if self._concat_rows:
            return self._row_joiner.join([str(item) for item in data])
        else:
            return data
