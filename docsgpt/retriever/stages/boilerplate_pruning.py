"""Extractive boilerplate pruning stage for DocsGPT.

Prunes clearly identifiable navigation and duplicate boilerplate from retrieved
chunks post-retrieval while leaving factual prose, code blocks, tables, and
qualifiers untouched.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

# Factual qualifiers, negations, and cautionary markers that MUST NEVER be pruned
_PROTECTED_QUALIFIERS = {
    "not",
    "never",
    "cannot",
    "cant",
    "can't",
    "wont",
    "won't",
    "don't",
    "neither",
    "none",
    "must",
    "required",
    "only",
    "except",
    "unless",
    "deprecated",
    "caution",
    "warning",
    "critical",
    "danger",
    "note",
    "important",
    "always",
}

# Regex for clearly identifiable breadcrumb patterns:
# Supports 'Home > API', 'Home / Guides / Setup', 'Docs » Reference', markdown link breadcrumbs
_BREADCRUMB_RE = re.compile(
    r"^(?:(?:\*?\s*\[[^\]]+\]\([^\)]+\)\s*|[\w\-&]+(?:\s+[\w\-&]+){0,2}\s*)(?:[›»>]|/(?!\S))\s*)+"
    r"(?:\[[^\]]+\]\([^\)]+\)|[\w\-&]+(?:\s+[\w\-&]+){0,2})?\s*$",
    re.IGNORECASE,
)

_NAV_VERBS = (
    r"is|are|was|were|be|been|being|have|has|had|do|does|did|will|would|shall|should|"
    r"may|might|must|can|could|returns?|returning|returned|requires?|requiring|required|"
    r"fails?|failing|failed|sends?|sending|sent|receives?|receiving|received|responds?|responding|responded|"
    r"access(?:es|ed|ing)?|allows?|allowing|allowed|provides?|providing|provided|uses?|using|used|"
    r"expires?|expiring|expired"
)

# Navigation label after a colon: bracketed links, arrows, page numbers, or
# short word sequences (up to 6 words) that do not contain a known verb.
_NAV_LABEL_COLON_PAT = (
    r"(?:"
    r"\[(?!.*?\b(?:" + _NAV_VERBS + r")\b)[^\]\r\n.!?]{1,60}\](?:\([^\)]+\))?|"
    r"[«»<>‹›←→]|\d+|"
    r"(?!.*?\b(?:" + _NAV_VERBS + r")\b)[\w\-&/]+(?:\s+[\w\-&/]+){0,5}"
    r")"
)

# Navigation label without a colon: same structure but the first word must
# start with an uppercase letter so that factual prose (e.g. "Next page token
# expires after 24 hours") is not mistaken for a navigation label.
_NAV_LABEL_SPACE_PAT = (
    r"(?:"
    r"\[(?!.*?\b(?:" + _NAV_VERBS + r")\b)[^\]\r\n.!?]{1,60}\](?:\([^\)]+\))?|"
    r"[«»<>‹›←→]|\d+|"
    r"(?!.*?\b(?:" + _NAV_VERBS + r")\b)[A-Z][\w\-&/]*(?:\s+[\w\-&/]+){0,5}"
    r")"
)

_NAV_CONTROL_RE = re.compile(
    r"^(?:#+\s*)?(?:table of contents|on this page|in this article|quick links|"
    r"skip to (?:main )?content|back to top|return to top|"
    r"(?:previous|next)\s+page:\s*" + _NAV_LABEL_COLON_PAT + r"|"
    r"(?:previous|next)\s+page\s+" + _NAV_LABEL_SPACE_PAT + r"|"
    r"(?:previous|next)\s+page|"
    r"«\s*previous\s*|\s*next\s*»|"
    r"edit this page(?: on github)?|was this (?:page|article) helpful\??|"
    r"share this page|print this page)$",
    re.IGNORECASE,
)

_PAGINATION_LINK_RE = re.compile(r"^\[\s*(?:«?\s*previous|\s*next\s*»)\s*\]\([^\)]+\)$", re.IGNORECASE)

_FENCE_START_RE = re.compile(r"^(`{3,}|~{3,})")


_TERM_RE = re.compile(r"\b\w+(?:[+#]+(?=\W|$))?")
_COMPOUND_STEM_RE = re.compile(r"\b\w+[+#]+(?=\d)")


def _tokenize_terms(text: str) -> Set[str]:
    terms = _TERM_RE.findall(text) + _COMPOUND_STEM_RE.findall(text)
    return {term.lower() for term in terms}


def _tokenize_query(query: str) -> Set[str]:
    """Extract lowercase alphanumeric query keywords for term preservation."""
    if not query:
        return set()
    return _tokenize_terms(query)


def _is_protected_line(line: str, query_tokens: Set[str]) -> bool:
    """Determine whether a line contains protected syntax, qualifiers, or query terms."""
    if not line.strip():
        return True

    # Indented code blocks (4 spaces or tab)
    if line.startswith("    ") or line.startswith("\t"):
        return True

    stripped = line.strip()

    # 1. Code blocks, markdown tables, and inline code
    if stripped.startswith("```") or stripped.startswith("~~~") or "|" in stripped:
        return True
    if "`" in stripped:
        return True

    # 2. HTTP methods / endpoints (e.g. GET /users, POST /api/v1/...)
    if re.match(r"^(?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+/\S*", stripped, re.IGNORECASE):
        return True

    # Normalize typographic/curly apostrophes (U+2018, U+2019) to straight apostrophe
    # so contractions like "Don't" tokenize identically to "Don't".
    normalized = stripped.lower().replace("\u2019", "'").replace("\u2018", "'")

    # 3. Query term overlap — use shared term tokenizer so compounds such as "C++"
    # and possessives like "user's" match query terms.
    words = _tokenize_terms(normalized)
    if query_tokens and words.intersection(query_tokens):
        return True

    # 4. Factual qualifiers, polarity, or negations — use apostrophe-aware tokens so
    # contractions like "don't" / "won't" match entries in _PROTECTED_QUALIFIERS.
    words_with_apostrophe = set(re.findall(r"\b[\w']+\b", normalized))
    if words_with_apostrophe.intersection(_PROTECTED_QUALIFIERS):
        return True

    # 4b. Comparison expressions with a numeric operand (e.g. "Password length > 8")
    if re.search(r"(?:<=?|>=?|≤|≥|!=)\s*[-+]?\d", stripped):
        return True

    # 5. URLs (unless a pagination link or recognized navigation control)
    if "http://" in stripped or "https://" in stripped:
        if not _PAGINATION_LINK_RE.match(stripped) and not _NAV_CONTROL_RE.match(stripped):
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


_DOC_TITLE_RE = re.compile(
    r"^(?:[\w.-]+(?:\s+[\w.-]+)*\s+)?(?:documentation|docs|user guide|reference manual|api reference)(?:\s+v?\d+(?:\.\d+)*)?$",
    re.IGNORECASE,
)

_PAGE_METADATA_RE = re.compile(
    r"^(?:page\s+\d+(?:\s+of\s+\d+)?|last\s+updated:?.*|version:?\s*v?\d+[\d.]*)$",
    re.IGNORECASE,
)


def _is_boilerplate_candidate(line: str) -> bool:
    """Classify whether a line represents identifiable boilerplate or title banners rather than factual prose or section headings."""
    stripped = line.strip()
    if not stripped:
        return False

    # Section headings (e.g. "# Authentication", "## Examples") must be preserved across chunks
    if stripped.startswith("#"):
        heading_text = stripped.lstrip("#").strip()
        return bool(_DOC_TITLE_RE.match(heading_text) or _PAGE_METADATA_RE.match(heading_text))

    # Navigation controls, breadcrumbs, or pagination
    if _is_navigation_boilerplate(line):
        return True

    # Copyright, license, or legal notices
    if re.search(r"(?:©|\bcopyright\b|\(c\)\b|\ball rights reserved\b|\blicensed under\b)", stripped, re.IGNORECASE):
        return True

    # Document titles, product headers, or version lines (e.g. "DocsGPT Documentation v2.4")
    if _DOC_TITLE_RE.match(stripped):
        return True

    # Page indicators or metadata headers (e.g. "Page 1 of 5", "Last updated: October 2024")
    if _PAGE_METADATA_RE.match(stripped):
        return True

    return False


def _normalize_fence_state(fence_state: Any) -> Optional[Tuple[str, int]]:
    """Normalizes chunk metadata representations of active code fences into (fence_char, fence_length)."""
    if fence_state is True:
        return ("`", 3)
    if isinstance(fence_state, (list, tuple)) and len(fence_state) == 2:
        try:
            char = str(fence_state[0])
            length = int(fence_state[1])
            if char in {"`", "~"} and length >= 3:
                return (char, length)
        except (ValueError, TypeError):
            return None
    if isinstance(fence_state, str) and len(fence_state) >= 3:
        if fence_state[0] in {"`", "~"} and all(c == fence_state[0] for c in fence_state):
            return (fence_state[0], len(fence_state))
    return None


def prune_chunk_text(
    text: str,
    query: str = "",
    seen_boilerplate: Optional[Set[str]] = None,
    initial_active_fence: Optional[Union[Tuple[str, int], str, bool]] = None,
) -> str:
    """Extractive pruning of navigation boilerplate and duplicate lines from a single chunk."""
    if not text:
        return ""

    query_tokens = _tokenize_query(query)
    lines = text.split("\n")
    cleaned_lines: List[Tuple[str, bool]] = []  # (line_text, is_inside_fence)
    chunk_boilerplate: Set[str] = set()

    # State tracking for code fences: (fence_char, fence_length)
    active_fence: Optional[Tuple[str, int]] = _normalize_fence_state(initial_active_fence)

    for line in lines:
        stripped = line.strip()

        # Handle fenced code blocks per CommonMark rules
        fence_match = _FENCE_START_RE.match(stripped)
        if active_fence is not None:
            cleaned_lines.append((line, True))
            char, length = active_fence
            # Closing fence must use the same character, have at least the opening length,
            # and have no trailing non-whitespace characters
            if fence_match and fence_match.group(1)[0] == char and len(fence_match.group(1)) >= length:
                rest = stripped[len(fence_match.group(1)) :].strip()
                if not rest:
                    active_fence = None
            continue
        elif fence_match:
            active_fence = (fence_match.group(1)[0], len(fence_match.group(1)))
            cleaned_lines.append((line, True))
            continue

        # Check for protected content BEFORE deduplication or navigation checks
        if _is_protected_line(line, query_tokens):
            cleaned_lines.append((line, False))
            continue

        # Check for navigation boilerplate
        if _is_navigation_boilerplate(line):
            continue

        # Check for duplicate boilerplate across chunks in same retrieval
        if seen_boilerplate is not None and _is_boilerplate_candidate(line):
            norm_line = stripped.lower()
            if len(norm_line) < 120 and norm_line in seen_boilerplate:
                continue
            chunk_boilerplate.add(norm_line)

        cleaned_lines.append((line, False))

    if seen_boilerplate is not None:
        seen_boilerplate.update(chunk_boilerplate)

    # Collapse multiple consecutive empty lines OUTSIDE of fenced code blocks only
    result: List[str] = []
    prev_empty = False
    for line_text, in_fence in cleaned_lines:
        is_empty = not line_text.strip()
        if in_fence:
            result.append(line_text)
            prev_empty = False
            continue

        if is_empty and prev_empty:
            continue
        result.append(line_text)
        prev_empty = is_empty

    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()

    return "\n".join(result)


def prune_boilerplate(docs: List[Dict[str, Any]], query: str = "") -> List[Dict[str, Any]]:
    """Prunes navigation and duplicate boilerplate across the final retrieved documents."""
    if not docs:
        return docs

    seen_boilerplate: Set[str] = set()
    seen_doc_ids: Set[int] = set()

    for doc in docs:
        doc_id = id(doc)
        if doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(doc_id)

        text = doc.get("text")
        if isinstance(text, str) and text:
            metadata = (
                doc.get("metadata")
                if isinstance(doc.get("metadata"), dict)
                else (doc.get("extra_info") if isinstance(doc.get("extra_info"), dict) else doc)
            )
            initial_active_fence = None
            if isinstance(metadata, dict):
                initial_active_fence = _normalize_fence_state(
                    metadata.get("active_fence")
                    or metadata.get("in_code_fence")
                    or metadata.get("fenced_code")
                    or metadata.get("in_code_block")
                )

            doc["text"] = prune_chunk_text(
                text,
                query=query,
                seen_boilerplate=seen_boilerplate,
                initial_active_fence=initial_active_fence,
            )

    return docs

def compress_retrieved_chunks(docs: List[Dict[str, Any]], query: str = "") -> List[Dict[str, Any]]:
    """Compresses retrieved chunks using SuperCompress when available, falling back to in-tree boilerplate pruning."""
    if not docs:
        return docs

    try:
        from supercompress import compress_for_turn

        compressed_texts = []
        for doc in docs:
            text = doc.get("text", "")
            if text:
                res = compress_for_turn(
                    context=text,
                    user_query=query or "",
                    context_blocks=[text],
                )
                compressed_texts.append(getattr(res, "compressed_text", str(res)))
            else:
                compressed_texts.append(None)

        for doc, comp_text in zip(docs, compressed_texts):
            if comp_text is not None:
                doc["text"] = comp_text
        return docs
    except (ImportError, Exception):
        pass

    return prune_boilerplate(docs, query=query or "")

