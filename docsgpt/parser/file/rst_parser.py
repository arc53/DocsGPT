"""reStructuredText parser.

Contains parser for md files.

"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from docsgpt.parser.file.base_parser import BaseParser


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
            # Be careful with remove_characters_excess, might cause data loss
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
            title_line = lines[i - 1] if header_match and i > 0 else ""
            title_len = len(title_line.strip())
            underline_len = len(header_match.group().strip()) if header_match else 0
            # A line of dashes/equals is a real section underline if the
            # line above it is an actual title (non-blank -- a heading
            # cannot have an empty title, so a blank line never counts,
            # even though its stripped length of 0 would otherwise satisfy
            # the length checks below) AND that underline is either at
            # least as long as the title (the common case), OR merely too
            # short for that title but still at least 4 characters:
            # docutils still parses this as a heading (emitting only a
            # "Title underline too short" warning, not rejecting it), so a
            # 4+ character underline under a longer title is still a real
            # section title, not ordinary text.
            if header_match and i > 0 and title_len > 0 and (
                    underline_len >= title_len or underline_len >= 4):
                # Strip the header's own title line back out of the text
                # accumulated so far, whether that text belongs to a
                # previous section (current_header is set) or is preamble
                # before the document's first header (current_header is
                # still None). Previously this whole block was skipped
                # whenever current_header was None, which silently
                # discarded any preamble text preceding the first header.
                if current_text.endswith(lines[i - 1] + "\n"):
                    # removes the next heading from current Document
                    current_text = current_text[:len(current_text) - len(lines[i - 1] + "\n")]
                    # An overline-style title (====\nTitle\n====) has a
                    # second adornment line directly above the title line
                    # we just removed. That line is decoration, not real
                    # preamble content, so strip it too when present -- but
                    # only when i >= 2, since lines[i - 2] is meaningless
                    # (wraps to the document's last line) for a header this
                    # close to the start of the document.
                    if i >= 2:
                        overline_candidate = lines[i - 2]
                        # reStructuredText requires an overline to match its
                        # underline exactly (same character, same length).
                        # A different adornment line (e.g. a "----" divider
                        # above a "=====" underline) is ordinary content and
                        # must stay in the preamble.
                        if (overline_candidate.strip() == header_match.group().strip()
                                and current_text.endswith(overline_candidate + "\n")):
                            current_text = current_text[:len(current_text) - len(overline_candidate + "\n")]
                # Skip the tuple only when there is truly nothing to keep:
                # no real header yet AND nothing but whitespace accumulated
                # (e.g. a header at the very start of the document, or a
                # file beginning with a blank line before its first
                # heading). .strip() rather than a bare "" check so a
                # whitespace-only preamble isn't silently kept as an empty
                # chunk either. A titled section's own text is always kept,
                # even if empty, since current_header is not None there.
                if current_text.strip() != "" or current_header is not None:
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

    def chunk_by_token_count(self, text: str, max_tokens: int = 100) -> List[str]:
        """Chunk text by token count."""
    
        avg_token_length = 5
    
        chunk_size = max_tokens * avg_token_length

        chunks = []
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i+chunk_size]
            if i + chunk_size < len(text):
                last_space = chunk.rfind(' ')
                if last_space != -1:
                    chunk = chunk[:last_space]
            
            chunks.append(chunk.strip())
        
        return chunks
    
    def remove_images(self, content: str) -> str:
        pattern = r"\.\. image:: (.*)"
        content = re.sub(pattern, "", content)
        return content

    def remove_hyperlinks(self, content: str) -> str:
        pattern = r"`(.*?) <(.*?)>`_"
        content = re.sub(pattern, r"\1", content)
        return content

    def remove_directives(self, content: str) -> str:
        """Remove standard reStructuredText directive markers."""
        pattern = r"^[ \t]*\.\.[ \t]+[\w-]+::[ \t]*"
        return re.sub(pattern, "", content, flags=re.MULTILINE)

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
            self, filepath: Path, errors: str = "ignore",max_tokens: Optional[int] = 1000
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

        # Apply chunking if max_tokens is provided
        if max_tokens is not None:
            chunked_tups = []
            for header, text in rst_tups:
                chunks = self.chunk_by_token_count(text, max_tokens)
                for idx, chunk in enumerate(chunks):
                    chunked_tups.append((f"{header} - Chunk {idx + 1}", chunk))
            return chunked_tups    
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
