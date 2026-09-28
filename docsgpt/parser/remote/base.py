"""Base reader class."""
import hashlib
import os
import re
from abc import abstractmethod
from typing import Any, Dict, List
from urllib.parse import parse_qsl, urldefrag, urlencode, urlparse

from docsgpt.parser.schema.base import Document
from docsgpt.vectorstore.document_class import Document as VectorDocument

_PAGE_EXTENSIONS = (".html", ".htm", ".php", ".asp", ".aspx", ".jsp")

# Joins a page's path to its encoded query string in the virtual file name.
_QUERY_SEPARATOR = "__"
# Longest encoded query kept verbatim; longer ones keep a prefix plus a hash.
MAX_QUERY_SEGMENT_LENGTH = 64
_QUERY_HASH_LENGTH = 10
# Anything but letters, digits, ``_``, ``.`` and ``-`` in a query key or value.
_UNSAFE_QUERY_CHARS = re.compile(r"[^\w.-]+")


def _query_segment(query: str) -> str:
    """Encode a URL query string as a deterministic, tree-safe name segment.

    Parameters are sorted so the same page maps to the same name across
    re-syncs whatever order its links list them in. Keys and values are
    percent-decoded and every run of characters outside ``[\\w.-]`` becomes
    ``-``, so the segment carries no ``/``, ``?``, ``#`` or ``%``. A segment
    longer than ``MAX_QUERY_SEGMENT_LENGTH`` keeps a prefix and a hash of the
    full query, which keeps it bounded and still distinct.

    Args:
        query: The raw query string, without the leading ``?``.

    Returns:
        The encoded segment, or ``""`` when the query has no parameters.
    """
    pairs = sorted(parse_qsl(query, keep_blank_values=True))
    if not pairs:
        return ""
    parts = []
    for key, value in pairs:
        key = _UNSAFE_QUERY_CHARS.sub("-", key)
        value = _UNSAFE_QUERY_CHARS.sub("-", value)
        parts.append(f"{key}={value}" if value else key)
    segment = "&".join(parts)
    if len(segment) <= MAX_QUERY_SEGMENT_LENGTH:
        return segment
    digest = hashlib.sha1(urlencode(pairs).encode("utf-8")).hexdigest()
    keep = MAX_QUERY_SEGMENT_LENGTH - _QUERY_HASH_LENGTH - 1
    return f"{segment[:keep]}-{digest[:_QUERY_HASH_LENGTH]}"


def url_to_virtual_path(url: str, include_host: bool = False) -> str:
    """Convert a page URL to the virtual ``.md`` path used as its tree key.

    Web ingests store this as the chunk's ``file_path``: the worker keys the
    source's file tree by it and the chunks view filters by it, so the two
    agree on which chunks belong to which file.

    The fragment is dropped (it names a spot on the same page), but the query
    string is kept, encoded into the file name (see ``_query_segment``), so
    ``/p?page=1`` and ``/p?page=2`` stay two files. A URL without a query maps
    exactly as before. Paths that still collide, such as ``/a`` and
    ``/a.html``, are told apart by ``dedupe_virtual_paths``.

    Args:
        url: Page URL, e.g. ``"https://docs.docsgpt.cloud/guides/setup"``.
        include_host: Prefix the host, for ingests spanning several hosts
            whose paths would otherwise collide (every root is ``index.md``).

    Returns:
        A relative path such as ``"index.md"``, ``"guides/setup.md"``,
        ``"list__page=2.md"`` or, with ``include_host``,
        ``"docs.docsgpt.cloud/guides/setup.md"``.
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if not path:
        path = "index.md"
    else:
        base, ext = os.path.splitext(path)
        if ext.lower() in _PAGE_EXTENSIONS:
            path = base
        if not path.endswith(".md"):
            path = f"{path}.md"

    query = _query_segment(parsed.query)
    if query:
        path = f"{path[:-len('.md')]}{_QUERY_SEPARATOR}{query}.md"

    if include_host and parsed.netloc:
        return f"{parsed.netloc}/{path}"
    return path


def spans_multiple_hosts(urls: List[str]) -> bool:
    """Return whether ``urls`` point at more than one host.

    Args:
        urls: Page URLs about to be ingested together.

    Returns:
        True when paths alone could collide and need a host prefix.
    """
    return len({urlparse(u).netloc for u in urls}) > 1


def dedupe_virtual_paths(documents: List[Document]) -> List[Document]:
    """Give distinct pages that share a virtual ``file_path`` distinct ones.

    ``url_to_virtual_path`` folds some different URLs onto one path (``/a`` and
    ``/a.html`` are both ``a.md``), and the worker would then merge those pages
    into one tree entry. Within a path, the pages are ordered by URL (fragment
    dropped): the first keeps the path and each later one gets ``-2``, ``-3``
    and so on before ``.md``, skipping any path another page already has.
    Ordering by URL rather than by fetch order keeps the names stable across
    re-syncs of the same pages. Documents for the same URL (one page reached
    via two fragments) are one page and keep one path.

    Args:
        documents: Loaded documents; each ``extra_info`` carries ``source``
            (the page URL) and ``file_path``. Others are left untouched.

    Returns:
        ``documents``, with colliding ``file_path`` values rewritten in place.
    """
    pages_by_path: Dict[str, Dict[str, List[Document]]] = {}
    for doc in documents:
        info = doc.extra_info or {}
        path = info.get("file_path")
        if not path:
            continue
        page = urldefrag(str(info.get("source") or path))[0]
        pages_by_path.setdefault(path, {}).setdefault(page, []).append(doc)

    taken = set(pages_by_path)
    for path in sorted(pages_by_path):
        pages = pages_by_path[path]
        if len(pages) < 2:
            continue
        stem = path[: -len(".md")] if path.endswith(".md") else path
        suffix = 1
        for page in sorted(pages)[1:]:
            suffix += 1
            while f"{stem}-{suffix}.md" in taken:
                suffix += 1
            new_path = f"{stem}-{suffix}.md"
            taken.add(new_path)
            for doc in pages[page]:
                doc.extra_info["file_path"] = new_path
    return documents


class BaseRemote:
    """Utilities for loading data from a directory."""

    @abstractmethod
    def load_data(self, *args: Any, **load_kwargs: Any) -> List[Document]:
        """Load data from the input directory."""

    def load_vector_documents(self, **load_kwargs: Any) -> List[VectorDocument]:
        """Load data in the vector-store document format."""
        docs = self.load_data(**load_kwargs)
        return [d.to_vector_format() for d in docs]
