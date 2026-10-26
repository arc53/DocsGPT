"""Pydantic contract for ``agents.config.guardrails``.

Validation policy mirrors ``storage/db/source_config.py``: strict on write
(``model_validate`` raises), lenient on read (``parse`` falls back to
all-defaults so a malformed row never breaks a stream).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, StrictInt, field_validator, model_validator

from docsgpt.analytics.config import AnalyticsConfig
from docsgpt.guardrails.types import ACTIONS_BY_STAGE, Action, Stage

logger = logging.getLogger(__name__)

DEFAULT_BLOCK_MESSAGE = "Sorry, I can't help with that request."


def _reason(exc: Exception) -> str:
    """The operator-readable half of a pydantic validation error."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            return str(errors()[0].get("msg", exc)).replace("Value error, ", "")
        except Exception:
            pass
    return str(exc)

MODES = ("monitor_only", "scan_all")

# Bounds of ``AgentConfig.context_window_limit``. Below the floor the system
# prompt, tool definitions and a compression summary (up to 4,000 tokens)
# would cross the compression threshold on their own, compressing every turn.
MIN_CONTEXT_WINDOW_LIMIT = 16000
MAX_CONTEXT_WINDOW_LIMIT = 10_000_000
# Floor of ``AgentConfig.history_token_limit``. Below it a single turn with a
# tool call or two passes the limit, summarizing on nearly every message.
MIN_HISTORY_TOKEN_LIMIT = 4000


def _item_level(check: str) -> bool:
    from docsgpt.guardrails.guardrail_creator import GuardrailCreator

    try:
        return bool(GuardrailCreator.get(check).item_level)
    except ValueError:
        return False


class GuardrailControl(BaseModel):
    """One detector bound to one intervention point with one action."""

    model_config = ConfigDict(extra="forbid")

    check: str
    stage: Stage
    action: Action = Action.FLAG
    enabled: bool = True
    settings: Dict[str, Any] = {}

    @field_validator("check")
    @classmethod
    def _known_check(cls, value: str) -> str:
        from docsgpt.guardrails.guardrail_creator import GuardrailCreator

        key = (value or "").strip().lower()
        if not key:
            raise ValueError("check is required")
        if not GuardrailCreator.is_registered(key):
            raise ValueError(f"unknown check '{value}'")
        # GUARDRAILS_CHECKS_ENABLED is a deployment control, not a UI filter:
        # an operator who disallows ``moderation`` must not be egressing user
        # text to a vendor because someone wrote the config through the API.
        if key not in GuardrailCreator.enabled_keys():
            raise ValueError(f"check '{value}' is not enabled on this instance")
        return key

    @model_validator(mode="after")
    def _coherent(self) -> "GuardrailControl":
        from docsgpt.guardrails.guardrail_creator import GuardrailCreator

        check_cls = GuardrailCreator.get(self.check)
        if self.stage not in check_cls.supported_stages:
            supported = ", ".join(sorted(s.value for s in check_cls.supported_stages))
            raise ValueError(
                f"check '{self.check}' does not support stage '{self.stage.value}' "
                f"(supported: {supported})"
            )
        if self.action not in ACTIONS_BY_STAGE[self.stage]:
            allowed = ", ".join(sorted(a.value for a in ACTIONS_BY_STAGE[self.stage]))
            raise ValueError(
                f"action '{self.action.value}' is not valid at stage "
                f"'{self.stage.value}' (allowed: {allowed})"
            )
        if self.action is Action.REDACT and not check_cls.supports_redaction:
            raise ValueError(f"check '{self.check}' cannot redact; it reports no spans")
        self.settings = check_cls.validate_settings(self.settings or {})
        return self


class GuardrailsConfig(BaseModel):
    """Per-agent guardrails contract."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    mode: str = "monitor_only"
    fail_open: bool = True
    timeout_ms: int = 2000
    block_message: str = DEFAULT_BLOCK_MESSAGE
    controls: List[GuardrailControl] = []

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value: str) -> str:
        key = (value or "monitor_only").strip().lower()
        if key not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        return key

    @field_validator("timeout_ms")
    @classmethod
    def _bounded_timeout(cls, value: int) -> int:
        if value < 100:
            raise ValueError("must be >= 100")
        if value > 60000:
            raise ValueError("must be <= 60000")
        return value

    @field_validator("block_message")
    @classmethod
    def _bounded_message(cls, value: str) -> str:
        text = (value or "").strip() or DEFAULT_BLOCK_MESSAGE
        if len(text) > 500:
            raise ValueError("must be <= 500 characters")
        return text

    @field_validator("controls")
    @classmethod
    def _unique_controls(cls, value: List[GuardrailControl]) -> List[GuardrailControl]:
        if len(value) > 50:
            raise ValueError("at most 50 controls")
        seen = set()
        for control in value:
            key = (control.check, control.stage)
            if key in seen:
                raise ValueError(
                    f"duplicate control for check '{control.check}' at stage "
                    f"'{control.stage.value}'"
                )
            seen.add(key)
        return value

    def controls_for(self, stage: Stage, item_level: Optional[bool] = None) -> List[GuardrailControl]:
        """Enabled controls for ``stage``, honouring ``mode``.

        ``monitor_only`` degrades every action to a log-only flag, which is the
        supported rollout path: turn checks on, watch what they would have
        done, then promote.

        Args:
            stage: The stage.
            item_level: ``True`` for only the checks that score items one by
                one (``GuardrailCheck.item_level``), ``False`` for only the
                others, ``None`` for both.
        """
        if not self.enabled:
            return []
        selected = [c for c in self.controls if c.enabled and c.stage == stage]
        if item_level is not None:
            selected = [c for c in selected if _item_level(c.check) is item_level]
        if self.mode != "scan_all":
            return [c.model_copy(update={"action": Action.FLAG}) for c in selected]
        return selected

    def has_any(self, stage: Stage) -> bool:
        return bool(self.controls_for(stage))

    @classmethod
    def parse(cls, raw: Optional[dict]) -> "GuardrailsConfig":
        """Lenient read: never raises, so a bad row can't break a stream.

        A control that stopped validating — its check disallowed by
        ``GUARDRAILS_CHECKS_ENABLED``, or renamed/removed in an upgrade — is
        dropped on its own. Discarding the whole config instead turned one
        stale control into "this agent has no guardrails at all", so an
        operator *tightening* the allowlist silently stripped every remaining
        control from every affected agent.
        """
        if not raw or not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            return cls._salvage(raw)

    @classmethod
    def _salvage(cls, raw: dict) -> "GuardrailsConfig":
        """Re-validate control by control, keeping the ones that still pass."""
        rest = {key: value for key, value in raw.items() if key != "controls"}
        entries = raw.get("controls")
        kept: List[Any] = []
        dropped: List[str] = []
        if isinstance(entries, list):
            for entry in entries:
                try:
                    GuardrailControl.model_validate(entry)
                except Exception as exc:
                    label = entry.get("check") if isinstance(entry, dict) else "?"
                    stage = entry.get("stage") if isinstance(entry, dict) else "?"
                    dropped.append(f"{label}:{stage} — {_reason(exc)}")
                    continue
                kept.append(entry)
        try:
            parsed = cls.model_validate({**rest, "controls": kept})
        except Exception:
            logger.warning(
                "Agent guardrails config is unusable and is being ignored; "
                "this agent runs unguarded until it is re-saved"
            )
            return cls()
        if dropped:
            logger.warning(
                "Dropped %d unusable guardrail control(s); %d still active: %s",
                len(dropped),
                len(kept),
                "; ".join(dropped),
            )
        return parsed


class AgentConfig(BaseModel):
    """Per-agent behavior contract stored in ``agents.config``."""

    model_config = ConfigDict(extra="forbid")

    guardrails: GuardrailsConfig = GuardrailsConfig()
    # Write actions on credentials the owner holds (a connected account, a
    # saved API tool key, a stored secret, an MCP sign-in) that someone who
    # can't approve for the owner may run: an API-key or widget caller, a
    # public-link user, and schedules either of them set. Any other such
    # write is refused for them. ``tool_id:action``.
    api_write_allowlist: List[str] = []
    # Conversation analytics (``docsgpt.analytics``): the owner's labelling
    # choices, not policy, so ``_policy_changed`` leaves them out.
    analytics: AnalyticsConfig = AnalyticsConfig()
    # Most tokens of history, documents and tool results one request of this
    # agent fills, below the model's own window (``get_context_budget``).
    # None uses the whole window.
    context_window_limit: Optional[StrictInt] = None
    # Most tokens of earlier messages a request replays word for word. Past
    # it, the older messages are summarized and the newest half stay
    # (``CompressionOrchestrator``). None summarizes only near the window.
    history_token_limit: Optional[StrictInt] = None

    @field_validator("context_window_limit")
    @classmethod
    def _bounded_context_window_limit(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if value < MIN_CONTEXT_WINDOW_LIMIT:
            raise ValueError(f"context_window_limit must be at least {MIN_CONTEXT_WINDOW_LIMIT:,} tokens")
        if value > MAX_CONTEXT_WINDOW_LIMIT:
            raise ValueError(f"context_window_limit must be at most {MAX_CONTEXT_WINDOW_LIMIT:,} tokens")
        return value

    @field_validator("history_token_limit")
    @classmethod
    def _bounded_history_token_limit(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if value < MIN_HISTORY_TOKEN_LIMIT:
            raise ValueError(f"history_token_limit must be at least {MIN_HISTORY_TOKEN_LIMIT:,} tokens")
        if value > MAX_CONTEXT_WINDOW_LIMIT:
            raise ValueError(f"history_token_limit must be at most {MAX_CONTEXT_WINDOW_LIMIT:,} tokens")
        return value

    @model_validator(mode="after")
    def _history_below_context(self) -> "AgentConfig":
        history, context = self.history_token_limit, self.context_window_limit
        if history is not None and context is not None and history >= context:
            raise ValueError("history_token_limit must be below context_window_limit")
        return self

    @field_validator("api_write_allowlist")
    @classmethod
    def _check_allowlist(cls, value: List[str]) -> List[str]:
        if len(value) > 200:
            raise ValueError("api_write_allowlist accepts at most 200 actions")
        cleaned = []
        for entry in value:
            tool_id, _, action = str(entry).partition(":")
            if not tool_id.strip() or not action.strip():
                raise ValueError("api_write_allowlist entries must be 'tool_id:action'")
            cleaned.append(f"{tool_id.strip()}:{action.strip()}")
        return sorted(set(cleaned))

    @classmethod
    def parse(cls, raw: Optional[dict]) -> "AgentConfig":
        """Lenient read: never raises, so a bad row can't break a stream."""
        if not raw or not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            # Each block is salvaged on its own, so a malformed guardrails or
            # analytics block (or an unknown key) keeps a valid allowlist. Only
            # a bad allowlist falls back to none: the safe side.
            try:
                allowlist = cls.model_validate({"api_write_allowlist": raw.get("api_write_allowlist") or []})
            except Exception:
                allowlist = cls()
            return cls(
                guardrails=GuardrailsConfig.parse(raw.get("guardrails")),
                api_write_allowlist=allowlist.api_write_allowlist,
                analytics=AnalyticsConfig.parse(raw.get("analytics")),
                context_window_limit=context_window_limit_of(raw),
                history_token_limit=history_token_limit_of(raw),
            )


def context_window_limit_of(raw: Optional[dict]) -> Optional[int]:
    """The context limit in a stored ``agents.config``, without validating the rest.

    Lenient like ``AgentConfig.parse``: a missing or invalid value is None,
    which leaves the model's whole window.

    Args:
        raw: The agent's stored ``config``.

    Returns:
        The limit in tokens, or None.
    """
    if not isinstance(raw, dict):
        return None
    try:
        return AgentConfig.model_validate(
            {"context_window_limit": raw.get("context_window_limit")}
        ).context_window_limit
    except Exception:
        return None


def history_token_limit_of(raw: Optional[dict]) -> Optional[int]:
    """The history limit in a stored ``agents.config``, without validating the rest.

    Lenient like ``context_window_limit_of``: a missing or invalid value is
    None, which summarizes only near the context window.

    Args:
        raw: The agent's stored ``config``.

    Returns:
        The limit in tokens, or None.
    """
    if not isinstance(raw, dict):
        return None
    try:
        return AgentConfig.model_validate(
            {"history_token_limit": raw.get("history_token_limit")}
        ).history_token_limit
    except Exception:
        return None
