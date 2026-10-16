"""Per-source retrieval dispatcher (D4).

Groups a per-source list by its ``config.retrieval.retriever`` key, builds one
retriever instance per group, and merges their results under a single shared
token budget so no group can starve another.

Parity guarantee: when every source is ``classic``/``default`` (the case for
every existing source) all sources flow into ONE ``ClassicRAG`` instance built
exactly as today, so the output — including token-budget behaviour — is
byte-identical to the pre-dispatch path.

The decision model's rerank (``DECISION_RERANK_MODE``) keeps that guarantee
whenever it cannot answer: the group's fetch is widened to a candidate pool,
the retriever tags the docs it would have returned anyway (``_base``), and a
stage that falls back returns exactly those. With
``PER_SOURCE_RETRIEVAL_ENABLED=False`` there is no Dispatcher, so no stage runs
and the model is never called.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from docsgpt.core.settings import settings
from docsgpt.decisions import record
from docsgpt.retriever.base import BaseRetriever
from docsgpt.retriever.retriever_creator import RetrieverCreator
from docsgpt.retriever.stages import build_group_stages
from docsgpt.retriever.stages.prescreen import max_candidate_k
from docsgpt.retriever.stages.relevance import (
    RERANK,
    base_selection,
    decision_prescreen_enabled,
    instance_mode,
    rollout_on,
    source_mode,
)
from docsgpt.storage.db.source_config import RetrievalConfig
from docsgpt.tracing.retrieval import describe_documents, start_retrieval_span
from docsgpt.utils import num_tokens_from_string

logger = logging.getLogger(__name__)

# Retriever keys that share ClassicRAG's single-instance / shared-budget model.
# Grouping all of them into one instance is what preserves byte-identical parity
# for the all-classic case.
_CLASSIC_KEYS = frozenset({"classic", "default"})

# Retriever keys that subclass ClassicRAG and accept ``defer_rephrase``, so the
# eager ctor rephrase can be skipped and computed lazily per-source. Unknown
# keys are excluded: a future non-ClassicRAG retriever may not accept the kwarg.
_DEFERRABLE_KEYS = _CLASSIC_KEYS | {"hybrid"}

# Fields that, when left at their defaults, mean the source did not opt into any
# per-source retrieval override — so it can flow through the global ClassicRAG
# path unchanged (byte-identical parity).
_DEFAULT_RETRIEVAL = RetrievalConfig()

# A post-retrieval stage: takes the candidate docs a group produced (plus the
# context: the raw ``query``, the ``search_query`` the retriever searched with,
# the ``retriever`` key and the ``selection_size`` of the retriever's usual
# selection) and returns a possibly-filtered/reordered list.
Stage = Callable[[List[Dict[str, Any]], Dict[str, Any]], List[Dict[str, Any]]]


class Dispatcher(BaseRetriever):
    """Route per-source retrieval to grouped retrievers under a shared budget."""

    def __init__(
        self,
        source,
        chat_history=None,
        prompt="",
        chunks=6,
        doc_token_limit=50000,
        model_id="docsgpt-local",
        user_api_key=None,
        agent_id=None,
        llm_name=settings.LLM_PROVIDER,
        api_key=settings.API_KEY,
        decoded_token=None,
        model_user_id=None,
        request_id=None,
        sources: Optional[List[Dict[str, Any]]] = None,
        stages: Optional[List[Stage]] = None,
        include_scores: bool = False,
        usage_source: str = "rag_prescreen",
        conversation_id: Optional[str] = None,
        relevance_feature: Optional[str] = None,
        apply_rollout: bool = True,
        record_candidates: bool = False,
    ):
        """Build the dispatcher.

        Args:
            source: ClassicRAG-style source dict (``{"active_docs": [...]}``)
                plus the original ``question``. Used as the fallback group when
                no per-source ``sources`` list is supplied.
            chunks: Global default top-k, used when a source carries no
                per-source ``chunks`` hint.
            doc_token_limit: Hard cap shared across all groups.
            sources: Per-source list; each entry is ``{"id": str, "retrieval":
                RetrievalConfig | dict | None}``. When empty the dispatcher
                falls back to the single classic group over ``source``.
            stages: Optional post-retrieval stages applied to each group's
                candidates before its prescreens and rerank, so a filter here
                (the search tool's path filter) narrows the pool they choose
                from. Default: none (pass-through).
            include_scores: Ask each group's retriever to attach the raw store
                score to every doc it returns. Off for the answer pipeline; on
                for the retrieval-test endpoint.
            usage_source: Cost-attribution tag for the prescreen stage's LLM
                calls.
            conversation_id: Keys the rerank's rollout arm
                (``DECISION_RERANK_ROLLOUT_PERCENT``); the request id stands in
                for a conversation not created yet.
            relevance_feature: Decision feature label of every relevance stage,
                instead of ``rag_rerank`` / ``rag_prescreen``.
            apply_rollout: False puts the request in the rollout whatever
                ``DECISION_RERANK_ROLLOUT_PERCENT`` says (the retrieval test,
                which has no conversation to hash).
            record_candidates: Keep every group's candidates as its stages
                received them in ``last_candidates``, for the retrieval test's
                comparison with retriever order.
        """
        self._usage_source = usage_source
        self._relevance_feature = relevance_feature
        self._rollout_key = conversation_id or request_id
        self._apply_rollout = apply_rollout
        self._record_candidates = record_candidates
        # After ``search()``: the best relevance any stage scored (None when
        # none did), how many candidates the groups handed their stages and,
        # with ``record_candidates``, those candidates: ``{"doc", "base",
        # "relevance"}`` in retriever order, ``base`` when the retrieval would
        # have returned the doc without the rerank's wider pool.
        self.last_top_relevance: Optional[float] = None
        self.last_candidate_count = 0
        self.last_candidates: List[Dict[str, Any]] = []
        self._ctor_kwargs = dict(
            include_scores=include_scores,
            chat_history=chat_history,
            prompt=prompt,
            doc_token_limit=doc_token_limit,
            model_id=model_id,
            user_api_key=user_api_key,
            agent_id=agent_id,
            llm_name=llm_name,
            api_key=api_key,
            decoded_token=decoded_token,
            model_user_id=model_user_id,
            request_id=request_id,
        )
        self.source = source or {}
        self.original_question = self.source.get("question", "")
        self.chunks = chunks
        self.doc_token_limit = doc_token_limit
        self.stages: List[Stage] = stages or []
        self._sources = sources or []
        self._groups = self._build_groups()

    def _build_groups(self) -> List[Dict[str, Any]]:
        """Group the per-source list by retriever key, rerank mode and decision prescreen.

        All classic/default sources collapse into one group (exact parity);
        each non-classic retriever key gets its own group. A source whose
        rerank mode differs from the rest of its retriever's sources (one that
        opted out, say) gets a group of its own, so it is never judged by a
        policy it turned off. Likewise each prescreen policy (LLM or decision
        model, with the settings that change what it keeps) groups only the
        sources that set it, so its ``max_keep`` and threshold never cut
        another source's chunks and the sources beside it keep their own
        prescreen or rerank. Without any prescreen the grouping is what it has
        always been. With no per-source list, a single classic group over
        ``self.source`` is produced.

        Each group's ``relevance`` holds its resolved rerank: ``mode``
        (``off``, ``monitor`` or ``on``), the rollout ``arm``, the pool size
        ``candidate_k`` and per-source ``thresholds``. It is read from every
        source's config, not through ``_is_override``: a source that sets only
        a reranker keeps the shared chunk budget.
        """
        active_docs = self.source.get("active_docs")
        if isinstance(active_docs, str):
            active_docs = [active_docs]
        active_docs = active_docs or []
        resolved: Dict[str, Any] = {}

        def rerank(key: str, retrieval: Optional[RetrievalConfig]) -> tuple:
            if "instance" not in resolved:
                resolved["instance"] = instance_mode()
                resolved["rollout"] = not self._apply_rollout or rollout_on(
                    self._rollout_key, settings.DECISION_RERANK_ROLLOUT_PERCENT
                )
            reranker = retrieval.reranker_config() if retrieval is not None else None
            mode, arm = source_mode(key, reranker, resolved["instance"], resolved["rollout"])
            return mode, arm, reranker

        def screened(retrieval: RetrievalConfig) -> Optional[tuple]:
            """The source's prescreen policy: what it runs on and the settings that change what it keeps.

            ``None`` without a prescreen, so sources that set none group exactly as they always have. A
            ``backend: decision`` prescreen that does not run on the model is an LLM one, and groups with them.
            """
            ps = retrieval.prescreen_config()
            if ps is None:
                return None
            if ps.backend == "decision":
                if "prescreen" not in resolved:
                    resolved["prescreen"] = decision_prescreen_enabled()
                if resolved["prescreen"]:
                    threshold = settings.DECISION_PRESCREEN_THRESHOLD if ps.min_relevance is None else ps.min_relevance
                    return "decision", ps.max_keep, threshold
            return "llm", ps.max_keep, ps.batch_size, ps.model

        def new_group(key: str, mode: str) -> Dict[str, Any]:
            return {
                "retriever": key,
                "doc_ids": [],
                "retrievals": {},
                "relevance": {"mode": mode, "arm": None, "candidate_k": 0, "thresholds": {}},
            }

        def add(group: Dict[str, Any], doc_id: str, arm: Optional[str], reranker: Any) -> None:
            relevance = group["relevance"]
            if arm and relevance["arm"] in (None, "source"):
                relevance["arm"] = arm
            if relevance["mode"] == "off":
                return
            k = reranker.candidate_k if reranker is not None and reranker.candidate_k else None
            relevance["candidate_k"] = max(relevance["candidate_k"], k or settings.DECISION_RERANK_CANDIDATE_K)
            if reranker is not None and reranker.min_relevance is not None:
                relevance["thresholds"][doc_id] = reranker.min_relevance

        if not self._sources:
            mode, arm, _ = rerank("classic", None)
            group = new_group("classic", mode)
            group["doc_ids"] = list(active_docs)
            add(group, "", arm, None)
            return [group]

        grouped: Dict[tuple, Dict[str, Any]] = {}
        for entry in self._sources:
            doc_id = entry.get("id")
            if not doc_id:
                continue
            retrieval = self._coerce_retrieval(entry.get("retrieval"))
            key = (retrieval.retriever or "classic").lower()
            if key in _CLASSIC_KEYS:
                key = "classic"
            mode, arm, reranker = rerank(key, retrieval)
            group = grouped.setdefault((key, mode, screened(retrieval)), new_group(key, mode))
            if doc_id not in group["doc_ids"]:
                group["doc_ids"].append(doc_id)
                add(group, doc_id, arm, reranker)
            # Only record an override when the source opted into a non-default
            # retrieval config; a default classic source stays on the global
            # ClassicRAG path so all-classic output is byte-identical to today.
            if self._is_override(retrieval):
                group["retrievals"][doc_id] = retrieval

        if not grouped:
            mode, arm, _ = rerank("classic", None)
            group = new_group("classic", mode)
            group["doc_ids"] = list(active_docs)
            add(group, "", arm, None)
            return [group]

        # Defend the parity guarantee: any active_doc the per-source list omitted
        # would otherwise be dropped from every group. Route the strays through
        # the classic group with default retrieval config so they're still
        # retrieved (creating the classic group if no source opted into it).
        grouped_ids = {
            doc_id for group in grouped.values() for doc_id in group["doc_ids"]
        }
        missing = [doc_id for doc_id in active_docs if doc_id not in grouped_ids]
        if missing:
            mode, arm, _ = rerank("classic", None)
            classic_group = grouped.setdefault(("classic", mode, None), new_group("classic", mode))
            for doc_id in missing:
                if doc_id not in classic_group["doc_ids"]:
                    classic_group["doc_ids"].append(doc_id)
                    add(classic_group, doc_id, arm, None)
        return list(grouped.values())

    @staticmethod
    def _is_override(retrieval: RetrievalConfig) -> bool:
        """True if the source opted into any read-path retrieval override.

        Compares the read-path knobs ClassicRAG acts on (chunks /
        score_threshold / rephrase_query) plus an opted-in prescreen config; a
        source left at defaults takes the global path so all-classic retrieval
        stays byte-identical with zero extra LLM calls.

        A graph source's ``graph`` options count too: they are read from the
        per-source config this records, so a source that changes only those
        would otherwise run the defaults and the options would do nothing.
        They mean nothing to any other retriever, so they only count for
        ``graphrag`` -- an override hands the source its own chunk budget as
        well, which a classic source must not pick up from a graph setting.
        """
        return (
            retrieval.chunks != _DEFAULT_RETRIEVAL.chunks
            or retrieval.score_threshold != _DEFAULT_RETRIEVAL.score_threshold
            or retrieval.rephrase_query != _DEFAULT_RETRIEVAL.rephrase_query
            or retrieval.prescreen is not None
            or (
                (retrieval.retriever or "").lower() == "graphrag"
                and retrieval.graph != _DEFAULT_RETRIEVAL.graph
            )
        )

    @staticmethod
    def _coerce_retrieval(raw: Any) -> RetrievalConfig:
        """Coerce a per-source ``retrieval`` value to a ``RetrievalConfig``."""
        if isinstance(raw, RetrievalConfig):
            return raw
        if isinstance(raw, dict):
            try:
                return RetrievalConfig.model_validate(raw)
            except Exception:
                return RetrievalConfig()
        return RetrievalConfig()

    def _budget_for_group(self, n_groups: int, group_idx: int) -> int:
        """Split the shared token budget across groups.

        With one group the full ``doc_token_limit`` is returned, so the single
        ClassicRAG instance reproduces today's budget exactly. With multiple
        groups the budget is divided evenly (remainder to the first groups) so
        the total never exceeds ``doc_token_limit``.
        """
        if n_groups <= 1:
            return self.doc_token_limit
        base = self.doc_token_limit // n_groups
        remainder = self.doc_token_limit % n_groups
        return base + (1 if group_idx < remainder else 0)

    def _build_group_retriever(self, group: Dict[str, Any], budget: int):
        """Build the retriever for ``group`` with its budget and source list."""
        retriever_key = group["retriever"]
        group_source = dict(self.source)
        group_source["active_docs"] = group["doc_ids"]
        kwargs = dict(self._ctor_kwargs)
        kwargs["doc_token_limit"] = budget
        kwargs["source"] = group_source
        # Prescreen fetches a larger candidate set, then a stage trims it; raise
        # the effective top-k to candidate_k so the base retriever fetches
        # enough for the stage to filter down to the final chunks.
        candidate_k = max_candidate_k(group["retrievals"])
        kwargs["chunks"] = max(self.chunks, candidate_k or 0)
        # With per-source configs the rephrase decision is per-source, so defer
        # the eager rephrase to let a rephrase_query=False source skip the call.
        if group["retrievals"] and retriever_key in _DEFERRABLE_KEYS:
            kwargs["defer_rephrase"] = True
        retriever = RetrieverCreator.create_retriever(retriever_key, **kwargs)
        # Hand the per-source retrieval configs to the classic retriever so it
        # can honour per-source chunks/score_threshold/rephrase in its loop, plus
        # the un-inflated top-k so a prescreen source's candidate_k doesn't
        # become the top-k of the sources beside it in the group.
        if group["retrievals"]:
            setattr(retriever, "per_source_retrieval", group["retrievals"])
        setattr(retriever, "base_chunks", self.chunks)
        # The rerank chooses from a wider pool. A prescreen already fetched its
        # own (the rerank then reorders what it kept), and a retriever that
        # cannot tag its usual selection is reranked within that selection.
        if self._pooled(group) and hasattr(retriever, "candidate_k"):
            setattr(retriever, "candidate_k", group["relevance"]["candidate_k"])
            setattr(retriever, "candidate_tokens", settings.DECISION_RERANK_CANDIDATE_TOKENS)
        return retriever

    @staticmethod
    def _pooled(group: Dict[str, Any]) -> bool:
        """Whether the group's rerank widens its fetch: on or monitor, with no prescreen."""
        relevance = group.get("relevance") or {}
        return relevance.get("mode") in ("on", "monitor") and max_candidate_k(group["retrievals"]) is None

    def _group_stages(self, group: Dict[str, Any]) -> List[Stage]:
        """Stages for a group: caller-supplied stages, then its prescreens and rerank.

        Prescreen and rerank stages come from ``stages.build_group_stages``, so a
        group with no opted-in source and the rerank off adds nothing — the
        default path stays a pure no-op with zero extra LLM or model calls.
        """
        keys = ("llm_name", "api_key", "model_id", "user_api_key", "decoded_token", "agent_id", "model_user_id",
                "request_id")
        built = build_group_stages(
            group,
            llm={key: self._ctor_kwargs.get(key) for key in keys},
            usage_source=self._usage_source,
            feature=self._relevance_feature,
        )
        return list(self.stages) + built

    def _run_stages(
        self,
        docs: List[Dict[str, Any]],
        context: Dict[str, Any],
        stages: List[Stage],
    ) -> List[Dict[str, Any]]:
        """Apply the given post-retrieval stages in order (no-op when empty).

        A widened pool never leaves unjudged: docs outside the usual selection
        that no relevance stage scored are dropped again.
        """
        for stage in stages:
            try:
                docs = stage(docs, context)
            except Exception as exc:
                logger.warning("Retrieval stage failed, skipping: %s", exc)
        if any("_base" in doc and not doc["_base"] and "relevance" not in doc for doc in docs):
            docs = [doc for doc in docs if doc.get("_base", True) or "relevance" in doc]
        return docs

    @staticmethod
    def _context(query: str, retriever: Any, group: Dict[str, Any]) -> Dict[str, Any]:
        """The stage context: the raw query, the query the retriever searched with, and the retriever key."""
        search_query = getattr(retriever, "search_query", None)
        return {
            "query": query,
            "search_query": search_query if isinstance(search_query, str) and search_query else query,
            "retriever": group["retriever"],
        }

    @staticmethod
    def _fit(docs: List[Dict[str, Any]], budget: int) -> List[Dict[str, Any]]:
        """``docs`` in order under 90% of ``budget`` tokens, as the multi-group merge counts them.

        Applied after a rerank that drew on a pool beyond the usual selection,
        whose candidate fetch had a larger budget; the usual selection already
        fits, so a list of only its docs is returned unchanged.
        """
        if all(doc.get("_base", True) for doc in docs):
            return docs
        cap = max(int(budget * 0.9), 100)
        cumulative_tokens = 0
        kept = []
        for doc in docs:
            if cumulative_tokens >= cap:
                break
            doc_tokens = num_tokens_from_string(f"{doc.get('filename', '')}\n{doc.get('text', '')}")
            if cumulative_tokens + doc_tokens < cap:
                kept.append(doc)
                cumulative_tokens += doc_tokens
        return kept

    def search(self, query: str = "") -> List[Dict[str, Any]]:
        """Run every group under the shared budget and merge the results."""
        sources = [s for group in self._groups for s in group.get("doc_ids", [])]
        arms = {group["relevance"]["arm"] for group in self._groups if group["relevance"]["arm"]}
        with start_retrieval_span(
            "retrieval",
            sources=sources,
            **{
                "docsgpt.retriever": "Dispatcher",
                "docsgpt.group_count": len(self._groups),
                "docsgpt.rerank.arm": ",".join(sorted(arms)) or None,
            },
        ) as span:
            self.last_top_relevance = None
            self.last_candidate_count = 0
            self.last_candidates = []
            if "control" in arms:
                # The control arm asks the model nothing; its entry is what an
                # A/B comparison counts the arm by.
                record.add(RERANK, {"arm": "control"}, status="skipped", applied=False)
            docs = self._search_groups(query)
            for doc in docs:
                doc.pop("_base", None)
            describe_documents(span, docs)
            return docs

    def _stage_group(self, query: str, retriever: Any, group: Dict[str, Any], docs: List[Dict[str, Any]],
                     budget: int) -> List[Dict[str, Any]]:
        """Run a group's stages over what its retriever returned, then fit it back into the group's budget."""
        context = self._context(query, retriever, group)
        context["selection_size"] = len(base_selection(docs))
        self.last_candidate_count += len(docs)
        before = [(doc, doc.get("_base", True)) for doc in docs] if self._record_candidates else []
        docs = self._run_stages(docs, context, self._group_stages(group))
        if before:
            scored = {id(doc): p for doc, p in context.get("scored") or []}
            self.last_candidates.extend(
                {"doc": doc, "base": bool(base), "relevance": scored.get(id(doc))} for doc, base in before
            )
        top = context.get("top_relevance")
        if top is not None and (self.last_top_relevance is None or top > self.last_top_relevance):
            self.last_top_relevance = top
        return self._fit(docs, budget)

    def _search_groups(self, query: str) -> List[Dict[str, Any]]:
        groups = self._groups
        n_groups = len(groups)

        # Fast path / exact parity: a single group is just the underlying
        # retriever with the full budget — no merge accounting at all.
        if n_groups == 1:
            retriever = self._build_group_retriever(
                groups[0], self.doc_token_limit
            )
            docs = retriever.search(query) if query else retriever.search()
            return self._stage_group(query, retriever, groups[0], docs, self.doc_token_limit)

        outputs: List[List[Dict[str, Any]]] = []
        for idx, group in enumerate(groups):
            budget = self._budget_for_group(n_groups, idx)
            retriever = self._build_group_retriever(group, budget)
            try:
                group_docs = retriever.search(query) if query else retriever.search()
            except Exception as exc:
                # Log the exception type only — a raw exception message can
                # carry the vector-store DSN (with credentials) on connection
                # errors.
                logger.error(
                    "Group '%s' search failed: %s",
                    group["retriever"],
                    type(exc).__name__,
                )
                continue
            outputs.append(self._stage_group(query, retriever, group, group_docs, budget))

        concatenated = [doc for group_docs in outputs for doc in group_docs]
        # Fully scored, the merge runs best-first, so the shared cap drops the
        # least relevant docs; partly scored, it keeps group order.
        if concatenated and all(isinstance(doc.get("relevance"), (int, float)) for doc in concatenated):
            concatenated.sort(key=lambda doc: -doc["relevance"])
        merged: List[Dict[str, Any]] = []
        cap = max(int(self.doc_token_limit * 0.9), 100)
        cumulative_tokens = 0
        for doc in concatenated:
            if cumulative_tokens >= cap:
                break
            header = f"{doc.get('filename', '')}\n{doc.get('text', '')}"
            doc_tokens = num_tokens_from_string(header)
            if cumulative_tokens + doc_tokens < cap:
                merged.append(doc)
                cumulative_tokens += doc_tokens
        return merged


def build_dispatcher(create_classic: Callable[[], BaseRetriever], **kwargs):
    """Build a Dispatcher, or fall back to the legacy single retriever.

    Honours ``settings.PER_SOURCE_RETRIEVAL_ENABLED``: when False, returns the
    legacy single ClassicRAG built by ``create_classic`` (the kill-switch).

    Args:
        create_classic: Zero-arg factory returning the legacy single retriever.
        **kwargs: Dispatcher constructor kwargs (including ``sources``).

    Returns:
        A ``Dispatcher`` or the legacy retriever from ``create_classic``.
    """
    if not settings.PER_SOURCE_RETRIEVAL_ENABLED:
        return create_classic()
    return Dispatcher(**kwargs)
