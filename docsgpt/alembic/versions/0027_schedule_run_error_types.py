"""0027 schedule_runs.error_type — allow 'stream_error' and 'empty_output'.

``schedule_runs.status`` could only ever be written ``success`` for a run whose
stream failed: the headless runner dropped the agent's error event, so the
worker saw an ordinary return with an empty answer and no error type. With that
fixed the worker now classifies two further outcomes, and both need to be
accepted by the CHECK constraint added in 0010:

* ``stream_error``  — the agent reported a mid-stream failure (provider error,
  failed fallback) rather than raising.
* ``empty_output``  — backstop: the run produced no answer, no tool call and no
  completion tokens, so it did no work even though nothing raised.

Constraint-only change; no data is rewritten and existing rows stay valid.
Idempotent both ways.

Revision ID: 0027_schedule_run_error_types
Revises: 0026_stack_logs_agent_id
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0027_schedule_run_error_types"
down_revision: Union[str, None] = "0026_stack_logs_agent_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD = (
    "'auth_expired', 'tool_not_allowed', 'budget_exceeded', "
    "'timeout', 'agent_error', 'internal', 'missed', 'overlap'"
)
_NEW = _OLD + ", 'stream_error', 'empty_output'"


def _recreate(values: str) -> None:
    op.execute(
        "ALTER TABLE schedule_runs "
        "DROP CONSTRAINT IF EXISTS schedule_runs_error_type_chk;"
    )
    op.execute(
        "ALTER TABLE schedule_runs ADD CONSTRAINT schedule_runs_error_type_chk "
        f"CHECK (error_type IS NULL OR error_type IN ({values}));"
    )


def upgrade() -> None:
    _recreate(_NEW)


def downgrade() -> None:
    # Rows written by the new classifier would violate the narrower constraint,
    # so retire those values before restoring it.
    op.execute(
        "UPDATE schedule_runs SET error_type = 'internal' "
        "WHERE error_type IN ('stream_error', 'empty_output');"
    )
    _recreate(_OLD)
