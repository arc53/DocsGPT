"""0054 when a schedule's plan last changed.

* ``schedules.plan_changed_at``: when the schedule was created, its timing
  (cron, time zone, one-time ``run_at``) was edited, or it was resumed. The
  Activity calendar only calls a slot "missed" after it: before it, the
  schedule fired at other times or was paused. ``updated_at`` can't say this,
  as its trigger also moves it on every dispatcher write. Existing rows start
  from ``updated_at``, the closest value they have.

Idempotent both ways. Downgrade drops the column.

Revision ID: 0054_schedule_plan_changed_at
Revises: 0053_workflow_run_progress
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0054_schedule_plan_changed_at"
down_revision: Union[str, None] = "0053_workflow_run_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
