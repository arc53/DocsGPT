"""0010 scheduler — schedules + schedule_runs tables.

Revision ID: 0010_schedules
Revises: 0009_tool_preferences
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0010_schedules"
down_revision: Union[str, None] = "0009_tool_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE schedules (
            id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                   TEXT NOT NULL,
            agent_id                  UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            trigger_type              TEXT NOT NULL,
            name                      TEXT,
            instruction               TEXT NOT NULL,
            status                    TEXT NOT NULL DEFAULT 'active',
            cron                      TEXT,
            run_at                    TIMESTAMPTZ,
            timezone                  TEXT NOT NULL DEFAULT 'UTC',
            next_run_at               TIMESTAMPTZ,
            last_run_at               TIMESTAMPTZ,
            end_at                    TIMESTAMPTZ,
            tool_allowlist            JSONB NOT NULL DEFAULT '[]'::jsonb,
            model_id                  TEXT,
            token_budget              INTEGER,
            origin_conversation_id    UUID REFERENCES conversations(id) ON DELETE SET NULL,
            created_via               TEXT NOT NULL DEFAULT 'ui',
            consecutive_failure_count INTEGER NOT NULL DEFAULT 0,
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT schedules_trigger_type_chk
                CHECK (trigger_type IN ('once', 'recurring')),
            CONSTRAINT schedules_status_chk
                CHECK (status IN ('active', 'paused', 'completed', 'cancelled')),
            CONSTRAINT schedules_created_via_chk
                CHECK (created_via IN ('chat', 'ui')),
            CONSTRAINT schedules_recurring_cron_chk
                CHECK (trigger_type <> 'recurring' OR cron IS NOT NULL),
            CONSTRAINT schedules_once_run_at_chk
                CHECK (trigger_type <> 'once' OR run_at IS NOT NULL)
        );
        """
    )

    op.execute(
        "CREATE INDEX schedules_user_idx ON schedules (user_id);"
    )
    op.execute(
        "CREATE INDEX schedules_agent_idx ON schedules (agent_id);"
    )
    # Dispatcher hot path: status='active' AND next_run_at <= now().
    op.execute(
        "CREATE INDEX schedules_due_idx "
        "ON schedules (status, next_run_at) "
        "WHERE status = 'active';"
    )

    op.execute(
        "CREATE TRIGGER schedules_set_updated_at "
        "BEFORE UPDATE ON schedules "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    op.execute(
        """
        CREATE TABLE schedule_runs (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            schedule_id       UUID NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
            user_id           TEXT NOT NULL,
            agent_id          UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            status            TEXT NOT NULL DEFAULT 'pending',
            scheduled_for     TIMESTAMPTZ NOT NULL,
            trigger_source    TEXT NOT NULL DEFAULT 'cron',
            started_at        TIMESTAMPTZ,
            finished_at       TIMESTAMPTZ,
            output            TEXT,
            output_truncated  BOOLEAN NOT NULL DEFAULT false,
            error             TEXT,
            error_type        TEXT,
            prompt_tokens     INTEGER NOT NULL DEFAULT 0,
            generated_tokens  INTEGER NOT NULL DEFAULT 0,
            conversation_id   UUID,
            message_id        UUID,
            celery_task_id    TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT schedule_runs_status_chk
                CHECK (status IN (
                    'pending', 'running', 'success', 'failed', 'skipped', 'timeout'
                )),
            CONSTRAINT schedule_runs_trigger_source_chk
                CHECK (trigger_source IN ('cron', 'manual')),
            CONSTRAINT schedule_runs_error_type_chk
                CHECK (error_type IS NULL OR error_type IN (
                    'auth_expired', 'tool_not_allowed', 'budget_exceeded',
                    'timeout', 'agent_error', 'internal', 'missed', 'overlap'
                ))
        );
        """
    )

    # Dedup primitive: racing dispatchers hit ON CONFLICT on this index.
    op.execute(
        "CREATE UNIQUE INDEX schedule_runs_dedup_uidx "
        "ON schedule_runs (schedule_id, scheduled_for);"
    )
    op.execute(
        "CREATE INDEX schedule_runs_schedule_recent_idx "
        "ON schedule_runs (schedule_id, scheduled_for DESC);"
    )
    op.execute(
        "CREATE INDEX schedule_runs_user_idx ON schedule_runs (user_id);"
    )
    op.execute(
        "CREATE INDEX schedule_runs_running_idx "
        "ON schedule_runs (status, started_at) "
        "WHERE status = 'running';"
    )
    op.execute(
        "CREATE TRIGGER schedule_runs_set_updated_at "
        "BEFORE UPDATE ON schedule_runs "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    # Drop triggers explicitly (grep-able) before CASCADE-dropping the tables.
    op.execute(
        "DROP TRIGGER IF EXISTS schedule_runs_set_updated_at ON schedule_runs;"
    )
    op.execute("DROP TABLE IF EXISTS schedule_runs CASCADE;")
    op.execute(
        "DROP TRIGGER IF EXISTS schedules_set_updated_at ON schedules;"
    )
    op.execute("DROP TABLE IF EXISTS schedules CASCADE;")
