"""HTML parser.

Contains parser for html files.

"""
from pathlib import Path
from typing import Dict, Union

from application.parser.file.base_parser import BaseParser


class HTMLParser(BaseParser):
    """HTML parser."""

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> Union[str, list[str]]:
        """Extract the visible text of an HTML file.

        Returns the text as a string, matching the other file parsers — the
        title is recovered separately by ``get_file_metadata``.
        """
        from bs4 import BeautifulSoup

        with open(file, "r", errors=errors) as f:
            soup = BeautifulSoup(f, "html.parser")
        return soup.get_text("\n")

    def get_file_metadata(self, file: Path) -> Dict:
        """Return the document title, when the markup carries one."""
        from bs4 import BeautifulSoup

        try:
            with open(file, "r", errors="ignore") as f:
                soup = BeautifulSoup(f, "html.parser")
        except OSError:
            return {}
        if soup.title and soup.title.string:
            return {"title": str(soup.title.string)}
        return {}
