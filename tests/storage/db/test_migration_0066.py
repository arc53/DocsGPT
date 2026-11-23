"""``sources.sync_manifest`` survives an idempotent migration round trip."""

import importlib
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from docsgpt.storage.db.repositories.sources import SourcesRepository


def _has_column(conn) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'sources' AND column_name = 'sync_manifest'"
    )).scalar())


def test_round_trip_adds_then_drops_the_column(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0066_source_sync_manifest")
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        repo = SourcesRepository(pg_conn)
        src = repo.create("docs", user_id="u")
        assert src["sync_manifest"] is None
        repo.update(str(src["id"]), "u", {"sync_manifest": {"version": 1, "generation": "g", "files": {}}})
        assert repo.get(str(src["id"]), "u")["sync_manifest"]["generation"] == "g"

        migration.downgrade()
        migration.downgrade()
        assert not _has_column(pg_conn)

        migration.upgrade()
        assert _has_column(pg_conn)
        assert repo.get(str(src["id"]), "u")["sync_manifest"] is None
