"""Extractive boilerplate pruning stage for DocsGPT.

Prunes clearly identifiable navigation and duplicate boilerplate from retrieved
chunks post-retrieval while leaving factual prose, code blocks, tables, and
qualifiers untouched.
"""

from __future__ import annotations

import logging
import re
import sys
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
    r"\[(?!.*?\b(?i:" + _NAV_VERBS + r")\b)[^\]\r\n.!?]{1,60}\](?:\([^\)]+\))?|"
    r"[«»<>‹›←→]|\d+|"
    r"(?!.*?\b(?i:" + _NAV_VERBS + r")\b)[\w\-&/]+(?:\s+[\w\-&/]+){0,5}"
    r")"
)

# Navigation label without a colon: strictly requires an uppercase initial letter
# so factual text (e.g. "Next page token lifetime: 24 hours") is preserved.
_NAV_LABEL_SPACE_PAT = (
    r"(?:"
    r"\[(?!.*?\b(?i:" + _NAV_VERBS + r")\b)[^\]\r\n.!?]{1,60}\](?:\([^\)]+\))?|"
    r"[«»<>‹›←→]|\d+|"
    r"(?!.*?\b(?i:" + _NAV_VERBS + r")\b)[A-Z][\w\-&/]*(?:\s+[\w\-&/]+){0,5}"
    r")"
)

_NAV_CONTROL_RE = re.compile(
    r"^(?:#+\s*)?(?:(?i:table of contents|on this page|in this article|quick links|"
    r"skip to (?:main )?content|back to top|return to top|"
    r"edit this page(?: on github)?|was this (?:page|article) helpful\??|"
    r"share this page|print this page|«\s*previous\s*|\s*next\s*»|"
    r"(?:previous|next)\s+page)|"
    r"(?i:previous|next)\s+page:\s*" + _NAV_LABEL_COLON_PAT + r"|"
    r"(?i:previous|next)\s+page\s+" + _NAV_LABEL_SPACE_PAT + r")$"
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

def _mac_torch_faiss_conflict() -> bool:
    """Check if loading PyTorch on macOS would collide with FAISS in the same process."""
    if sys.platform != "darwin":
        return False
    if "faiss" in sys.modules:
        return True
    try:
        from docsgpt.core.settings import settings

        return getattr(settings, "VECTOR_STORE", "faiss") == "faiss"
    except Exception:
        return True


def _extract_protected_elements(
    text: str,
    query: str = "",
    initial_active_fence: Optional[Tuple[str, int]] = None,
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Extracts verbatim fenced code blocks, table rows, qualifier/warning sentences, and query-bearing lines."""
    lines = text.split("\n")
    fenced_blocks: List[str] = []
    table_rows: List[str] = []
    warning_lines: List[str] = []
    query_bearing_lines: List[str] = []

    active_fence = _normalize_fence_state(initial_active_fence)
    current_fence_lines: List[str] = []
    query_tokens = _tokenize_query(query)

    for line in lines:
        stripped = line.strip()
        fence_match = _FENCE_START_RE.match(stripped)

        if active_fence is not None:
            current_fence_lines.append(line)
            char, length = active_fence
            if fence_match and fence_match.group(1)[0] == char and len(fence_match.group(1)) >= length:
                rest = stripped[len(fence_match.group(1)) :].strip()
                if not rest:
                    fenced_blocks.append("\n".join(current_fence_lines))
                    current_fence_lines = []
                    active_fence = None
            continue

        if fence_match:
            char = fence_match.group(1)[0]
            length = len(fence_match.group(1))
            active_fence = (char, length)
            current_fence_lines = [line]
            continue

        # Table rows: any line containing a pipe delimiter (e.g. '| col1 | col2 |' or 'Name | Type')
        if "|" in line and not stripped.startswith("#"):
            table_rows.append(stripped)

        # Warning / qualifier sentences: lines containing protected qualifiers
        words = set(re.findall(r"\b[\w']+\b", stripped.lower().replace("\u2019", "'").replace("\u2018", "'")))
        if words.intersection(_PROTECTED_QUALIFIERS):
            warning_lines.append(stripped)

        # Query-bearing lines: factual lines matching query tokens (preserving numbers and details verbatim)
        if query_tokens and not _NAV_CONTROL_RE.match(stripped) and not _BREADCRUMB_RE.match(stripped):
            line_terms = query_tokens.intersection(_tokenize_terms(stripped.lower()))
            if line_terms:
                query_bearing_lines.append(stripped)

    if current_fence_lines:
        fenced_blocks.append("\n".join(current_fence_lines))

    return fenced_blocks, table_rows, warning_lines, query_bearing_lines


def _enforce_supercompress_safeguards(
    original_text: str,
    compressed_text: str,
    query: str = "",
    initial_active_fence: Optional[Tuple[str, int]] = None,
) -> str:
    """Enforces verbatim preservation of code blocks, tables, qualifiers, and query-bearing lines.

    If the compressed text drops or alters protected content (code blocks, table rows,
    warning/qualifier sentences, or query-bearing factual lines), falls back to in-tree
    boilerplate pruning for that chunk.
    """
    if not compressed_text or not isinstance(compressed_text, str):
        return prune_chunk_text(original_text, query=query, initial_active_fence=initial_active_fence)

    orig_blocks, orig_tables, orig_warnings, orig_query_lines = _extract_protected_elements(
        original_text, query=query, initial_active_fence=initial_active_fence
    )

    # 1. Code blocks must be preserved verbatim (not just fence presence)
    for block in orig_blocks:
        if block not in compressed_text:
            return prune_chunk_text(original_text, query=query, initial_active_fence=initial_active_fence)

    # 2. Table rows must be preserved verbatim (no deleted or modified rows like 'Name | Type')
    for row in orig_tables:
        if row not in compressed_text:
            return prune_chunk_text(original_text, query=query, initial_active_fence=initial_active_fence)

    # 3. Warning and qualifier-bearing lines must be preserved verbatim
    for warning in orig_warnings:
        if warning not in compressed_text:
            return prune_chunk_text(original_text, query=query, initial_active_fence=initial_active_fence)

    # 4. Query-bearing factual lines must be preserved verbatim (e.g. preventing '24 hours' changing to '12 hours')
    for qline in orig_query_lines:
        if qline not in compressed_text:
            return prune_chunk_text(original_text, query=query, initial_active_fence=initial_active_fence)

    # 5. ALL query terms present in the original chunk must be preserved (not just one term)
    query_tokens = _tokenize_query(query)
    if query_tokens:
        orig_query_terms = query_tokens.intersection(_tokenize_terms(original_text.lower()))
        comp_query_terms = query_tokens.intersection(_tokenize_terms(compressed_text.lower()))
        if not orig_query_terms.issubset(comp_query_terms):
            return prune_chunk_text(original_text, query=query, initial_active_fence=initial_active_fence)

    # Apply in-tree boilerplate pruning on the compressed text as final pass
    return prune_chunk_text(compressed_text, query=query, initial_active_fence=initial_active_fence)


def compress_retrieved_chunks(docs: List[Dict[str, Any]], query: str = "") -> List[Dict[str, Any]]:
    """Compresses retrieved chunks using SuperCompress when available, falling back to in-tree boilerplate pruning."""
    if not docs:
        return docs

    # On macOS, PyTorch and FAISS cannot share the same process without aborting.
    # Fall back to in-tree boilerplate pruning when they would share a macOS process.
    if _mac_torch_faiss_conflict():
        return prune_boilerplate(docs, query=query or "")

    try:
        from supercompress import compress_for_turn

        orig_texts = [doc.get("text", "") for doc in docs]
        compressed_texts = []
        for text in orig_texts:
            if text:
                res = compress_for_turn(
                    context_blocks=[text],
                    user_query=query or "",
                )
                if isinstance(res, (tuple, list)) and res:
                    comp_text = res[0]
                elif hasattr(res, "compressed_text"):
                    comp_text = res.compressed_text
                elif isinstance(res, str):
                    comp_text = res
                else:
                    comp_text = str(res)
                compressed_texts.append(comp_text)
            else:
                compressed_texts.append(None)

        for doc, orig_text, comp_text in zip(docs, orig_texts, compressed_texts):
            if comp_text is not None:
                metadata = doc.get("metadata") or doc.get("extra_info")
                initial_active_fence = None
                if isinstance(metadata, dict):
                    initial_active_fence = _normalize_fence_state(
                        metadata.get("active_fence")
                        or metadata.get("in_code_fence")
                        or metadata.get("fenced_code")
                        or metadata.get("in_code_block")
                    )
                doc["text"] = _enforce_supercompress_safeguards(
                    original_text=orig_text,
                    compressed_text=comp_text,
                    query=query or "",
                    initial_active_fence=initial_active_fence,
                )
        return docs
    except (ImportError, Exception):
        pass

    return prune_boilerplate(docs, query=query or "")

