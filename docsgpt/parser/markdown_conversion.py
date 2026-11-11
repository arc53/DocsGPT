"""The markdownify converter every HTML to Markdown path in DocsGPT uses.

The file parser (``parser/file/html_parser.py``), the web extractor
(``parser/remote/page_content.py``) and the web tool (``agents/tools/read_webpage.py``)
convert with ``WhitespacePreservingConverter`` and the shared ``MARKDOWNIFY_OPTIONS``, so
a word boundary that a styled space carries survives all three.
"""

from typing import Any

from markdownify import MarkdownConverter

from docsgpt.parser.file.html_parser import MARKDOWNIFY_OPTIONS

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


def _whitespace_only_inline(node: Any) -> bool:
    """Whether ``node`` is an inline element this converter turns into one space or none."""
    name = getattr(node, "name", None)
    if not isinstance(name, str) or name.lower() not in _WHITESPACE_ONLY_PRESERVING_TAGS:
        return False
    text = node.get_text()
    return bool(text) and not text.strip(" \t\r\n")


def _whitespace_beside(el: Any) -> bool:
    """Whether the text around ``el`` already separates it from its neighbours.

    A run of whitespace-only elements, such as ``<b> </b><i> </i>``, gives one space between
    the words around it: the first decides, by the text before it and after the run, and the
    rest give none.
    """
    before = el.previous_sibling
    if _whitespace_only_inline(before):
        return True
    after = el.next_sibling
    while _whitespace_only_inline(after):
        after = after.next_sibling
    return (isinstance(before, str) and before[-1:].isspace()) or (isinstance(after, str) and after[:1].isspace())


class WhitespacePreservingConverter(MarkdownConverter):
    """markdownify's converter, with a whitespace-only inline element kept as a word boundary."""

    def get_conv_fn(self, tag_name: str) -> Any:
        convert_fn = super().get_conv_fn(tag_name)
        if convert_fn is None or tag_name.lower() not in _WHITESPACE_ONLY_PRESERVING_TAGS:
            return convert_fn

        def keep_whitespace_only(el: Any, text: str, *args: Any, **kwargs: Any) -> str:
            # Inside <pre> markdownify keeps whitespace as written (the ``_noformat``
            # pseudo-tag), so the tag's own conversion decides there.
            parent_tags = kwargs.get("parent_tags", args[0] if args else ())
            if text.strip() or "_noformat" in parent_tags:
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
