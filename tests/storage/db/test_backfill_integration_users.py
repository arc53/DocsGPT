"""Integration tests for ``_backfill_users`` / ``_backfill_prompts`` /
``_backfill_user_tools`` against an ephemeral Postgres.

These exercise the Mongo→PG shape translations end-to-end: a fake Mongo
(mongomock) is populated with representative docs, the ``_backfill_*``
function under test runs against ``pg_conn``, and the resulting rows are
asserted to carry the translated fields. Each function is also run twice
to validate idempotency (no row duplication) and — where the SQL uses
``DO UPDATE`` — convergence on mutated source data.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mongomock
import pytest
from sqlalchemy import text

# Make ``scripts.db.backfill`` importable (scripts/ isn't on sys.path by default).
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.db.backfill import (  # noqa: E402
    SYSTEM_USER_ID,
    _backfill_prompts,
    _backfill_user_tools,
    _backfill_users,
)


@pytest.fixture
def mongo_db() -> Any:
    """Fresh in-memory Mongo database per test."""
    client = mongomock.MongoClient()
    return client["docsgpt_test"]


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------


class TestBackfillUsers:
    def test_users_happy_shape_merges_agent_preferences(self, pg_conn, mongo_db):
        mongo_db["users"].insert_many(
            [
                {
                    "user_id": "alice",
                    "agent_preferences": {
                        "pinned": ["agent-1"],
                        "theme": "dark",
                    },
                },
                {
                    "user_id": "bob",
                    "agent_preferences": {},
                },
            ]
        )

        stats = _backfill_users(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        assert stats["seen"] == 2
        assert stats["written"] == 2
        assert stats["skipped_no_user_id"] == 0

        rows = pg_conn.execute(
            text(
                "SELECT user_id, agent_preferences FROM users "
                "WHERE user_id IN ('alice', 'bob') ORDER BY user_id"
            )
        ).fetchall()
        assert len(rows) == 2

        alice = rows[0]._mapping
        bob = rows[1]._mapping
        # Unknown top-level prefs (``theme``) survive untouched.
        assert alice["agent_preferences"]["theme"] == "dark"
        assert alice["agent_preferences"]["pinned"] == ["agent-1"]
        # Missing ``shared_with_me`` gets filled to [].
        assert alice["agent_preferences"]["shared_with_me"] == []
        assert bob["agent_preferences"]["pinned"] == []
        assert bob["agent_preferences"]["shared_with_me"] == []

    def test_users_skips_rows_without_user_id(self, pg_conn, mongo_db):
        mongo_db["users"].insert_many(
            [{"user_id": "alice"}, {"agent_preferences": {"pinned": []}}]
        )

        stats = _backfill_users(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        assert stats["seen"] == 2
        assert stats["skipped_no_user_id"] == 1
        assert stats["written"] == 1

    def test_users_rerun_does_not_duplicate(self, pg_conn, mongo_db):
        mongo_db["users"].insert_one(
            {"user_id": "alice", "agent_preferences": {"pinned": ["a-1"]}}
        )

        _backfill_users(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        _backfill_users(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        count = pg_conn.execute(
            text("SELECT count(*) FROM users WHERE user_id = 'alice'")
        ).scalar()
        assert count == 1

    def test_users_rerun_converges_on_mutated_pinned(self, pg_conn, mongo_db):
        mongo_db["users"].insert_one(
            {"user_id": "alice", "agent_preferences": {"pinned": ["a-1"]}}
        )
        _backfill_users(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        # Mutate Mongo.
        mongo_db["users"].update_one(
            {"user_id": "alice"},
            {"$set": {"agent_preferences": {"pinned": ["a-1", "a-2"]}}},
        )
        _backfill_users(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        prefs = pg_conn.execute(
            text("SELECT agent_preferences FROM users WHERE user_id = 'alice'")
        ).scalar()
        assert prefs["pinned"] == ["a-1", "a-2"]


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------


class TestBackfillPrompts:
    def test_prompts_happy_shape(self, pg_conn, mongo_db):
        mongo_db["prompts"].insert_many(
            [
                {
                    "_id": "507f1f77bcf86cd799439011",
                    "user": "alice",
                    "name": "Greet",
                    "content": "Say hi",
                },
                {
                    "_id": "507f1f77bcf86cd799439012",
                    "user": "system",
                    "name": "Template",
                    "content": "Seed",
                },
            ]
        )

        stats = _backfill_prompts(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        assert stats["seen"] == 2
        assert stats["written"] == 2

        rows = pg_conn.execute(
            text(
                "SELECT user_id, name, content, legacy_mongo_id "
                "FROM prompts ORDER BY name"
            )
        ).fetchall()
        assert len(rows) == 2

        greet = rows[0]._mapping
        template = rows[1]._mapping
        assert greet["user_id"] == "alice"
        assert greet["name"] == "Greet"
        assert greet["content"] == "Say hi"
        assert greet["legacy_mongo_id"] == "507f1f77bcf86cd799439011"
        # Legacy ``user="system"`` collapses to the sentinel.
        assert template["user_id"] == SYSTEM_USER_ID

    def test_prompts_rerun_does_not_duplicate(self, pg_conn, mongo_db):
        mongo_db["prompts"].insert_one(
            {
                "_id": "507f1f77bcf86cd799439011",
                "user": "alice",
                "name": "Greet",
                "content": "Say hi",
            }
        )
        _backfill_prompts(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        _backfill_prompts(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        count = pg_conn.execute(
            text(
                "SELECT count(*) FROM prompts WHERE "
                "legacy_mongo_id = '507f1f77bcf86cd799439011'"
            )
        ).scalar()
        assert count == 1

    def test_prompts_rerun_converges_on_content(self, pg_conn, mongo_db):
        mongo_db["prompts"].insert_one(
            {
                "_id": "507f1f77bcf86cd799439011",
                "user": "alice",
                "name": "Greet",
                "content": "v1",
            }
        )
        _backfill_prompts(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        mongo_db["prompts"].update_one(
            {"_id": "507f1f77bcf86cd799439011"},
            {"$set": {"content": "v2"}},
        )
        _backfill_prompts(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        row = pg_conn.execute(
            text(
                "SELECT content FROM prompts WHERE "
                "legacy_mongo_id = '507f1f77bcf86cd799439011'"
            )
        ).scalar()
        assert row == "v2"


# ---------------------------------------------------------------------------
# user_tools
# ---------------------------------------------------------------------------


class TestBackfillUserTools:
    def test_user_tools_nested_values_stringified(self, pg_conn, mongo_db):
        # Use a dict with a datetime-like / non-JSON-native type nested
        # inside config to verify ``default=str`` gets applied.
        mongo_db["user_tools"].insert_one(
            {
                "_id": "507f1f77bcf86cd799439011",
                "user": "alice",
                "name": "calendar",
                "displayName": "Calendar",
                "customName": "My Calendar",
                "description": "cal desc",
                "config": {
                    "api_key": "secret",
                    "expires_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                },
                "configRequirements": {"api_key": {"type": "string"}},
                "actions": [{"name": "create_event"}],
                "status": True,
            }
        )

        _backfill_user_tools(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        row = pg_conn.execute(
            text(
                "SELECT name, custom_name, display_name, description, "
                "config, config_requirements, actions, status "
                "FROM user_tools WHERE legacy_mongo_id = :lid"
            ),
            {"lid": "507f1f77bcf86cd799439011"},
        ).one()._mapping

        assert row["name"] == "calendar"
        assert row["custom_name"] == "My Calendar"
        assert row["display_name"] == "Calendar"
        assert row["description"] == "cal desc"
        assert row["status"] is True
        # Nested config datetime is serialized to a string (default=str).
        assert row["config"]["api_key"] == "secret"
        assert isinstance(row["config"]["expires_at"], str)
        assert row["config_requirements"] == {"api_key": {"type": "string"}}
        assert row["actions"] == [{"name": "create_event"}]

    def test_user_tools_rerun_converges(self, pg_conn, mongo_db):
        mongo_db["user_tools"].insert_one(
            {
                "_id": "507f1f77bcf86cd799439011",
                "user": "alice",
                "name": "cal",
                "config": {"k": "v1"},
            }
        )
        _backfill_user_tools(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        mongo_db["user_tools"].update_one(
            {"_id": "507f1f77bcf86cd799439011"},
            {"$set": {"config": {"k": "v2"}, "description": "new"}},
        )
        _backfill_user_tools(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        rows = pg_conn.execute(
            text(
                "SELECT config, description FROM user_tools "
                "WHERE legacy_mongo_id = '507f1f77bcf86cd799439011'"
            )
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]._mapping["config"] == {"k": "v2"}
        assert rows[0]._mapping["description"] == "new"

    def test_user_tools_rerun_does_not_duplicate(self, pg_conn, mongo_db):
        mongo_db["user_tools"].insert_one(
            {
                "_id": "507f1f77bcf86cd799439011",
                "user": "alice",
                "name": "cal",
            }
        )
        _backfill_user_tools(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        _backfill_user_tools(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        count = pg_conn.execute(
            text(
                "SELECT count(*) FROM user_tools "
                "WHERE legacy_mongo_id = '507f1f77bcf86cd799439011'"
            )
        ).scalar()
        assert count == 1


