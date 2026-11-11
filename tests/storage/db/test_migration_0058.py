"""Continuation wakes survive an idempotent migration round trip."""

import importlib
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from docsgpt.storage.db.repositories.conversation_wakes import ConversationWakesRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository


def test_round_trip_keeps_the_wake(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0058_continuation_wakes")
    conv = ConversationsRepository(pg_conn).create("u", "round")
    repo = ConversationWakesRepository(pg_conn)
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        row = repo.enqueue(user_id="u", conversation_id=str(conv["id"]), source="continuation", dedupe_key="round")
        migration.downgrade()
        migration.downgrade()
        assert repo.get(str(row["id"]))["source"] == "approval"
        migration.upgrade()
        assert pg_conn.execute(text("SELECT count(*) FROM conversation_wakes")).scalar() == 1
