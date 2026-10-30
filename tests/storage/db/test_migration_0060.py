"""Agent prompt presets survive an idempotent migration round trip."""

import importlib
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from docsgpt.storage.db.repositories.agents import AgentsRepository


def _columns(conn) -> set:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'agents'")
        )
    }


def test_round_trip_adds_and_drops_the_preset(pg_conn):
    migration = importlib.import_module("docsgpt.alembic.versions.0060_agent_prompt_preset")
    repo = AgentsRepository(pg_conn)
    with patch.object(migration, "op", Operations(MigrationContext.configure(pg_conn))):
        migration.upgrade()
        migration.upgrade()
        row = repo.create("u", "a", "draft", prompt_id="creative")
        assert repo.get(str(row["id"]), "u")["prompt_id"] == "creative"
        with pytest.raises(IntegrityError), pg_conn.begin_nested():
            pg_conn.execute(text("UPDATE agents SET prompt_preset = 'bogus'"))
        migration.downgrade()
        migration.downgrade()
        assert "prompt_preset" not in _columns(pg_conn)
        # The agent survives on the default prompt.
        assert repo.get(str(row["id"]), "u")["prompt_id"] is None
        migration.upgrade()
        assert "prompt_preset" in _columns(pg_conn)
        assert pg_conn.execute(text("SELECT count(*) FROM agents")).scalar() == 1
