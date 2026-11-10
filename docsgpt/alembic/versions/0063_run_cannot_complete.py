"""0063 schedule_runs.error_type — allow 'cannot_complete'.

A scheduled run whose agent has no way to do the task (no tool, account or
access for a step it needs) now opens its answer with a marker, and the worker
records the run as failed with ``cannot_complete`` so the failure count rises
and a recurring schedule auto-pauses.

Constraint-only change; existing rows stay valid. Downgrade rewrites rows with
the new value to ``agent_error`` before restoring the narrower constraint.
Idempotent both ways.

Revision ID: 0063_run_cannot_complete
Revises: 0062_ingest_resume
"""

from alembic import op

revision = "0063_run_cannot_complete"
down_revision = "0062_ingest_resume"
branch_labels = None
depends_on = None


_OLD = (
    "'auth_expired', 'tool_not_allowed', 'budget_exceeded', "
    "'timeout', 'agent_error', 'internal', 'missed', 'overlap', "
    "'stream_error', 'empty_output'"
)
_NEW = _OLD + ", 'cannot_complete'"


def _recreate(values: str) -> None:
    op.execute("ALTER TABLE schedule_runs DROP CONSTRAINT IF EXISTS schedule_runs_error_type_chk;")
    op.execute(
        "ALTER TABLE schedule_runs ADD CONSTRAINT schedule_runs_error_type_chk "
        f"CHECK (error_type IS NULL OR error_type IN ({values}));"
    )


def upgrade() -> None:
    """Accept ``cannot_complete`` as a run's error type."""
    _recreate(_NEW)


def downgrade() -> None:
    """Fold ``cannot_complete`` rows into ``agent_error`` and restore the previous values."""
    op.execute("UPDATE schedule_runs SET error_type = 'agent_error' WHERE error_type = 'cannot_complete';")
    _recreate(_OLD)
