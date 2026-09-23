"""0037 request_traces — one execution trace per request for the Logs UI.

Each row is the full span tree of one execution (a chat turn, a tool-approval
continuation, a scheduled or webhook run, a search, a graph extraction):
agent runs, LLM calls, tool calls, retrieval and embeddings with their
timings, stored as a ``spans`` JSONB array. The Logs UI loads a trace whole,
so one row per trace keeps the write to a single INSERT and lets retention
and conversation deletion remove a trace in one step.

``message_id`` cascades: truncating a conversation when a turn is
superseded removes that turn's traces with it. Deleting a conversation also
deletes, by ``conversation_id``, the traces that have no message (scheduled
runs, stateless ``/v1`` rounds, turns whose message was never reserved); the
conversation index serves that. The link ids (``request_id``,
``activity_id``, ``workflow_run_id``) carry partial indexes because only the
Logs rows that have them look traces up by them. Traces with no log row of
their own (searches, graph builds) are listed per user or agent and source,
hence the source-leading indexes.

``status`` is the only CHECK; span kinds and sources are validated in code so
new ones need no migration.

Idempotent both ways.

Revision ID: 0037_request_traces
Revises: 0036_device_audit_created_idx
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0037_request_traces"
down_revision: Union[str, None] = "0036_device_audit_created_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS request_traces (
            id               UUID PRIMARY KEY,
            request_id       TEXT,
            message_id       UUID REFERENCES conversation_messages(id) ON DELETE CASCADE,
            conversation_id  UUID,
            activity_id      TEXT,
            workflow_run_id  UUID,
            user_id          TEXT,
            agent_id         UUID,
            source           TEXT NOT NULL,
            name             TEXT,
            status           TEXT NOT NULL
                CONSTRAINT request_traces_status_chk
                CHECK (status IN ('ok', 'error', 'paused', 'cancelled')),
            started_at       TIMESTAMPTZ NOT NULL,
            duration_ms      INTEGER NOT NULL DEFAULT 0,
            span_count       INTEGER NOT NULL DEFAULT 0,
            dropped_spans    INTEGER NOT NULL DEFAULT 0,
            summary          JSONB NOT NULL DEFAULT '{}'::jsonb,
            spans            JSONB NOT NULL DEFAULT '[]'::jsonb,
            otel_trace_id    TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS request_traces_request_idx
            ON request_traces (request_id) WHERE request_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS request_traces_message_idx
            ON request_traces (message_id) WHERE message_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS request_traces_activity_idx
            ON request_traces (activity_id) WHERE activity_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS request_traces_workflow_run_idx
            ON request_traces (workflow_run_id) WHERE workflow_run_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS request_traces_conversation_idx
            ON request_traces (conversation_id) WHERE conversation_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS request_traces_user_source_started_idx
            ON request_traces (user_id, source, started_at DESC);
        CREATE INDEX IF NOT EXISTS request_traces_agent_source_started_idx
            ON request_traces (agent_id, source, started_at DESC) WHERE agent_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS request_traces_created_idx
            ON request_traces (created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS request_traces;")
