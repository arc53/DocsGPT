"""``scripts/db/backfill.py`` main(): schema bootstrap and Mongo database selection.

Runs without MongoDB or Postgres: ``pymongo`` and the engine are replaced by mocks.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make the backfill module importable (scripts/ isn't on sys.path by default).
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.db import backfill  # noqa: E402


@pytest.fixture
def wired(monkeypatch):
    """Point main() at fake Mongo and Postgres and record the order of the setup steps."""
    calls: list[str] = []
    client = MagicMock()
    fake_pymongo = types.SimpleNamespace(MongoClient=MagicMock(return_value=client))
    monkeypatch.setitem(sys.modules, "pymongo", fake_pymongo)
    monkeypatch.setattr(backfill.settings, "POSTGRES_URI", "postgresql://docsgpt@localhost/docsgpt")
    monkeypatch.setattr(backfill.settings, "MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setattr(backfill.settings, "AUTO_CREATE_DB", True)
    monkeypatch.setattr(backfill.settings, "AUTO_MIGRATE", True)
    ensure = MagicMock(side_effect=lambda *a, **k: calls.append("ensure_database_ready"))
    monkeypatch.setattr(backfill, "ensure_database_ready", ensure)
    monkeypatch.setattr(backfill, "_ensure_system_user", lambda conn: calls.append("system_user"))
    monkeypatch.setattr(backfill, "get_engine", MagicMock())
    table = MagicMock(return_value={"seen": 0})
    monkeypatch.setattr(backfill, "BACKFILLERS", {"users": table})
    return types.SimpleNamespace(calls=calls, ensure=ensure, client=client, table=table)


class TestSchemaBootstrap:
    def test_migrates_before_writing(self, wired):
        """A fresh database has no tables; the copy must not fail with ``relation does not exist``."""
        assert backfill.main([]) == 0
        assert wired.calls == ["ensure_database_ready", "system_user"]
        assert wired.ensure.call_args.args[0] == "postgresql://docsgpt@localhost/docsgpt"
        assert wired.ensure.call_args.kwargs == {"create_db": True, "migrate": True, "logger": backfill.logger}

    def test_follows_the_app_settings(self, wired, monkeypatch):
        """Operators who manage the schema themselves (AUTO_MIGRATE=false) keep control of it."""
        monkeypatch.setattr(backfill.settings, "AUTO_CREATE_DB", False)
        monkeypatch.setattr(backfill.settings, "AUTO_MIGRATE", False)
        assert backfill.main([]) == 0
        assert wired.ensure.call_args.kwargs["create_db"] is False
        assert wired.ensure.call_args.kwargs["migrate"] is False

    def test_dry_run_changes_nothing(self, wired):
        assert backfill.main(["--dry-run"]) == 0
        wired.ensure.assert_not_called()
        assert wired.calls == []


class TestMongoDatabase:
    def test_defaults_to_docsgpt(self, wired):
        assert backfill.main(["--dry-run"]) == 0
        wired.client.__getitem__.assert_called_once_with("docsgpt")

    def test_mongo_db_flag_selects_another_database(self, wired):
        assert backfill.main(["--dry-run", "--mongo-db", "legacy"]) == 0
        wired.client.__getitem__.assert_called_once_with("legacy")
