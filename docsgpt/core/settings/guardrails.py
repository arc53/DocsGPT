"""Agent guardrails."""

from __future__ import annotations

from typing import Annotated, Any, Optional

from pydantic import Field
from pydantic_settings import NoDecode

from docsgpt.core.settings._shared import EnvList, SettingsGroup


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
