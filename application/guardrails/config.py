"""Pydantic contract for ``agents.config.guardrails``.

Validation policy mirrors ``storage/db/source_config.py``: strict on write
(``model_validate`` raises), lenient on read (``parse`` falls back to
all-defaults so a malformed row never breaks a stream).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from application.guardrails.types import ACTIONS_BY_STAGE, Action, Stage

DEFAULT_BLOCK_MESSAGE = "Sorry, I can't help with that request."

MODES = ("monitor_only", "background_scan", "dangerous_tools_only", "scan_all")


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
        from application.guardrails.guardrail_creator import GuardrailCreator

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
        from application.guardrails.guardrail_creator import GuardrailCreator

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
        done, then promote. ``dangerous_tools_only`` narrows scanning to the
        gate where an action has real-world effect.
        """
        if not self.enabled:
            return []
        if self.mode == "dangerous_tools_only" and stage is not Stage.TOOL_CALL:
            return []
        selected = [c for c in self.controls if c.enabled and c.stage == stage]
        if self.mode in ("monitor_only", "background_scan"):
            return [c.model_copy(update={"action": Action.FLAG}) for c in selected]
        return selected

    def has_any(self, stage: Stage) -> bool:
        return bool(self.controls_for(stage))

    @classmethod
    def parse(cls, raw: Optional[dict]) -> "GuardrailsConfig":
        """Lenient read: all-defaults (disabled) for empty or invalid input."""
        if not raw or not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            return cls()


class AgentConfig(BaseModel):
    """Per-agent behavior contract stored in ``agents.config``."""

    model_config = ConfigDict(extra="forbid")

    guardrails: GuardrailsConfig = GuardrailsConfig()

    @classmethod
    def parse(cls, raw: Optional[dict]) -> "AgentConfig":
        """Lenient read: never raises, so a bad row can't break a stream."""
        if not raw or not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            return cls(guardrails=GuardrailsConfig.parse(raw.get("guardrails")))
