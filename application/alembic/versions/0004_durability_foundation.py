"""0004 durability foundation — idempotency, tool-call log, ingest checkpoint.

Adds ``task_dedup``, ``webhook_dedup``, ``tool_call_attempts``,
``ingest_chunk_progress``, and per-row status flags on
``conversation_messages`` and ``pending_tool_state``. Also adds
``token_usage.source`` and ``token_usage.request_id`` so per-channel
cost attribution (``agent_stream`` / ``title`` / ``compression`` /
``rag_condense`` / ``fallback``) is queryable and multi-call agent runs
can be DISTINCT-collapsed into a single user request for rate limiting.

Revision ID: 0004_durability_foundation
Revises: 0003_user_custom_models
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0004_durability_foundation"
down_revision: Union[str, None] = "0003_user_custom_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # New tables
    # ------------------------------------------------------------------
    # ``attempt_count`` bounds the per-Celery-task idempotency wrapper's
    # retry loop so a poison message can't run forever; default 0 means
    # existing rows behave as if no attempts have run yet.
    op.execute(
        """
        CREATE TABLE task_dedup (
            idempotency_key TEXT PRIMARY KEY,
            task_name       TEXT NOT NULL,
            task_id         TEXT NOT NULL,
            result_json     JSONB,
            status          TEXT NOT NULL
                            CHECK (status IN ('pending', 'completed', 'failed')),
            attempt_count   INT  NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE webhook_dedup (
            idempotency_key TEXT PRIMARY KEY,
            agent_id        UUID NOT NULL,
            task_id         TEXT NOT NULL,
            response_json   JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    # FK on ``message_id`` uses ``ON DELETE SET NULL`` so the journal row
    # survives parent-message deletion (compliance / cost-attribution).
    op.execute(
        """
        CREATE TABLE tool_call_attempts (
            call_id      TEXT PRIMARY KEY,
            message_id   UUID
                         REFERENCES conversation_messages (id)
                         ON DELETE SET NULL,
            tool_id      UUID,
            tool_name    TEXT NOT NULL,
            action_name  TEXT NOT NULL,
            arguments    JSONB NOT NULL,
            result       JSONB,
            error        TEXT,
            status       TEXT NOT NULL
                         CHECK (status IN (
                             'proposed', 'executed', 'confirmed',
                             'compensated', 'failed'
                         )),
            attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE ingest_chunk_progress (
            source_id        UUID PRIMARY KEY,
            total_chunks     INT NOT NULL,
            embedded_chunks  INT NOT NULL DEFAULT 0,
            last_index       INT NOT NULL DEFAULT -1,
            last_updated     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    # ------------------------------------------------------------------
    # Column additions on existing tables
    # ------------------------------------------------------------------
    # DEFAULT 'complete' backfills existing rows — they're already done.
    op.execute(
        """
        ALTER TABLE conversation_messages
            ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'
                CHECK (status IN ('pending', 'streaming', 'complete', 'failed')),
            ADD COLUMN request_id TEXT;
        """
    )

    op.execute(
        """
        ALTER TABLE pending_tool_state
            ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'resuming')),
            ADD COLUMN resumed_at TIMESTAMPTZ;
        """
    )

    # Default ``agent_stream`` backfills historical rows under the
    # assumption they were written from the primary path — pre-fix the
    # only path that wrote was the error branch reading agent.llm.
    # ``request_id`` is the stream-scoped UUID stamped by the route on
    # ``agent.llm`` so multi-tool agent runs (which produce N rows)
    # collapse to one request via DISTINCT in ``count_in_range``.
    # Side-channel sources (``title`` / ``compression`` / ``rag_condense``
    # / ``fallback``) leave it NULL and are excluded from the request
    # count by source filter.
    op.execute(
        """
        ALTER TABLE token_usage
            ADD COLUMN source     TEXT NOT NULL DEFAULT 'agent_stream',
            ADD COLUMN request_id TEXT;
        """
    )

    # ------------------------------------------------------------------
    # Indexes — partial where the predicate selects only non-terminal rows
    # ------------------------------------------------------------------
    op.execute(
        "CREATE INDEX conversation_messages_pending_ts_idx "
        "ON conversation_messages (timestamp) "
        "WHERE status IN ('pending', 'streaming');"
    )
    op.execute(
        "CREATE INDEX tool_call_attempts_pending_ts_idx "
        "ON tool_call_attempts (attempted_at) "
        "WHERE status IN ('proposed', 'executed');"
    )
    op.execute(
        "CREATE INDEX tool_call_attempts_message_idx "
        "ON tool_call_attempts (message_id) "
        "WHERE message_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX pending_tool_state_resuming_ts_idx "
        "ON pending_tool_state (resumed_at) "
        "WHERE status = 'resuming';"
    )
    op.execute(
        "CREATE INDEX webhook_dedup_agent_idx "
        "ON webhook_dedup (agent_id);"
    )
    op.execute(
        "CREATE INDEX task_dedup_pending_attempts_idx "
        "ON task_dedup (attempt_count) WHERE status = 'pending';"
    )
    # Cost-attribution dashboards filter ``token_usage`` by
    # ``(timestamp, source)``; index the same shape so they stay cheap.
    op.execute(
        "CREATE INDEX token_usage_source_ts_idx "
        "ON token_usage (source, timestamp);"
    )
    # Partial index — only rows with a stamped request_id participate
    # in the DISTINCT count. NULL rows fall through to the COUNT(*)
    # branch in the repository query.
    op.execute(
        "CREATE INDEX token_usage_request_id_idx "
        "ON token_usage (request_id) "
        "WHERE request_id IS NOT NULL;"
    )

    op.execute(
        "CREATE TRIGGER tool_call_attempts_set_updated_at "
        "BEFORE UPDATE ON tool_call_attempts "
        "FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) "
        "EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    # CASCADE so the downgrade stays safe if later migrations FK into these.
    for table in (
        "ingest_chunk_progress",
        "tool_call_attempts",
        "webhook_dedup",
        "task_dedup",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")

    op.execute(
        "ALTER TABLE conversation_messages "
        "DROP COLUMN IF EXISTS request_id, "
        "DROP COLUMN IF EXISTS status;"
    )
    op.execute(
        "ALTER TABLE pending_tool_state "
        "DROP COLUMN IF EXISTS resumed_at, "
        "DROP COLUMN IF EXISTS status;"
    )
    op.execute("DROP INDEX IF EXISTS token_usage_request_id_idx;")
    op.execute("DROP INDEX IF EXISTS token_usage_source_ts_idx;")
    op.execute(
        "ALTER TABLE token_usage "
        "DROP COLUMN IF EXISTS request_id, "
        "DROP COLUMN IF EXISTS source;"
    )
