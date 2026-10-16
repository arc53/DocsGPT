"""Relevance scored by the decision model: the rerank stage and the prescreen's ``decision`` backend.

Each candidate chunk gets a calibrated ``p(relevant)`` against the query the retrieval searched with
(``search_query``), in one call per stage. The rerank orders the candidates by it and keeps as many chunks as the
retrieval would have returned without it; the decision prescreen keeps those at or above a threshold, capped at
``max_keep``. Both fail open: on any answer short of every candidate scored, the stage returns exactly what the
retrieval would have returned without it.

The Dispatcher marks that selection. When it widens a group's fetch for the rerank, the retriever tags every
candidate with ``_base``: ``True`` for the chunks it would have returned at its normal size. A list without the tag
was not widened, so all of it is the selection.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from docsgpt import decisions, tracing
from docsgpt.core.settings import settings
from docsgpt.decisions import Budget, Q, Request, record, states
from docsgpt.retriever.labels import normalize_source_id

logger = logging.getLogger(__name__)

RERANK = "rag_rerank"
PRESCREEN = "rag_prescreen"

#: Characters of the query kept in a state, so a runaway rephrase cannot crowd out the passage.
QUERY_CHARS = 1000

#: What a non-``ok`` batch status is recorded as; ``partial`` counts as no answer.
_STATUS = {"ok": "ok", "timeout": "timeout", "unavailable": "unavailable"}


@dataclass(frozen=True)
class RelevancePolicy:
    """What a ``RelevanceStage`` does with the scores.

    Attributes:
        keep: Most chunks returned; ``None`` keeps as many as the retrieval's own selection had.
        threshold: Chunks scoring below it are dropped; 0 reorders only.
        min_keep: Chunks a threshold always leaves, most relevant first, from a non-empty input.
        thresholds_by_source: Per-source thresholds, by source id (a doc's ``source_id``).
        feature: The decision feature label: ``rag_rerank``, ``rag_prescreen`` or ``retrieval_test``.
        mode: ``on`` acts on the scores; ``monitor`` only records them.
        arm: The rollout arm the stage runs in (``on``, or ``source`` where a source turned it on itself).
    """

    keep: Optional[int]
    threshold: float
    min_keep: int
    thresholds_by_source: Dict[str, float] = field(default_factory=dict)
    feature: str = RERANK
    mode: str = "on"
    arm: Optional[str] = None


@dataclass(frozen=True)
class Scores:
    """The outcome of one relevance call.

    Attributes:
        values: ``p(relevant)`` per passage, or ``None`` unless every passage was scored.
        status: The decision record's status: ``ok``, ``timeout``, ``unavailable``, ``skipped`` or ``error``.
        reason: Why there are no values, else ``None``.
        passage_select: ``best`` when passages were cut to their best window (a CPU runtime), else ``full``.
        passage_tokens: The window's size in tokens, or ``None`` for whole passages.
        ms: Time spent waiting for the model.
    """

    values: Optional[List[float]]
    status: str
    reason: Optional[str] = None
    passage_select: str = "full"
    passage_tokens: Optional[int] = None
    ms: float = 0.0


def base_selection(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What the retrieval would have returned without the widened fetch, in retriever order."""
    if any("_base" in doc for doc in docs):
        return [doc for doc in docs if doc.get("_base")]
    return list(docs)


def score(docs: List[Dict[str, Any]], query: str, *, feature: str, budget: Budget) -> Scores:
    """Score every doc's text against ``query`` in one decision call.

    Where the model runs on a CPU, each passage is cut to its best window of
    ``DECISION_RELEVANCE_CPU_PASSAGE_TOKENS`` tokens first (``states.best_window``); elsewhere whole chunks are
    scored.

    Args:
        docs: Retrieved docs; only ``text`` is read.
        query: The query to judge against; cut to ``QUERY_CHARS`` characters.
        feature: The decision feature label.
        budget: Lane and deadline of the call.
    """
    query = query[:QUERY_CHARS]
    texts = [str(doc.get("text") or "") for doc in docs]
    info = decisions.model_info()
    select, size = "full", None
    if info is not None and states.cpu_runtime(info.runtime):
        select, size = "best", settings.DECISION_RELEVANCE_CPU_PASSAGE_TOKENS
        windows = [states.best_window(text, query, size) for text in texts]
        if any(window is None for window in windows):
            # The tokenizer comes up with the model; whole chunks would not finish on a CPU anyway.
            decisions.warm()
            return Scores(None, "unavailable", "loading", select, size)
        texts = windows
    started = time.monotonic()
    batch = decisions.decide_batch(
        [Request(states.relevance(query, text), {"relevant": Q.RELEVANT}) for text in texts],
        feature=feature,
        budget=budget,
    )
    ms = (time.monotonic() - started) * 1000
    if batch.status != "ok":
        status = _STATUS.get(batch.status) or ("timeout" if "timeout" in batch.reasons else "error")
        reason = next((r for r in batch.reasons if r), None) or batch.status
        return Scores(None, status, reason, select, size, ms)
    return Scores([decision.p("relevant") for decision in batch], "ok", None, select, size, ms)


def score_relevance(
    docs: List[Dict[str, Any]], query: str, *, feature: str, budget: Budget
) -> Optional[List[float]]:
    """``p(relevant)`` per doc, or ``None`` (partial, timeout, unavailable): see ``score``."""
    return score(docs, query, feature=feature, budget=budget).values


def rollout_on(key: Optional[str], percent: int) -> bool:
    """Whether a conversation is in the rollout of ``DECISION_RERANK_ROLLOUT_PERCENT``.

    Deterministic per key, so every turn of a conversation lands in the same arm. Without a key only a full
    rollout includes it.

    Args:
        key: The conversation id (else the request id).
        percent: Share of keys in the rollout, 0 to 100.
    """
    if percent >= 100:
        return True
    if percent <= 0 or not key:
        return False
    bucket = int(hashlib.sha256(str(key).encode()).hexdigest()[:8], 16) % 100
    return bucket < percent


def instance_mode() -> str:
    """What ``DECISION_RERANK_MODE`` does now: ``off``, ``monitor`` or ``on`` (``auto`` resolved by measurement)."""
    mode = settings.DECISION_RERANK_MODE
    if mode == "off" or not decisions.get_decider().enabled:
        return "off"
    if mode == "auto":
        from docsgpt.decisions.features import RAG_RERANK

        return RAG_RERANK.auto_mode if decisions.auto_on(RAG_RERANK.name) else "off"
    return mode


def rerank_enabled() -> bool:
    """Whether the operator turned the rerank on (``DECISION_RERANK_MODE`` not ``off``), from settings alone.

    Unlike ``instance_mode`` it never measures, loads or times the model, so a public route can ask it; under
    ``auto`` the rerank may still resolve off.
    """
    return settings.DECISION_RERANK_MODE != "off" and decisions.get_decider().enabled


def source_mode(retriever: str, reranker: Any, instance: str, in_rollout: bool) -> tuple[str, Optional[str]]:
    """The rerank mode of one source and its rollout arm.

    The operator turns the rerank on (``DECISION_RERANK_MODE``); a source cannot. While the instance mode is
    ``off`` every source is off, a stored ``reranker: {type: decision}`` included, so no source can make the
    process load the model. While it is on, such a source is reranked even where the instance default does not
    reach (a retriever outside ``DECISION_RERANK_RETRIEVERS``, the control arm), and ``type: off`` opts a source
    out.

    Args:
        retriever: The source's retriever key (``classic`` for the classic aliases).
        reranker: The source's ``RerankerConfig``, or ``None`` to follow the instance.
        instance: ``instance_mode()``.
        in_rollout: ``rollout_on`` for the request.

    Returns:
        ``(mode, arm)``: ``off``, ``monitor`` or ``on``, and ``on``, ``control``, ``source`` or ``None`` when the
        rollout does not apply.
    """
    if instance == "off" or (reranker is not None and reranker.type == "off"):
        return "off", None
    if reranker is not None:
        return "on", "source"
    if retriever not in {key.lower() for key in settings.DECISION_RERANK_RETRIEVERS}:
        return "off", None
    if not in_rollout:
        return "off", "control"
    return instance, "on"


def decision_prescreen_enabled() -> bool:
    """Whether a prescreen with ``backend: decision`` runs on the decision model (``DECISION_PRESCREEN_ENABLED``).

    While it does not, such a prescreen runs as the LLM prescreen, so no source can make the process load the
    model.
    """
    return settings.DECISION_PRESCREEN_ENABLED and decisions.get_decider().enabled


class RelevanceStage:
    """A Dispatcher stage that scores a group's candidates and orders, filters or only records them."""

    def __init__(self, policy: RelevancePolicy):
        self.policy = policy

    def _threshold(self, doc: Dict[str, Any]) -> float:
        source = normalize_source_id(doc.get("source_id"))
        return self.policy.thresholds_by_source.get(source, self.policy.threshold)

    def _fallback(self, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        selection = base_selection(docs)
        return selection if self.policy.keep is None else selection[: self.policy.keep]

    def _choose(self, docs: List[Dict[str, Any]], values: List[float], keep: int) -> List[tuple]:
        """``(doc, p)`` kept from the scored docs: best first, ties in retriever order."""
        ranked = sorted(zip(docs, values), key=lambda pair: -pair[1])
        min_keep = self.policy.min_keep
        kept = [(doc, p) for rank, (doc, p) in enumerate(ranked) if rank < min_keep or p >= self._threshold(doc)]
        return kept[:keep]

    def __call__(self, docs: List[Dict[str, Any]], context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Score ``docs`` against the context's ``search_query`` (else ``query``) and apply the policy.

        The context's ``selection_size``, when set, is how many chunks the retrieval's own selection had before
        any stage ran; a policy without ``keep`` keeps that many.
        """
        if not docs:
            return docs
        policy = self.policy
        query = context.get("search_query") or context.get("query") or ""
        fallback = self._fallback(docs)
        # Scored at most DECISION_RELEVANCE_MAX_PASSAGES; later candidates are not considered.
        candidates = docs[: settings.DECISION_RELEVANCE_MAX_PASSAGES]
        # A stage before this one (the search tool's path filter) may have narrowed the pool; the rerank still
        # keeps as many chunks as the retrieval's own selection had, now from inside what is left.
        keep = max(len(fallback), context.get("selection_size") or 0) if policy.keep is None else policy.keep
        attributes = {
            "gen_ai.operation.name": "rerank",
            "docsgpt.rerank.backend": "decision",
            "docsgpt.rerank.mode": policy.mode,
            "docsgpt.rerank.feature": policy.feature,
            "docsgpt.rerank.arm": policy.arm,
            "docsgpt.candidate_count": len(candidates),
            "docsgpt.relevance_threshold": policy.threshold,
            "docsgpt.query_source": "rephrased" if query != (context.get("query") or "") else "raw",
        }
        with tracing.span(
            tracing.KIND_RERANK, "rerank relevance", attributes={k: v for k, v in attributes.items() if v is not None}
        ) as span:
            if not query:
                scores = Scores(None, "skipped", "no_query")
            else:
                try:
                    scores = score(
                        candidates, query, feature=policy.feature,
                        budget=Budget.hot(settings.DECISION_RELEVANCE_TIMEOUT),
                    )
                except Exception as exc:  # noqa: BLE001 -- a relevance call must never fail the retrieval
                    logger.warning("Relevance scoring failed, keeping the retrieval's own selection: %s",
                                   type(exc).__name__)
                    scores = Scores(None, "error", "error")
            chosen = self._choose(candidates, scores.values, keep) if scores.values is not None else None
            applied = chosen is not None and policy.mode == "on"
            if applied:
                result = []
                for doc, p in chosen:
                    doc["relevance"] = round(p, 4)
                    result.append(doc)
            else:
                result = fallback
            top = round(max(scores.values), 4) if scores.values else None
            context["top_relevance"] = top
            # Every candidate's score, kept or not, for a caller that shows them (the retrieval test's compare).
            context["scored"] = (
                [(doc, round(p, 4)) for doc, p in zip(candidates, scores.values)] if scores.values else []
            )
            fallback_ids = {id(doc) for doc in fallback}
            kept = [doc for doc, _ in chosen] if chosen is not None else fallback
            span.set(
                **{
                    "docsgpt.kept_count": len(result),
                    "docsgpt.top_relevance": top,
                    "docsgpt.decision.fallback": scores.reason,
                    "docsgpt.relevance.passage_select": scores.passage_select,
                    "docsgpt.relevance.passage_tokens": scores.passage_tokens,
                }
            )
            record.add(
                policy.feature,
                {
                    "candidates": len(candidates),
                    "kept": len(kept),
                    "replaced": sum(id(doc) not in fallback_ids for doc in kept),
                    "top": top,
                    "threshold": policy.threshold,
                    "query_source": attributes["docsgpt.query_source"],
                    "arm": policy.arm,
                    "passage_select": scores.passage_select,
                    "passage_tokens": scores.passage_tokens,
                },
                status=scores.status,
                applied=applied,
                ms=scores.ms,
            )
        return result


#: Retriever keys that name the classic retriever (``Dispatcher`` groups them as ``classic``).
_CLASSIC_ALIASES = frozenset({"classic", "default"})


def apply_relevance(
    docs: List[Dict[str, Any]], query: str, *, retriever: Optional[str] = None, rollout_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Order ``docs`` by relevance to ``query`` under the instance rerank, for a caller with no Dispatcher.

    It reorders only: every doc is kept, with its ``relevance``. The rerank's own gates apply
    (``instance_mode``, ``DECISION_RERANK_RETRIEVERS`` and the rollout), and while they leave it off, or when the
    call fails, ``docs`` come back as they were. Workflow agent nodes use it; they build their retriever directly,
    so no source config takes part.

    Args:
        docs: The retrieved docs, in retriever order.
        query: The query the docs were retrieved with.
        retriever: The retriever key that produced them (``classic`` when omitted).
        rollout_key: Keys the rollout arm (the conversation id, else the request id).
    """
    if not docs or not query:
        return docs
    key = (retriever or "classic").lower()
    key = "classic" if key in _CLASSIC_ALIASES else key
    mode, arm = source_mode(
        key, None, instance_mode(), rollout_on(rollout_key, settings.DECISION_RERANK_ROLLOUT_PERCENT)
    )
    if arm == "control":
        record.add(RERANK, {"arm": "control"}, status="skipped", applied=False)
    if mode == "off":
        return docs
    stage = RelevanceStage(RelevancePolicy(keep=len(docs), threshold=0.0, min_keep=len(docs), mode=mode, arm=arm))
    try:
        return stage(list(docs), {"query": query, "search_query": query})
    except Exception as exc:  # noqa: BLE001 -- a rerank must never fail the caller's retrieval
        logger.warning("Relevance ordering failed, keeping the retrieval's order: %s", type(exc).__name__)
        return docs
