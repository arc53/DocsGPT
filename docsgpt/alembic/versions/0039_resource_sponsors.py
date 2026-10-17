"""0039 resource sponsors — who vouches for a saved resource the owner can't use.

An agent (and a workflow) runs as its owner, so every source, prompt and tool
it references is authorized against the owner. A team editor who attaches
their own private tool, prompt or source would have it dropped at run time.
``resource_sponsors`` records the editor who attached such a resource, keyed
``"<type>:<id>"`` (e.g. ``{"tool:<uuid>": "bob"}``). At run time the resource
is authorized as that sponsor, provided they can still edit the agent and
still use the resource (``docsgpt/api/user/resource_access.py``).

An empty map means today's behaviour: owner-only authorization.

Idempotent both ways.

Revision ID: 0039_resource_sponsors
Revises: 0038_resource_access_settings
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0039_resource_sponsors"
down_revision: Union[str, None] = "0038_resource_access_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("agents", "workflows"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
            "resource_sponsors JSONB NOT NULL DEFAULT '{}'::jsonb;"
        )


def downgrade() -> None:
    for table in ("agents", "workflows"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS resource_sponsors;")
