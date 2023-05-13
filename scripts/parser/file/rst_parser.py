"""reStructuredText parser.

Contains parser for md files.

"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from parser.file.base_parser import BaseParser


class RstParser(BaseParser):
    """reStructuredText parser.

    Extract text from .rst files.
    Returns dictionary with keys as headers and values as the text between headers.

    """

    def __init__(
            self,
            *args: Any,
            remove_hyperlinks: bool = True,
            remove_images: bool = True,
            remove_table_excess: bool = True,
            remove_interpreters: bool = True,
            remove_directives: bool = True,
            remove_whitespaces_excess: bool = True,
            # Be carefull with remove_characters_excess, might cause data loss
            remove_characters_excess: bool = True,
            **kwargs: Any,
    ) -> None:
        """Init params."""
        super().__init__(*args, **kwargs)
        self._remove_hyperlinks = remove_hyperlinks
        self._remove_images = remove_images
        self._remove_table_excess = remove_table_excess
        self._remove_interpreters = remove_interpreters
        self._remove_directives = remove_directives
        self._remove_whitespaces_excess = remove_whitespaces_excess
        self._remove_characters_excess = remove_characters_excess

    def rst_to_tups(self, rst_text: str) -> List[Tuple[Optional[str], str]]:
        """Convert a reStructuredText file to a dictionary.

        The keys are the headers and the values are the text under each header.

        """
        rst_tups: List[Tuple[Optional[str], str]] = []
        lines = rst_text.split("\n")

        current_header = None
        current_text = ""

        for i, line in enumerate(lines):
            header_match = re.match(r"^[^\S\n]*[-=]+[^\S\n]*$", line)
            if header_match and i > 0 and (
                    len(lines[i - 1].strip()) == len(header_match.group().strip()) or lines[i - 2] == lines[i - 2]):
                if current_header is not None:
                    if current_text == "" or None:
                        continue
                    # removes the next heading from current Document
                    if current_text.endswith(lines[i - 1] + "\n"):
                        current_text = current_text[:len(current_text) - len(lines[i - 1] + "\n")]
                    rst_tups.append((current_header, current_text))

                current_header = lines[i - 1]
                current_text = ""
            else:
                current_text += line + "\n"

        rst_tups.append((current_header, current_text))

        # TODO: Format for rst
        #
        # if current_header is not None:
        #     # pass linting, assert keys are defined
        #     rst_tups = [
        #         (re.sub(r"#", "", cast(str, key)).strip(), re.sub(r"<.*?>", "", value))
        #         for key, value in rst_tups
        #     ]
        # else:
        #     rst_tups = [
        #         (key, re.sub("\n", "", value)) for key, value in rst_tups
        #     ]

        if current_header is None:
            rst_tups = [
                (key, re.sub("\n", "", value)) for key, value in rst_tups
            ]
        return rst_tups

    def remove_images(self, content: str) -> str:
        pattern = r"\.\. image:: (.*)"
        content = re.sub(pattern, "", content)
        return content

    def remove_hyperlinks(self, content: str) -> str:
        pattern = r"`(.*?) <(.*?)>`_"
        content = re.sub(pattern, r"\1", content)
        return content

    def remove_directives(self, content: str) -> str:
        """Removes reStructuredText Directives"""
        pattern = r"`\.\.([^:]+)::"
        content = re.sub(pattern, "", content)
        return content

    def remove_interpreters(self, content: str) -> str:
        """Removes reStructuredText Interpreted Text Roles"""
        pattern = r":(\w+):"
        content = re.sub(pattern, "", content)
        return content

    def remove_table_excess(self, content: str) -> str:
        """Pattern to remove grid table separators"""
        pattern = r"^\+[-]+\+[-]+\+$"
        content = re.sub(pattern, "", content, flags=re.MULTILINE)
        return content

    def remove_whitespaces_excess(self, content: List[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
        """Pattern to match 2 or more consecutive whitespaces"""
        pattern = r"\s{2,}"
        content = [(key, re.sub(pattern, "  ", value)) for key, value in content]
        return content

    def remove_characters_excess(self, content: List[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
        """Pattern to match 2 or more consecutive characters"""
        pattern = r"(\S)\1{2,}"
        content = [(key, re.sub(pattern, r"\1\1\1", value, flags=re.MULTILINE)) for key, value in content]
        return content

    def _init_parser(self) -> Dict:
        """Initialize the parser with the config."""
        return {}

    def parse_tups(
            self, filepath: Path, errors: str = "ignore"
    ) -> List[Tuple[Optional[str], str]]:
        """Parse file into tuples."""
        with open(filepath, "r") as f:
            content = f.read()
        if self._remove_hyperlinks:
            content = self.remove_hyperlinks(content)
        if self._remove_images:
            content = self.remove_images(content)
        if self._remove_table_excess:
            content = self.remove_table_excess(content)
        if self._remove_directives:
            content = self.remove_directives(content)
        if self._remove_interpreters:
            content = self.remove_interpreters(content)
        rst_tups = self.rst_to_tups(content)
        if self._remove_whitespaces_excess:
            rst_tups = self.remove_whitespaces_excess(rst_tups)
        if self._remove_characters_excess:
            rst_tups = self.remove_characters_excess(rst_tups)
        return rst_tups

    def parse_file(
            self, filepath: Path, errors: str = "ignore"
    ) -> Union[str, List[str]]:
        """Parse file into string."""
        tups = self.parse_tups(filepath, errors=errors)
        results = []
        # TODO: don't include headers right now
        for header, value in tups:
            if header is None:
                results.append(value)
            else:
                results.append(f"\n\n{header}\n{value}")
        return results
