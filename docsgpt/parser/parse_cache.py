"""Reuse the text parsed from a source file when the same user ingests the same bytes again.

A scanned PDF costs OCR every time it is parsed. A source ingest parses the
same bytes again when a user adds the same (or an overlapping) folder twice,
when a sync falls back to a full re-ingest, when a file is moved or copied in
its provider and gets a new id, when a failed ingest is retried, and when only
the chunking settings changed. ``SimpleDirectoryReader`` (given a
``parse_cache_user``) looks each file up here first, by the SHA-256 of its
bytes and :func:`parser_key`, and stores what it parsed.

Rules:

* Only a complete parse is stored: never one the parser raised on, and never
  one whose metadata says pages were left out (``ocr_pages_failed``).
* Rows belong to one user and are never read for another: reusing across
  users would tell one user that someone else holds the same file.
* Metadata that depends on where the file came from (``source``, ``url``,
  ``title``, the token count) is set by the reader after the lookup, so it
  is never cached.
* Nothing here raises into an ingest: a database or storage failure is
  logged, and the reader parses as if there were no cache.

The table is ``parsed_files`` (migration 0067). Rows unused for
``PARSE_CACHE_TTL_DAYS`` are deleted by the ``cleanup_parsed_files`` beat task.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docsgpt.core.settings import settings
from docsgpt.storage.db.session import db_session
from docsgpt.utils import strip_null_bytes

logger = logging.getLogger(__name__)

#: Bump when a parser changes what it returns for the same bytes, so every
#: stored parse misses once and is parsed again.
PARSER_VERSION = 1

#: Parser outputs larger than this (UTF-8 JSON) go to the storage backend
#: instead of the row, as attachments keep their full text beside the file.
INLINE_MAX_BYTES = 256 * 1024

#: Formats whose parse costs about as much as a cache lookup; they are not stored.
CHEAP_SUFFIXES = frozenset(
    {
        ".md", ".mdx", ".rst", ".txt", ".json", ".csv", ".html", ".xhtml", ".htm",
        ".xml", ".adoc", ".asciidoc", ".vtt",
    }
)

#: Settings that change what some parser returns for the same bytes.
_KEY_SETTINGS = (
    "DOC_PARSER_ENGINE",
    "OCR_ENABLED",
    "OCR_BACKEND",
    "OCR_ENGINE",
    "OCR_LANGS",
    "OCR_RENDER_DPI",
    "OCR_MIN_CHARS_PER_PAGE",
    "OCR_DEEPSEEK_PROMPT",
    "PARSE_PDF_AS_IMAGE",
    "PARSE_IMAGE_REMOTE",
    "STT_PROVIDER",
    "OPENAI_STT_MODEL",
    "STT_LANGUAGE",
    "STT_ENABLE_TIMESTAMPS",
    "STT_ENABLE_DIARIZATION",
)

#: Parser attributes holding a parser it hands files to.
_DELEGATE_ATTRS = ("fallback_parser", "text_parser")


def cache_enabled() -> bool:
    """Whether ``PARSE_CACHE_ENABLED`` is on (and there is a database to keep the cache in)."""
    return getattr(settings, "PARSE_CACHE_ENABLED", True) is True and bool(getattr(settings, "POSTGRES_URI", None))


def worth_caching(path: Path) -> bool:
    """Whether a file's parse is worth storing: not one of the cheap text formats."""
    return Path(path).suffix.lower() not in CHEAP_SUFFIXES


def _parser_chain(parser: Any, depth: int = 0) -> List[Dict[str, Any]]:
    """The parser and the parsers it delegates to, as what in each of them shapes the output."""
    if parser is None or depth > 4:
        return []
    entry: Dict[str, Any] = {"class": f"{type(parser).__module__}.{type(parser).__qualname__}"}
    for attr in ("ocr_enabled", "ocr_engine", "min_text_chars", "min_median_chars"):
        value = getattr(parser, attr, None)
        if isinstance(value, (bool, int, float, str)):
            entry[attr] = value
    # A parser's engine object is left out: it is built on first use, so it
    # would key a parser differently before and after its first parse. The
    # engine the settings resolve to is in the key instead (``_resolved_ocr``).
    chain = [entry]
    for attr in _DELEGATE_ATTRS:
        chain.extend(_parser_chain(getattr(parser, attr, None), depth + 1))
    return chain


def _resolved_ocr() -> Dict[str, Any]:
    """The OCR stack the settings resolve to (backend, engine, DeepSeek endpoint), without contacting it."""
    resolved: Dict[str, Any] = {}
    try:
        from docsgpt.parser.file.ocr_parser import (
            resolve_deepseek_endpoint,
            resolve_native_ocr_engine,
            resolve_ocr_backend,
        )

        resolved["backend"] = resolve_ocr_backend()
        resolved["engine"] = resolve_native_ocr_engine()
        if resolved["engine"] == "deepseek":
            endpoint = resolve_deepseek_endpoint()
            resolved["deepseek"] = [endpoint.provider, endpoint.model, endpoint.prompt]
    except Exception:  # noqa: BLE001 - the raw settings are in the key too
        logger.debug("Could not resolve the OCR stack for the parse cache key", exc_info=True)
    return resolved


def parser_key(parser: Any) -> str:
    """Hash everything that changes what ``parser`` returns for a file.

    The parser's class and the classes it delegates to (a fallback parser, a
    text-layer parser) with their OCR switches, the OCR backend,
    engine, model, prompt, render DPI and languages the settings resolve to,
    the other parse settings (``DOC_PARSER_ENGINE``, speech-to-text) and
    :data:`PARSER_VERSION`. A change to any of them misses the cache.

    Args:
        parser: The ``BaseParser`` that would read the file.

    Returns:
        A hex SHA-256.
    """
    payload = {
        "version": PARSER_VERSION,
        "parsers": _parser_chain(parser),
        "settings": {name: getattr(settings, name, None) for name in _KEY_SETTINGS},
        "ocr": _resolved_ocr(),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _storage():
    from docsgpt.storage.storage_creator import StorageCreator

    return StorageCreator.get_storage()


def storage_path_for(user_id: str, content_sha256: str, key: str) -> str:
    """Where a large parse of ``content_sha256`` under ``key`` is kept; the user's id is hashed into it."""
    user_dir = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:32]
    return f"parse_cache/{user_dir}/{content_sha256}/{key}.json"


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _page_counts(metadata: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """``(page_count, billed_pages)`` from what a parser reported."""
    page_count = _as_int(metadata.get("pdf_pages", metadata.get("page_count")))
    billed = _as_int(metadata.get("billed_pages"))
    if billed is None and metadata.get("ocr_requests"):
        # A hosted OCR engine reported requests: its OCR'd pages are the billed ones.
        billed = _as_int(metadata.get("ocr_pages"))
    return page_count, billed


class ParseCache:
    """One reader's view of a user's stored parses.

    Attributes:
        user_id: The user whose parses are read and written.
        hits: Files answered from the cache.
        stored: Parses written.
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = str(user_id)
        self.hits = 0
        self.stored = 0
        self._keys: Dict[int, Tuple[Any, str]] = {}
        # Set on the first database or storage failure, so a cache that is
        # down costs one warning, not one per file.
        self._broken = False

    def key_for(self, parser: Any) -> str:
        """``parser_key(parser)``, computed once per parser object."""
        cached = self._keys.get(id(parser))
        if cached is not None and cached[0] is parser:
            return cached[1]
        key = parser_key(parser)
        self._keys[id(parser)] = (parser, key)
        return key

    def _fail(self, what: str, exc: BaseException) -> None:
        logger.warning("Parse cache %s failed; parsing without it: %s", what, exc, exc_info=True)
        self._broken = True

    def lookup(self, content_sha256: str, parser: Any) -> Optional[Tuple[Any, Dict[str, Any]]]:
        """The stored ``(parser output, parser metadata)`` for this content and parser, or ``None``.

        Args:
            content_sha256: SHA-256 of the file's bytes.
            parser: The parser that would read it.
        """
        if self._broken:
            return None
        try:
            from docsgpt.storage.db.repositories.parsed_files import ParsedFilesRepository

            key = self.key_for(parser)
            with db_session() as conn:
                row = ParsedFilesRepository(conn).find(self.user_id, content_sha256, key)
        except Exception as exc:  # noqa: BLE001 - the ingest parses without the cache
            self._fail("lookup", exc)
            return None
        if row is None:
            return None
        content = row.get("content")
        if row.get("storage_path"):
            content = self._read_stored(row["storage_path"])
        if not isinstance(content, (str, list)):
            # Unreadable side file or a malformed row: parse again, and the store replaces it.
            return None
        metadata = row.get("parser_metadata")
        self.hits += 1
        return content, dict(metadata) if isinstance(metadata, dict) else {}

    def _read_stored(self, path: str) -> Any:
        try:
            handle = _storage().get_file(path)
            try:
                raw = handle.read()
            finally:
                close = getattr(handle, "close", None)
                if callable(close):
                    close()
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - a miss, not a failure of the ingest
            logger.info("Stored parse %s unavailable; parsing again: %s", path, exc)
            return None

    def store(self, content_sha256: str, parser: Any, content: Any, metadata: Optional[Dict[str, Any]]) -> bool:
        """Keep a complete parse; a partly OCR'd one (``ocr_pages_failed``) is refused.

        Args:
            content_sha256: SHA-256 of the file's bytes.
            parser: The parser that read it.
            content: What ``parse_file`` returned.
            metadata: What ``get_file_metadata`` returned.

        Returns:
            Whether the parse was stored.
        """
        metadata = dict(metadata or {})
        if self._broken or metadata.get("ocr_pages_failed"):
            return False
        if isinstance(content, list):
            content = [str(part) for part in content]
        elif not isinstance(content, str):
            return False
        # Postgres refuses a NUL in text and JSONB alike.
        content = strip_null_bytes(content)
        metadata = strip_null_bytes(json.loads(json.dumps(metadata, default=str)))
        page_count, billed = _page_counts(metadata)
        try:
            from docsgpt.storage.db.repositories.parsed_files import ParsedFilesRepository

            key = self.key_for(parser)
            encoded = json.dumps(content).encode("utf-8")
            storage_path = None
            inline: Any = content
            if len(encoded) > INLINE_MAX_BYTES:
                storage_path = storage_path_for(self.user_id, content_sha256, key)
                _storage().save_file(io.BytesIO(encoded), storage_path)
                inline = None
            with db_session() as conn:
                ParsedFilesRepository(conn).store(
                    self.user_id,
                    content_sha256,
                    key,
                    content=inline,
                    parser_metadata=metadata,
                    storage_path=storage_path,
                    page_count=page_count,
                    billed_pages=billed,
                )
        except Exception as exc:  # noqa: BLE001 - the parse itself succeeded
            self._fail("store", exc)
            return False
        self.stored += 1
        return True


def remove_stored_files(paths: List[Optional[str]]) -> None:
    """Delete the storage files of deleted rows; best effort, never raises."""
    paths = [path for path in paths if path]
    if not paths:
        return
    try:
        storage = _storage()
    except Exception:  # noqa: BLE001
        logger.warning("Parse cache cleanup: storage unavailable", exc_info=True)
        return
    for path in paths:
        try:
            storage.delete_file(path)
        except Exception:  # noqa: BLE001
            logger.warning("Parse cache cleanup: could not delete %s", path, exc_info=True)


def cleanup_stale_parses(days: Optional[int] = None) -> Dict[str, Any]:
    """Delete parses unused for ``days`` (``PARSE_CACHE_TTL_DAYS``), with their storage files.

    Returns:
        ``{"deleted": n, "ttl_days": days}``.
    """
    ttl_days = int(days if days is not None else getattr(settings, "PARSE_CACHE_TTL_DAYS", 90))
    from docsgpt.storage.db.repositories.parsed_files import ParsedFilesRepository

    with db_session() as conn:
        paths = ParsedFilesRepository(conn).delete_stale(ttl_days)
    remove_stored_files(paths)
    return {"deleted": len(paths), "ttl_days": ttl_days}
