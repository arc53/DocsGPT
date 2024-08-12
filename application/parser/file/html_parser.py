"""HTML parser.

Contains parser for html files.

"""
import re
from pathlib import Path
from typing import Dict, Union

from application.parser.file.base_parser import BaseParser


class HTMLParser(BaseParser):
    """HTML parser."""

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, list[str]]:
        from langchain_community.document_loaders import BSHTMLLoader

        loader = BSHTMLLoader(file)
        data = loader.load()        
        return data
