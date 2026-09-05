"""Type definitions for compression module."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# The visible summary row appended after a compression. These rows are
# display-only: their content already reaches the model through the system
# prompt (``compressed_summary``), so history replay skips them. New rows carry
# ``metadata[COMPRESSION_SUMMARY_MARKER]``; the prompt text is the display label.
COMPRESSION_SUMMARY_PROMPT = "[Context Compression Summary]"
COMPRESSION_SUMMARY_MARKER = "compression_summary"


def is_usable_compression_point(point: Any) -> bool:
    """True when a saved compression point can stand in for the history it
    covers: a non-blank summary and, when recorded, a positive token count.

    Earlier versions persisted points with an empty summary (a 494k-token
    conversation was "compressed" to 0 tokens in production); reusing such a
    point would drop the history it covers and replace it with nothing.
    """
    if not isinstance(point, dict):
        return False
    summary = point.get("compressed_summary")
    if not isinstance(summary, str) or not summary.strip():
        return False
    count = point.get("compressed_token_count")
    if count is None:
        return True
    try:
        return int(count) > 0
    except (TypeError, ValueError):
        return False


def latest_usable_compression_point(points: Any) -> Optional[Dict[str, Any]]:
    """The most recent point that ``is_usable_compression_point``, or None."""
    for point in reversed(list(points or [])):
        if is_usable_compression_point(point):
            return point
    return None


def is_compression_summary_row(query: Any) -> bool:
    """True for the visible summary row written by ``append_compression_message``.

    Rows written since the marker exists are recognised by it alone. Rows
    written before it are recognised by the label only when nothing marks them
    as a real turn (no tool calls, no per-turn metadata), so a user who types
    the label text as a question keeps that turn in their history.
    """
    if not isinstance(query, dict):
        return False
    metadata = query.get("metadata")
    if isinstance(metadata, dict) and metadata.get(COMPRESSION_SUMMARY_MARKER) is True:
        return True
    return (
        query.get("prompt") == COMPRESSION_SUMMARY_PROMPT
        and not query.get("tool_calls")
        and not metadata
    )


@dataclass
class CompressionMetadata:
    """Metadata about a compression operation."""

    timestamp: datetime
    query_index: int
    compressed_summary: str
    original_token_count: int
    compressed_token_count: int
    compression_ratio: float
    model_used: str
    compression_prompt_version: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DB storage."""
        return {
            "timestamp": self.timestamp,
            "query_index": self.query_index,
            "compressed_summary": self.compressed_summary,
            "original_token_count": self.original_token_count,
            "compressed_token_count": self.compressed_token_count,
            "compression_ratio": self.compression_ratio,
            "model_used": self.model_used,
            "compression_prompt_version": self.compression_prompt_version,
        }


@dataclass
class CompressionResult:
    """Result of a compression operation."""

    success: bool
    compressed_summary: Optional[str] = None
    recent_queries: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Optional[CompressionMetadata] = None
    error: Optional[str] = None
    compression_performed: bool = False
    # When the conversation was last compressed — the point this turn's
    # history reflects, whether it was made now or reused from the DB.
    last_compression_at: Optional[Any] = None

    @classmethod
    def success_with_compression(
        cls,
        summary: str,
        queries: List[Dict],
        metadata: CompressionMetadata,
        last_compression_at: Optional[Any] = None,
    ) -> "CompressionResult":
        """Create a successful result with compression."""
        return cls(
            success=True,
            compressed_summary=summary,
            recent_queries=queries,
            metadata=metadata,
            compression_performed=True,
            last_compression_at=(
                last_compression_at
                if last_compression_at is not None
                else getattr(metadata, "timestamp", None)
            ),
        )

    @classmethod
    def success_from_existing(
        cls,
        summary: Optional[str],
        queries: List[Dict],
        last_compression_at: Optional[Any] = None,
    ) -> "CompressionResult":
        """A previously saved compression point applied to this turn.

        No LLM call was made; the summary and the queries after its point
        are what the turn replays instead of the raw history.
        """
        return cls(
            success=True,
            compressed_summary=summary,
            recent_queries=queries,
            compression_performed=False,
            last_compression_at=last_compression_at,
        )

    @classmethod
    def success_no_compression(cls, queries: List[Dict]) -> "CompressionResult":
        """Create a successful result without compression needed."""
        return cls(
            success=True,
            recent_queries=queries,
            compression_performed=False,
        )

    @classmethod
    def failure(cls, error: str) -> "CompressionResult":
        """Create a failure result."""
        return cls(success=False, error=error, compression_performed=False)

    def as_history(self) -> List[Dict[str, str]]:
        """
        Convert recent queries to history format.

        Returns:
            List of prompt/response dicts (with thought when present so
            DeepSeek-style providers can re-attach reasoning_content on
            replay).
        """
        out: List[Dict[str, str]] = []
        for q in self.recent_queries:
            if is_compression_summary_row(q):
                continue
            entry: Dict[str, str] = {
                "prompt": q["prompt"],
                "response": q["response"],
            }
            if q.get("thought"):
                entry["thought"] = q["thought"]
            if q.get("tool_calls"):
                entry["tool_calls"] = q["tool_calls"]
            out.append(entry)
        return out
