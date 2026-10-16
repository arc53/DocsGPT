"""Agent guardrails."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import NoDecode

from docsgpt.core.settings._shared import EnvList, SettingsGroup, normalize_choice


class GuardrailSettings(SettingsGroup):
    """Input/output checks every agent runs, and the floor no agent may weaken."""

    GUARDRAILS_ENABLED: bool = Field(default=True, description="Master switch; False disables every stage.")
    GUARDRAILS_CHECKS_ENABLED: Annotated[list[str], NoDecode, EnvList()] = Field(
        default=[],
        description=(
            "Allowlist of GuardrailCreator.checks keys, as a JSON list or comma-separated names; unset or empty "
            "means every registered check."
        ),
    )
    GUARDRAILS_FLOOR: dict[str, Any] = Field(
        default={},
        description=(
            "A GuardrailsConfig fragment every agent inherits and cannot weaken; agents may add controls or "
            'make an action stricter, never looser. "enabled" is required; without it the floor parses but '
            'applies to nothing. Example: {"enabled": true, "mode": "scan_all", "controls": [{"check": '
            '"secrets", "stage": "output", "action": "redact"}]}'
        ),
    )
    GUARDRAILS_JUDGE_MODEL: Optional[str] = Field(
        default=None, description="Judge model for the topic/policy checks; unset reuses the request's model."
    )
    GUARDRAILS_STORE_SCANNED_TEXT: bool = Field(
        default=False,
        description=(
            "Persist scanned text alongside guardrail_events. Off by default: pre-redaction text is exactly the "
            "material a PII control exists to keep out of storage."
        ),
    )
    GUARDRAILS_EVENTS_RETENTION_DAYS: int = Field(
        default=30, ge=1, description="Days guardrail events are kept before the cleanup task removes them."
    )
    GUARDRAILS_INJECTION_INPUT_MODE: Literal["off", "monitor", "on", "auto"] = Field(
        default="off",
        description=(
            "Give every agent an `injection_model` check on user input, scored by the decision model. `monitor` "
            "flags; `on` also blocks at GUARDRAILS_INJECTION_THRESHOLD, on agents that enforce (`scan_all`); "
            "`auto` flags while the check's predicted time on this machine fits GUARDRAILS_INJECTION_INPUT_BUDGET. "
            "An agent's own `injection_model` input control replaces it. The first mode other than `off` downloads "
            "the decision model (~0.5 GB)."
        ),
    )
    GUARDRAILS_INJECTION_INPUT_BUDGET: float = Field(
        default=0.5,
        gt=0,
        description=(
            "Under GUARDRAILS_INJECTION_INPUT_MODE=auto, the longest predicted time, in seconds, the input check may "
            "add before an answer starts."
        ),
    )
    GUARDRAILS_INJECTION_THRESHOLD: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description=(
            "Default `threshold` of an `injection_model` control: the probability from which the control's own "
            "action (such as block) applies."
        ),
    )
    GUARDRAILS_INJECTION_FLAG_THRESHOLD: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Default `flag_threshold` of an `injection_model` control: from this probability up to the threshold "
            "a text is flagged as suspected, never blocked."
        ),
    )

    @field_validator("GUARDRAILS_INJECTION_INPUT_MODE", mode="before")
    @classmethod
    def _normalize_injection_input_mode(cls, v):
        return normalize_choice(v)

    @model_validator(mode="after")
    def _ordered_injection_thresholds(self):
        if self.GUARDRAILS_INJECTION_FLAG_THRESHOLD > self.GUARDRAILS_INJECTION_THRESHOLD:
            raise ValueError("GUARDRAILS_INJECTION_FLAG_THRESHOLD must not exceed GUARDRAILS_INJECTION_THRESHOLD")
        return self
