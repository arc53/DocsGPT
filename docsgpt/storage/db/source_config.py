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


#: Most candidates one decision-model relevance call takes (``DECISION_RELEVANCE_MAX_PASSAGES`` caps it too).
DECISION_MAX_CANDIDATES = 100


def _probability(value: Optional[float]) -> Optional[float]:
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError("must be between 0 and 1")
    return value


class PreScreenConfig(BaseModel):
    """Map-reduce candidate-filter config (D12); off unless set.

    A base retriever fetches ``candidate_k`` candidates and at most
    ``max_keep`` survivors pass to the answer. With ``backend="llm"`` an LLM
    screens them in batches of ``batch_size`` (``model`` is optional; when None
    the stage reuses the request's resolved model), a query-time LLM cost, so
    it stays opt-in. With ``backend="decision"``, while the operator has set
    ``DECISION_PRESCREEN_ENABLED``, the decision model scores them in one call
    and keeps those at or above ``min_relevance``, most relevant first, and
    ``batch_size`` and ``model`` are ignored; otherwise it runs as ``llm``.
    Stored rows without a backend are ``llm``.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_k: int = 40  # candidates to fetch before screening
    model: Optional[str] = None  # None → reuse the resolved request model
    batch_size: int = 10  # candidates per LLM screening call
    max_keep: int = 8  # survivors kept after screening
    backend: Literal["llm", "decision"] = "llm"
    min_relevance: Optional[float] = None  # decision only; None → DECISION_PRESCREEN_THRESHOLD

    @field_validator("candidate_k", "batch_size", "max_keep")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        if value > 500:
            raise ValueError("must be <= 500")
        return value

    @field_validator("min_relevance")
    @classmethod
    def _min_relevance(cls, value: Optional[float]) -> Optional[float]:
        return _probability(value)

    @model_validator(mode="after")
    def _coherent(self) -> "PreScreenConfig":
        if self.max_keep > self.candidate_k:
            raise ValueError("max_keep must be <= candidate_k")
        if self.backend == "decision" and self.candidate_k > DECISION_MAX_CANDIDATES:
            raise ValueError(f"candidate_k must be <= {DECISION_MAX_CANDIDATES} with the decision backend")
        return self


class RerankerConfig(BaseModel):
    """A source's rerank by the decision model, under the instance's ``DECISION_RERANK_MODE``.

    The operator turns the rerank on; while that mode is ``off`` this config
    does nothing. While it is on, ``type="decision"`` reranks the source with
    these overrides even where the instance default does not reach (another
    retriever, the rollout's control arm), and ``type="off"`` opts the source
    out, for example a source of one-line rows, which score low against any
    query. No ``reranker`` at all follows the instance mode.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["decision", "off"] = "decision"
    min_relevance: Optional[float] = None  # None → DECISION_RERANK_THRESHOLD
    candidate_k: Optional[int] = None  # None → DECISION_RERANK_CANDIDATE_K

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
    reranker: Optional[dict] = None  # None = the instance mode; else RerankerConfig dict
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
        """Validate ``reranker`` through ``RerankerConfig`` when present (strict, as ``prescreen``)."""
        if self.reranker is not None:
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
        # this version cannot read follows the instance mode, keeping the rest.
        retrieval = raw.get("retrieval")
        if isinstance(retrieval, dict) and retrieval.get("reranker") is not None:
            try:
                RerankerConfig.model_validate(retrieval["reranker"])
            except Exception:
                raw = {**raw, "retrieval": {**retrieval, "reranker": None}}
        try:
            return cls.model_validate(raw)
        except Exception:
            return cls()
