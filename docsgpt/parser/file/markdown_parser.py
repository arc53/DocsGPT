"""Markdown parser.

Contains parser for md files.

"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from docsgpt.parser.file.base_parser import BaseParser
from docsgpt.parser.tokenization import count_tokens_windowed

# Only these names count as tags, so prose like "x < 10" or "List<String>" survives.
_HTML_TAG_NAMES = """
    a abbr address area article aside audio b base bdi bdo blockquote body br button canvas caption
    center cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed
    fieldset figcaption figure font footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i
    iframe img input ins kbd label legend li link main map mark menu meta meter nav noscript object
    ol optgroup option output p param picture pre progress q rp rt ruby s samp script search
    section select slot small source span strike strong style sub summary sup svg table tbody td
    template textarea tfoot th thead time title tr track tt u ul var video wbr
""".split()
_HTML_TAG_PATTERN = "|".join(_HTML_TAG_NAMES)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG_LOWERCASE = re.compile(r"</?(?:%s)(?=[\s/>])[^<>]*>" % _HTML_TAG_PATTERN)
# Tag-shapes inside an <svg> are all markup, so strip them there rather than
# listing names like "path" globally, where they would eat prose placeholders.
_SVG_ELEMENT = re.compile(r"<svg(?=[\s/>])[^<>]*>.*?</svg\s*>", re.DOTALL | re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^<>]*>")
# Case only has to match for a bare tag, where <BR> cannot be told from
# Array<Map>. Attributes or a trailing slash mark it as markup either way.
_HTML_TAG_ANY_CASE = re.compile(
    r"</?(?:%s)(?:\s+[^\s<>][^<>]*|\s*/)>" % _HTML_TAG_PATTERN,
    re.IGNORECASE,
)
# A bare tag is markup when the same name closes somewhere in the text, however
# it nests. Collected first, since removing pairs one at a time would orphan the
# opening tag of any nested pair.
_HTML_BARE_TAG = re.compile(r"</?(%s)\s*>" % _HTML_TAG_PATTERN, re.IGNORECASE)
_HTML_CLOSING_TAG = re.compile(r"</(%s)\s*>" % _HTML_TAG_PATTERN, re.IGNORECASE)


def _strip_html(text: str) -> str:
    """Remove inline SVG markup, known HTML tags and HTML comments from text.

    Comments go first, so a tag commented out cannot make a generic argument of
    the same name look like markup.
    """
    text = _HTML_COMMENT.sub("", text)
    text = _SVG_ELEMENT.sub(lambda match: _ANY_TAG.sub("", match.group(0)), text)
    text = _HTML_TAG_ANY_CASE.sub("", text)
    closed = {match.group(1).lower() for match in _HTML_CLOSING_TAG.finditer(text)}
    if closed:
        text = _HTML_BARE_TAG.sub(
            lambda match: "" if match.group(1).lower() in closed else match.group(0), text
        )
    return _HTML_TAG_LOWERCASE.sub("", text)


# A fenced code block opens with three or more backticks or tildes, indented by
# at most three spaces (CommonMark). Backtick info strings cannot hold backticks.
_FENCE_OPEN = re.compile(r"^ {0,3}(?:(`{3,})[^`]*|(~{3,}).*)$")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t\r]*$")


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
        num_tokens = count_tokens_windowed(current_text)
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
                (re.sub(r"#", "", cast(str, key)).strip(), _strip_html(value))
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
