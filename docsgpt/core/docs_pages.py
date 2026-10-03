"""Read and set the ``lastUpdated`` date in a docs page's frontmatter.

Every page under ``docs/content`` carries ``lastUpdated: YYYY-MM-DD``. The docs
site shows it on the page and uses it for the sitemap's ``lastmod`` and the
page's structured data, so it should move only when the content does. The
generators that write docs pages keep it current with these helpers.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?\r?\n)?---", re.S)
_FIELD = re.compile(r"^lastUpdated:[ \t]*(['\"]?)(\d{4}-\d{2}-\d{2})\1[ \t]*$", re.M)


def today() -> str:
    """Today's date as ``YYYY-MM-DD``, the format ``lastUpdated`` uses."""
    return date.today().isoformat()


def read_last_updated(text: str) -> Optional[str]:
    """Return a page's ``lastUpdated`` date.

    Args:
        text: The page source, frontmatter included.

    Returns:
        The date as ``YYYY-MM-DD``, or None when the frontmatter has no
        ``lastUpdated`` field (or the page has no frontmatter).
    """
    frontmatter = _FRONTMATTER.match(text)
    if not frontmatter or frontmatter.group(1) is None:
        return None
    field = _FIELD.search(frontmatter.group(1))
    return field.group(2) if field else None


def set_last_updated(text: str, day: str) -> str:
    """Return the page with its ``lastUpdated`` date set to ``day``.

    The field is replaced where it is, or added as the last frontmatter line.

    Args:
        text: The page source, frontmatter included.
        day: The new date, ``YYYY-MM-DD``.

    Returns:
        The page source with the new date; the body is untouched.

    Raises:
        ValueError: The page has no frontmatter block.
    """
    frontmatter = _FRONTMATTER.match(text)
    if not frontmatter:
        raise ValueError("page has no frontmatter block")
    block = frontmatter.group(1) or ""
    if _FIELD.search(block):
        block = _FIELD.sub(f"lastUpdated: {day}", block, count=1)
    else:
        block += f"lastUpdated: {day}\n"
    return f"---\n{block}---" + text[frontmatter.end():]
