"""SQLAlchemy Core metadata for the user-data Postgres database.

Tables are added here one at a time as repositories are built during the
MongoDB→Postgres migration. The baseline schema in the Alembic migration
(``application/alembic/versions/0001_initial.py``) is the source of truth
for DDL; the ``Table`` definitions below must match it column-for-column.
If the two drift, migrations win — update this file to match.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    UniqueConstraint,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

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


# --- Phase 2, Tier 2 --------------------------------------------------------

agent_folders_table = Table(
    "agent_folders",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

sources_table = Table(
    "sources",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text),
    Column("name", Text, nullable=False),
    Column("type", Text),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

agents_table = Table(
    "agents",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("agent_type", Text),
    Column("status", Text, nullable=False),
    Column("key", Text, unique=True),
    Column("source_id", UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")),
    Column("extra_source_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
    Column("chunks", Integer),
    Column("retriever", Text),
    Column("prompt_id", UUID(as_uuid=True), ForeignKey("prompts.id", ondelete="SET NULL")),
    Column("tools", JSONB, nullable=False, server_default="[]"),
    Column("json_schema", JSONB),
    Column("models", JSONB),
    Column("default_model_id", Text),
    Column("folder_id", UUID(as_uuid=True), ForeignKey("agent_folders.id", ondelete="SET NULL")),
    Column("limited_token_mode", Boolean, nullable=False, server_default="false"),
    Column("token_limit", Integer),
    Column("limited_request_mode", Boolean, nullable=False, server_default="false"),
    Column("request_limit", Integer),
    Column("shared", Boolean, nullable=False, server_default="false"),
    Column("incoming_webhook_token", Text, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_used_at", DateTime(timezone=True)),
)

attachments_table = Table(
    "attachments",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("filename", Text, nullable=False),
    Column("upload_path", Text, nullable=False),
    Column("mime_type", Text),
    Column("size", BigInteger),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

memories_table = Table(
    "memories",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("tool_id", UUID(as_uuid=True), ForeignKey("user_tools.id", ondelete="CASCADE")),
    Column("path", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("user_id", "tool_id", "path", name="memories_user_tool_path_uidx"),
)

todos_table = Table(
    "todos",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("tool_id", UUID(as_uuid=True), ForeignKey("user_tools.id", ondelete="CASCADE")),
    Column("title", Text, nullable=False),
    Column("completed", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

notes_table = Table(
    "notes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("tool_id", UUID(as_uuid=True), ForeignKey("user_tools.id", ondelete="CASCADE")),
    Column("title", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("user_id", "tool_id", name="notes_user_tool_uidx"),
)

connector_sessions_table = Table(
    "connector_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("session_data", JSONB, nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("user_id", "provider", name="connector_sessions_user_provider_uidx"),
)
