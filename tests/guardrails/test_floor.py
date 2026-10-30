"""The floor stored in ``app_metadata``: the per-process cache, the one-time import of ``GUARDRAILS_FLOOR``."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager

import pytest

from docsgpt.core.settings import settings
from docsgpt.guardrails import floor
from docsgpt.guardrails.config import GuardrailsConfig
from docsgpt.guardrails.runtime import resolve_config
from docsgpt.guardrails.types import Action, Stage
from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository

SECRETS = {"check": "secrets", "stage": "output", "action": "redact"}
FLOOR = {"enabled": True, "mode": "scan_all", "controls": [SECRETS]}
DENYLIST = {"check": "denylist", "stage": "input", "action": "block", "settings": {"terms": ["raven"]}}


@contextmanager
def _yielding(conn):
    yield conn


@pytest.fixture
def db(pg_conn, monkeypatch):
    """The floor module reads and writes the test database, through a cache that starts empty."""
    reads = []

    @contextmanager
    def readonly():
        reads.append(1)
        yield pg_conn

    monkeypatch.setattr(floor, "db_readonly", readonly)
    monkeypatch.setattr(floor, "db_session", lambda: _yielding(pg_conn))
    floor.invalidate()
    pg_conn.reads = reads
    return pg_conn


@pytest.fixture
def clock(monkeypatch):
    """A monotonic clock the test moves by hand."""
    now = [1000.0]
    monkeypatch.setattr(floor.time, "monotonic", lambda: now[0])
    return now


def _store(conn, value):
    floor.save(conn, GuardrailsConfig.model_validate(value) if value is not None else None)


@pytest.mark.unit
class TestStorage:
    def test_nothing_stored_is_no_floor(self, db):
        assert floor.stored(db) is None and floor.current() is None

    def test_a_saved_floor_is_read_back_normalised(self, db):
        _store(db, FLOOR)
        assert floor.stored(db) == GuardrailsConfig.model_validate(FLOOR).model_dump(mode="json")
        floor.invalidate()
        assert [c.check for c in floor.current().controls] == ["secrets"]

    def test_clearing_stores_null_so_the_key_stays(self, db):
        _store(db, FLOOR)
        _store(db, None)
        assert floor.stored(db) is None and AppMetadataRepository(db).get(floor.KEY) == "null"
        floor.invalidate()
        assert floor.current() is None

    def test_a_floor_that_is_not_enabled_applies_to_nothing(self, db):
        _store(db, {**FLOOR, "enabled": False})
        floor.invalidate()
        assert floor.current() is None

    def test_a_control_this_instance_no_longer_allows_is_dropped_alone(self, db, monkeypatch):
        _store(db, {**FLOOR, "controls": [SECRETS, DENYLIST]})
        monkeypatch.setattr(settings, "GUARDRAILS_CHECKS_ENABLED", ["denylist"])
        floor.invalidate()
        assert [c.check for c in floor.current().controls] == ["denylist"]

    def test_the_mcp_warnings_toggle_is_off_until_stored(self, db):
        assert floor.mcp_description_warnings(db) is False
        floor.set_mcp_description_warnings(db, True)
        assert floor.mcp_description_warnings(db) is True
        floor.set_mcp_description_warnings(db, False)
        assert floor.mcp_description_warnings(db) is False


@pytest.mark.unit
class TestCache:
    def test_reads_once_per_ttl(self, db, clock):
        _store(db, FLOOR)
        for _ in range(5):
            assert floor.current() is not None
        assert len(db.reads) == 1
        clock[0] += floor.TTL_SECONDS + 1
        floor.current()
        assert len(db.reads) == 2

    def test_another_process_picks_a_change_up_within_the_ttl(self, db, clock):
        """A write elsewhere does not invalidate this process: the TTL bounds how long it keeps the old floor."""
        assert floor.current() is None
        AppMetadataRepository(db).set(floor.KEY, json.dumps(FLOOR))
        clock[0] += floor.TTL_SECONDS - 1
        assert floor.current() is None
        clock[0] += 2
        assert floor.current() is not None

    def test_the_writing_process_sees_its_write_at_once(self, db, clock):
        assert floor.current() is None
        _store(db, FLOOR)
        floor.invalidate()
        assert floor.current() is not None

    def test_a_read_failure_keeps_the_last_floor_without_retrying_every_turn(self, db, clock, monkeypatch, caplog):
        _store(db, FLOOR)
        assert floor.current() is not None
        attempts = []

        @contextmanager
        def down():
            attempts.append(1)
            raise ConnectionError("database down")
            yield  # pragma: no cover

        monkeypatch.setattr(floor, "db_readonly", down)
        clock[0] += floor.TTL_SECONDS + 1
        with caplog.at_level(logging.WARNING):
            assert [c.check for c in floor.current().controls] == ["secrets"]
            assert floor.current() is not None
        assert len(attempts) == 1 and "floor last read" in caplog.text

    def test_the_floor_is_enforced_from_the_store(self, db):
        _store(db, {"enabled": True, "mode": "scan_all", "controls": [DENYLIST]})
        floor.invalidate()
        config = resolve_config({})
        assert config.enabled and config.controls_for(Stage.INPUT)[0].action is Action.BLOCK


@pytest.mark.unit
class TestImport:
    def test_env_only_is_stored_once_with_a_deprecation_warning(self, db, monkeypatch, caplog):
        monkeypatch.setattr(settings, "GUARDRAILS_FLOOR", FLOOR)
        with caplog.at_level(logging.WARNING):
            floor.import_env_floor()
        assert floor.stored(db) == GuardrailsConfig.model_validate(FLOOR).model_dump(mode="json")
        assert "GUARDRAILS_FLOOR is deprecated" in caplog.text and "Admin > Guardrails" in caplog.text
        assert floor.current() is not None

    def test_stored_only_changes_nothing_and_says_nothing(self, db, caplog):
        _store(db, FLOOR)
        before = AppMetadataRepository(db).get(floor.KEY)
        with caplog.at_level(logging.WARNING):
            floor.import_env_floor()
        assert AppMetadataRepository(db).get(floor.KEY) == before and caplog.text == ""

    @pytest.mark.parametrize("stored", [FLOOR, None])
    def test_with_both_the_stored_floor_wins_and_the_env_is_ignored(self, db, monkeypatch, caplog, stored):
        _store(db, stored)
        before = AppMetadataRepository(db).get(floor.KEY)
        monkeypatch.setattr(settings, "GUARDRAILS_FLOOR", {"enabled": True, "controls": [DENYLIST]})
        with caplog.at_level(logging.WARNING):
            floor.import_env_floor()
        assert AppMetadataRepository(db).get(floor.KEY) == before
        assert "deprecated and ignored" in caplog.text

    def test_an_invalid_env_floor_is_not_stored(self, db, monkeypatch, caplog):
        monkeypatch.setattr(settings, "GUARDRAILS_FLOOR", {"mode": "not-a-mode"})
        with caplog.at_level(logging.ERROR):
            floor.import_env_floor()
        assert AppMetadataRepository(db).get(floor.KEY) is None and "invalid" in caplog.text

    def test_an_env_floor_without_enabled_is_imported_and_said_to_apply_to_nothing(self, db, monkeypatch, caplog):
        monkeypatch.setattr(settings, "GUARDRAILS_FLOOR", {"controls": [SECRETS]})
        with caplog.at_level(logging.WARNING):
            floor.import_env_floor()
        assert floor.stored(db)["controls"][0]["check"] == "secrets"
        assert '"enabled": false' in caplog.text and floor.current() is None

    def test_an_unreachable_database_never_stops_the_start(self, monkeypatch, caplog):
        @contextmanager
        def down():
            raise ConnectionError("database down")
            yield  # pragma: no cover

        monkeypatch.setattr(floor, "db_session", down)
        monkeypatch.setattr(settings, "GUARDRAILS_FLOOR", FLOOR)
        with caplog.at_level(logging.WARNING):
            floor.import_env_floor()
        assert "retried at the next start" in caplog.text

    def test_unset_reads_nothing(self, monkeypatch):
        def refuse():
            raise AssertionError("no env floor, no database call")

        monkeypatch.setattr(floor, "db_session", refuse)
        floor.import_env_floor()
