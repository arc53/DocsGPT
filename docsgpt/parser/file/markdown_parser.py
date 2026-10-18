"""Markdown parser.

Contains parser for md files.

"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from docsgpt.parser.file.base_parser import BaseParser
from docsgpt.utils import num_tokens_from_string

# A fenced code block opens with three or more backticks or tildes, indented by
# at most three spaces (CommonMark). Backtick info strings cannot hold backticks.
_FENCE_OPEN = re.compile(r"^ {0,3}(?:(`{3,})[^`]*|(~{3,}).*)$")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")


class MarkdownParser(BaseParser):
    """Markdown parser.

    Extract text from markdown files.
    Returns dictionary with keys as headers and values as the text between headers.

    """

    def __init__(
            self,
            *args: Any,
            remove_hyperlinks: bool = True,
            remove_images: bool = True,
            max_tokens: int = 2048,
            # remove_tables: bool = True,
            **kwargs: Any,
    ) -> None:
        """Init params."""
        super().__init__(*args, **kwargs)
        self._remove_hyperlinks = remove_hyperlinks
        self._remove_images = remove_images
        self._max_tokens = max_tokens
        # self._remove_tables = remove_tables

    def tups_chunk_append(self, tups: List[Tuple[Optional[str], str]], current_header: Optional[str],
                          current_text: str):
        """Append to tups chunk."""
        num_tokens = num_tokens_from_string(current_text)
        if num_tokens > self._max_tokens:
            chunks = [current_text[i:i + self._max_tokens] for i in range(0, len(current_text), self._max_tokens)]
            for chunk in chunks:
                tups.append((current_header, chunk))
        else:
            tups.append((current_header, current_text))
        return tups

    def markdown_to_tups(self, markdown_text: str) -> List[Tuple[Optional[str], str]]:
        """Convert a markdown file to a dictionary.

        The keys are the headers and the values are the text under each header.

        """
        markdown_tups: List[Tuple[Optional[str], str]] = []
        lines = markdown_text.split("\n")

        current_header = None
        current_text = ""
        # Marker of the open fenced code block, or None outside a code block.
        open_fence: Optional[str] = None

        for line in lines:
            # A "#" line inside a fenced code block is code (a shell comment, say), not a heading.
            in_code_block = open_fence is not None
            open_fence = self._next_fence_state(line, open_fence)
            header_match = None if in_code_block else re.match(r"^#+\s", line)
            if header_match:
                if current_header is not None:
                    if current_text == "" or None:
                        continue
                    markdown_tups = self.tups_chunk_append(markdown_tups, current_header, current_text)

                current_header = line
                current_text = ""
            else:
                current_text += line + "\n"
        markdown_tups = self.tups_chunk_append(markdown_tups, current_header, current_text)

        if current_header is not None:
            # pass linting, assert keys are defined
            markdown_tups = [
                (re.sub(r"#", "", cast(str, key)).strip(), re.sub(r"<.*?>", "", value))
                for key, value in markdown_tups
            ]
        else:
            markdown_tups = [
                (key, re.sub("\n", "", value)) for key, value in markdown_tups
            ]

        return markdown_tups

    @staticmethod
    def _next_fence_state(line: str, open_fence: Optional[str]) -> Optional[str]:
        """Track whether the parser is inside a fenced code block.

        Args:
            line: A single line of markdown, without the trailing newline.
            open_fence: The marker of the currently open fence, or None.

        Returns:
            The marker of the fence that is open after this line, or None.
        """
        if open_fence is None:
            match = _FENCE_OPEN.match(line)
            return (match.group(1) or match.group(2)) if match else None
        close = _FENCE_CLOSE.match(line)
        # A fence is closed by the same character, repeated at least as many times.
        if close and close.group(1)[0] == open_fence[0] and len(close.group(1)) >= len(open_fence):
            return None
        return open_fence

    def remove_images(self, content: str) -> str:
        """Get a dictionary of a markdown file from its path."""
        pattern = r"!{1}\[\[(.*)\]\]"
        content = re.sub(pattern, "", content)
        return content

    # def remove_tables(self, content: str) -> List[List[str]]:
    #     """Convert markdown tables to nested lists."""
    #     table_rows_pattern = r"((\r?\n){2}|^)([^\r\n]*\|[^\r\n]*(\r?\n)?)+(?=(\r?\n){2}|$)"
    #     table_cells_pattern = r"([^\|\r\n]*)\|"
    #
    #     table_rows = re.findall(table_rows_pattern, content, re.MULTILINE)
    #     table_lists = []
    #     for row in table_rows:
    #         cells = re.findall(table_cells_pattern, row[2])
    #         cells = [cell.strip() for cell in cells if cell.strip()]
    #         table_lists.append(cells)
    #     return str(table_lists)

    def remove_hyperlinks(self, content: str) -> str:
        """Get a dictionary of a markdown file from its path."""
        pattern = r"\[(.*?)\]\((.*?)\)"
        content = re.sub(pattern, r"\1", content)
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
        # if self._remove_tables:
        #     content = self.remove_tables(content)
        markdown_tups = self.markdown_to_tups(content)
        return markdown_tups

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
