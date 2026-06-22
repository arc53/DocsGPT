"""Pydantic models for the ``sources.config`` per-source behavior contract.

Validation policy (D7): strict on write (``model_validate`` raises on bad
input), lenient on read (``SourceConfig.parse`` falls back to all-defaults for
``{}``/``None`` and tolerates partial/legacy dicts so a malformed row never
crashes ingest or retrieval).

The defaults mirror the ingest pipeline's current behavior: ``max_tokens`` /
``min_tokens`` match ``application/worker.py`` (1250 / 150), so an empty config
reproduces today's chunking byte-for-byte.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class PreScreenConfig(BaseModel):
    """Map-reduce candidate-filter config (D12); off unless set.

    A base retriever fetches ``candidate_k`` candidates, an LLM screens them in
    batches of ``batch_size``, and at most ``max_keep`` survivors pass to the
    answer. ``model`` is optional; when None the stage reuses the request's
    resolved model. This is a query-time LLM cost, so it stays opt-in.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_k: int = 40  # candidates to fetch before screening
    model: Optional[str] = None  # None → reuse the resolved request model
    batch_size: int = 10  # candidates per LLM screening call
    max_keep: int = 8  # survivors kept after screening

    @field_validator("candidate_k", "batch_size", "max_keep")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        if value > 500:
            raise ValueError("must be <= 500")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> "PreScreenConfig":
        if self.max_keep > self.candidate_k:
            raise ValueError("max_keep must be <= candidate_k")
        return self


class ChunkingConfig(BaseModel):
    """Ingest-time chunking knobs (bake-time; change requires re-ingest)."""

    model_config = ConfigDict(extra="forbid")

    strategy: str = "classic_chunk"  # ChunkerCreator key
    max_tokens: int = 1250  # matches application/worker.py MAX_TOKENS
    min_tokens: int = 150  # matches application/worker.py MIN_TOKENS
    duplicate_headers: bool = False


class RetrievalConfig(BaseModel):
    """Query-time retrieval knobs (live; no re-ingest needed)."""

    model_config = ConfigDict(extra="forbid")

    retriever: str = "classic"  # RetrieverCreator key
    exposure: str = "prefetch"  # prefetch | agentic_tool (D11)
    chunks: int = 2  # final top-k
    score_threshold: Optional[float] = None  # pgvector/mongo honor it; others ignore
    rephrase_query: bool = True  # toggle ClassicRAG._rephrase_query side-call
    reranker: Optional[dict] = None  # reserved: future cross-encoder/LLM reorder
    prescreen: Optional[dict] = None  # None = off; else PreScreenConfig dict (D12)

    @field_validator("chunks")
    @classmethod
    def _bounded_chunks(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        if value > 500:
            raise ValueError("must be <= 500")
        return value

    @model_validator(mode="after")
    def _validate_prescreen(self) -> "RetrievalConfig":
        """Validate ``prescreen`` through ``PreScreenConfig`` when present.

        Kept as a dict on the model for lenient storage, but parsed strictly
        here so a bad object is rejected on the API write path; cross-checks
        ``candidate_k >= chunks`` so the final top-k can always be satisfied.
        """
        if self.prescreen is not None:
            ps = PreScreenConfig.model_validate(self.prescreen)
            if ps.candidate_k < self.chunks:
                raise ValueError("prescreen.candidate_k must be >= chunks")
            # Normalise to the validated dict (drops any extras / fills defaults).
            self.prescreen = ps.model_dump()
        return self

    def prescreen_config(self) -> Optional[PreScreenConfig]:
        """Return the parsed ``PreScreenConfig`` or None (lenient read)."""
        if not self.prescreen:
            return None
        try:
            return PreScreenConfig.model_validate(self.prescreen)
        except Exception:
            return None


class SourceConfig(BaseModel):
    """Per-source behavior contract stored in ``sources.config``."""

    model_config = ConfigDict(extra="forbid")

    kind: str = "classic"  # behavior selector: classic | wiki | graphrag | ...
    chunking: ChunkingConfig = ChunkingConfig()
    retrieval: RetrievalConfig = RetrievalConfig()

    @classmethod
    def parse(cls, raw: Optional[dict]) -> "SourceConfig":
        """Lenient read: return all-defaults for ``{}``/``None``.

        Falls back to classic defaults when ``raw`` is empty or cannot be
        validated, so legacy/bad rows never break the read path (D7).
        Partial dicts are merged onto the defaults.

        Args:
            raw: The stored ``sources.config`` value (or ``None``).

        Returns:
            A fully populated ``SourceConfig``.
        """
        if not raw:
            return cls()
        if not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            return cls()
