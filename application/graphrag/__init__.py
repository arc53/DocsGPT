"""GraphRAG feature package (flag-gated, pgvector-only per D29)."""

from __future__ import annotations

from application.core.settings import settings


def graphrag_available() -> bool:
    """Return True when GraphRAG is enabled and the store is pgvector (D29)."""
    return settings.GRAPHRAG_ENABLED and settings.VECTOR_STORE == "pgvector"
