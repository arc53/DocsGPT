"""Type definitions for compression module."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# ``prompt`` of the visible summary row appended after a compression. These
# rows are display-only: their content already reaches the model through the
# system prompt (``compressed_summary``), so history replay skips them.
COMPRESSION_SUMMARY_PROMPT = "[Context Compression Summary]"


def is_compression_summary_row(query: Any) -> bool:
    """True for the visible summary row written by ``append_compression_message``."""
    return isinstance(query, dict) and query.get("prompt") == COMPRESSION_SUMMARY_PROMPT


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
