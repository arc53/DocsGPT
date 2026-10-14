"""0053 workflow run progress — where a running workflow is.

* ``workflow_runs.progress``: the step a run is on, written as each step
  starts (``{done, total, current: {node_id, title, type, started_at}}``).
  ``total`` is set only when the graph has one path. Kept after the run ends,
  so a failed run still says which step it stopped at. ``steps`` is still
  written once, when the run ends.

Idempotent both ways. Downgrade drops the column.

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


def downgrade() -> None:
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS progress;")
