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
