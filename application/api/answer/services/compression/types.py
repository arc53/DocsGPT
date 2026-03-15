"""Type definitions for compression module."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


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

    @classmethod
    def success_with_compression(
        cls, summary: str, queries: List[Dict], metadata: CompressionMetadata
    ) -> "CompressionResult":
        """Create a successful result with compression."""
        return cls(
            success=True,
            compressed_summary=summary,
            recent_queries=queries,
            metadata=metadata,
            compression_performed=True,
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
            List of prompt/response dicts
        """
        return [
            {"prompt": q["prompt"], "response": q["response"]}
            for q in self.recent_queries
        ]
