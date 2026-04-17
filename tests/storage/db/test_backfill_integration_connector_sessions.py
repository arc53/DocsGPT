"""Integration tests for ``_backfill_connector_sessions``.

Mongo routinely contains multiple rows for the same
``(user_id, server_url, provider)`` triple — each OAuth-button click
inserts a pending row and only the last one is authorized. The Postgres
schema has a unique index on that triple, so the backfill does a Python-
side dedup *before* the insert, preferring authorized rows over pending
ones and newer ``created_at`` over older.

This test seeds exactly that shape and asserts the dedup keeps the
authorized row.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mongomock
import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.db.backfill import _backfill_connector_sessions  # noqa: E402


@pytest.fixture
def mongo_db() -> Any:
    client = mongomock.MongoClient()
    return client["docsgpt_test"]


class TestBackfillConnectorSessions:
    def test_dedups_authorized_over_pending(self, pg_conn, mongo_db):
        # Two rows, same (user, server_url, provider) triple. The pending
        # row was inserted first; the authorized row was inserted later
        # when the OAuth redirect completed. Dedup should keep the
        # authorized one (has ``token_info``).
        mongo_db["connector_sessions"].insert_many(
            [
                {
                    "_id": "777777777777777777777771",
                    "user_id": "alice",
                    "provider": "google_drive",
                    "server_url": "https://drive.google.com",
                    "status": "pending",
                    "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                },
                {
                    "_id": "777777777777777777777772",
                    "user_id": "alice",
                    "provider": "google_drive",
                    "server_url": "https://drive.google.com",
                    "status": "authorized",
                    "token_info": {"access_token": "xyz"},
                    "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
                },
            ]
        )

        stats = _backfill_connector_sessions(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        assert stats["seen"] == 2
        assert stats["written"] == 1
        assert stats["skipped"] == 1

        rows = pg_conn.execute(
            text(
                "SELECT status, legacy_mongo_id, token_info FROM "
                "connector_sessions WHERE user_id = 'alice'"
            )
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]._mapping["status"] == "authorized"
        assert rows[0]._mapping["legacy_mongo_id"] == "777777777777777777777772"
        assert rows[0]._mapping["token_info"] == {"access_token": "xyz"}

    def test_dedups_newer_created_at_when_both_pending(self, pg_conn, mongo_db):
        # Both rows are pending. Newer created_at wins.
        mongo_db["connector_sessions"].insert_many(
            [
                {
                    "_id": "777777777777777777777771",
                    "user_id": "alice",
                    "provider": "github",
                    "server_url": "",
                    "status": "pending",
                    "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                },
                {
                    "_id": "777777777777777777777772",
                    "user_id": "alice",
                    "provider": "github",
                    "server_url": "",
                    "status": "pending",
                    "created_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                },
            ]
        )

        _backfill_connector_sessions(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        rows = pg_conn.execute(
            text(
                "SELECT legacy_mongo_id FROM connector_sessions "
                "WHERE user_id = 'alice' AND provider = 'github'"
            )
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]._mapping["legacy_mongo_id"] == "777777777777777777777772"

    def test_rerun_does_not_duplicate(self, pg_conn, mongo_db):
        mongo_db["connector_sessions"].insert_one(
            {
                "_id": "777777777777777777777771",
                "user_id": "alice",
                "provider": "google_drive",
                "server_url": "https://drive.google.com",
                "status": "authorized",
                "token_info": {"access_token": "xyz"},
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }
        )
        _backfill_connector_sessions(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        _backfill_connector_sessions(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        count = pg_conn.execute(
            text(
                "SELECT count(*) FROM connector_sessions "
                "WHERE legacy_mongo_id = '777777777777777777777771'"
            )
        ).scalar()
        assert count == 1

    def test_skips_rows_without_user_or_provider(self, pg_conn, mongo_db):
        mongo_db["connector_sessions"].insert_many(
            [
                {
                    "_id": "777777777777777777777771",
                    "provider": "github",  # no user
                },
                {
                    "_id": "777777777777777777777772",
                    "user_id": "alice",  # no provider
                },
            ]
        )
        stats = _backfill_connector_sessions(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        assert stats["seen"] == 2
        assert stats["written"] == 0
        assert stats["skipped"] == 2
