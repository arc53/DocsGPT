"""Epub parser.

Contains parsers for epub files.
"""

from pathlib import Path
from typing import Dict

from application.parser.file.base_parser import BaseParser


class EpubParser(BaseParser):
    """Epub Parser."""

    def _init_parser(self) -> Dict:
        """Init parser."""
        return {}

    def parse_file(self, file: Path, errors: str = "ignore") -> str:
        """Parse file."""
        try:
            from fast_ebook import epub
        except ImportError:
            raise ValueError("`fast-ebook` is required to read Epub files.")

        book = epub.read_epub(file)
        text = book.to_markdown()
        return text
