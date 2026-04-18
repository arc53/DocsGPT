"""Integration tests for ``_backfill_sources``.

The notable translation here is the optional Mongo ``user`` field: system
seed rows arrive with no ``user`` (or ``user="system"``) and must land
with ``user_id = '__system__'`` in Postgres so the NOT NULL constraint
accepts them.
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
    SYSTEM_USER_ID,
    _backfill_sources,
)


@pytest.fixture
def mongo_db() -> Any:
    client = mongomock.MongoClient()
    return client["docsgpt_test"]


class TestBackfillSources:
    def test_sources_system_rows_get_sentinel_user(self, pg_conn, mongo_db):
        mongo_db["sources"].insert_many(
            [
                {
                    "_id": "555555555555555555555555",
                    "name": "Seed Source",
                    "type": "url",
                    # Intentionally no ``user`` field.
                },
                {
                    "_id": "666666666666666666666666",
                    "user": "alice",
                    "name": "Alice's Upload",
                    "type": "file",
                },
            ]
        )

        stats = _backfill_sources(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        assert stats["seen"] == 2
        assert stats["written"] == 2

        rows = pg_conn.execute(
            text(
                "SELECT user_id, name FROM sources "
                "WHERE legacy_mongo_id IN "
                "('555555555555555555555555', '666666666666666666666666') "
                "ORDER BY name"
            )
        ).fetchall()
        assert len(rows) == 2
        # Alphabetical by name: "Alice's Upload" comes before "Seed Source".
        assert rows[0]._mapping["user_id"] == "alice"
        assert rows[1]._mapping["user_id"] == SYSTEM_USER_ID

    def test_sources_preserves_legacy_fields_under_metadata(
        self, pg_conn, mongo_db
    ):
        mongo_db["sources"].insert_one(
            {
                "_id": "555555555555555555555555",
                "user": "alice",
                "name": "s1",
                "type": "url",
                "status": "ingested",  # legacy ingestion field
                "reason": None,
            }
        )
        _backfill_sources(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        meta = pg_conn.execute(
            text(
                "SELECT metadata FROM sources "
                "WHERE legacy_mongo_id = '555555555555555555555555'"
            )
        ).scalar()
        assert meta["legacy_fields"]["status"] == "ingested"

    def test_sources_rerun_does_not_duplicate(self, pg_conn, mongo_db):
        mongo_db["sources"].insert_one(
            {
                "_id": "555555555555555555555555",
                "user": "alice",
                "name": "s1",
                "type": "url",
            }
        )
        _backfill_sources(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        _backfill_sources(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        count = pg_conn.execute(
            text(
                "SELECT count(*) FROM sources "
                "WHERE legacy_mongo_id = '555555555555555555555555'"
            )
        ).scalar()
        assert count == 1

    def test_sources_rerun_converges_on_name(self, pg_conn, mongo_db):
        mongo_db["sources"].insert_one(
            {
                "_id": "555555555555555555555555",
                "user": "alice",
                "name": "old-name",
                "type": "url",
            }
        )
        _backfill_sources(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )
        mongo_db["sources"].update_one(
            {"_id": "555555555555555555555555"},
            {"$set": {"name": "new-name"}},
        )
        _backfill_sources(
            conn=pg_conn, mongo_db=mongo_db, batch_size=100, dry_run=False
        )

        name = pg_conn.execute(
            text(
                "SELECT name FROM sources "
                "WHERE legacy_mongo_id = '555555555555555555555555'"
            )
        ).scalar()
        assert name == "new-name"
