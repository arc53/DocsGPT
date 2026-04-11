"""SQLAlchemy Core metadata for the user-data Postgres database.

Tables are added here one at a time as repositories are built during the
MongoDB→Postgres migration. The baseline schema in the Alembic migration
(``application/alembic/versions/0001_initial.py``) is the source of truth
for DDL; the ``Table`` definitions below must match it column-for-column.
If the two drift, migrations win — update this file to match.
"""

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()


# --- Phase 1, Tier 1 --------------------------------------------------------

users_table = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False, unique=True),
    Column(
        "agent_preferences",
        JSONB,
        nullable=False,
        server_default='{"pinned": [], "shared_with_me": []}',
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
