"""Agent runtime: default tools, context management, workflows and artifacts."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class AgentSettings(SettingsGroup):
    """What an agent may do per turn and how its context is kept within budget."""

    AGENT_NAME: str = Field(default="classic", description="Default agent type for agentless chats.")
    DEFAULT_AGENT_LIMITS: dict[str, int] = Field(
        default={"token_limit": 50000, "request_limit": 500},
        description="Per-agent default quotas: tokens and requests.",
    )
    DEFAULT_CHAT_TOOLS: list[str] = Field(
        default=["memory", "read_webpage", "scheduler"],
        description=(
            "Config-free tools on by default in agentless chats. scheduler is dual-registered in "
            "BUILTIN_AGENT_TOOLS so one synthetic id resolves via defaults or the agent picker. Add "
            "code_executor and artifact_generator once a sandbox runner is configured; both execute through "
            "it and would fail on every call without one."
        ),
    )
    ENABLE_TOOL_PREFETCH: bool = Field(default=True, description="Pre-fetch retrieval before the agent's first turn.")
    TOOL_RESULT_MAX_TOKENS: int = Field(
        default=20000,
        ge=0,
        description="Cap on one tool result entering the LLM context (0 disables); journal and DB keep it whole.",
    )

    # Chat attachments.
    ATTACHMENT_CONTEXT_SHARE: float = Field(
        default=0.6,
        gt=0,
        le=1,
        description=(
            "Largest share of the model's context window a turn's attachments may take. Files are inlined in "
            "upload order until it is spent; the rest stay reachable through the attachments tool."
        ),
    )
    ATTACHMENT_NATIVE_MAX_FILES: int = Field(
        default=10,
        ge=0,
        description="Most files sent to the model as native file or image parts in one turn; later ones go as text.",
    )
    ATTACHMENT_PARTIAL_MIN_TOKENS: int = Field(
        default=4000,
        ge=0,
        description=(
            "Smallest leftover budget worth inlining the start of a file that does not fit whole. The cut is "
            "marked so the model can read on with the attachments tool."
        ),
    )
    ATTACHMENT_READ_MAX_TOKENS: int = Field(
        default=8000,
        ge=500,
        description="Most tokens one attachments_read call returns; the reply names the offset to continue from.",
    )
    ATTACHMENT_INDEXING_ENABLED: bool = Field(
        default=True,
        description=(
            "Embed each chat attachment in the background after parsing, so attachments_search can rank by "
            "meaning. Until an attachment is indexed (or with this off) search falls back to keyword ranking."
        ),
    )

    # Conversation compression.
    ENABLE_CONVERSATION_COMPRESSION: bool = Field(
        default=True, description="Compress long conversations once they approach the context window."
    )
    COMPRESSION_THRESHOLD_PERCENTAGE: float = Field(
        default=0.8, gt=0, le=1, description="Fraction of the context window at which compression triggers."
    )
    COMPRESSION_MODEL_OVERRIDE: Optional[str] = Field(
        default=None, description="Use a different model for compression; unset reuses the answer model."
    )
    COMPRESSION_PROMPT_VERSION: str = Field(default="v1.0", description="Tracks compression prompt iterations.")
    COMPRESSION_MAX_HISTORY_POINTS: int = Field(
        default=3, description="Keep only the last N compression points to prevent DB bloat."
    )
    COMPRESSION_RECENT_FIELD_MAX_TOKENS: int = Field(
        default=8000, ge=0, description="Per-field cap on the verbatim tail kept after a compression point (0 disables)."
    )

    # Workflows.
    WORKFLOW_NODE_NATIVE_MAX_FILES: int = Field(
        default=5,
        description=(
            "Files per node passed natively to the LLM; past the cap they are extracted to text or dropped, to "
            "bound context and cost. Re-uses SANDBOX_MAX_INPUT_BYTES per file."
        ),
    )
    WORKFLOW_NODE_EXTRACT_MAX_FILES: int = Field(
        default=5,
        description=(
            "Documents per node extracted via the parsing worker. Each issues a separate blocking parse; past "
            "the cap they are skipped with a truncation note."
        ),
    )
    WORKFLOW_NODE_EXTRACT_BUDGET_SECONDS: int = Field(
        default=900,
        description=(
            "Wall clock one node may spend on blocking parses, shared across all of them. Without it a node "
            "could serialize WORKFLOW_NODE_EXTRACT_MAX_FILES full windows on a web threadpool slot."
        ),
    )
    WORKFLOW_RUN_STALE_SECONDS: int = Field(
        default=3600,
        description=(
            "A run row is pre-created as running; a disconnect or crash can strand it there. The beat reaper "
            "fails runs still running past this. Generous so a long run is never cut off."
        ),
    )

    # Per-user artifact quotas, enforced at persistence time. 0 or negative disables a quota.
    ARTIFACT_MAX_BYTES: int = Field(
        default=50 * 1024 * 1024, description="Cap on a single stored artifact version's bytes (0 disables)."
    )
    ARTIFACT_MAX_COUNT_PER_USER: int = Field(default=5000, description="Cap on artifacts a user may own (0 disables).")
    ARTIFACT_MAX_TOTAL_BYTES_PER_USER: int = Field(
        default=5 * 1024 * 1024 * 1024, description="Cap on a user's total stored artifact bytes (0 disables)."
    )
