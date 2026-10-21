"""0053 workflow run progress, when a conversation was last read, and when a
schedule's plan last changed.

* ``workflow_runs.progress``: the step a run is on, written as each step
  starts (``{done, total, current: {node_id, title, type, started_at}}``).
  ``total`` is set only when the graph has one path. Kept after the run ends,
  so a failed run still says which step it stopped at. ``steps`` is still
  written once, when the run ends.
* ``conversations.read_at``: when the owner last read the conversation
  (opened it, or was watching when something landed). Activity marks a chat
  whose background job failed after it, and only then.
* ``schedules.plan_changed_at``: when the schedule was created, its timing
  (cron, time zone, one-time ``run_at``) was edited, or it was resumed. The
  Activity calendar only calls a slot "missed" after it: before it, the
  schedule fired at other times or was paused. ``updated_at`` can't say this,
  as its trigger also moves it on every dispatcher write. Existing rows start
  from ``updated_at``, the closest value they have.

Idempotent both ways. Downgrade drops the columns.

Revision ID: 0053_workflow_run_progress
Revises: 0052_connector_oauth_flows
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0053_workflow_run_progress"
down_revision: Union[str, None] = "0052_connector_oauth_flows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS progress JSONB;")
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ;")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'schedules' AND column_name = 'plan_changed_at'
            ) THEN
                ALTER TABLE schedules ADD COLUMN plan_changed_at TIMESTAMPTZ NOT NULL DEFAULT now();
                -- The backfill must not move updated_at itself.
                ALTER TABLE schedules DISABLE TRIGGER schedules_set_updated_at;
                UPDATE schedules SET plan_changed_at = updated_at;
                ALTER TABLE schedules ENABLE TRIGGER schedules_set_updated_at;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE schedules DROP COLUMN IF EXISTS plan_changed_at;")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS read_at;")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS progress;")
