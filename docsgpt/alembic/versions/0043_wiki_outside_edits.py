"""0043 wiki outside edits — the wiki owner's say on API and widget edits.

An agent run from its API key or widget acts as the agent's owner, so it
could rewrite any wiki the owner can edit. ``wiki_outside_edits`` records
whether the wiki's owner allows that; it is off by default, so such runs can
still read the wiki but not change it.

Idempotent both ways.

Revision ID: 0043_wiki_outside_edits
Revises: 0042_schedule_created_via_api
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0043_wiki_outside_edits"
down_revision: Union[str, None] = "0042_schedule_created_via_api"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS wiki_outside_edits BOOLEAN NOT NULL DEFAULT false;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sources DROP COLUMN IF EXISTS wiki_outside_edits;")
