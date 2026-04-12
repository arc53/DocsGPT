"""SQLAlchemy Core metadata for the user-data Postgres database.

Tables are added here one at a time as repositories are built during the
MongoDB→Postgres migration. The baseline schema in the Alembic migration
(``application/alembic/versions/0001_initial.py``) is the source of truth
for DDL; the ``Table`` definitions below must match it column-for-column.
If the two drift, migrations win — update this file to match.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
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

prompts_table = Table(
    "prompts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

user_tools_table = Table(
    "user_tools",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("custom_name", Text),
    Column("display_name", Text),
    Column("config", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

token_usage_table = Table(
    "token_usage",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", Text),
    Column("api_key", Text),
    Column("agent_id", UUID(as_uuid=True)),
    Column("prompt_tokens", Integer, nullable=False, server_default="0"),
    Column("generated_tokens", Integer, nullable=False, server_default="0"),
    Column("timestamp", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

user_logs_table = Table(
    "user_logs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", Text),
    Column("endpoint", Text),
    Column("timestamp", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("data", JSONB),
)

feedback_table = Table(
    "feedback",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("conversation_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", Text, nullable=False),
    Column("question_index", Integer, nullable=False),
    Column("feedback_text", Text),
    Column("timestamp", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

stack_logs_table = Table(
    "stack_logs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("activity_id", Text, nullable=False),
    Column("endpoint", Text),
    Column("level", Text),
    Column("user_id", Text),
    Column("api_key", Text),
    Column("query", Text),
    Column("stacks", JSONB, nullable=False, server_default="[]"),
    Column("timestamp", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
