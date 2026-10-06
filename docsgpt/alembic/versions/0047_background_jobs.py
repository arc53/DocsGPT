"""0047 background jobs — slow tool calls handed off from a turn, and the wakes that resume it.

``background_jobs`` holds one row per tool call a turn handed off: what runs,
its state, its result and how that result reaches the conversation. The row
is written before the turn hears the job id, so Postgres, not the process
running the call, is the source of truth. A process that dies leaves its
rows with a stale ``heartbeat_at``; the reconciler marks them ``lost``.

* ``tool_call_id`` stores the turn-scoped call key (``<message_id>:<call_id>``,
  the ``tool_call_attempts`` key): providers reuse call ids across turns, so
  the bare id would collide within one conversation. ``UNIQUE
  (conversation_id, tool_call_id)`` makes a hand-off idempotent.
* ``status`` follows MCP Tasks names (``working``/``completed``/``failed``/
  ``cancelled``) plus the internal ``lost``. ``delivery_state`` records how
  the final result reached the model, exactly once: polled with
  ``check_job``, resumed in a continuation turn, folded into the user's next
  message, or suppressed.

``conversation_wakes`` is the queue of events that resume a conversation: a
finished job, and (later) a matched monitor, a hit trigger link or a human
decision. ``dedupe_key`` is unique, so an event is queued once however many
times it is reported; a continuation turn claims up to eight pending rows
and answers them together.

Both tables cascade with their conversation. Idempotent both ways.

Revision ID: 0047_background_jobs
Revises: 0046_pending_tool_state_json
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0047_background_jobs"
down_revision: Union[str, None] = "0046_pending_tool_state_json"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS background_jobs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id             TEXT NOT NULL,
            conversation_id     UUID REFERENCES conversations(id) ON DELETE CASCADE,
            workflow_run_id     UUID,
            origin_message_id   UUID,
            tool_call_id        TEXT,
            agent_id            UUID,
            tool_name           TEXT NOT NULL,
            action_name         TEXT NOT NULL,
            kind                TEXT NOT NULL DEFAULT 'tool_call'
                CONSTRAINT background_jobs_kind_chk
                CHECK (kind IN ('tool_call', 'code_exec', 'mcp_task', 'monitor_tick')),
            args                JSONB NOT NULL DEFAULT '{}'::jsonb,
            status              TEXT NOT NULL DEFAULT 'working'
                CONSTRAINT background_jobs_status_chk
                CHECK (status IN ('working', 'completed', 'failed', 'cancelled', 'lost')),
            status_message      TEXT,
            progress            JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_tail         TEXT,
            result              JSONB,
            error               JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at         TIMESTAMPTZ,
            deadline_at         TIMESTAMPTZ NOT NULL,
            expires_at          TIMESTAMPTZ,
            runner              TEXT NOT NULL DEFAULT 'inprocess'
                CONSTRAINT background_jobs_runner_chk
                CHECK (runner IN ('inprocess', 'celery', 'sandbox', 'mcp')),
            lease_owner         TEXT,
            heartbeat_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            attempts            INTEGER NOT NULL DEFAULT 0,
            cancel_requested_at TIMESTAMPTZ,
            auto_resume         BOOLEAN NOT NULL DEFAULT true,
            delivery_state      TEXT NOT NULL DEFAULT 'pending'
                CONSTRAINT background_jobs_delivery_state_chk
                CHECK (delivery_state IN (
                    'pending', 'claimed_by_poll', 'resumed', 'folded', 'suppressed', 'failed'
                )),
            delivered_at        TIMESTAMPTZ,
            followup_message_id UUID,
            watch               JSONB,
            external            JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT background_jobs_conversation_call_uidx UNIQUE (conversation_id, tool_call_id)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS background_jobs_user_status_idx ON background_jobs (user_id, status);")
    op.execute("CREATE INDEX IF NOT EXISTS background_jobs_conversation_idx ON background_jobs (conversation_id);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS background_jobs_status_heartbeat_idx ON background_jobs (status, heartbeat_at);"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_wakes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            source          TEXT NOT NULL
                CONSTRAINT conversation_wakes_source_chk
                CHECK (source IN ('job', 'monitor', 'trigger', 'approval', 'lost')),
            ref_id          TEXT,
            title           TEXT NOT NULL DEFAULT '',
            body            TEXT NOT NULL DEFAULT '',
            payload         JSONB,
            dedupe_key      TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending'
                CONSTRAINT conversation_wakes_status_chk
                CHECK (status IN (
                    'pending', 'claimed', 'delivered', 'folded', 'suppressed', 'superseded', 'failed'
                )),
            attempts        INTEGER NOT NULL DEFAULT 0,
            error           TEXT,
            message_id      UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            claimed_at      TIMESTAMPTZ,
            delivered_at    TIMESTAMPTZ,
            CONSTRAINT conversation_wakes_dedupe_uidx UNIQUE (dedupe_key)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS conversation_wakes_conversation_status_idx "
        "ON conversation_wakes (conversation_id, status);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS conversation_wakes_status_created_idx ON conversation_wakes (status, created_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_wakes;")
    op.execute("DROP TABLE IF EXISTS background_jobs;")
