"""``parsed_files`` survives an idempotent migration round trip."""

import importlib
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from docsgpt.storage.db.repositories.parsed_files import ParsedFilesRepository


def _has_table(conn) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = 'parsed_files'"
    )).scalar())


def test_round_trip_creates_then_drops_the_table(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0067_parsed_files")
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        repo = ParsedFilesRepository(pg_conn)
        repo.store("u", "sha", "key", content=["a", "b"])
        assert repo.find("u", "sha", "key")["content"] == ["a", "b"]
        triggers = set(pg_conn.execute(text(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = 'parsed_files'::regclass AND NOT tgisinternal"
        )).scalars())
        assert "parsed_files_ensure_user" in triggers

        migration.downgrade()
        migration.downgrade()
        assert not _has_table(pg_conn)

        migration.upgrade()
        assert _has_table(pg_conn)
        assert repo.find("u", "sha", "key") is None
