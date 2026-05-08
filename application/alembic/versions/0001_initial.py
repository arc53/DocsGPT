"""0001 initial schema — consolidated Phase-1..3 baseline.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-13
"""

from typing import Sequence, Union

from alembic import op


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
    # Trigger functions
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE FUNCTION ensure_user_exists() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.user_id IS NOT NULL THEN
                INSERT INTO users (user_id) VALUES (NEW.user_id)
                ON CONFLICT (user_id) DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE FUNCTION cleanup_message_attachment_refs() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE conversation_messages
            SET attachments = array_remove(attachments, OLD.id)
            WHERE OLD.id = ANY(attachments);
            RETURN OLD;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE FUNCTION cleanup_agent_extra_source_refs() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE agents
            SET extra_source_ids = array_remove(extra_source_ids, OLD.id)
            WHERE OLD.id = ANY(extra_source_ids);
            RETURN OLD;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE FUNCTION cleanup_user_agent_prefs() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            agent_id_text text := OLD.id::text;
        BEGIN
            UPDATE users
            SET agent_preferences = jsonb_set(
                jsonb_set(
                    agent_preferences,
                    '{pinned}',
                    COALESCE((
                        SELECT jsonb_agg(e)
                        FROM jsonb_array_elements(
                            COALESCE(agent_preferences->'pinned', '[]'::jsonb)
                        ) e
                        WHERE (e #>> '{}') <> agent_id_text
                    ), '[]'::jsonb)
                ),
                '{shared_with_me}',
                COALESCE((
                    SELECT jsonb_agg(e)
                    FROM jsonb_array_elements(
                        COALESCE(agent_preferences->'shared_with_me', '[]'::jsonb)
                    ) e
                    WHERE (e #>> '{}') <> agent_id_text
                ), '[]'::jsonb)
            )
            WHERE agent_preferences->'pinned' @> to_jsonb(agent_id_text)
               OR agent_preferences->'shared_with_me' @> to_jsonb(agent_id_text);
            RETURN OLD;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE FUNCTION conversation_messages_fill_user_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.user_id IS NULL THEN
                SELECT user_id INTO NEW.user_id
                FROM conversations
                WHERE id = NEW.conversation_id;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE users (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           TEXT NOT NULL UNIQUE,
            agent_preferences JSONB NOT NULL
                              DEFAULT '{"pinned": [], "shared_with_me": []}'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE prompts (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL,
            name            TEXT NOT NULL,
            content         TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            legacy_mongo_id TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE user_tools (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id             TEXT NOT NULL,
            name                TEXT NOT NULL,
            custom_name         TEXT,
            display_name        TEXT,
            description         TEXT,
            config              JSONB NOT NULL DEFAULT '{}'::jsonb,
            config_requirements JSONB NOT NULL DEFAULT '{}'::jsonb,
            actions             JSONB NOT NULL DEFAULT '[]'::jsonb,
            status              BOOLEAN NOT NULL DEFAULT true,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            legacy_mongo_id     TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE token_usage (
            id               BIGSERIAL PRIMARY KEY,
            user_id          TEXT,
            api_key          TEXT,
            agent_id         UUID,
            prompt_tokens    INTEGER NOT NULL DEFAULT 0,
            generated_tokens INTEGER NOT NULL DEFAULT 0,
            timestamp        TIMESTAMPTZ NOT NULL DEFAULT now(),
            mongo_id         TEXT
        );
        """
    )
    op.execute(
        "ALTER TABLE token_usage ADD CONSTRAINT token_usage_attribution_chk "
        "CHECK (user_id IS NOT NULL OR api_key IS NOT NULL) NOT VALID;"
    )

    op.execute(
        """
        CREATE TABLE user_logs (
            id        BIGSERIAL PRIMARY KEY,
            user_id   TEXT,
            endpoint  TEXT,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
            data      JSONB,
            mongo_id  TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE stack_logs (
            id          BIGSERIAL PRIMARY KEY,
            activity_id TEXT NOT NULL,
            endpoint    TEXT,
            level       TEXT,
            user_id     TEXT,
            api_key     TEXT,
            query       TEXT,
            stacks      JSONB NOT NULL DEFAULT '[]'::jsonb,
            timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
            mongo_id    TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE agent_folders (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL,
            name            TEXT NOT NULL,
            description     TEXT,
            parent_id       UUID REFERENCES agent_folders(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            legacy_mongo_id TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE sources (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id             TEXT NOT NULL,
            name                TEXT NOT NULL,
            language            TEXT,
            date                TIMESTAMPTZ NOT NULL DEFAULT now(),
            model               TEXT,
            type                TEXT,
            metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
            retriever           TEXT,
            sync_frequency      TEXT,
            tokens              TEXT,
            file_path           TEXT,
            remote_data         JSONB,
            directory_structure JSONB,
            file_name_map       JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            legacy_mongo_id     TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE agents (
            id                           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                      TEXT NOT NULL,
            name                         TEXT NOT NULL,
            description                  TEXT,
            agent_type                   TEXT,
            status                       TEXT NOT NULL,
            key                          CITEXT UNIQUE,
            image                        TEXT,
            source_id                    UUID REFERENCES sources(id) ON DELETE SET NULL,
            extra_source_ids             UUID[] NOT NULL DEFAULT '{}',
            chunks                       INTEGER,
            retriever                    TEXT,
            prompt_id                    UUID REFERENCES prompts(id) ON DELETE SET NULL,
            tools                        JSONB NOT NULL DEFAULT '[]'::jsonb,
            json_schema                  JSONB,
            models                       JSONB,
            default_model_id             TEXT,
            folder_id                    UUID REFERENCES agent_folders(id) ON DELETE SET NULL,
            workflow_id                  UUID,
            limited_token_mode           BOOLEAN NOT NULL DEFAULT false,
            token_limit                  INTEGER,
            limited_request_mode         BOOLEAN NOT NULL DEFAULT false,
            request_limit                INTEGER,
            allow_system_prompt_override BOOLEAN NOT NULL DEFAULT false,
            shared                       BOOLEAN NOT NULL DEFAULT false,
            shared_token                 CITEXT UNIQUE,
            shared_metadata              JSONB,
            incoming_webhook_token       CITEXT UNIQUE,
            created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at                 TIMESTAMPTZ,
            legacy_mongo_id              TEXT
        );
        """
    )
    op.execute(
        "ALTER TABLE token_usage ADD CONSTRAINT token_usage_agent_fk "
        "FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL;"
    )

    op.execute(
        """
        CREATE TABLE attachments (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL,
            filename        TEXT NOT NULL,
            upload_path     TEXT NOT NULL,
            mime_type       TEXT,
            size            BIGINT,
            content         TEXT,
            token_count     INTEGER,
            openai_file_id  TEXT,
            google_file_uri TEXT,
            metadata        JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            legacy_mongo_id TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE memories (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    TEXT NOT NULL,
            tool_id    UUID REFERENCES user_tools(id) ON DELETE CASCADE,
            path       TEXT NOT NULL,
            content    TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE todos (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL,
            tool_id         UUID REFERENCES user_tools(id) ON DELETE CASCADE,
            todo_id         INTEGER,
            title           TEXT NOT NULL,
            completed       BOOLEAN NOT NULL DEFAULT false,
            metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            legacy_mongo_id TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE notes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL,
            tool_id         UUID REFERENCES user_tools(id) ON DELETE CASCADE,
            title           TEXT NOT NULL,
            content         TEXT NOT NULL,
            metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            legacy_mongo_id TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE connector_sessions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         TEXT NOT NULL,
            provider        TEXT NOT NULL,
            server_url      TEXT,
            session_token   TEXT UNIQUE,
            user_email      TEXT,
            status          TEXT,
            token_info      JSONB,
            session_data    JSONB NOT NULL DEFAULT '{}'::jsonb,
            expires_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            legacy_mongo_id TEXT
        );
        """
    )

    op.execute(
        """
        CREATE TABLE conversations (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id              TEXT NOT NULL,
            agent_id             UUID REFERENCES agents(id) ON DELETE SET NULL,
            name                 TEXT,
            api_key              TEXT,
            is_shared_usage      BOOLEAN NOT NULL DEFAULT false,
            shared_token         TEXT,
            date                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            shared_with          TEXT[] NOT NULL DEFAULT '{}'::text[],
            compression_metadata JSONB,
            legacy_mongo_id      TEXT,
            CONSTRAINT conversations_api_key_nonempty_chk
                CHECK (api_key IS NULL OR api_key <> '')
        );
        """
    )

    op.execute(
        """
        CREATE TABLE conversation_messages (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            position         INTEGER NOT NULL,
            prompt           TEXT,
            response         TEXT,
            thought          TEXT,
            sources          JSONB NOT NULL DEFAULT '[]'::jsonb,
            tool_calls       JSONB NOT NULL DEFAULT '[]'::jsonb,
            attachments      UUID[] NOT NULL DEFAULT '{}'::uuid[],
            model_id         TEXT,
            message_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            feedback         JSONB,
            timestamp        TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id          TEXT NOT NULL,
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE shared_conversations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            user_id         TEXT NOT NULL,
            is_promptable   BOOLEAN NOT NULL DEFAULT false,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            uuid            UUID NOT NULL,
            first_n_queries INTEGER NOT NULL DEFAULT 0,
            api_key         TEXT,
            prompt_id       UUID REFERENCES prompts(id) ON DELETE SET NULL,
            chunks          INTEGER,
            CONSTRAINT shared_conversations_api_key_nonempty_chk
                CHECK (api_key IS NULL OR api_key <> '')
        );
        """
    )

    op.execute(
        """
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
        """
    )

    op.execute(
        """
        CREATE TABLE workflows (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id               TEXT NOT NULL,
            name                  TEXT NOT NULL,
            description           TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            current_graph_version INTEGER NOT NULL DEFAULT 1,
            legacy_mongo_id       TEXT
        );
        """
    )
    # Backfill the agents.workflow_id FK now that workflows exists.
    # The column was created without a FK (forward reference to a table
    # that hadn't been declared yet); add the constraint here so workflow
    # deletion still cascades through to agent unset.
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT agents_workflow_fk "
        "FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE SET NULL;"
    )

    op.execute(
        """
        CREATE TABLE workflow_nodes (
            id              UUID DEFAULT gen_random_uuid() NOT NULL,
            workflow_id     UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            graph_version   INTEGER NOT NULL,
            node_type       TEXT NOT NULL,
            config          JSONB NOT NULL DEFAULT '{}'::jsonb,
            node_id         TEXT NOT NULL,
            title           TEXT,
            description     TEXT,
            position        JSONB NOT NULL DEFAULT '{"x": 0, "y": 0}'::jsonb,
            legacy_mongo_id TEXT,
            PRIMARY KEY (id),
            CONSTRAINT workflow_nodes_id_wf_ver_key
                UNIQUE (id, workflow_id, graph_version)
        );
        """
    )

    op.execute(
        """
        CREATE TABLE workflow_edges (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id   UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            graph_version INTEGER NOT NULL,
            from_node_id  UUID NOT NULL,
            to_node_id    UUID NOT NULL,
            config        JSONB NOT NULL DEFAULT '{}'::jsonb,
            edge_id       TEXT NOT NULL,
            source_handle TEXT,
            target_handle TEXT,
            CONSTRAINT workflow_edges_from_node_fk
                FOREIGN KEY (from_node_id, workflow_id, graph_version)
                REFERENCES workflow_nodes(id, workflow_id, graph_version) ON DELETE CASCADE,
            CONSTRAINT workflow_edges_to_node_fk
                FOREIGN KEY (to_node_id, workflow_id, graph_version)
                REFERENCES workflow_nodes(id, workflow_id, graph_version) ON DELETE CASCADE
        );
        """
    )

    op.execute(
        """
        CREATE TABLE workflow_runs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id     UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            user_id         TEXT NOT NULL,
            status          TEXT NOT NULL,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at        TIMESTAMPTZ,
            result          JSONB,
            inputs          JSONB,
            steps           JSONB NOT NULL DEFAULT '[]'::jsonb,
            legacy_mongo_id TEXT,
            CONSTRAINT workflow_runs_status_chk
                CHECK (status IN ('pending', 'running', 'completed', 'failed'))
        );
        """
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    op.execute("CREATE INDEX agent_folders_user_idx ON agent_folders (user_id);")

    op.execute("CREATE INDEX agents_user_idx   ON agents (user_id);")
    op.execute("CREATE INDEX agents_shared_idx ON agents (shared) WHERE shared = true;")
    op.execute("CREATE INDEX agents_status_idx ON agents (status);")
    op.execute("CREATE INDEX agents_source_id_idx ON agents (source_id);")
    op.execute("CREATE INDEX agents_prompt_id_idx ON agents (prompt_id);")
    op.execute("CREATE INDEX agents_folder_id_idx ON agents (folder_id);")
    op.execute(
        "CREATE UNIQUE INDEX agents_legacy_mongo_id_uidx "
        "ON agents (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )

    op.execute("CREATE INDEX attachments_user_idx ON attachments (user_id);")
    op.execute(
        "CREATE UNIQUE INDEX attachments_legacy_mongo_id_uidx "
        "ON attachments (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )

    op.execute(
        # MCP and OAuth connectors share the ``provider`` slot, so the
        # dedup key is ``(user_id, server_url, provider)``: MCP rows
        # differentiate by server_url (one per MCP server), OAuth rows
        # have server_url = NULL and differentiate by provider alone.
        # COALESCE lets NULL server_url participate in the constraint.
        "CREATE UNIQUE INDEX connector_sessions_user_endpoint_uidx "
        "ON connector_sessions (user_id, COALESCE(server_url, ''), provider);"
    )
    op.execute(
        "CREATE INDEX connector_sessions_expiry_idx "
        "ON connector_sessions (expires_at) WHERE expires_at IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX connector_sessions_server_url_idx "
        "ON connector_sessions (server_url) WHERE server_url IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX connector_sessions_legacy_mongo_id_uidx "
        "ON connector_sessions (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )

    op.execute(
        "CREATE UNIQUE INDEX conversation_messages_conv_pos_uidx "
        "ON conversation_messages (conversation_id, position);"
    )
    op.execute(
        "CREATE INDEX conversation_messages_user_ts_idx "
        "ON conversation_messages (user_id, timestamp DESC);"
    )

    op.execute("CREATE INDEX conversations_user_date_idx ON conversations (user_id, date DESC);")
    op.execute("CREATE INDEX conversations_agent_idx    ON conversations (agent_id);")
    op.execute(
        "CREATE UNIQUE INDEX conversations_shared_token_uidx "
        "ON conversations (shared_token) WHERE shared_token IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX conversations_api_key_date_idx "
        "ON conversations (api_key, date DESC) WHERE api_key IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX conversations_legacy_mongo_id_uidx "
        "ON conversations (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )

    op.execute(
        "CREATE UNIQUE INDEX memories_user_tool_path_uidx "
        "ON memories (user_id, tool_id, path);"
    )
    op.execute(
        "CREATE UNIQUE INDEX memories_user_path_null_tool_uidx "
        "ON memories (user_id, path) WHERE tool_id IS NULL;"
    )
    op.execute(
        "CREATE INDEX memories_path_prefix_idx "
        "ON memories (user_id, tool_id, path text_pattern_ops);"
    )
    op.execute("CREATE INDEX memories_tool_id_idx ON memories (tool_id);")

    op.execute("CREATE UNIQUE INDEX notes_user_tool_uidx ON notes (user_id, tool_id);")
    op.execute("CREATE INDEX notes_tool_id_idx ON notes (tool_id);")
    op.execute(
        "CREATE UNIQUE INDEX notes_legacy_mongo_id_uidx "
        "ON notes (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )

    op.execute(
        "CREATE UNIQUE INDEX pending_tool_state_conv_user_uidx "
        "ON pending_tool_state (conversation_id, user_id);"
    )
    op.execute(
        "CREATE INDEX pending_tool_state_expires_idx ON pending_tool_state (expires_at);"
    )

    op.execute("CREATE INDEX prompts_user_id_idx ON prompts (user_id);")
    op.execute(
        "CREATE UNIQUE INDEX prompts_legacy_mongo_id_uidx "
        "ON prompts (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )

    op.execute("CREATE INDEX shared_conversations_user_idx ON shared_conversations (user_id);")
    op.execute("CREATE INDEX shared_conversations_conv_idx ON shared_conversations (conversation_id);")
    op.execute(
        "CREATE INDEX shared_conversations_prompt_id_idx ON shared_conversations (prompt_id);"
    )
    op.execute(
        "CREATE UNIQUE INDEX shared_conversations_uuid_uidx ON shared_conversations (uuid);"
    )
    op.execute(
        "CREATE UNIQUE INDEX shared_conversations_dedup_uidx "
        "ON shared_conversations (conversation_id, user_id, is_promptable, first_n_queries, COALESCE(api_key, ''));"
    )

    op.execute("CREATE INDEX sources_user_idx ON sources (user_id);")
    op.execute(
        "CREATE UNIQUE INDEX sources_legacy_mongo_id_uidx "
        "ON sources (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX user_tools_legacy_mongo_id_uidx "
        "ON user_tools (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX agent_folders_legacy_mongo_id_uidx "
        "ON agent_folders (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )
    op.execute("CREATE INDEX agent_folders_parent_idx ON agent_folders (parent_id);")
    op.execute("CREATE INDEX agents_workflow_idx ON agents (workflow_id);")

    op.execute('CREATE INDEX stack_logs_timestamp_idx ON stack_logs ("timestamp" DESC);')
    op.execute('CREATE INDEX stack_logs_user_ts_idx   ON stack_logs (user_id, "timestamp" DESC);')
    op.execute('CREATE INDEX stack_logs_level_ts_idx  ON stack_logs (level, "timestamp" DESC);')
    op.execute("CREATE INDEX stack_logs_activity_idx  ON stack_logs (activity_id);")
    op.execute(
        "CREATE UNIQUE INDEX stack_logs_mongo_id_uidx "
        "ON stack_logs (mongo_id) WHERE mongo_id IS NOT NULL;"
    )

    op.execute("CREATE INDEX todos_user_tool_idx ON todos (user_id, tool_id);")
    op.execute("CREATE INDEX todos_tool_id_idx   ON todos (tool_id);")
    op.execute(
        "CREATE UNIQUE INDEX todos_legacy_mongo_id_uidx "
        "ON todos (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )
    op.execute(
        "CREATE UNIQUE INDEX todos_tool_todo_id_uidx "
        "ON todos (tool_id, todo_id) WHERE todo_id IS NOT NULL;"
    )

    op.execute('CREATE INDEX token_usage_user_ts_idx  ON token_usage (user_id, "timestamp" DESC);')
    op.execute('CREATE INDEX token_usage_key_ts_idx   ON token_usage (api_key, "timestamp" DESC);')
    op.execute('CREATE INDEX token_usage_agent_ts_idx ON token_usage (agent_id, "timestamp" DESC);')
    op.execute(
        "CREATE UNIQUE INDEX token_usage_mongo_id_uidx "
        "ON token_usage (mongo_id) WHERE mongo_id IS NOT NULL;"
    )

    op.execute('CREATE INDEX user_logs_user_ts_idx ON user_logs (user_id, "timestamp" DESC);')
    op.execute(
        "CREATE UNIQUE INDEX user_logs_mongo_id_uidx "
        "ON user_logs (mongo_id) WHERE mongo_id IS NOT NULL;"
    )

    op.execute("CREATE INDEX user_tools_user_id_idx ON user_tools (user_id);")

    op.execute("CREATE INDEX workflow_edges_from_node_idx ON workflow_edges (from_node_id);")
    op.execute("CREATE INDEX workflow_edges_to_node_idx   ON workflow_edges (to_node_id);")
    op.execute(
        "CREATE UNIQUE INDEX workflow_edges_wf_ver_eid_uidx "
        "ON workflow_edges (workflow_id, graph_version, edge_id);"
    )

    op.execute(
        "CREATE UNIQUE INDEX workflow_nodes_wf_ver_nid_uidx "
        "ON workflow_nodes (workflow_id, graph_version, node_id);"
    )
    op.execute(
        "CREATE UNIQUE INDEX workflow_nodes_legacy_mongo_id_uidx "
        "ON workflow_nodes (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )

    op.execute("CREATE INDEX workflow_runs_workflow_idx ON workflow_runs (workflow_id);")
    op.execute("CREATE INDEX workflow_runs_user_idx     ON workflow_runs (user_id);")
    op.execute(
        "CREATE INDEX workflow_runs_status_started_idx "
        "ON workflow_runs (status, started_at DESC);"
    )
    op.execute(
        "CREATE UNIQUE INDEX workflow_runs_legacy_mongo_id_uidx "
        "ON workflow_runs (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )

    op.execute("CREATE INDEX workflows_user_idx ON workflows (user_id);")
    op.execute(
        "CREATE UNIQUE INDEX workflows_legacy_mongo_id_uidx "
        "ON workflows (legacy_mongo_id) WHERE legacy_mongo_id IS NOT NULL;"
    )

    # ------------------------------------------------------------------
    # user_id foreign keys (deferrable so backfills can stage rows)
    # ------------------------------------------------------------------
    user_fk_tables = (
        "agent_folders",
        "agents",
        "attachments",
        "connector_sessions",
        "conversation_messages",
        "conversations",
        "memories",
        "notes",
        "pending_tool_state",
        "prompts",
        "shared_conversations",
        "sources",
        "stack_logs",
        "todos",
        "token_usage",
        "user_logs",
        "user_tools",
        "workflow_runs",
        "workflows",
    )
    for table in user_fk_tables:
        op.execute(
            f"ALTER TABLE {table} "
            f"ADD CONSTRAINT {table}_user_id_fk "
            f"FOREIGN KEY (user_id) REFERENCES users(user_id) "
            f"ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE;"
        )

    # ------------------------------------------------------------------
    # Triggers
    # ------------------------------------------------------------------
    updated_at_tables = (
        "agent_folders",
        "agents",
        "conversation_messages",
        "conversations",
        "memories",
        "notes",
        "prompts",
        "sources",
        "todos",
        "user_tools",
        "users",
        "workflows",
    )
    for table in updated_at_tables:
        op.execute(
            f"CREATE TRIGGER {table}_set_updated_at "
            f"BEFORE UPDATE ON {table} "
            f"FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) "
            f"EXECUTE FUNCTION set_updated_at();"
        )

    ensure_user_tables = (
        "agent_folders",
        "agents",
        "attachments",
        "connector_sessions",
        "conversation_messages",
        "conversations",
        "memories",
        "notes",
        "pending_tool_state",
        "prompts",
        "shared_conversations",
        "sources",
        "stack_logs",
        "todos",
        "token_usage",
        "user_logs",
        "user_tools",
        "workflow_runs",
        "workflows",
    )
    for table in ensure_user_tables:
        op.execute(
            f"CREATE TRIGGER {table}_ensure_user "
            f"BEFORE INSERT OR UPDATE OF user_id ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION ensure_user_exists();"
        )

    op.execute(
        "CREATE TRIGGER conversation_messages_fill_user "
        "BEFORE INSERT ON conversation_messages "
        "FOR EACH ROW EXECUTE FUNCTION conversation_messages_fill_user_id();"
    )

    op.execute(
        "CREATE TRIGGER attachments_cleanup_message_refs "
        "AFTER DELETE ON attachments "
        "FOR EACH ROW EXECUTE FUNCTION cleanup_message_attachment_refs();"
    )
    op.execute(
        "CREATE TRIGGER agents_cleanup_user_prefs "
        "AFTER DELETE ON agents "
        "FOR EACH ROW EXECUTE FUNCTION cleanup_user_agent_prefs();"
    )
    op.execute(
        "CREATE TRIGGER sources_cleanup_agent_extra_refs "
        "AFTER DELETE ON sources "
        "FOR EACH ROW EXECUTE FUNCTION cleanup_agent_extra_source_refs();"
    )

    # ------------------------------------------------------------------
    # Seed sentinel __system__ user (system/template sources attribute here)
    # ------------------------------------------------------------------
    op.execute(
        "INSERT INTO users (user_id) VALUES ('__system__') "
        "ON CONFLICT (user_id) DO NOTHING;"
    )


def downgrade() -> None:
    # Nuclear downgrade: drop everything this migration created. The
    # ordering drops FK-bearing children before parents; CASCADE would
    # also work but explicit ordering is easier to reason about in code
    # review.
    tables_in_drop_order = (
        "workflow_edges",
        "workflow_runs",
        "workflow_nodes",
        "workflows",
        "pending_tool_state",
        "shared_conversations",
        "conversation_messages",
        "conversations",
        "connector_sessions",
        "notes",
        "todos",
        "memories",
        "attachments",
        "agents",
        "sources",
        "agent_folders",
        "stack_logs",
        "user_logs",
        "token_usage",
        "user_tools",
        "prompts",
        "users",
    )
    for table in tables_in_drop_order:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")

    for fn in (
        "conversation_messages_fill_user_id",
        "cleanup_user_agent_prefs",
        "cleanup_agent_extra_source_refs",
        "cleanup_message_attachment_refs",
        "ensure_user_exists",
        "set_updated_at",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}();")
