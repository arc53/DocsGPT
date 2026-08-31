"""0029 agent guardrails — per-agent config column + decision audit journal.

Adds ``agents.config`` (JSONB, NOT NULL, default ``{}``), holding a
Pydantic-validated ``AgentConfig``. The server default backfills every existing
row with ``{}``, which parses to guardrails-disabled, so existing agents behave
exactly as before.

Adds ``guardrail_events``, the decision journal. Deliberately polymorphic
(``detector_type`` / ``category`` / ``matched_value``) so new checks record into
it without a schema change, and ``message_id`` is ON DELETE SET NULL so the
compliance trail outlives the conversation it came from — same reasoning as
``tool_call_attempts``.

Revision ID: 0029_agent_guardrails
Revises: 0028_user_logs_agent_lookup_idx
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0029_agent_guardrails"
down_revision: Union[str, None] = "0028_user_logs_agent_lookup_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "config",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "guardrail_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Text),
        sa.Column("api_key", sa.Text),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_id", sa.Text),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("check_name", sa.Text, nullable=False),
        sa.Column("detector_type", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("category", sa.Text),
        sa.Column("score", sa.Float),
        sa.Column("match_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("matched_value", sa.Text),
        sa.Column("detail", sa.Text),
        sa.Column("policy_snapshot", postgresql.JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_guardrail_events_agent_created",
        "guardrail_events",
        ["agent_id", "created_at"],
    )
    op.create_index(
        "ix_guardrail_events_user_created",
        "guardrail_events",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_guardrail_events_message", "guardrail_events", ["message_id"]
    )
    # Supports the retention purge, whose predicate is created_at alone and so
    # cannot use either composite index above.
    op.create_index(
        "ix_guardrail_events_created", "guardrail_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_guardrail_events_created", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_message", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_user_created", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_agent_created", table_name="guardrail_events")
    op.drop_table("guardrail_events")
    op.drop_column("agents", "config")
