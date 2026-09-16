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

# A <pre> is the one place the whitespace is the content, so its text is lifted
# out before the rest is normalised and put back afterwards. A page that carries
# this exact text is read as text: the lookup is bounds-checked.
_PREFORMATTED_MARK = "\x00docsgpt-pre-{}\x00"

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
    """Return the visible text of ``soup``, one line per block."""
    for line_break in soup.find_all("br"):
        line_break.replace_with("\n")

    preformatted = []
    for block in soup.find_all("pre"):
        if block.parent is None:  # a <pre> inside a <pre> that already went
            continue
        mark = _PREFORMATTED_MARK.format(len(preformatted))
        preformatted.append(block.get_text().strip("\n"))
        block.replace_with(NavigableString(f"\n{mark}\n"))

    for block in soup.find_all(BLOCK_LEVEL_TAGS):
        block.append("\n")

    lines = []
    for line in soup.get_text().splitlines():
        stripped = line.strip()
        block_text = _preformatted_at(stripped, preformatted)
        if block_text is not None:
            lines.append(block_text)
        elif stripped:
            lines.append(stripped)
    return "\n".join(lines)


def _preformatted_at(line: str, blocks: "list[str]") -> "str | None":
    """Return the lifted-out ``<pre>`` this line stands for, if it stands for one."""
    prefix, suffix = _PREFORMATTED_MARK.split("{}")
    if not (line.startswith(prefix) and line.endswith(suffix)):
        return None
    try:
        index = int(line[len(prefix) : -len(suffix)])
    except ValueError:
        return None
    return blocks[index] if 0 <= index < len(blocks) else None
