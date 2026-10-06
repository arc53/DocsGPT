"""0050 device jobs and links — background jobs on paired devices, and what links can do.

* ``background_jobs.runner`` takes ``device``: a ``remote_device`` command a
  turn handed off, followed by a Celery poll chain that reads the device's
  output from the broker until the command reports its exit code.

Idempotent both ways. Downgrade first reports running device jobs ``lost``
(nothing would follow them any more), then narrows the check.

Revision ID: 0050_device_jobs_links
Revises: 0049_push_and_unread
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0050_device_jobs_links"
down_revision: Union[str, None] = "0049_push_and_unread"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RUNNERS_BEFORE = "'inprocess', 'celery', 'sandbox', 'mcp'"
_RUNNERS_AFTER = "'inprocess', 'celery', 'sandbox', 'mcp', 'device'"

_LOST_ON_DOWNGRADE = (
    '{"type": "Lost", "message": "This job was interrupted before it finished and will not report back. It may '
    "or may not have taken effect: verify before retrying, and never re-run a non-idempotent action blindly.\"}"
)


def _runners(values: str) -> None:
    op.execute("ALTER TABLE background_jobs DROP CONSTRAINT IF EXISTS background_jobs_runner_chk;")
    op.execute(
        f"ALTER TABLE background_jobs ADD CONSTRAINT background_jobs_runner_chk CHECK (runner IN ({values}));"
    )


def upgrade() -> None:
    _runners(_RUNNERS_AFTER)


def downgrade() -> None:
    op.execute(
        "UPDATE background_jobs SET status = 'lost', finished_at = now(), last_updated_at = now(), "
        "expires_at = now() + interval '7 days', "
        "status_message = 'interrupted: the server was downgraded', "
        f"error = CAST('{_LOST_ON_DOWNGRADE}' AS jsonb) "
        "WHERE runner = 'device' AND status = 'working';"
    )
    op.execute("UPDATE background_jobs SET runner = 'inprocess' WHERE runner = 'device';")
    _runners(_RUNNERS_BEFORE)
