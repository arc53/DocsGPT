"""Flatten parsed HTML to the text a reader sees.

Every HTML reader in this package used to call
``soup.get_text(separator="\\n")``. BeautifulSoup puts that separator between
**every** pair of strings, and it counts the text of each inline element as its
own string, so the newline lands inside sentences as well as between blocks::

    <p>Hello <b>world</b>! See <a href="#">this</a>.</p>
    -> "Hello\\nworld\\n! See\\nthis\\n."

A block boundary is the only place the markup puts a line break, so that is the
only place one belongs.
"""

import re
from typing import TYPE_CHECKING

from bs4 import NavigableString

if TYPE_CHECKING:  # pragma: no cover - import cost, and bs4 is loaded lazily
    from bs4 import BeautifulSoup

_END_OF_CHILDREN = object()

# The whitespace HTML collapses outside <pre>. A non-breaking space is not part of it.
_COLLAPSIBLE_WHITESPACE = re.compile(r"[ \t\n\r\f]+")

# Elements a browser lays out on a line of their own, plus the few that are not
# laid out at all but still read as a line when the document is flattened
# (`title`, `option`).
BLOCK_LEVEL_TAGS = (
    "address",
    "article",
    "aside",
    "blockquote",
    "caption",
    "center",
    "dd",
    "div",
    "dl",
    "dt",
    "details",
    "dialog",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hgroup",
    "hr",
    "legend",
    "li",
    "main",
    "menu",
    "nav",
    "ol",
    "option",
    "p",
    "pre",
    "search",
    "section",
    "summary",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "title",
    "tr",
    "ul",
)


def html_to_text(soup: "BeautifulSoup") -> str:
    """Return the visible text of ``soup``, one line per block.

    A line break is written at the start and end of each block-level element
    and at each ``<br>``. Everywhere else whitespace collapses to one space, as
    in a browser, and two inline elements with nothing between them, such as
    ``<a>Home</a><a>Docs</a>``, are kept apart by a space; text that touches an
    element (``<b>world</b>!``) is joined as written. Lines are stripped and
    blank lines dropped. A ``<pre>`` is the one place the whitespace is the
    content, so its text is kept exactly as it is.

    The tree is walked once and left unchanged. Replacing each ``<br>`` in
    place scans its siblings on every call, which is quadratic on a page made
    of tens of thousands of them.
    """
    # The strings get_text() joins: script, style and template text stays out
    # exactly as it does there.
    wanted = {id(string) for string in soup.strings}
    lines: "list[str]" = []
    text: "list[str]" = []
    preformatted: "list[str]" = []
    pre_depth = 0

    def flush_text() -> None:
        for line in "".join(text).splitlines():
            line = re.sub(" {2,}", " ", line).strip()
            if line:
                lines.append(line)
        text.clear()

    children = [iter(soup.contents)]
    open_tags: "list[str | None]" = [None]
    # Per open element: whether its last child so far was an inline element.
    after_inline: "list[bool]" = [False]
    while children:
        node = next(children[-1], _END_OF_CHILDREN)
        if node is _END_OF_CHILDREN:
            children.pop()
            after_inline.pop()
            name = open_tags.pop()
            if name == "pre":
                pre_depth -= 1
                if not pre_depth:
                    block = "".join(preformatted).strip("\n")
                    preformatted.clear()
                    if block:
                        lines.append(block)
            elif name in BLOCK_LEVEL_TAGS and not pre_depth:
                text.append("\n")
            continue

        sink = preformatted if pre_depth else text
        if isinstance(node, NavigableString):
            if id(node) in wanted:
                sink.append(node if pre_depth else _COLLAPSIBLE_WHITESPACE.sub(" ", node))
                after_inline[-1] = False
        elif node.name == "br":
            sink.append("\n")
            after_inline[-1] = False
        else:
            inline = node.name != "pre" and node.name not in BLOCK_LEVEL_TAGS
            if node.name == "pre":
                if not pre_depth:
                    flush_text()
                pre_depth += 1
            elif node.name in BLOCK_LEVEL_TAGS and not pre_depth:
                text.append("\n")
            elif after_inline[-1] and not pre_depth:
                sink.append(" ")
            after_inline[-1] = inline
            children.append(iter(node.contents))
            open_tags.append(node.name)
            after_inline.append(False)

    flush_text()
    return "\n".join(lines)
