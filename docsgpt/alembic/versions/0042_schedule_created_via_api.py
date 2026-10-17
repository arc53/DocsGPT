"""0042 schedule created_via api — schedules set by an API-key caller.

A schedule the agent sets from a widget or API chat is stored under the
agent's owner, like the run itself. ``created_via = 'api'`` records that
it came from outside the app, so its runs keep that caller's limits: no
writes on the owner's accounts or credentials unless the owner allowed
them in the agent's API write allowlist.

Idempotent both ways. Downgrade folds ``api`` back into ``chat``.

Revision ID: 0042_schedule_created_via_api
Revises: 0041_connection_account_name
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0042_schedule_created_via_api"
down_revision: Union[str, None] = "0041_connection_account_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE schedules DROP CONSTRAINT IF EXISTS schedules_created_via_chk;")
    op.execute(
        "ALTER TABLE schedules ADD CONSTRAINT schedules_created_via_chk "
        "CHECK (created_via IN ('chat', 'ui', 'api'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE schedules DROP CONSTRAINT IF EXISTS schedules_created_via_chk;")
    op.execute("UPDATE schedules SET created_via = 'chat' WHERE created_via = 'api';")
    op.execute(
        "ALTER TABLE schedules ADD CONSTRAINT schedules_created_via_chk "
        "CHECK (created_via IN ('chat', 'ui'));"
    )
