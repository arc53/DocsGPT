"""The registry of features that call the decision model, and what ``auto`` resolves each one to.

Every feature has a mode setting, ``off|monitor|on|auto`` (or a plain switch, which is ``on`` or ``off``), and ships
``off``. ``auto`` is an opt-in that turns the feature on (or to ``monitor``, for a shadow-first feature) only while
the latency predicted on this machine fits the feature's budget. Once on, it turns off only above 1.25x the budget,
so a verdict near the line does not flap; each change is logged with its numbers. Explicit ``off``, ``monitor`` and
``on`` always win.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from docsgpt.decisions.latency import GUARD, RELEVANCE, SpeedProfile
from docsgpt.decisions.types import FeatureSpec, Shape

logger = logging.getLogger(__name__)

#: Factor over the budget at which an ``auto`` feature that is on turns off again.
HYSTERESIS = 1.25

_specs: dict[str, FeatureSpec] = {}
_on: dict[str, bool] = {}


def register(spec: FeatureSpec) -> FeatureSpec:
    """Add a feature; registering a name again replaces it."""
    _specs[spec.name] = spec
    return spec


def configured(spec: FeatureSpec, settings: Any = None) -> str:
    """The feature's mode setting, ``off`` when the setting is unset; a boolean switch reads as ``on`` or ``off``.

    Args:
        spec: The feature.
        settings: The settings to read; the process's when omitted.
    """
    if settings is None:
        from docsgpt.core.settings import settings

    value = getattr(settings, spec.mode_setting, None)
    if isinstance(value, bool):
        return "on" if value else "off"
    return value or "off"


def shape_of(spec: FeatureSpec, settings: Any = None, runtime: Optional[str] = None) -> Shape:
    """The call a feature's prediction is for, here and now.

    Args:
        spec: The feature.
        settings: The settings to read; the process's when omitted.
        runtime: Where the model runs (``ModelInfo.runtime``); this process's model when ``settings`` is omitted
            too, else unknown.
    """
    if spec.shape_for is None:
        return spec.shape
    if settings is None:
        from docsgpt import decisions
        from docsgpt.core.settings import settings

        info = decisions.model_info()
        runtime = info.runtime if info else None
    return spec.shape_for(settings, runtime)


def verdict(spec: FeatureSpec, profile: Optional[SpeedProfile]) -> tuple[bool, Optional[float], str]:
    """Whether ``auto`` would run the feature now.

    Returns:
        ``(on, predicted seconds, reason)``; the reason is ``not_measured``, ``fits`` or ``over_budget``.
    """
    from docsgpt.core.settings import settings

    if profile is None:
        return False, None, "not_measured"
    budget = float(getattr(settings, spec.budget_setting))
    predicted = profile.predict_s(shape_of(spec))
    was_on = _on.get(spec.name, False)
    on = predicted <= budget * (HYSTERESIS if was_on else 1.0)
    if on != was_on:
        logger.info("Decision feature %s under auto is now %s: predicted %.2fs against a budget of %.2fs",
                    spec.name, "on" if on else "off", predicted, budget)
    _on[spec.name] = on
    return on, predicted, "fits" if on else "over_budget"


def effective(spec: FeatureSpec, enabled: bool, profile: Optional[SpeedProfile]) -> tuple[str, Optional[float], str]:
    """What the feature does now: ``off``, ``monitor`` or ``on``, with the prediction and the reason.

    Args:
        spec: The feature.
        enabled: Whether the decision model is on at all (``DECISION_MODE`` is not ``none``).
        profile: This machine's latency model, or ``None`` before it is measured.
    """
    mode = configured(spec)
    predicted = profile.predict_s(shape_of(spec)) if profile else None
    if not enabled:
        return "off", predicted, "decisions_off"
    if mode != "auto":
        return mode, predicted, "configured"
    on, predicted, reason = verdict(spec, profile)
    return (spec.auto_mode if on else "off"), predicted, reason


def wanted_at_start() -> bool:
    """Whether a setting asks for the model as soon as a process that serves it starts.

    That is ``DECISION_PRELOAD`` or any registered feature set to something other than ``off``: ``auto`` has to
    measure first, and a feature that is on (``DECISION_RELEVANCE_ENABLED``, say) would otherwise fail open while
    the model loads.
    """
    from docsgpt.core.settings import settings

    return settings.DECISION_PRELOAD or any(configured(spec) != "off" for spec in specs())


def nothing_fits(profile: SpeedProfile) -> bool:
    """Whether the model was loaded only to judge ``auto`` and no feature will call it.

    True when some feature is set to ``auto``, every ``auto`` verdict on ``profile`` is off, and no feature is set
    to ``on`` or ``monitor``.
    """
    registered = specs()
    if not any(configured(spec) == "auto" for spec in registered):
        return False
    return all(effective(spec, True, profile)[0] == "off" for spec in registered)


def specs() -> list[FeatureSpec]:
    """Every registered feature."""
    return list(_specs.values())


def reset() -> None:
    """Forget the ``auto`` verdicts (after a fork); registrations stay, since they come from imports."""
    _on.clear()


# The features DocsGPT ships are registered here rather than by the modules that call the model, so every process
# knows all of them whatever it has imported: the API warms the model at start for any that is not ``off``, and
# ``docsgpt decisions status`` lists them.

#: The ``injection_model`` guardrail check on user input (``GUARDRAILS_INJECTION_INPUT_MODE``). It is predicted on a
#: message of up to 320 tokens with the one ``injection`` question; under ``auto`` it only flags.
INJECTION_INPUT = register(
    FeatureSpec(
        name="injection_input",
        mode_setting="GUARDRAILS_INJECTION_INPUT_MODE",
        budget_setting="GUARDRAILS_INJECTION_INPUT_BUDGET",
        shape=Shape(state_tokens=320, question_tokens=GUARD.question_tokens),
        auto_mode="monitor",
    )
)


def _rerank_shape(settings: Any, runtime: Optional[str]) -> Shape:
    """A relevance call over the default candidate pool (``reranker.candidate_k`` unset): best-window passages where
    the model runs on a CPU, whole chunks (DocsGPT's default chunk size) elsewhere."""
    from docsgpt.decisions.states import MARGIN, cpu_runtime
    from docsgpt.storage.db.source_config import DEFAULT_CANDIDATE_K

    tokens = settings.DECISION_RELEVANCE_CPU_PASSAGE_TOKENS + MARGIN if cpu_runtime(runtime) else RELEVANCE.state_tokens
    return Shape(state_tokens=tokens, question_tokens=RELEVANCE.question_tokens, states=DEFAULT_CANDIDATE_K)


#: Relevance in retrieval (``docsgpt.retriever.stages.relevance``) for the sources whose ``reranker`` is set. It has
#: a switch, not a mode: ``DECISION_RELEVANCE_ENABLED`` is ``on``, so the model warms at start. Its budget is the
#: call's deadline, which the admin Defaults panel compares the prediction against.
RAG_RERANK = register(
    FeatureSpec(
        name="rag_rerank",
        mode_setting="DECISION_RELEVANCE_ENABLED",
        budget_setting="DECISION_RELEVANCE_TIMEOUT",
        shape=Shape(state_tokens=RELEVANCE.state_tokens, question_tokens=RELEVANCE.question_tokens, states=20),
        shape_for=_rerank_shape,
    )
)
