"""Tests for StackLogsRepository against a real Postgres instance."""

from __future__ import annotations

from sqlalchemy import text

from application.storage.db.repositories.stack_logs import StackLogsRepository


def _repo(conn) -> StackLogsRepository:
    return StackLogsRepository(conn)


class TestInsert:
    def test_inserts_log(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(
            activity_id="act-1",
            endpoint="/api/answer",
            level="info",
            user_id="u1",
            api_key="k1",
            query="what is python?",
            stacks=[{"component": "retriever", "data": {"docs": 3}}],
        )
        row = pg_conn.execute(
            text("SELECT * FROM stack_logs WHERE activity_id = 'act-1'")
        ).fetchone()
        assert row is not None
        mapping = dict(row._mapping)
        assert mapping["endpoint"] == "/api/answer"
        assert mapping["level"] == "info"
        assert mapping["user_id"] == "u1"
        assert mapping["stacks"] == [{"component": "retriever", "data": {"docs": 3}}]

    def test_inserts_with_agent_id(self, pg_conn):
        repo = _repo(pg_conn)
        agent_uuid = "11111111-1111-1111-1111-111111111111"
        repo.insert(
            activity_id="act-agent",
            api_key="k-agent",
            agent_id=agent_uuid,
        )
        row = pg_conn.execute(
            text("SELECT agent_id FROM stack_logs WHERE activity_id = 'act-agent'")
        ).fetchone()
        assert str(dict(row._mapping)["agent_id"]) == agent_uuid

    def test_non_uuid_agent_id_coerced_to_null(self, pg_conn):
        # A stray/legacy (non-UUID) id must not break the activity-log write.
        repo = _repo(pg_conn)
        repo.insert(
            activity_id="act-badid",
            api_key="k-badid",
            agent_id="507f1f77bcf86cd799439011",  # 24-hex Mongo ObjectId
        )
        row = pg_conn.execute(
            text("SELECT agent_id FROM stack_logs WHERE activity_id = 'act-badid'")
        ).fetchone()
        assert dict(row._mapping)["agent_id"] is None

    def test_inserts_with_empty_stacks(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(activity_id="act-2", level="error")
        row = pg_conn.execute(
            text("SELECT stacks FROM stack_logs WHERE activity_id = 'act-2'")
        ).fetchone()
        assert row is not None
        assert dict(row._mapping)["stacks"] == []

    def test_truncated_query_stored(self, pg_conn):
        repo = _repo(pg_conn)
        long_query = "x" * 20000
        repo.insert(activity_id="act-3", query=long_query)
        row = pg_conn.execute(
            text("SELECT query FROM stack_logs WHERE activity_id = 'act-3'")
        ).fetchone()
        assert len(dict(row._mapping)["query"]) == 20000

    def test_secrets_redacted_from_stacks(self, pg_conn):
        # The ``llm`` stack component is built from every public attr of
        # the LLM and includes the provider secret + the caller's key.
        # These must never persist (the unified-logs endpoint returns
        # stacks verbatim).
        repo = _repo(pg_conn)
        repo.insert(
            activity_id="act-secret",
            level="error",
            stacks=[
                {
                    "component": "llm",
                    "data": {
                        "api_key": "sk-deployment-secret",
                        "user_api_key": "agent-key",
                        "OPENAI_API_KEY": "sk-env",
                        "model": "gpt-x",
                        "prompt_tokens": 42,
                    },
                }
            ],
        )
        row = pg_conn.execute(
            text("SELECT stacks FROM stack_logs WHERE activity_id = 'act-secret'")
        ).fetchone()
        data = dict(row._mapping)["stacks"][0]["data"]
        assert data["api_key"] == "[REDACTED]"
        assert data["user_api_key"] == "[REDACTED]"
        assert data["OPENAI_API_KEY"] == "[REDACTED]"
        # Non-secret fields (incl. token *counts*) are untouched.
        assert data["model"] == "gpt-x"
        assert data["prompt_tokens"] == 42

    def test_redacts_broadened_secret_keys(self, pg_conn):
        # Credentials beyond ``*api_key`` — OAuth tokens, bearer/auth
        # headers, private keys — must also be scrubbed, while token
        # *count* fields are preserved.
        repo = _repo(pg_conn)
        repo.insert(
            activity_id="act-broad",
            level="error",
            stacks=[
                {
                    "component": "tool",
                    "data": {
                        "access_token": "ya29.secret",
                        "api_token": "r8_secret",
                        "token": "hf_secret",
                        "Authorization": "Bearer xyz",
                        "private_key": "-----BEGIN-----",
                        "client_secret": "cs_secret",
                        "prompt_tokens": 10,
                        "generated_tokens": 5,
                        "token_budget": 1000,
                    },
                }
            ],
        )
        row = pg_conn.execute(
            text("SELECT stacks FROM stack_logs WHERE activity_id = 'act-broad'")
        ).fetchone()
        data = dict(row._mapping)["stacks"][0]["data"]
        for key in (
            "access_token",
            "api_token",
            "token",
            "Authorization",
            "private_key",
            "client_secret",
        ):
            assert data[key] == "[REDACTED]", key
        # Token *counts* / budgets are not credentials and must survive.
        assert data["prompt_tokens"] == 10
        assert data["generated_tokens"] == 5
        assert data["token_budget"] == 1000

    def test_strips_null_bytes_from_stacks(self, pg_conn):
        # Postgres jsonb rejects the NUL escape — a NUL-laden tool result in the
        # stacks would otherwise kill the whole activity-log INSERT (and
        # with it the error visibility for the incident that caused it).
        repo = _repo(pg_conn)
        repo.insert(
            activity_id="act-nul",
            level="error",
            query="q\x00uery",
            stacks=[{"component": "tool", "data": {"result": "pdf\x00junk\x00"}}],
        )
        row = pg_conn.execute(
            text("SELECT query, stacks FROM stack_logs WHERE activity_id = 'act-nul'")
        ).fetchone()
        mapping = dict(row._mapping)
        assert mapping["query"] == "query"
        assert mapping["stacks"][0]["data"]["result"] == "pdfjunk"

    def test_bounds_oversized_strings_in_stacks(self, pg_conn):
        # The 07-17 incident put a 634k-token tool result into stacks
        # whole; long strings must be truncated before insert.
        repo = _repo(pg_conn)
        repo.insert(
            activity_id="act-big",
            level="info",
            stacks=[{"component": "tool", "data": {"result": "x" * 50000}}],
        )
        row = pg_conn.execute(
            text("SELECT stacks FROM stack_logs WHERE activity_id = 'act-big'")
        ).fetchone()
        stored = dict(row._mapping)["stacks"][0]["data"]["result"]
        assert len(stored) <= 10100  # 10k cap plus a short truncation marker

    def test_short_strings_in_stacks_untouched(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(
            activity_id="act-small",
            level="info",
            stacks=[{"component": "tool", "data": {"result": "ok"}}],
        )
        row = pg_conn.execute(
            text("SELECT stacks FROM stack_logs WHERE activity_id = 'act-small'")
        ).fetchone()
        assert dict(row._mapping)["stacks"][0]["data"]["result"] == "ok"


class TestReassignApiKey:
    def test_rewrites_matching_rows_regardless_of_user(self, pg_conn):
        # stack_logs has no agent_id; on key rotation, rows must follow the
        # key. Rows are stamped with the caller's user_id (not the owner),
        # so the migration must NOT be scoped by user_id.
        repo = _repo(pg_conn)
        repo.insert(activity_id="ra-1", api_key="old-k", user_id="owner")
        repo.insert(activity_id="ra-2", api_key="old-k", user_id="a-caller")
        repo.insert(activity_id="ra-3", api_key="other-k", user_id="owner")

        moved = repo.reassign_api_key(old_key="old-k", new_key="new-k")
        assert moved == 2

        assert pg_conn.execute(
            text("SELECT COUNT(*) FROM stack_logs WHERE api_key = 'old-k'")
        ).scalar() == 0
        assert pg_conn.execute(
            text("SELECT COUNT(*) FROM stack_logs WHERE api_key = 'new-k'")
        ).scalar() == 2
        # Unrelated key untouched.
        assert pg_conn.execute(
            text("SELECT COUNT(*) FROM stack_logs WHERE api_key = 'other-k'")
        ).scalar() == 1

    def test_noop_on_blank_keys(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.reassign_api_key(old_key="", new_key="x") == 0
        assert repo.reassign_api_key(old_key="x", new_key="") == 0
