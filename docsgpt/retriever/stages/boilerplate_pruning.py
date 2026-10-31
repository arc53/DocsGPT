"""Extractive boilerplate pruning stage for DocsGPT.

Prunes clearly identifiable navigation and duplicate boilerplate from retrieved
chunks post-retrieval while leaving factual prose, code blocks, tables, and
qualifiers untouched.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Factual qualifiers, negations, and cautionary markers that MUST NEVER be pruned
_PROTECTED_QUALIFIERS = {
    "not", "never", "cannot", "cant", "wont", "neither", "none", "must",
    "required", "only", "except", "unless", "deprecated", "caution", "warning",
    "critical", "danger", "note", "important", "always"
}

# Regex for clearly identifiable navigation patterns
_BREADCRUMB_RE = re.compile(
    r"^(?:[\w\s\-]+(?:\s*[›>»/|\\]\s*[\w\s\-]+)+|(?:\*?\s*\[[^\]]+\]\([^\)]+\)\s*[›>»/|\\]\s*)+\[?[^\]]*\]?)$",
    re.IGNORECASE
)

_NAV_CONTROL_RE = re.compile(
    r"^(?:#+\s*)?(?:table of contents|on this page|in this article|quick links|"
    r"skip to (?:main )?content|back to top|return to top|"
    r"previous page:?.*|next page:?.*|«\s*previous\s*|\s*next\s*»|"
    r"edit this page(?: on github)?|was this (?:page|article) helpful\??|"
    r"share this page|print this page)$",
    re.IGNORECASE
)

_PAGINATION_LINK_RE = re.compile(
    r"^\[\s*(?:«?\s*previous|\s*next\s*»)\s*\]\([^\)]+\)$",
    re.IGNORECASE
)


def _tokenize_query(query: str) -> Set[str]:
    """Extract lowercase alphanumeric query keywords for term preservation."""
    if not query:
        return set()
    return {w.lower() for w in re.findall(r"\b\w{2,}\b", query)}


def _is_protected_line(line: str, query_tokens: Set[str]) -> bool:
    """Determine whether a line contains protected syntax, qualifiers, or query terms."""
    stripped = line.strip()
    if not stripped:
        return True

    # 1. Code blocks and tables
    if stripped.startswith("```") or stripped.startswith("~~~") or stripped.startswith("|"):
        return True
    if "`" in stripped:
        return True

    # 2. Query term overlap
    words = set(re.findall(r"\b\w+\b", stripped.lower()))
    if query_tokens and words.intersection(query_tokens):
        return True

    # 3. Factual qualifiers, polarity, or negations
    if words.intersection(_PROTECTED_QUALIFIERS):
        return True

    # 4. URLs (unless a pagination link)
    if "http://" in stripped or "https://" in stripped:
        if not _PAGINATION_LINK_RE.match(stripped):
            return True

    return False


def _is_navigation_boilerplate(line: str) -> bool:
    """Check if a line matches clearly identifiable navigation boilerplate."""
    stripped = line.strip()
    if not stripped:
        return False

    if _NAV_CONTROL_RE.match(stripped):
        return True
    if _BREADCRUMB_RE.match(stripped):
        return True
    if _PAGINATION_LINK_RE.match(stripped):
        return True

    return False


def prune_chunk_text(
    text: str,
    query: str = "",
    seen_boilerplate: Optional[Set[str]] = None
) -> str:
    """Extractive pruning of navigation boilerplate and duplicate lines from a single chunk."""
    if not text:
        return ""

    query_tokens = _tokenize_query(query)
    lines = text.split("\n")
    cleaned_lines: List[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        # Track fenced code block state
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            cleaned_lines.append(line)
            continue

        if in_code_block:
            cleaned_lines.append(line)
            continue

        # Check for navigation boilerplate first
        if _is_navigation_boilerplate(line):
            continue

        # Check for exact duplicate boilerplate across chunks in same retrieval
        if seen_boilerplate is not None and not stripped.startswith("|"):
            norm_line = stripped.lower()
            if len(norm_line) < 120 and norm_line in seen_boilerplate:
                continue
            seen_boilerplate.add(norm_line)

        # If line contains protected elements, preserve untouched
        if _is_protected_line(line, query_tokens):
            cleaned_lines.append(line)
            continue

        cleaned_lines.append(line)

    # Collapse multiple consecutive empty lines
    result: List[str] = []
    prev_empty = False
    for line in cleaned_lines:
        is_empty = not line.strip()
        if is_empty and prev_empty:
            continue
        result.append(line)
        prev_empty = is_empty

    return "\n".join(result).strip()


def prune_boilerplate(
    docs: List[Dict[str, Any]],
    query: str = ""
) -> List[Dict[str, Any]]:
    """Prunes navigation and duplicate boilerplate across the final retrieved documents."""
    if not docs:
        return docs

    seen_boilerplate: Set[str] = set()
    pruned_docs: List[Dict[str, Any]] = []

    for doc in docs:
        # Create a shallow copy to preserve original dict references if needed
        pruned_doc = dict(doc)
        text = doc.get("text")
        if isinstance(text, str) and text:
            pruned_doc["text"] = prune_chunk_text(
                text,
                query=query,
                seen_boilerplate=seen_boilerplate
            )
        pruned_docs.append(pruned_doc)

    return pruned_docs
