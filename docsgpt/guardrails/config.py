"""Pydantic contract for ``agents.config.guardrails``.

Validation policy mirrors ``storage/db/source_config.py``: strict on write
(``model_validate`` raises), lenient on read (``parse`` falls back to
all-defaults so a malformed row never breaks a stream).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from docsgpt.guardrails.types import ACTIONS_BY_STAGE, Action, Stage
from docsgpt.security.origins import canonical_origin, normalize_origin

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

    def controls_for(self, stage: Stage) -> List[GuardrailControl]:
        """Enabled controls for ``stage``, honouring ``mode``.

        ``monitor_only`` degrades every action to a log-only flag, which is the
        supported rollout path: turn checks on, watch what they would have
        done, then promote.
        """
        if not self.enabled:
            return []
        selected = [c for c in self.controls if c.enabled and c.stage == stage]
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
    # Browser origins that may call the agent with its API key. While
    # ``restrict_origins`` is on, a keyed request must come from one of these
    # or a trusted origin (``docsgpt/api/agent_origins.py``); turning it off
    # keeps the list.
    restrict_origins: bool = False
    allowed_origins: List[str] = []

    @field_validator("allowed_origins")
    @classmethod
    def _check_origins(cls, value: List[str]) -> List[str]:
        if len(value) > 100:
            raise ValueError("allowed_origins accepts at most 100 origins")
        cleaned: List[str] = []
        for entry in value:
            origin = canonical_origin(entry)
            if origin not in cleaned:
                cleaned.append(origin)
        return cleaned

    @model_validator(mode="after")
    def _origins_listed(self) -> "AgentConfig":
        if self.restrict_origins and not self.allowed_origins:
            raise ValueError("restrict_origins needs at least one entry in allowed_origins")
        return self

    def origin_allowed(self, origin: Optional[str], trusted: List[str]) -> bool:
        """Whether a request from ``origin`` may use the agent's API key.

        Args:
            origin: The request's normalized origin, or None when it sent none.
            trusted: Origins every restricted agent accepts (normalized).

        Returns:
            True when the agent is unrestricted or ``origin`` is listed.
        """
        if not self.restrict_origins:
            return True
        return origin is not None and (origin in self.allowed_origins or origin in trusted)

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
            # A bad allowlist falls back to none: the safe side. For origins
            # the safe side is the opposite, so a restriction stays on and
            # keeps every entry that still parses.
            return cls.model_construct(
                guardrails=GuardrailsConfig.parse(raw.get("guardrails")),
                api_write_allowlist=[],
                restrict_origins=bool(raw.get("restrict_origins")),
                allowed_origins=_salvage_origins(raw.get("allowed_origins")),
            )


def _salvage_origins(raw: Any) -> List[str]:
    """The entries of a stored ``allowed_origins`` that still normalize."""
    if not isinstance(raw, list):
        return []
    kept: List[str] = []
    for entry in raw:
        origin = normalize_origin(entry) if isinstance(entry, str) else None
        if origin and origin not in kept:
            kept.append(origin)
    return kept
