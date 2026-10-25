"""Pydantic models for the ``sources.config`` per-source behavior contract.

Validation policy (D7): strict on write (``model_validate`` raises on bad
input), lenient on read (``SourceConfig.parse`` falls back to all-defaults for
``{}``/``None`` and tolerates partial/legacy dicts so a malformed row never
crashes ingest or retrieval).

The defaults mirror the ingest pipeline's current behavior: ``max_tokens`` /
``min_tokens`` match ``docsgpt/worker.py`` (1250 / 150), so an empty config
reproduces today's chunking byte-for-byte.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from docsgpt.parser.limits import MAX_CHUNK_TOKENS


#: Most candidates one relevance call takes (``DECISION_RELEVANCE_MAX_PASSAGES`` caps it too, at run time).
DECISION_MAX_CANDIDATES = 100
#: Candidates a source's relevance fetches and scores when its ``reranker.candidate_k`` is unset.
DEFAULT_CANDIDATE_K = 20

#: Why a retrieval config with both ``reranker`` and ``prescreen`` is refused; routes show it as it is.
RELEVANCE_OR_PRESCREEN = (
    "Relevance and LLM screening cannot both be on: set reranker or prescreen, not both."
)


def validation_message(error: Exception, default: str) -> str:
    """The message a route returns for a config that failed validation.

    Validation internals stay hidden behind ``default``, except the one rule a
    user has to act on: relevance and LLM screening are mutually exclusive.

    Args:
        error: The ``ValidationError`` (or ``ValueError``) validation raised.
        default: The route's static message for every other failure.
    """
    return RELEVANCE_OR_PRESCREEN if RELEVANCE_OR_PRESCREEN in str(error) else default


def _probability(value: Optional[float]) -> Optional[float]:
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError("must be between 0 and 1")
    return value


class PreScreenConfig(BaseModel):
    """Map-reduce candidate-filter config (D12); off unless set.

    A base retriever fetches ``candidate_k`` candidates, an LLM screens them in
    batches of ``batch_size``, and at most ``max_keep`` survivors pass to the
    answer. ``model`` is optional; when None the stage reuses the request's
    resolved model. This is a query-time LLM cost, so it stays opt-in. A stored
    ``backend: "llm"`` (the only screening there is) is accepted and dropped.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_k: int = 40  # candidates to fetch before screening
    model: Optional[str] = None  # None → reuse the resolved request model
    batch_size: int = 10  # candidates per LLM screening call
    max_keep: int = 8  # survivors kept after screening

    @model_validator(mode="before")
    @classmethod
    def _drop_llm_backend(cls, data):
        if isinstance(data, dict) and data.get("backend") == "llm":
            data = {key: value for key, value in data.items() if key != "backend"}
        return data

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


class RerankerConfig(BaseModel):
    """A source's relevance: its chunks scored by the decision model.

    A source without one is off. With one, while the operator has set
    ``DECISION_RELEVANCE_ENABLED``, the source fetches ``candidate_k``
    candidates (``DEFAULT_CANDIDATE_K`` when unset), scores them in one call
    and keeps as many chunks as it would without it, most relevant first
    (``min_relevance`` unset or 0: reorder). A ``min_relevance`` above 0 also
    drops chunks scoring below it, keeping ``DECISION_RELEVANCE_MIN_KEEP``
    (reorder and filter). Any retriever can use it.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["decision"] = "decision"
    min_relevance: Optional[float] = None  # None or 0 → reorder only
    candidate_k: Optional[int] = None  # None → DEFAULT_CANDIDATE_K

    @field_validator("min_relevance")
    @classmethod
    def _min_relevance(cls, value: Optional[float]) -> Optional[float]:
        return _probability(value)

    @field_validator("candidate_k")
    @classmethod
    def _candidate_k(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and not 1 <= value <= DECISION_MAX_CANDIDATES:
            raise ValueError(f"must be between 1 and {DECISION_MAX_CANDIDATES}")
        return value

    @property
    def threshold(self) -> float:
        """The relevance a kept chunk needs; 0 reorders only."""
        return self.min_relevance or 0.0

    @property
    def pool(self) -> int:
        """Candidates to fetch and score."""
        return self.candidate_k or DEFAULT_CANDIDATE_K


class GraphConfig(BaseModel):
    """Ingest-time GraphRAG extraction knobs (pgvector-only).

    ``extraction_model`` None reuses the instance default model
    (``LLM_PROVIDER``/``LLM_NAME``); ``max_chunks`` None falls back to the
    ``GRAPHRAG_MAX_CHUNKS_FOR_EXTRACTION`` setting. ``gleanings`` is off by
    default (cost control).
    """

    model_config = ConfigDict(extra="forbid")

    extraction_model: Optional[str] = None  # None → instance default model
    max_chunks: Optional[int] = None  # None → GRAPHRAG_MAX_CHUNKS_FOR_EXTRACTION
    gleanings: int = 0  # extra extraction passes per chunk

    @field_validator("max_chunks")
    @classmethod
    def _positive_max_chunks(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 1:
            raise ValueError("must be >= 1")
        return value

    @field_validator("gleanings")
    @classmethod
    def _non_negative_gleanings(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be >= 0")
        return value


class ChunkingConfig(BaseModel):
    """Ingest-time chunking knobs (bake-time; change requires re-ingest)."""

    model_config = ConfigDict(extra="forbid")

    strategy: str = "classic_chunk"  # ChunkerCreator key
    max_tokens: int = 1250  # matches docsgpt/worker.py MAX_TOKENS
    min_tokens: int = 150  # matches docsgpt/worker.py MIN_TOKENS
    chunk_overlap: int = 0  # Token overlap across adjacent chunks
    duplicate_headers: bool = False

    @field_validator("max_tokens")
    @classmethod
    def _bounded_max_tokens(cls, value: int) -> int:
        """Reject unsafe chunk sizes on API writes."""
        if value < 1:
            raise ValueError("must be >= 1")
        if value > MAX_CHUNK_TOKENS:
            raise ValueError(f"must be <= {MAX_CHUNK_TOKENS}")
        return value

    @field_validator("chunk_overlap")
    @classmethod
    def _non_negative_chunk_overlap(cls, value: int) -> int:
        """Validate that chunk_overlap is non-negative.

        Args:
            value: Number of overlapping tokens between chunks.

        Returns:
            The validated non-negative chunk_overlap value.

        Raises:
            ValueError: If value is negative.
        """
        if value < 0:
            raise ValueError("chunk_overlap must be >= 0")
        return value


class GraphRetrievalConfig(BaseModel):
    """How the graph retriever walks a graphrag source (live; no re-ingest).

    The defaults are the configuration that measured best across the corpora
    tested rather than a neutral starting point: seed from entity matches, put
    the passages in the walk, and blend with the source's own vector ranking.
    """

    model_config = ConfigDict(extra="forbid")

    # Where the walk starts: entities whose descriptions match the question, or
    # relationships ("A streams_to B") that do. Relationships can start the
    # walk on an entity the question never names.
    seed_strategy: Literal["entities", "relationships"] = "entities"
    # Chunks join the walk as nodes, so a passage is reachable both by being
    # about the question and by being connected to what is.
    passage_nodes: bool = True
    # Fuse the graph ranking with plain vector search by reciprocal rank.
    blend_vector: bool = True


class RetrievalConfig(BaseModel):
    """Query-time retrieval knobs (live; no re-ingest needed)."""

    model_config = ConfigDict(extra="forbid")

    retriever: str = "classic"  # RetrieverCreator key
    exposure: str = "prefetch"  # prefetch | agentic_tool (D11)
    chunks: int = 6  # final top-k
    score_threshold: Optional[float] = None  # pgvector/mongo/qdrant/milvus honor it; others ignore
    rephrase_query: bool = True  # toggle ClassicRAG._rephrase_query side-call
    show_links: bool = True  # synced sources: citations and the agent get each file's link in its service
    reranker: Optional[dict] = None  # None = relevance off; else RerankerConfig dict
    prescreen: Optional[dict] = None  # None = off; else PreScreenConfig dict (D12)
    graph: GraphRetrievalConfig = GraphRetrievalConfig()  # graphrag retriever only

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

    @model_validator(mode="after")
    def _validate_reranker(self) -> "RetrievalConfig":
        """Validate ``reranker`` through ``RerankerConfig`` when present (strict, as ``prescreen``).

        A source is judged by relevance or by the LLM prescreen, never both.
        """
        if self.reranker is not None:
            if self.prescreen is not None:
                raise ValueError(RELEVANCE_OR_PRESCREEN)
            self.reranker = RerankerConfig.model_validate(self.reranker).model_dump()
        return self

    def prescreen_config(self) -> Optional[PreScreenConfig]:
        """Return the parsed ``PreScreenConfig`` or None (lenient read)."""
        if not self.prescreen:
            return None
        try:
            return PreScreenConfig.model_validate(self.prescreen)
        except Exception:
            return None

    def reranker_config(self) -> Optional[RerankerConfig]:
        """Return the parsed ``RerankerConfig`` or None (lenient read)."""
        if not self.reranker:
            return None
        try:
            return RerankerConfig.model_validate(self.reranker)
        except Exception:
            return None


class SourceConfig(BaseModel):
    """Per-source behavior contract stored in ``sources.config``."""

    model_config = ConfigDict(extra="forbid")

    kind: str = "classic"  # behavior selector: classic | wiki | graphrag | ...
    chunking: ChunkingConfig = ChunkingConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    graph: GraphConfig = GraphConfig()

    def wiki_enabled(self) -> dict:
        """Return a config dict flipped to wiki mode + browse-as-you-go exposure.

        Sets ``kind="wiki"`` and defaults ``retrieval.exposure`` to
        ``agentic_tool`` (a wiki is navigated, not bulk-prefetched), preserving
        any non-default exposure the source already carries.
        """
        new_config = self.model_dump()
        new_config["kind"] = "wiki"
        if self.retrieval.exposure == "prefetch":
            new_config["retrieval"]["exposure"] = "agentic_tool"
        return new_config

    def graph_enabled(self) -> dict:
        """Return a config dict flipped to GraphRAG mode.

        Sets ``kind="graphrag"`` so ingest paths run graph extraction and
        ``retrieval.retriever="graphrag"`` so the Dispatcher routes queries to
        the graph retriever. All other fields are preserved.
        """
        new_config = self.model_dump()
        new_config["kind"] = "graphrag"
        new_config["retrieval"]["retriever"] = "graphrag"
        return new_config

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
        # Writes are strict, but an existing source may predate the ceiling.
        # Clamp only that legacy field and preserve the rest of its behavior
        # instead of making the whole row fall back to defaults.
        chunking = raw.get("chunking")
        if isinstance(chunking, dict):
            stored_max = chunking.get("max_tokens")
            if (
                isinstance(stored_max, int)
                and not isinstance(stored_max, bool)
                and stored_max > MAX_CHUNK_TOKENS
            ):
                raw = {
                    **raw,
                    "chunking": {
                        **chunking,
                        "max_tokens": MAX_CHUNK_TOKENS,
                    },
                }
        # ``reranker`` was a reserved slot that took any dict; a row holding one
        # this version cannot read has relevance off, keeping the rest. So has a
        # row that also sets a prescreen, which keeps that.
        retrieval = raw.get("retrieval")
        if isinstance(retrieval, dict) and retrieval.get("reranker") is not None:
            try:
                RerankerConfig.model_validate(retrieval["reranker"])
                readable = retrieval.get("prescreen") is None
            except Exception:
                readable = False
            if not readable:
                raw = {**raw, "retrieval": {**retrieval, "reranker": None}}
        try:
            return cls.model_validate(raw)
        except Exception:
            return cls()
