"""Integration tests for ``_backfill_conversations`` +
``_backfill_conversation_messages`` flattening and attachment FK
resolution.

The conversations backfill does two things the other backfillers don't:
1. It flattens Mongo's nested ``queries[]`` array into rows in a child
   table (``conversation_messages``), with ``position`` = array index.
2. It resolves attachment refs (strings pointing to Mongo ObjectIds) to
   Postgres UUIDs via a ``legacy_mongo_id`` lookup. Unresolvable refs are
   dropped rather than crashing the whole batch.

These are the two bits we assert below, alongside the standard
happy-shape / idempotency / convergence checks.
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
    _backfill_attachments,
    _backfill_conversations,
)


@pytest.fixture
def mongo_db() -> Any:
    client = mongomock.MongoClient()
    return client["docsgpt_test"]


# ---------------------------------------------------------------------------
# attachments — prerequisite for conversations (DBRef→UUID via legacy map)
# ---------------------------------------------------------------------------


class TestBackfillAttachments:
    def test_attachments_happy_shape_preserves_mime_and_size(
        self, pg_conn, mongo_db
    ):
        mongo_db["attachments"].insert_one(
            {
                "_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
                "user": "alice",
                "filename": "report.pdf",
                # Worker writes the blob path as ``path``; the PG column is
                # ``upload_path``. If the backfill ever reads the wrong key,
                # this test will fail with an empty string.
                "path": "uploads/alice/report.pdf",
                "mime_type": "application/pdf",
                "size": 12345,
                "content": "extracted text",
                "token_count": 42,
            }
        )

        _backfill_attachments(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        row = pg_conn.execute(
            text(
                "SELECT filename, upload_path, mime_type, size, "
                "content, token_count, legacy_mongo_id "
                "FROM attachments WHERE user_id = 'alice'"
            )
        ).one()._mapping
        assert row["filename"] == "report.pdf"
        assert row["upload_path"] == "uploads/alice/report.pdf"
        assert row["mime_type"] == "application/pdf"
        assert row["size"] == 12345
        assert row["content"] == "extracted text"
        assert row["token_count"] == 42
        assert row["legacy_mongo_id"] == "aaaaaaaaaaaaaaaaaaaaaaaa"

    def test_attachments_rerun_does_not_duplicate(self, pg_conn, mongo_db):
        mongo_db["attachments"].insert_one(
            {
                "_id": "aaaaaaaaaaaaaaaaaaaaaaaa",
                "user": "alice",
                "filename": "r.pdf",
                "path": "u/alice/r.pdf",
            }
        )
        _backfill_attachments(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        _backfill_attachments(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        count = pg_conn.execute(
            text(
                "SELECT count(*) FROM attachments "
                "WHERE legacy_mongo_id = 'aaaaaaaaaaaaaaaaaaaaaaaa'"
            )
        ).scalar()
        assert count == 1


# ---------------------------------------------------------------------------
# conversations + conversation_messages
# ---------------------------------------------------------------------------


def _seed_attachment(mongo_db: Any, _id: str, user: str = "alice") -> None:
    mongo_db["attachments"].insert_one(
        {
            "_id": _id,
            "user": user,
            "filename": f"{_id}.txt",
            "path": f"uploads/{user}/{_id}.txt",
        }
    )


class TestBackfillConversations:
    def test_conversations_flattens_queries_into_messages(
        self, pg_conn, mongo_db
    ):
        _seed_attachment(mongo_db, "aaaaaaaaaaaaaaaaaaaaaaa1")
        _backfill_attachments(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        mongo_db["conversations"].insert_one(
            {
                "_id": "cccccccccccccccccccccccc",
                "user": "alice",
                "name": "chat-1",
                "queries": [
                    {
                        "prompt": "hello",
                        "response": "hi",
                        "attachments": ["aaaaaaaaaaaaaaaaaaaaaaa1"],
                    },
                    {
                        "prompt": "how are you",
                        "response": "fine",
                    },
                ],
            }
        )

        stats = _backfill_conversations(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        assert stats["seen"] == 1
        assert stats["written"] == 1
        assert stats["messages_written"] == 2

        conv_id = pg_conn.execute(
            text(
                "SELECT id FROM conversations "
                "WHERE legacy_mongo_id = 'cccccccccccccccccccccccc'"
            )
        ).scalar()

        rows = pg_conn.execute(
            text(
                "SELECT position, prompt, response, attachments "
                "FROM conversation_messages WHERE conversation_id = :cid "
                "ORDER BY position"
            ),
            {"cid": str(conv_id)},
        ).fetchall()
        assert [r._mapping["position"] for r in rows] == [0, 1]
        assert rows[0]._mapping["prompt"] == "hello"
        assert rows[1]._mapping["response"] == "fine"
        # Attachment ObjectId string was mapped to the PG UUID.
        resolved = rows[0]._mapping["attachments"]
        assert len(resolved) == 1
        pg_att_id = pg_conn.execute(
            text(
                "SELECT id FROM attachments "
                "WHERE legacy_mongo_id = 'aaaaaaaaaaaaaaaaaaaaaaa1'"
            )
        ).scalar()
        assert str(resolved[0]) == str(pg_att_id)

    def test_conversations_drops_unresolved_attachments(
        self, pg_conn, mongo_db
    ):
        mongo_db["conversations"].insert_one(
            {
                "_id": "cccccccccccccccccccccccc",
                "user": "alice",
                "queries": [
                    {
                        "prompt": "hi",
                        # Unknown attachment objectid — not present in PG.
                        "attachments": ["bbbbbbbbbbbbbbbbbbbbbbb0"],
                    }
                ],
            }
        )
        stats = _backfill_conversations(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        assert stats["unresolved_attachment_refs"] == 1
        row = pg_conn.execute(
            text(
                "SELECT attachments FROM conversation_messages "
                "WHERE position = 0"
            )
        ).one()._mapping
        assert list(row["attachments"]) == []

    def test_conversations_rerun_does_not_double_messages(
        self, pg_conn, mongo_db
    ):
        mongo_db["conversations"].insert_one(
            {
                "_id": "cccccccccccccccccccccccc",
                "user": "alice",
                "queries": [
                    {"prompt": "a", "response": "1"},
                    {"prompt": "b", "response": "2"},
                ],
            }
        )
        _backfill_conversations(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        _backfill_conversations(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        conv_count = pg_conn.execute(
            text(
                "SELECT count(*) FROM conversations "
                "WHERE legacy_mongo_id = 'cccccccccccccccccccccccc'"
            )
        ).scalar()
        msg_count = pg_conn.execute(
            text(
                "SELECT count(*) FROM conversation_messages "
                "WHERE conversation_id = ("
                "  SELECT id FROM conversations "
                "  WHERE legacy_mongo_id = 'cccccccccccccccccccccccc'"
                ")"
            )
        ).scalar()
        assert conv_count == 1
        assert msg_count == 2

    def test_conversations_rerun_truncates_removed_tail_messages(
        self, pg_conn, mongo_db
    ):
        # First run: 3 messages. Then Mongo truncates to 1. Second run
        # should drop positions 1 and 2.
        mongo_db["conversations"].insert_one(
            {
                "_id": "cccccccccccccccccccccccc",
                "user": "alice",
                "queries": [
                    {"prompt": "a", "response": "1"},
                    {"prompt": "b", "response": "2"},
                    {"prompt": "c", "response": "3"},
                ],
            }
        )
        _backfill_conversations(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        mongo_db["conversations"].update_one(
            {"_id": "cccccccccccccccccccccccc"},
            {"$set": {"queries": [{"prompt": "a", "response": "1-updated"}]}},
        )
        _backfill_conversations(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        rows = pg_conn.execute(
            text(
                "SELECT position, response FROM conversation_messages "
                "WHERE conversation_id = ("
                "  SELECT id FROM conversations "
                "  WHERE legacy_mongo_id = 'cccccccccccccccccccccccc'"
                ") ORDER BY position"
            )
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]._mapping["response"] == "1-updated"
