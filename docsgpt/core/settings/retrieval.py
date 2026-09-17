"""Retrieval strategy and GraphRAG."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator

from docsgpt.core.settings._shared import SettingsGroup, normalize_choice


class RetrievalSettings(SettingsGroup):
    """Which vector store answers searches and how retrieval fans out across sources."""

    VECTOR_STORE: Literal["faiss", "elasticsearch", "mongodb", "qdrant", "milvus", "pgvector"] = Field(
        default="faiss", description="Vector store backend."
    )
    RETRIEVAL_MAX_PARALLEL_SOURCES: int = Field(
        default=4,
        ge=1,
        description="Concurrent per-source searches in one retrieval; the query is embedded once and shared.",
    )
    PER_SOURCE_RETRIEVAL_ENABLED: bool = Field(
        default=True,
        description="Kill-switch for per-source retrieval dispatch; False collapses to a single retriever.",
    )
    GRAPHRAG_ENABLED: bool = Field(default=False, description="Gates graph-aware ingestion and retrieval.")
    GRAPHRAG_EXTRACTION_MODEL: Optional[str] = Field(
        default=None, description="Model for ingest-time graph extraction; unset reuses LLM_PROVIDER/LLM_NAME."
    )
    GRAPHRAG_MAX_CHUNKS_FOR_EXTRACTION: int = Field(
        default=2000, ge=0, description="Hard cap on chunks extracted per source (cost control); 0 extracts nothing."
    )

    @field_validator("VECTOR_STORE", mode="before")
    @classmethod
    def _normalize_vector_store(cls, v):
        return normalize_choice(v)
