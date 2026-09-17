"""Retrieval strategy and GraphRAG."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class RetrievalSettings(SettingsGroup):
    """Which vector store answers searches and how retrieval fans out across sources."""

    VECTOR_STORE: str = Field(
        default="faiss",
        description="Vector store backend: faiss, elasticsearch, mongodb, qdrant, milvus or pgvector.",
    )
    RETRIEVERS_ENABLED: list = Field(
        default=["classic", "default"],
        description=(
            "Retriever keys an agent may use; must match RetrieverCreator.retrievers registry keys, NOT the "
            "legacy classic_rag label which never matched the registry."
        ),
    )
    RETRIEVAL_MAX_PARALLEL_SOURCES: int = Field(
        default=4,
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
        default=2000, description="Hard cap on chunks extracted per source (cost control)."
    )
