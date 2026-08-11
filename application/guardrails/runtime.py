"""Wiring between an agent row and a runnable guardrail engine.

Holds three concerns the engine deliberately does not know about: the instance
floor, where a judge LLM comes from, and where decisions are journalled.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from application.core.settings import settings
from application.guardrails.base import ScanContext
from application.guardrails.config import AgentConfig, GuardrailsConfig
from application.guardrails.engine import GuardrailEngine
from application.guardrails.types import Action, StageDecision

logger = logging.getLogger(__name__)

# Higher wins when the floor and an agent disagree about the same control.
_ACTION_RANK = {
    Action.FLAG: 0,
    Action.REDACT: 1,
    Action.BLOCK: 2,
}

# Both modes scan every stage, so the merge is only about whether the floor
# enforces.
_ENFORCING_MODES = {"scan_all"}


def _merge_mode(agent_mode: str, floor_mode: str) -> str:
    """Enforce if either side enforces; otherwise keep the agent's label."""
    if floor_mode in _ENFORCING_MODES:
        return floor_mode
    return agent_mode


def instance_floor() -> Optional[GuardrailsConfig]:
    """The operator-set minimum, or None when unset/invalid."""
    raw = getattr(settings, "GUARDRAILS_FLOOR", None)
    if not raw:
        return None
    try:
        return GuardrailsConfig.model_validate(raw)
    except Exception:
        logger.error(
            "GUARDRAILS_FLOOR is invalid and is being ignored; agents run "
            "without an instance floor until it is fixed"
        )
        return None


def merge_floor(agent: GuardrailsConfig, floor: Optional[GuardrailsConfig]) -> GuardrailsConfig:
    """Apply the floor to an agent config. An agent may tighten, never loosen.

    Where both define the same ``(check, stage)``, the floor's **settings** are
    authoritative and the stricter **action** wins. Merging the two settings
    dicts is not an option: whether a union tightens or loosens is per-key
    (adding to ``denylist.terms`` tightens, adding to ``url.allow_hosts``
    loosens), so an agent that could edit them could always find a loosening
    edit. An agent that wants different settings adds a control at a stage the
    floor does not claim.
    """
    if floor is None or not floor.enabled:
        return agent

    merged = agent.model_copy(deep=True)
    merged.enabled = True
    merged.mode = _merge_mode(merged.mode, floor.mode)
    if not floor.fail_open:
        merged.fail_open = False
    merged.timeout_ms = max(merged.timeout_ms, floor.timeout_ms)

    by_key = {(c.check, c.stage): c for c in merged.controls}
    for control in floor.controls:
        key = (control.check, control.stage)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = control.model_copy(deep=True)
            continue
        existing.enabled = True
        existing.settings = dict(control.settings)
        if _ACTION_RANK.get(existing.action, 0) < _ACTION_RANK.get(control.action, 0):
            existing.action = control.action
    merged.controls = list(by_key.values())
    return merged


def floor_keys() -> set:
    """``{"check:stage"}`` claimed by the floor, for the builder UI."""
    floor = instance_floor()
    if floor is None or not floor.enabled:
        return set()
    return {f"{c.check}:{c.stage.value}" for c in floor.controls}


def resolve_config(raw_agent_config: Optional[dict]) -> GuardrailsConfig:
    """Parse ``agents.config`` and apply the instance floor."""
    if not getattr(settings, "GUARDRAILS_ENABLED", True):
        return GuardrailsConfig()
    agent = AgentConfig.parse(raw_agent_config).guardrails
    return merge_floor(agent, instance_floor())


def _judge_factory(agent):
    """Return a callable that mints a judge LLM tagged for cost attribution."""

    def factory(model_override: Optional[str] = None):
        from application.llm.llm_creator import LLMCreator

        llm = LLMCreator.create_llm(
            agent.llm_name,
            api_key=agent.api_key,
            user_api_key=agent.user_api_key,
            decoded_token=agent.decoded_token,
            model_id=(
                model_override
                or getattr(settings, "GUARDRAILS_JUDGE_MODEL", None)
                or agent.upstream_model_id
            ),
            agent_id=agent.agent_id,
            model_user_id=agent.model_user_id,
        )
        llm._token_usage_source = "guardrail"
        llm._request_id = getattr(agent, "request_id", None)
        return llm

    return factory


class GuardrailRecorder:
    """Buffers decisions and flushes them to ``guardrail_events``.

    Buffered rather than written per verdict so a chunked output stream does not
    turn into one INSERT per chunk.
    """

    def __init__(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        api_key: Optional[str] = None,
        request_id: Optional[str] = None,
        log_context=None,
        mode: str = "",
        fail_open: bool = True,
    ):
        self.mode = mode
        self.fail_open = fail_open
        self.user_id = user_id
        self.agent_id = agent_id
        self.api_key = api_key
        self.request_id = request_id
        self.log_context = log_context
        self.message_id: Optional[str] = None
        self._rows: List[Dict[str, Any]] = []
        # A streamed answer re-scans its held buffer every chunk, so the same
        # span re-triggers until it scrolls out of the window. Without this the
        # row count would scale with the provider's chunk size rather than with
        # what actually happened.
        self._seen: set = set()

    def __call__(self, decision: StageDecision) -> None:
        store_text = bool(getattr(settings, "GUARDRAILS_STORE_SCANNED_TEXT", False))
        for verdict in decision.verdicts:
            if not verdict.outcome.triggered and verdict.outcome.evaluated:
                continue
            categories = verdict.outcome.categories or [None]
            for category in categories:
                dedup_key = (
                    verdict.stage.value,
                    verdict.check,
                    verdict.action.value,
                    category,
                    verdict.outcome.triggered,
                )
                if dedup_key in self._seen:
                    continue
                self._seen.add(dedup_key)
                self._rows.append(
                    {
                        "user_id": self.user_id,
                        "api_key": self.api_key,
                        "agent_id": self.agent_id,
                        "request_id": self.request_id,
                        "stage": verdict.stage.value,
                        "check_name": verdict.check,
                        "detector_type": verdict.check.upper(),
                        "policy_snapshot": {
                            "mode": self.mode,
                            "fail_open": self.fail_open,
                        },
                        "action": verdict.action.value,
                        "outcome": "triggered" if verdict.outcome.triggered else "not_evaluated",
                        "category": category,
                        "score": verdict.outcome.score,
                        "match_count": len(verdict.outcome.spans),
                        "matched_value": (
                            self._sample(decision.text, verdict) if store_text else None
                        ),
                        "detail": verdict.outcome.detail or verdict.outcome.error,
                    }
                )
        if self.log_context is not None:
            try:
                self.log_context.stacks.append(
                    {"component": "guardrail", "data": decision.as_log()}
                )
            except Exception:
                logger.debug("Could not append guardrail entry to the activity log")

    @staticmethod
    def _sample(text: str, verdict) -> Optional[str]:
        if not verdict.outcome.spans:
            return None
        span = verdict.outcome.spans[0]
        return text[span.start : span.end][:200]

    def flush(self, message_id: Optional[str] = None) -> int:
        """Persist buffered rows. Safe to call more than once."""
        if not self._rows:
            return 0
        rows, self._rows = self._rows, []
        target = message_id or self.message_id
        for row in rows:
            row["message_id"] = target
        try:
            from application.storage.db.repositories.guardrail_events import (
                GuardrailEventsRepository,
            )
            from application.storage.db.session import db_session

            with db_session() as conn:
                return GuardrailEventsRepository(conn).record_many(rows)
        except Exception:
            logger.exception("Failed to persist %d guardrail event(s)", len(rows))
            return 0


def build_engine(agent, log_context=None) -> Optional[GuardrailEngine]:
    """Build the engine for ``agent``, or None when guardrails are inactive."""
    config = getattr(agent, "guardrails_config", None)
    if config is None or not config.enabled or not config.controls:
        return None
    recorder = GuardrailRecorder(
        user_id=getattr(agent, "user", None),
        agent_id=str(agent.agent_id) if getattr(agent, "agent_id", None) else None,
        api_key=getattr(agent, "user_api_key", None),
        request_id=getattr(agent, "request_id", None),
        log_context=log_context,
        mode=config.mode,
        fail_open=config.fail_open,
    )
    context = ScanContext(
        docs_provider=lambda: getattr(agent, "retrieved_docs", None),
        llm_factory=_judge_factory(agent),
        agent_id=str(agent.agent_id) if getattr(agent, "agent_id", None) else None,
        user=getattr(agent, "user", None),
    )
    return GuardrailEngine(config, context=context, recorder=recorder)
