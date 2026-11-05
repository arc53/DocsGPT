"""Agent guardrails."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from docsgpt.core.settings._shared import EnvList, SettingsGroup


class GuardrailSettings(SettingsGroup):
    """Input/output checks every agent runs; the floor no agent may weaken is edited in Admin > Guardrails."""

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
            "Deprecated: the rules every agent follows are edited in Admin > Guardrails and stored in the "
            "database. On the first start with this set and no stored floor, its value is imported once, with a "
            "warning; after that it is ignored. It is the same GuardrailsConfig fragment the page edits, "
            'e.g. {"enabled": true, "mode": "scan_all", "controls": [{"check": "secrets", "stage": "output", '
            '"action": "redact"}]}'
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
    GUARDRAILS_INJECTION_MAX_WINDOWS: int = Field(
        default=24,
        ge=1,
        le=64,
        description=(
            "Windows (512 model tokens each) the `injection_model` check reads of one text at chat time: the user's "
            "message, a tool result, a retrieved document or an attached file. Past it the first window and the "
            "last ones are read, and a text that scored clean is not evaluated."
        ),
    )
    GUARDRAILS_INJECTION_ATTACHMENT_MAX_WINDOWS: int = Field(
        default=64,
        ge=1,
        le=256,
        description=(
            "Windows (512 model tokens each) read of a chat attachment's text when it is scored for prompt "
            "injection in the background after upload, about 30,000 tokens at the default. Past it the first "
            "window and the last ones are read."
        ),
    )
    GUARDRAILS_INJECTION_LIVE_ITEMS: Union[int, Literal["auto"]] = Field(
        default="auto",
        description=(
            "Retrieved documents or attached files the `injection_model` check scores with the model during a turn "
            "when no score is cached; the rest are scored in the background for the next turn that uses them. "
            "`auto` is 4 where the decision model is measured to score four full chunks within the stage deadline "
            "(a GPU), else 0; or a number from 0 to 40."
        ),
    )
    GUARDRAILS_INJECTION_BATCH_STATES: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Windows sent to the decision model per call when texts are scored in the background.",
    )
    GUARDRAILS_INJECTION_LAZY: bool = Field(
        default=True,
        description=(
            "Score in the background the retrieved documents and attached files a turn could not score in time, so "
            "the next turn finds their scores cached."
        ),
    )
    GUARDRAILS_CONTENT_SCORES_RETENTION_DAYS: int = Field(
        default=180,
        ge=1,
        description="Days a cached prompt-injection score is kept after its text was last scored or seen.",
    )

    @field_validator("GUARDRAILS_INJECTION_LIVE_ITEMS")
    @classmethod
    def _live_items_in_range(cls, value: Union[int, str]) -> Union[int, str]:
        if isinstance(value, int) and not 0 <= value <= 40:
            raise ValueError("must be auto or a number from 0 to 40")
        return value
