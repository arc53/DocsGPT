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

from typing import TYPE_CHECKING

from bs4 import NavigableString

if TYPE_CHECKING:  # pragma: no cover - import cost, and bs4 is loaded lazily
    from bs4 import BeautifulSoup

_END_OF_CHILDREN = object()

# Elements a browser lays out on a line of their own, plus the few that are not
# laid out at all but still read as a line when the document is flattened
# (`title`, `option`).
BLOCK_LEVEL_TAGS = (
    "address",
    "article",
    "aside",
    "blockquote",
    "caption",
    "dd",
    "div",
    "dl",
    "dt",
    "details",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
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
    "nav",
    "ol",
    "option",
    "p",
    "pre",
    "section",
    "summary",
    "table",
    "td",
    "th",
    "title",
    "tr",
    "ul",
)


def html_to_text(soup: "BeautifulSoup") -> str:
    """Return the visible text of ``soup``, one line per block.

    A line break is written at the start and end of each block-level element
    and at each ``<br>``; ordinary text is stripped line by line and blank
    lines are dropped. A ``<pre>`` is the one place the whitespace is the
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
            if line.strip():
                lines.append(line.strip())
        text.clear()

    children = [iter(soup.contents)]
    open_tags: "list[str | None]" = [None]
    while children:
        node = next(children[-1], _END_OF_CHILDREN)
        if node is _END_OF_CHILDREN:
            children.pop()
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
                sink.append(node)
        elif node.name == "br":
            sink.append("\n")
        else:
            if node.name == "pre":
                if not pre_depth:
                    flush_text()
                pre_depth += 1
            elif node.name in BLOCK_LEVEL_TAGS and not pre_depth:
                text.append("\n")
            children.append(iter(node.contents))
            open_tags.append(node.name)

    flush_text()
    return "\n".join(lines)
