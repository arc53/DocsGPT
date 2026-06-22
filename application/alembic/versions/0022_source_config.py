"""0022 source config — per-source behavior contract JSONB column.

Adds ``sources.config`` (JSONB, NOT NULL, default ``{}``). The column holds a
Pydantic-validated ``SourceConfig`` (chunking + retrieval knobs) separate from
the display/provenance ``metadata`` bag. The server default backfills every
existing row with ``{}``, which ``SourceConfig.parse()`` reads as classic
defaults — so existing sources behave byte-for-byte as before.

No new Postgres extensions (keeps it Neon/DBngin-portable).

Revision ID: 0022_source_config
Revises: 0021_teams
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0022_source_config"
down_revision: Union[str, None] = "0021_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "config",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sources", "config")
