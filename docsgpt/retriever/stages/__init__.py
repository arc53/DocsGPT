"""Post-retrieval stages applied by the Dispatcher to a group's candidates.

``build_group_stages`` composes them for one group: the LLM prescreens, the decision-model prescreens, then the
rerank. Each stage module stands alone; only this factory knows about all of them.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from docsgpt.core.settings import settings
from docsgpt.retriever.labels import normalize_source_id
from docsgpt.retriever.stages.prescreen import build_prescreen_stages
from docsgpt.retriever.stages.relevance import (
    PRESCREEN,
    RERANK,
    RelevancePolicy,
    RelevanceStage,
    decision_prescreen_enabled,
)

Stage = Callable[[List[Dict[str, Any]], Dict[str, Any]], List[Dict[str, Any]]]


def decision_prescreen_stages(retrievals: Dict[str, Any], *, feature: Optional[str] = None) -> List[Stage]:
    """One ``RelevanceStage`` per distinct ``backend: decision`` prescreen config in the group.

    Args:
        retrievals: ``{doc_id: RetrievalConfig}`` for sources with overrides.
        feature: The decision feature label; ``rag_prescreen`` when omitted.
    """
    stages: List[Stage] = []
    seen: set = set()
    for retrieval in (retrievals or {}).values():
        getter = getattr(retrieval, "prescreen_config", None)
        ps = getter() if callable(getter) else None
        if ps is None or ps.backend != "decision":
            continue
        threshold = settings.DECISION_PRESCREEN_THRESHOLD if ps.min_relevance is None else ps.min_relevance
        key = (ps.max_keep, threshold)
        if key in seen:
            continue
        seen.add(key)
        stages.append(
            RelevanceStage(
                RelevancePolicy(
                    keep=ps.max_keep,
                    threshold=threshold,
                    min_keep=settings.DECISION_RELEVANCE_MIN_KEEP,
                    feature=feature or PRESCREEN,
                )
            )
        )
    return stages


def rerank_policy(relevance: Dict[str, Any], *, feature: Optional[str] = None) -> RelevancePolicy:
    """The rerank's policy for a group's resolved ``relevance`` (see ``Dispatcher._build_groups``)."""
    thresholds = {
        normalize_source_id(doc_id): value for doc_id, value in (relevance.get("thresholds") or {}).items()
    }
    return RelevancePolicy(
        keep=None,
        threshold=settings.DECISION_RERANK_THRESHOLD,
        min_keep=settings.DECISION_RELEVANCE_MIN_KEEP,
        thresholds_by_source=thresholds,
        feature=feature or RERANK,
        mode=relevance["mode"],
        arm=relevance.get("arm"),
    )


def build_group_stages(
    group: Dict[str, Any],
    *,
    llm: Dict[str, Any],
    usage_source: str = "rag_prescreen",
    feature: Optional[str] = None,
) -> List[Stage]:
    """The stages for one Dispatcher group, in the order they run.

    1. An LLM ``PreScreenStage`` per ``backend: llm`` prescreen config, and per ``backend: decision`` config
       while ``DECISION_PRESCREEN_ENABLED`` is off (or the decision model is off).
    2. Otherwise a prescreen-policy ``RelevanceStage`` per ``backend: decision`` config.
    3. The rerank ``RelevanceStage`` when the group's rerank mode is ``on`` or ``monitor`` and no decision
       prescreen already scored it. After an LLM prescreen it reorders the survivors.

    A group with none of these gets no stages, so retrieval stays exactly as it was with zero extra calls.

    Args:
        group: A Dispatcher group: ``retrievals`` and ``relevance``.
        llm: LLM-resolution context for the LLM prescreen (``llm_name``, ``api_key``, ``model_id``, ...).
        usage_source: Cost-attribution tag of the LLM prescreen's calls.
        feature: Decision feature label for every relevance stage (the retrieval test's ``retrieval_test``);
            ``rag_prescreen`` and ``rag_rerank`` when omitted.
    """
    retrievals = group.get("retrievals") or {}
    on_model = decision_prescreen_enabled()
    stages: List[Stage] = list(
        build_prescreen_stages(retrievals, usage_source=usage_source, decision_as_llm=not on_model, **llm)
    )
    decision = decision_prescreen_stages(retrievals, feature=feature) if on_model else []
    stages += decision
    relevance = group.get("relevance") or {}
    if relevance.get("mode") in ("on", "monitor") and not decision:
        stages.append(RelevanceStage(rerank_policy(relevance, feature=feature)))
    return stages
