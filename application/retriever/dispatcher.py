"""Per-source retrieval dispatcher (D4).

Groups a per-source list by its ``config.retrieval.retriever`` key, builds one
retriever instance per group, and merges their results under a single shared
token budget so no group can starve another.

Parity guarantee: when every source is ``classic``/``default`` (the case for
every existing source) all sources flow into ONE ``ClassicRAG`` instance built
exactly as today, so the output — including token-budget behaviour — is
byte-identical to the pre-dispatch path.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from application.core.settings import settings
from application.retriever.base import BaseRetriever
from application.retriever.retriever_creator import RetrieverCreator
from application.retriever.stages.prescreen import (
    build_prescreen_stages,
    max_candidate_k,
)
from application.storage.db.source_config import RetrievalConfig
from application.utils import num_tokens_from_string

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
# resolved query and context) and returns a possibly-filtered/reordered list.
# Left a no-op seam for the later prescreen/rerank stages (F1) to bolt onto.
Stage = Callable[[List[Dict[str, Any]], Dict[str, Any]], List[Dict[str, Any]]]


class Dispatcher(BaseRetriever):
    """Route per-source retrieval to grouped retrievers under a shared budget."""

    def __init__(
        self,
        source,
        chat_history=None,
        prompt="",
        chunks=2,
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
                candidates before final budgeting. Default: none (pass-through).
        """
        self._ctor_kwargs = dict(
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
        """Group the per-source list by retriever key.

        All classic/default sources collapse into one group (exact parity);
        each non-classic retriever key gets its own group. With no per-source
        list, a single classic group over ``self.source`` is produced.
        """
        active_docs = self.source.get("active_docs")
        if isinstance(active_docs, str):
            active_docs = [active_docs]
        active_docs = active_docs or []

        if not self._sources:
            return [
                {
                    "retriever": "classic",
                    "doc_ids": list(active_docs),
                    "retrievals": {},
                }
            ]

        grouped: Dict[str, Dict[str, Any]] = {}
        for entry in self._sources:
            doc_id = entry.get("id")
            if not doc_id:
                continue
            retrieval = self._coerce_retrieval(entry.get("retrieval"))
            key = (retrieval.retriever or "classic").lower()
            if key in _CLASSIC_KEYS:
                key = "classic"
            group = grouped.setdefault(
                key, {"retriever": key, "doc_ids": [], "retrievals": {}}
            )
            if doc_id not in group["doc_ids"]:
                group["doc_ids"].append(doc_id)
            # Only record an override when the source opted into a non-default
            # retrieval config; a default classic source stays on the global
            # ClassicRAG path so all-classic output is byte-identical to today.
            if self._is_override(retrieval):
                group["retrievals"][doc_id] = retrieval

        if not grouped:
            return [
                {"retriever": "classic", "doc_ids": list(active_docs), "retrievals": {}}
            ]

        # Defend the parity guarantee: any active_doc the per-source list omitted
        # would otherwise be dropped from every group. Route the strays through
        # the classic group with default retrieval config so they're still
        # retrieved (creating the classic group if no source opted into it).
        grouped_ids = {
            doc_id for group in grouped.values() for doc_id in group["doc_ids"]
        }
        missing = [doc_id for doc_id in active_docs if doc_id not in grouped_ids]
        if missing:
            classic_group = grouped.setdefault(
                "classic", {"retriever": "classic", "doc_ids": [], "retrievals": {}}
            )
            for doc_id in missing:
                if doc_id not in classic_group["doc_ids"]:
                    classic_group["doc_ids"].append(doc_id)
        return list(grouped.values())

    @staticmethod
    def _is_override(retrieval: RetrievalConfig) -> bool:
        """True if the source opted into any read-path retrieval override.

        Compares the read-path knobs ClassicRAG acts on (chunks /
        score_threshold / rephrase_query) plus an opted-in prescreen config; a
        source left at defaults takes the global path so all-classic retrieval
        stays byte-identical with zero extra LLM calls.
        """
        return (
            retrieval.chunks != _DEFAULT_RETRIEVAL.chunks
            or retrieval.score_threshold != _DEFAULT_RETRIEVAL.score_threshold
            or retrieval.rephrase_query != _DEFAULT_RETRIEVAL.rephrase_query
            or retrieval.prescreen is not None
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
        # can honour per-source chunks/score_threshold/rephrase in its loop.
        if group["retrievals"]:
            setattr(retriever, "per_source_retrieval", group["retrievals"])
        return retriever

    def _group_stages(self, group: Dict[str, Any]) -> List[Stage]:
        """Stages for a group: caller-supplied stages + prescreen stages.

        Prescreen stages are built from the group's per-source prescreen config,
        so a group with no opted-in source adds nothing — the default path stays
        a pure no-op with zero extra LLM calls.
        """
        prescreen = build_prescreen_stages(
            group["retrievals"],
            llm_name=self._ctor_kwargs.get("llm_name"),
            api_key=self._ctor_kwargs.get("api_key"),
            model_id=self._ctor_kwargs.get("model_id"),
            user_api_key=self._ctor_kwargs.get("user_api_key"),
            decoded_token=self._ctor_kwargs.get("decoded_token"),
            agent_id=self._ctor_kwargs.get("agent_id"),
            model_user_id=self._ctor_kwargs.get("model_user_id"),
            request_id=self._ctor_kwargs.get("request_id"),
        )
        return list(self.stages) + prescreen

    def _run_stages(
        self,
        docs: List[Dict[str, Any]],
        context: Dict[str, Any],
        stages: List[Stage],
    ) -> List[Dict[str, Any]]:
        """Apply the given post-retrieval stages in order (no-op when empty)."""
        for stage in stages:
            try:
                docs = stage(docs, context)
            except Exception as exc:
                logger.warning("Retrieval stage failed, skipping: %s", exc)
        return docs

    def search(self, query: str = "") -> List[Dict[str, Any]]:
        """Run every group under the shared budget and merge the results."""
        groups = self._groups
        n_groups = len(groups)

        # Fast path / exact parity: a single group is just the underlying
        # retriever with the full budget — no merge accounting at all.
        if n_groups == 1:
            retriever = self._build_group_retriever(
                groups[0], self.doc_token_limit
            )
            docs = retriever.search(query) if query else retriever.search()
            context = {"query": query, "retriever": groups[0]["retriever"]}
            return self._run_stages(docs, context, self._group_stages(groups[0]))

        merged: List[Dict[str, Any]] = []
        cap = max(int(self.doc_token_limit * 0.9), 100)
        cumulative_tokens = 0
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
            context = {"query": query, "retriever": group["retriever"]}
            group_docs = self._run_stages(
                group_docs, context, self._group_stages(group)
            )
            for doc in group_docs:
                if cumulative_tokens >= cap:
                    break
                header = f"{doc.get('filename', '')}\n{doc.get('text', '')}"
                doc_tokens = num_tokens_from_string(header)
                if cumulative_tokens + doc_tokens < cap:
                    merged.append(doc)
                    cumulative_tokens += doc_tokens
            if cumulative_tokens >= cap:
                break
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
    if not getattr(settings, "PER_SOURCE_RETRIEVAL_ENABLED", True):
        return create_classic()
    return Dispatcher(**kwargs)
