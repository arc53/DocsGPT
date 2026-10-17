"""Shared HTML to Markdown conversion.

The file parser (``parser/file/html_parser.py``), the crawler
(``parser/remote/crawler_markdown.py``) and the web tool
(``agents/tools/read_webpage.py``) all produce Markdown from HTML and are meant to
produce the same shape, so the options and the converter live here rather than in
three copies.
"""

from typing import Any

from markdownify import MarkdownConverter

# The crawler's conventions, so file and web ingestion produce the same Markdown shape.
#
# ``table_infer_header``: a GFM table cannot start with a body row, so without
# it markdownify puts an empty header above any table that carries no ``<th>``
# and the column names end up in the first body row. Plenty of pages -- and
# every Word table converted to HTML -- are written that way, and the header is
# what gives each value in the table its meaning.
MARKDOWNIFY_OPTIONS = {
    "heading_style": "ATX",
    "newline_style": "BACKSLASH",
    "table_infer_header": True,
}

# Inline tags whose markdownify conversion runs the text through ``chomp()``, which
# lifts the surrounding whitespace out of the text and then returns an empty string
# once nothing is left. An element holding only whitespace therefore disappears
# together with its whitespace and the words on either side run together:
# ``Hello<b> </b>world`` is ingested as ``Helloworld``. An editor that emits one
# element per styled run produces exactly that for a space between two bold words,
# so it is ordinary page markup rather than an edge case.
_WHITESPACE_ONLY_PRESERVING_TAGS = frozenset(
    {
        "a",
        "b",
        "code",
        "del",
        "em",
        "i",
        "kbd",
        "s",
        "samp",
        "strong",
        "sub",
        "sup",
    }
)


def _whitespace_beside(el: Any) -> bool:
    """Whether the text right before or after ``el`` already separates it from its neighbours."""
    before, after = el.previous_sibling, el.next_sibling
    return (isinstance(before, str) and before[-1:].isspace()) or (isinstance(after, str) and after[:1].isspace())


class WhitespacePreservingConverter(MarkdownConverter):
    """markdownify's converter, with a whitespace-only inline element kept as a word boundary."""

    def get_conv_fn(self, tag_name: str) -> Any:
        convert_fn = super().get_conv_fn(tag_name)
        if convert_fn is None or tag_name.lower() not in _WHITESPACE_ONLY_PRESERVING_TAGS:
            return convert_fn

        def keep_whitespace_only(el: Any, text: str, *args: Any, **kwargs: Any) -> str:
            if text.strip():
                return convert_fn(el, text, *args, **kwargs)
            # Ordinary whitespace becomes one space, or none when a neighbour already
            # supplies it; a non-breaking space is content and stays as written.
            if not text or text.strip(" \t\r\n"):
                return text
            return "" if _whitespace_beside(el) else " "

        return keep_whitespace_only


def html_to_markdown_text(html: str, **options: Any) -> str:
    """Convert an HTML string to Markdown without losing the word boundaries it carries."""
    return WhitespacePreservingConverter(**{**MARKDOWNIFY_OPTIONS, **options}).convert(html)
