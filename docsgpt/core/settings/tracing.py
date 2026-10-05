"""Execution traces: the per-request timeline shown in the Logs UI and exported as OTel GenAI spans."""

from __future__ import annotations

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class TracingSettings(SettingsGroup):
    """Recording of agent, LLM, tool and retrieval steps per request."""

    TRACES_ENABLED: bool = Field(
        default=True,
        description=(
            "Record an execution trace (agent runs, LLM calls, tool calls, retrieval, embeddings) for every "
            "request, store it in request_traces and show it in the Logs UI. False records nothing."
        ),
    )
    TRACES_CAPTURE_CONTENT: bool = Field(
        default=True,
        description=(
            "Store short, secret-redacted previews (tool arguments and results, retrieved chunk titles, "
            "rephrased queries, answer excerpts) with each stored trace. Full prompts are never stored. OTel "
            "export follows OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT instead."
        ),
    )
    TRACES_PREVIEW_CHARS: int = Field(
        default=2000, ge=100, description="Maximum characters kept per stored trace preview."
    )
    TRACES_MAX_SPANS: int = Field(
        default=500,
        ge=10,
        description="Maximum spans recorded per trace; further spans are counted as dropped, not stored.",
    )
    TRACES_RETENTION_DAYS: int = Field(
        default=30, ge=1, description="Days stored traces are kept before the cleanup task removes them."
    )
    TRACES_OTEL_EXPORT: bool = Field(
        default=True,
        description=(
            "Also emit each finished trace as OpenTelemetry GenAI spans (gen_ai.*) and metrics. Has no effect "
            "unless an OTel SDK is configured, e.g. by launching under opentelemetry-instrument."
        ),
    )
