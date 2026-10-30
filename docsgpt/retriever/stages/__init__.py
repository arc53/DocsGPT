"""Post-retrieval stages applied by the Dispatcher to a group's candidates.

``build_group_stages`` composes them for one group: the LLM prescreens, then the relevance stage. Each stage
module stands alone; only this factory knows about all of them.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from docsgpt.core.settings import settings
from docsgpt.retriever.labels import normalize_source_id
from docsgpt.retriever.stages.prescreen import build_prescreen_stages
from docsgpt.retriever.stages.relevance import RERANK, RelevancePolicy, RelevanceStage

Stage = Callable[[List[Dict[str, Any]], Dict[str, Any]], List[Dict[str, Any]]]


def rerank_policy(relevance: Dict[str, Any], *, feature: Optional[str] = None) -> RelevancePolicy:
    """The relevance policy for a group's resolved ``relevance`` (see ``Dispatcher._build_groups``)."""
    thresholds = {
        normalize_source_id(doc_id): value for doc_id, value in (relevance.get("thresholds") or {}).items()
    }
    return RelevancePolicy(
        keep=None,
        threshold=0.0,
        min_keep=settings.DECISION_RELEVANCE_MIN_KEEP,
        thresholds_by_source=thresholds,
        feature=feature or RERANK,
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

    1. An LLM ``PreScreenStage`` per distinct prescreen config.
    2. The relevance ``RelevanceStage`` when the group's relevance is ``on``.

    A source sets one or the other, never both, and the Dispatcher groups sources by both policies, so neither
    ever judges another source's chunks. A group with neither gets no stages, so retrieval stays exactly as it
    was with zero extra calls.

    Args:
        group: A Dispatcher group: ``retrievals`` and ``relevance``.
        llm: LLM-resolution context for the LLM prescreen (``llm_name``, ``api_key``, ``model_id``, ...).
        usage_source: Cost-attribution tag of the LLM prescreen's calls.
        feature: Decision feature label of the relevance stage (the retrieval test's ``retrieval_test``);
            ``rag_rerank`` when omitted.
    """
    stages: List[Stage] = list(
        build_prescreen_stages(group.get("retrievals") or {}, usage_source=usage_source, **llm)
    )
    relevance = group.get("relevance") or {}
    if relevance.get("mode") == "on":
        stages.append(RelevanceStage(rerank_policy(relevance, feature=feature)))
    return stages
