"""Integration tests for the per-tool-child collections: todos, notes,
and memories.

These all depend on ``user_tools`` having been backfilled first, because
:func:`scripts.db.backfill._build_tool_id_map` joins Mongo
``user_tools._id`` to Postgres ``user_tools.id`` via ``(user_id, name)``.
Each test seeds a single tool row to keep fixtures minimal.

Memories are the odd one out: the SQL uses ``ON CONFLICT DO NOTHING`` and
the table has no ``legacy_mongo_id`` column, so a re-run can't converge
on mutated content. The negative test locks in the current behavior so a
future fix (adding ``legacy_mongo_id`` + DO UPDATE, tracked in
``migration-postgres.md``) will flip the assertion.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import mongomock
import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.db.backfill import (  # noqa: E402
    _backfill_memories,
    _backfill_notes,
    _backfill_todos,
    _backfill_user_tools,
)


_TOOL_MONGO_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def mongo_db() -> Any:
    client = mongomock.MongoClient()
    return client["docsgpt_test"]


@pytest.fixture
def seeded_tool(pg_conn, mongo_db) -> str:
    """Seed one tool in both Mongo and Postgres and return its PG UUID.

    Having a user_tools row on both sides is a prerequisite for every
    backfill function in this file — ``_build_tool_id_map`` needs it to
    resolve ``tool_id`` FKs.
    """
    mongo_db["user_tools"].insert_one(
        {
            "_id": _TOOL_MONGO_ID,
            "user": "alice",
            "name": "my-tool",
        }
    )
    _backfill_user_tools(
        conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
    )
    return str(
        pg_conn.execute(
            text("SELECT id FROM user_tools WHERE legacy_mongo_id = :lid"),
            {"lid": _TOOL_MONGO_ID},
        ).scalar()
    )


# ---------------------------------------------------------------------------
# todos
# ---------------------------------------------------------------------------


class TestBackfillTodos:
    def test_todos_status_completed_translation(self, pg_conn, mongo_db, seeded_tool):
        # Two todos: one "open", one "completed". Asserts the Mongo
        # ``status`` string is translated to the PG ``completed`` bool.
        mongo_db["todos"].insert_many(
            [
                {
                    "_id": "111111111111111111111111",
                    "user_id": "alice",
                    "tool_id": _TOOL_MONGO_ID,
                    "todo_id": 1,
                    "title": "Write tests",
                    "status": "open",
                },
                {
                    "_id": "222222222222222222222222",
                    "user_id": "alice",
                    "tool_id": _TOOL_MONGO_ID,
                    "todo_id": 2,
                    "title": "Ship it",
                    "status": "completed",
                },
            ]
        )

        stats = _backfill_todos(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        assert stats["seen"] == 2
        assert stats["written"] == 2

        rows = pg_conn.execute(
            text(
                "SELECT todo_id, title, completed, legacy_mongo_id FROM todos "
                "WHERE user_id = 'alice' ORDER BY todo_id"
            )
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]._mapping["todo_id"] == 1
        assert rows[0]._mapping["completed"] is False
        assert rows[1]._mapping["todo_id"] == 2
        assert rows[1]._mapping["completed"] is True
        # legacy_mongo_id preserved for idempotency on re-run.
        assert rows[0]._mapping["legacy_mongo_id"] == "111111111111111111111111"

    def test_todos_legacy_fields_stashed_in_metadata(
        self, pg_conn, mongo_db, seeded_tool
    ):
        # Legacy top-level ``conversation_id`` field should survive under
        # metadata.legacy_fields.
        mongo_db["todos"].insert_one(
            {
                "_id": "111111111111111111111111",
                "user_id": "alice",
                "tool_id": _TOOL_MONGO_ID,
                "title": "t",
                "status": "open",
                "conversation_id": "abc-legacy",
            }
        )
        _backfill_todos(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        meta = pg_conn.execute(
            text("SELECT metadata FROM todos WHERE legacy_mongo_id = :lid"),
            {"lid": "111111111111111111111111"},
        ).scalar()
        assert meta["legacy_fields"]["conversation_id"] == "abc-legacy"

    def test_todos_rerun_does_not_duplicate(self, pg_conn, mongo_db, seeded_tool):
        mongo_db["todos"].insert_one(
            {
                "_id": "111111111111111111111111",
                "user_id": "alice",
                "tool_id": _TOOL_MONGO_ID,
                "todo_id": 1,
                "title": "t",
                "status": "open",
            }
        )
        _backfill_todos(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        _backfill_todos(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        count = pg_conn.execute(
            text(
                "SELECT count(*) FROM todos "
                "WHERE legacy_mongo_id = '111111111111111111111111'"
            )
        ).scalar()
        assert count == 1

    def test_todos_rerun_converges_on_status_and_title(
        self, pg_conn, mongo_db, seeded_tool
    ):
        mongo_db["todos"].insert_one(
            {
                "_id": "111111111111111111111111",
                "user_id": "alice",
                "tool_id": _TOOL_MONGO_ID,
                "todo_id": 1,
                "title": "Old title",
                "status": "open",
            }
        )
        _backfill_todos(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        mongo_db["todos"].update_one(
            {"_id": "111111111111111111111111"},
            {"$set": {"status": "completed", "title": "Done title"}},
        )
        _backfill_todos(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        row = pg_conn.execute(
            text(
                "SELECT title, completed FROM todos "
                "WHERE legacy_mongo_id = '111111111111111111111111'"
            )
        ).one()._mapping
        assert row["title"] == "Done title"
        assert row["completed"] is True


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------


class TestBackfillNotes:
    def test_notes_translates_note_to_content(
        self, pg_conn, mongo_db, seeded_tool
    ):
        mongo_db["notes"].insert_one(
            {
                "_id": "333333333333333333333333",
                "user_id": "alice",
                "tool_id": _TOOL_MONGO_ID,
                "note": "hello world",
                # No explicit title — backfill should fall back to "note".
            }
        )
        _backfill_notes(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        row = pg_conn.execute(
            text(
                "SELECT title, content, legacy_mongo_id FROM notes "
                "WHERE user_id = 'alice'"
            )
        ).one()._mapping
        assert row["content"] == "hello world"
        assert row["title"] == "note"
        # legacy_mongo_id column landed recently — lock in its presence.
        assert row["legacy_mongo_id"] == "333333333333333333333333"

    def test_notes_uses_title_when_present(self, pg_conn, mongo_db, seeded_tool):
        mongo_db["notes"].insert_one(
            {
                "_id": "333333333333333333333333",
                "user_id": "alice",
                "tool_id": _TOOL_MONGO_ID,
                "title": "My title",
                "content": "direct content",
            }
        )
        _backfill_notes(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        row = pg_conn.execute(
            text("SELECT title, content FROM notes WHERE user_id = 'alice'")
        ).one()._mapping
        assert row["title"] == "My title"
        assert row["content"] == "direct content"

    def test_notes_rerun_converges_on_content(
        self, pg_conn, mongo_db, seeded_tool
    ):
        mongo_db["notes"].insert_one(
            {
                "_id": "333333333333333333333333",
                "user_id": "alice",
                "tool_id": _TOOL_MONGO_ID,
                "note": "v1",
            }
        )
        _backfill_notes(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        mongo_db["notes"].update_one(
            {"_id": "333333333333333333333333"},
            {"$set": {"note": "v2"}},
        )
        _backfill_notes(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        rows = pg_conn.execute(
            text(
                "SELECT content FROM notes "
                "WHERE legacy_mongo_id = '333333333333333333333333'"
            )
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]._mapping["content"] == "v2"


# ---------------------------------------------------------------------------
# memories
# ---------------------------------------------------------------------------


class TestBackfillMemories:
    def test_memories_happy_shape(self, pg_conn, mongo_db, seeded_tool):
        mongo_db["memories"].insert_one(
            {
                "_id": "444444444444444444444444",
                "user_id": "alice",
                "tool_id": _TOOL_MONGO_ID,
                "path": "/foo",
                "content": "memory body",
            }
        )
        _backfill_memories(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        row = pg_conn.execute(
            text("SELECT path, content FROM memories WHERE user_id = 'alice'")
        ).one()._mapping
        assert row["path"] == "/foo"
        assert row["content"] == "memory body"

    def test_memories_rerun_does_not_duplicate(
        self, pg_conn, mongo_db, seeded_tool
    ):
        # The unique index is (user_id, tool_id, path). Same-row re-insert
        # is expected to be a no-op because the SQL uses DO NOTHING.
        mongo_db["memories"].insert_one(
            {
                "_id": "444444444444444444444444",
                "user_id": "alice",
                "tool_id": _TOOL_MONGO_ID,
                "path": "/foo",
                "content": "v1",
            }
        )
        _backfill_memories(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        _backfill_memories(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        count = pg_conn.execute(
            text(
                "SELECT count(*) FROM memories "
                "WHERE user_id = 'alice' AND path = '/foo'"
            )
        ).scalar()
        assert count == 1

    def test_memories_rerun_does_not_converge_content(
        self, pg_conn, mongo_db, seeded_tool
    ):
        # KNOWN non-idempotent behavior: memories have no legacy_mongo_id
        # column and the SQL uses ``ON CONFLICT DO NOTHING`` rather than
        # DO UPDATE. A content change in Mongo is NOT reflected in PG on
        # re-run. See migration-postgres.md for the tracked fix. When the
        # backfill gains a legacy_mongo_id column + DO UPDATE branch,
        # flip this assertion to assert the new content wins.
        mongo_db["memories"].insert_one(
            {
                "_id": "444444444444444444444444",
                "user_id": "alice",
                "tool_id": _TOOL_MONGO_ID,
                "path": "/foo",
                "content": "original",
            }
        )
        _backfill_memories(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        mongo_db["memories"].update_one(
            {"_id": "444444444444444444444444"},
            {"$set": {"content": "updated"}},
        )
        _backfill_memories(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        content = pg_conn.execute(
            text(
                "SELECT content FROM memories "
                "WHERE user_id = 'alice' AND path = '/foo'"
            )
        ).scalar()
        # Lock in the non-convergent behavior.
        assert content == "original"
