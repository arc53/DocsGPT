"""Workflow retry defaults survive an idempotent migration round trip."""

import importlib
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from docsgpt.storage.db.repositories.workflows import WorkflowsRepository


def test_round_trip_adds_and_drops_the_column(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0059_workflow_retry_defaults")
    repo = WorkflowsRepository(pg_conn)
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        row = repo.create("u", "wf", retry_defaults={"max_attempts": 2})
        assert repo.get(str(row["id"]), "u")["retry_defaults"] == {"max_attempts": 2}
        migration.downgrade()
        migration.downgrade()
        assert "retry_defaults" not in repo.get(str(row["id"]), "u")
        migration.upgrade()
        assert pg_conn.execute(text("SELECT count(*) FROM workflows")).scalar() == 1
