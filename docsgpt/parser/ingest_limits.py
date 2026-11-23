"""Size caps on one source ingest: files once the remote is listed, tokens once it is parsed."""

from __future__ import annotations

from typing import Any, Dict

from docsgpt.core.settings import settings

TOO_MANY_FILES = "too_many_files"
TOO_MANY_TOKENS = "too_many_tokens"


class IngestTooLarge(Exception):
    """A source is over ``INGEST_MAX_FILES`` or ``INGEST_MAX_TOKENS``; every attempt fails the same way."""

    def __init__(self, reason: str, count: int, limit: int, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.count = count
        self.limit = limit


def check_file_count(count: int) -> None:
    """Raise :class:`IngestTooLarge` when ``count`` files are over ``INGEST_MAX_FILES``.

    Args:
        count: Files the ingest would load.

    Raises:
        IngestTooLarge: The cap is on and ``count`` is over it.
    """
    limit = int(settings.INGEST_MAX_FILES)
    if limit > 0 and count > limit:
        raise IngestTooLarge(
            TOO_MANY_FILES, count, limit,
            f"This source has {count:,} files; one source can hold at most {limit:,}. "
            "Choose a smaller folder, path or selection.",
        )


def check_token_count(count: int) -> None:
    """Raise :class:`IngestTooLarge` when ``count`` tokens are over ``INGEST_MAX_TOKENS``.

    Args:
        count: Tokens of chunked text the ingest would embed.

    Raises:
        IngestTooLarge: The cap is on and ``count`` is over it.
    """
    limit = int(settings.INGEST_MAX_TOKENS)
    if limit > 0 and count > limit:
        raise IngestTooLarge(
            TOO_MANY_TOKENS, count, limit,
            f"This source has {count:,} tokens of text; one source can hold at most {limit:,}. "
            "Split it into smaller sources.",
        )


def failure_fields(error: BaseException) -> Dict[str, Any]:
    """The ``reason`` and ``limit`` a ``source.ingest.failed`` event carries for a capped ingest.

    Args:
        error: The error the ingest failed with.

    Returns:
        ``{"reason", "limit"}`` for :class:`IngestTooLarge`, else ``{}``.
    """
    if isinstance(error, IngestTooLarge):
        return {"reason": error.reason, "limit": error.limit}
    return {}
