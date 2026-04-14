"""SQLAlchemy Core metadata for the user-data Postgres database.

Tables are added here one at a time as repositories are built during the
MongoDB→Postgres migration. The baseline schema in the Alembic migration
(``application/alembic/versions/0001_initial.py``) is the source of truth
for DDL; the ``Table`` definitions below must match it column-for-column.
If the two drift, migrations win — update this file to match.

Cross-table invariant not expressed in the Core ``Table`` definitions
below: every ``user_id`` column is FK-enforced against
``users(user_id)`` with ``ON DELETE RESTRICT``, and a
``BEFORE INSERT OR UPDATE OF user_id`` trigger on each child table
auto-creates the ``users`` row if it does not yet exist. See migration
``0015_user_id_fk``. The FKs are intentionally omitted from the Core
declarations to keep this file readable; the DB is the authority.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    UniqueConstraint,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID

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
    Column("legacy_mongo_id", Text),
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
    Column("user_id", Text, nullable=False),
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
    Column("key", CITEXT, unique=True),
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
    Column("incoming_webhook_token", CITEXT, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_used_at", DateTime(timezone=True)),
    Column("legacy_mongo_id", Text),
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
    Column("legacy_mongo_id", Text),
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


# --- Phase 3, Tier 3 --------------------------------------------------------

conversations_table = Table(
    "conversations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL")),
    Column("name", Text),
    Column("api_key", Text),
    Column("is_shared_usage", Boolean, nullable=False, server_default="false"),
    Column("shared_token", Text),
    Column("shared_with", ARRAY(Text), nullable=False, server_default="{}"),
    Column("compression_metadata", JSONB),
    Column("date", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("legacy_mongo_id", Text),
)

conversation_messages_table = Table(
    "conversation_messages",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("conversation_id", UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    # Denormalised from conversations.user_id. Auto-filled on insert by a
    # BEFORE INSERT trigger when the caller omits it. See migration 0020.
    Column("user_id", Text, nullable=False),
    Column("position", Integer, nullable=False),
    Column("prompt", Text),
    Column("response", Text),
    Column("thought", Text),
    Column("sources", JSONB, nullable=False, server_default="[]"),
    Column("tool_calls", JSONB, nullable=False, server_default="[]"),
    # Postgres cannot FK-enforce array elements, so the referential
    # invariant is kept by an AFTER DELETE trigger on ``attachments``
    # that array_removes the id from every row that references it.
    # See migration 0017_cleanup_dangling_refs.
    Column("attachments", ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"),
    Column("model_id", Text),
    # Renamed from ``metadata`` in migration 0016 to avoid SQLAlchemy's
    # reserved attribute collision on declarative models. The repository
    # translates this ↔ API dict key ``metadata`` so external callers
    # still see ``metadata``.
    Column("message_metadata", JSONB, nullable=False, server_default="{}"),
    Column("feedback", JSONB),
    Column("timestamp", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("conversation_id", "position", name="conversation_messages_conv_pos_uidx"),
)

shared_conversations_table = Table(
    "shared_conversations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("uuid", UUID(as_uuid=True), nullable=False, unique=True),
    Column("conversation_id", UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Text, nullable=False),
    Column("prompt_id", UUID(as_uuid=True), ForeignKey("prompts.id", ondelete="SET NULL")),
    Column("chunks", Integer),
    Column("is_promptable", Boolean, nullable=False, server_default="false"),
    Column("first_n_queries", Integer, nullable=False, server_default="0"),
    Column("api_key", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

pending_tool_state_table = Table(
    "pending_tool_state",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("conversation_id", UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Text, nullable=False),
    Column("messages", JSONB, nullable=False),
    Column("pending_tool_calls", JSONB, nullable=False),
    Column("tools_dict", JSONB, nullable=False),
    Column("tool_schemas", JSONB, nullable=False),
    Column("agent_config", JSONB, nullable=False),
    Column("client_tools", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("conversation_id", "user_id", name="pending_tool_state_conv_user_uidx"),
)

workflows_table = Table(
    "workflows",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("current_graph_version", Integer, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("legacy_mongo_id", Text),
)

workflow_nodes_table = Table(
    "workflow_nodes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("workflow_id", UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
    Column("graph_version", Integer, nullable=False),
    Column("node_id", Text, nullable=False),
    Column("node_type", Text, nullable=False),
    Column("title", Text),
    Column("description", Text),
    Column("position", JSONB, nullable=False, server_default='{"x": 0, "y": 0}'),
    Column("config", JSONB, nullable=False, server_default="{}"),
    Column("legacy_mongo_id", Text),
    # Composite UNIQUE so workflow_edges can use a composite FK that
    # enforces endpoint nodes belong to the same (workflow, version) as
    # the edge itself. See migration 0008.
    UniqueConstraint(
        "id", "workflow_id", "graph_version",
        name="workflow_nodes_id_wf_ver_key",
    ),
)

workflow_edges_table = Table(
    "workflow_edges",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("workflow_id", UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
    Column("graph_version", Integer, nullable=False),
    Column("edge_id", Text, nullable=False),
    Column("from_node_id", UUID(as_uuid=True), nullable=False),
    Column("to_node_id", UUID(as_uuid=True), nullable=False),
    Column("source_handle", Text),
    Column("target_handle", Text),
    Column("config", JSONB, nullable=False, server_default="{}"),
    # Composite FKs: endpoints must belong to the same (workflow, version)
    # as the edge. Prevents cross-workflow / cross-version edges that the
    # single-column FKs couldn't catch. See migration 0008.
    ForeignKeyConstraint(
        ["from_node_id", "workflow_id", "graph_version"],
        ["workflow_nodes.id", "workflow_nodes.workflow_id", "workflow_nodes.graph_version"],
        ondelete="CASCADE",
        name="workflow_edges_from_node_fk",
    ),
    ForeignKeyConstraint(
        ["to_node_id", "workflow_id", "graph_version"],
        ["workflow_nodes.id", "workflow_nodes.workflow_id", "workflow_nodes.graph_version"],
        ondelete="CASCADE",
        name="workflow_edges_to_node_fk",
    ),
)

workflow_runs_table = Table(
    "workflow_runs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("workflow_id", UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("inputs", JSONB),
    Column("result", JSONB),
    Column("steps", JSONB, nullable=False, server_default="[]"),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("ended_at", DateTime(timezone=True)),
    Column("legacy_mongo_id", Text),
)
