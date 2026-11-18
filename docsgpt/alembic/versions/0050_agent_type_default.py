"""0050 agents.agent_type defaults to classic and is never NULL.

Two writers left the column unset: the promptable share route (its backing
agent had no type) and the Mongo backfill (it copied a missing type as NULL
and Mongo's ``""`` as is). In Mongo the key was absent, so readers fell back
to the default; a Postgres row carries every column, so they read ``None``
and the run failed (``'NoneType' object has no attribute 'lower'``). Every
promptable share made since the cutover was broken for its visitors.

The upgrade rewrites NULL and blank types to ``classic``, then sets that as
the column default and forbids NULL. The downgrade lifts both; it leaves the
repaired values alone.

Idempotent both ways.

Revision ID: 0050_agent_type_default
Revises: 0049_push_and_unread
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0050_agent_type_default"
down_revision: Union[str, None] = "0049_push_and_unread"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE agents SET agent_type = 'classic' WHERE agent_type IS NULL OR btrim(agent_type) = '';")
    op.execute("ALTER TABLE agents ALTER COLUMN agent_type SET DEFAULT 'classic';")
    op.execute("ALTER TABLE agents ALTER COLUMN agent_type SET NOT NULL;")


def downgrade() -> None:
    op.execute("ALTER TABLE agents ALTER COLUMN agent_type DROP NOT NULL;")
    op.execute("ALTER TABLE agents ALTER COLUMN agent_type DROP DEFAULT;")
