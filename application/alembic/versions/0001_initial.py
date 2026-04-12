"""0001 initial schema — user-level tables migrated from MongoDB.

Creates every table described in §2.2 of ``migration-postgres.md``: tiers 1,
2, and 3 in one shot. The schema is small enough that splitting the baseline
across multiple revisions would only cost clarity.

Subsequent migrations will add columns / tables incrementally. This file is
hand-written raw DDL rather than Core ``op.create_table`` calls because the
DDL uses several Postgres-specific features (``CITEXT``, partial indexes,
``text_pattern_ops``, JSONB defaults) that are clearer in SQL than in
Alembic's Python API.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-10
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext";')

    # ------------------------------------------------------------------
    # Tier 1: leaf tables, no FKs into other migrated tables
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE users (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           TEXT NOT NULL UNIQUE,
            agent_preferences JSONB NOT NULL
                              DEFAULT '{"pinned": [], "shared_with_me": []}'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX users_user_id_idx ON users (user_id);")

    op.execute("""
        CREATE TABLE prompts (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     TEXT NOT NULL,
            name        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX prompts_user_id_idx ON prompts (user_id);")

    op.execute("""
        CREATE TABLE user_tools (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      TEXT NOT NULL,
            name         TEXT NOT NULL,
            custom_name  TEXT,
            display_name TEXT,
            config       JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX user_tools_user_id_idx ON user_tools (user_id);")

    op.execute("""
        CREATE TABLE token_usage (
            id               BIGSERIAL PRIMARY KEY,
            user_id          TEXT,
            api_key          TEXT,
            agent_id         UUID,                      -- FK added later in this migration
            prompt_tokens    INTEGER NOT NULL DEFAULT 0,
            generated_tokens INTEGER NOT NULL DEFAULT 0,
            timestamp        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX token_usage_user_ts_idx  ON token_usage (user_id, timestamp DESC);")
    op.execute("CREATE INDEX token_usage_key_ts_idx   ON token_usage (api_key, timestamp DESC);")
    op.execute("CREATE INDEX token_usage_agent_ts_idx ON token_usage (agent_id, timestamp DESC);")

    op.execute("""
        CREATE TABLE user_logs (
            id        BIGSERIAL PRIMARY KEY,
            user_id   TEXT,
            endpoint  TEXT,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
            data      JSONB
        );
    """)
    op.execute("CREATE INDEX user_logs_user_ts_idx ON user_logs (user_id, timestamp DESC);")

    op.execute("""
        CREATE TABLE feedback (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL,              -- FK added later in this migration
            user_id         TEXT NOT NULL,
            question_index  INTEGER NOT NULL,
            feedback_text   TEXT,
            timestamp       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX feedback_conv_idx ON feedback (conversation_id);")

    # Append-only debug/error log. The Mongo doc has both `_id` (auto) and an
    # `id` field (the activity id). Here the serial PK owns `id`; the
    # application-level identifier is renamed to `activity_id`.
    op.execute("""
        CREATE TABLE stack_logs (
            id          BIGSERIAL PRIMARY KEY,
            activity_id TEXT NOT NULL,
            endpoint    TEXT,
            level       TEXT,
            user_id     TEXT,
            api_key     TEXT,
            query       TEXT,
            stacks      JSONB NOT NULL DEFAULT '[]'::jsonb,
            timestamp   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX stack_logs_timestamp_idx ON stack_logs (timestamp DESC);")
    op.execute("CREATE INDEX stack_logs_user_ts_idx   ON stack_logs (user_id, timestamp DESC);")
    op.execute("CREATE INDEX stack_logs_level_ts_idx  ON stack_logs (level, timestamp DESC);")
    op.execute("CREATE INDEX stack_logs_activity_idx  ON stack_logs (activity_id);")

    # ------------------------------------------------------------------
    # Tier 2: FK-bearing tables
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE agent_folders (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     TEXT NOT NULL,
            name        TEXT NOT NULL,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX agent_folders_user_idx ON agent_folders (user_id);")

    op.execute("""
        CREATE TABLE sources (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    TEXT,                 -- NULL for system/template sources
            name       TEXT NOT NULL,
            type       TEXT,
            metadata   JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX sources_user_idx ON sources (user_id);")

    op.execute("""
        CREATE TABLE agents (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                TEXT NOT NULL,
            name                   TEXT NOT NULL,
            description            TEXT,
            agent_type             TEXT,
            status                 TEXT NOT NULL,
            key                    CITEXT UNIQUE,
            source_id              UUID REFERENCES sources(id) ON DELETE SET NULL,
            extra_source_ids       UUID[] NOT NULL DEFAULT '{}',
            chunks                 INTEGER,
            retriever              TEXT,
            prompt_id              UUID REFERENCES prompts(id) ON DELETE SET NULL,
            tools                  JSONB NOT NULL DEFAULT '[]'::jsonb,
            json_schema            JSONB,
            models                 JSONB,
            default_model_id       TEXT,
            folder_id              UUID REFERENCES agent_folders(id) ON DELETE SET NULL,
            limited_token_mode     BOOLEAN NOT NULL DEFAULT false,
            token_limit            INTEGER,
            limited_request_mode   BOOLEAN NOT NULL DEFAULT false,
            request_limit          INTEGER,
            shared                 BOOLEAN NOT NULL DEFAULT false,
            incoming_webhook_token CITEXT UNIQUE,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at           TIMESTAMPTZ
        );
    """)
    op.execute("CREATE INDEX agents_user_idx   ON agents (user_id);")
    op.execute("CREATE INDEX agents_shared_idx ON agents (shared) WHERE shared = true;")
    op.execute("CREATE INDEX agents_status_idx ON agents (status);")

    # Backfill the token_usage.agent_id FK now that agents exists.
    op.execute("""
        ALTER TABLE token_usage
          ADD CONSTRAINT token_usage_agent_fk
          FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL;
    """)

    op.execute("""
        CREATE TABLE attachments (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     TEXT NOT NULL,
            filename    TEXT NOT NULL,
            upload_path TEXT NOT NULL,
            mime_type   TEXT,
            size        BIGINT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX attachments_user_idx ON attachments (user_id);")

    op.execute("""
        CREATE TABLE memories (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    TEXT NOT NULL,
            tool_id    UUID REFERENCES user_tools(id) ON DELETE CASCADE,
            path       TEXT NOT NULL,
            content    TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX memories_user_tool_path_uidx
            ON memories (user_id, tool_id, path);
    """)
    op.execute("""
        CREATE INDEX memories_path_prefix_idx
            ON memories (user_id, tool_id, path text_pattern_ops);
    """)

    op.execute("""
        CREATE TABLE todos (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    TEXT NOT NULL,
            tool_id    UUID REFERENCES user_tools(id) ON DELETE CASCADE,
            title      TEXT NOT NULL,
            completed  BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX todos_user_tool_idx ON todos (user_id, tool_id);")

    op.execute("""
        CREATE TABLE notes (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    TEXT NOT NULL,
            tool_id    UUID REFERENCES user_tools(id) ON DELETE CASCADE,
            title      TEXT NOT NULL,
            content    TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX notes_user_tool_idx ON notes (user_id, tool_id);")

    op.execute("""
        CREATE TABLE connector_sessions (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      TEXT NOT NULL,
            provider     TEXT NOT NULL,
            session_data JSONB NOT NULL,
            expires_at   TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        CREATE INDEX connector_sessions_user_provider_idx
            ON connector_sessions (user_id, provider);
    """)
    op.execute("""
        CREATE INDEX connector_sessions_expiry_idx
            ON connector_sessions (expires_at) WHERE expires_at IS NOT NULL;
    """)

    # ------------------------------------------------------------------
    # Tier 3: conversations, pending_tool_state, workflows
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE conversations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL,
            agent_id        UUID REFERENCES agents(id) ON DELETE SET NULL,
            name            TEXT,
            api_key         TEXT,
            is_shared_usage BOOLEAN NOT NULL DEFAULT false,
            shared_token    TEXT,
            date            TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX conversations_user_date_idx ON conversations (user_id, date DESC);")
    op.execute("CREATE INDEX conversations_agent_idx     ON conversations (agent_id);")
    op.execute("""
        CREATE INDEX conversations_shared_token_idx
            ON conversations (shared_token) WHERE shared_token IS NOT NULL;
    """)

    op.execute("""
        CREATE TABLE conversation_messages (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            position        INTEGER NOT NULL,
            prompt          TEXT,
            response        TEXT,
            thought         TEXT,
            sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
            tool_calls      JSONB NOT NULL DEFAULT '[]'::jsonb,
            attachments     UUID[] NOT NULL DEFAULT '{}',
            model_id        TEXT,
            metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
            feedback        JSONB,
            timestamp       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX conversation_messages_conv_pos_uidx
            ON conversation_messages (conversation_id, position);
    """)

    # Backfill the feedback.conversation_id FK now that conversations exists.
    op.execute("""
        ALTER TABLE feedback
          ADD CONSTRAINT feedback_conv_fk
          FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE;
    """)

    op.execute("""
        CREATE TABLE shared_conversations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            user_id         TEXT NOT NULL,
            prompt_id       UUID REFERENCES prompts(id) ON DELETE SET NULL,
            chunks          INTEGER,
            is_promptable   BOOLEAN NOT NULL DEFAULT false,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX shared_conversations_user_idx ON shared_conversations (user_id);")
    op.execute("CREATE INDEX shared_conversations_conv_idx ON shared_conversations (conversation_id);")

    # Paused-tool continuation state. The Mongo version relies on a TTL index;
    # Postgres has no native TTL, so a Celery beat task (added in Phase 3)
    # deletes rows where expires_at < now() once a minute. The unique
    # constraint on (conversation_id, user_id) matches the existing upsert
    # semantics.
    op.execute("""
        CREATE TABLE pending_tool_state (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id    UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            user_id            TEXT NOT NULL,
            messages           JSONB NOT NULL,
            pending_tool_calls JSONB NOT NULL,
            tools_dict         JSONB NOT NULL,
            tool_schemas       JSONB NOT NULL,
            agent_config       JSONB NOT NULL,
            client_tools       JSONB,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at         TIMESTAMPTZ NOT NULL
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX pending_tool_state_conv_user_uidx
            ON pending_tool_state (conversation_id, user_id);
    """)
    op.execute("""
        CREATE INDEX pending_tool_state_expires_idx
            ON pending_tool_state (expires_at);
    """)

    # Workflows
    op.execute("""
        CREATE TABLE workflows (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     TEXT NOT NULL,
            name        TEXT NOT NULL,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX workflows_user_idx ON workflows (user_id);")

    op.execute("""
        CREATE TABLE workflow_nodes (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id   UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            graph_version INTEGER NOT NULL,
            node_type     TEXT NOT NULL,
            config        JSONB NOT NULL DEFAULT '{}'::jsonb
        );
    """)
    op.execute("""
        CREATE INDEX workflow_nodes_workflow_version_idx
            ON workflow_nodes (workflow_id, graph_version);
    """)

    op.execute("""
        CREATE TABLE workflow_edges (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id   UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            graph_version INTEGER NOT NULL,
            from_node_id  UUID NOT NULL REFERENCES workflow_nodes(id) ON DELETE CASCADE,
            to_node_id    UUID NOT NULL REFERENCES workflow_nodes(id) ON DELETE CASCADE,
            config        JSONB NOT NULL DEFAULT '{}'::jsonb
        );
    """)
    op.execute("""
        CREATE INDEX workflow_edges_workflow_version_idx
            ON workflow_edges (workflow_id, graph_version);
    """)

    op.execute("""
        CREATE TABLE workflow_runs (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            user_id     TEXT NOT NULL,
            status      TEXT NOT NULL,
            started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at    TIMESTAMPTZ,
            result      JSONB
        );
    """)
    op.execute("CREATE INDEX workflow_runs_workflow_idx ON workflow_runs (workflow_id);")
    op.execute("CREATE INDEX workflow_runs_user_idx     ON workflow_runs (user_id);")


def downgrade() -> None:
    # Reverse dependency order. CASCADE would handle FKs anyway, but explicit
    # is clearer for anyone reading the migration.
    op.execute("DROP TABLE IF EXISTS workflow_runs CASCADE;")
    op.execute("DROP TABLE IF EXISTS workflow_edges CASCADE;")
    op.execute("DROP TABLE IF EXISTS workflow_nodes CASCADE;")
    op.execute("DROP TABLE IF EXISTS workflows CASCADE;")
    op.execute("DROP TABLE IF EXISTS pending_tool_state CASCADE;")
    op.execute("DROP TABLE IF EXISTS shared_conversations CASCADE;")
    op.execute("DROP TABLE IF EXISTS conversation_messages CASCADE;")
    op.execute("DROP TABLE IF EXISTS conversations CASCADE;")
    op.execute("DROP TABLE IF EXISTS connector_sessions CASCADE;")
    op.execute("DROP TABLE IF EXISTS notes CASCADE;")
    op.execute("DROP TABLE IF EXISTS todos CASCADE;")
    op.execute("DROP TABLE IF EXISTS memories CASCADE;")
    op.execute("DROP TABLE IF EXISTS attachments CASCADE;")
    op.execute("DROP TABLE IF EXISTS agents CASCADE;")
    op.execute("DROP TABLE IF EXISTS sources CASCADE;")
    op.execute("DROP TABLE IF EXISTS agent_folders CASCADE;")
    op.execute("DROP TABLE IF EXISTS stack_logs CASCADE;")
    op.execute("DROP TABLE IF EXISTS feedback CASCADE;")
    op.execute("DROP TABLE IF EXISTS user_logs CASCADE;")
    op.execute("DROP TABLE IF EXISTS token_usage CASCADE;")
    op.execute("DROP TABLE IF EXISTS user_tools CASCADE;")
    op.execute("DROP TABLE IF EXISTS prompts CASCADE;")
    op.execute("DROP TABLE IF EXISTS users CASCADE;")
    # Extensions are intentionally left in place — they may be shared with
    # pgvector or other extensions already enabled on the cluster.
