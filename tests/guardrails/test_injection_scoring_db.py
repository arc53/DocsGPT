"""The scorer's own reads and writes: the score cache, retention touches and the owners' allowlists, against Postgres."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from docsgpt.guardrails import injection_scoring as scoring
from docsgpt.storage.db.repositories.content_scores import ContentScoresRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository

pytestmark = pytest.mark.integration

SCORER = "injection:v:q1:w512o50"
# The root conftest stubs these out for every test; this module tests the real ones.
REAL = {name: getattr(scoring, name) for name in ("_load", "_store", "_touch", "_touch_later", "_queue",
                                                  "allowed_hashes")}


def row(content_hash, p=0.5):
    return {"content_hash": content_hash, "scorer": SCORER, "p": p, "windows_scored": 1, "windows_total": 1}


@pytest.fixture(autouse=True)
def real_helpers(monkeypatch):
    for name, fn in REAL.items():
        monkeypatch.setattr(scoring, name, fn)


@pytest.fixture
def use_pg(pg_conn, monkeypatch):
    @contextmanager
    def _use():
        yield pg_conn

    monkeypatch.setattr("docsgpt.storage.db.session.db_session", _use)
    monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", _use)
    return pg_conn


@pytest.fixture
def broken_db(monkeypatch):
    @contextmanager
    def _fail():
        raise RuntimeError("database down")
        yield

    monkeypatch.setattr("docsgpt.storage.db.session.db_session", _fail)
    monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", _fail)


class TestCache:
    def test_stored_scores_are_read_back_for_their_scorer(self, use_pg):
        scoring._store([row("h1", 0.25), row("h2", 0.75)])
        loaded = scoring._load(["h1", "h2", "h3"], SCORER)
        assert {k: v["p"] for k, v in loaded.items()} == {"h1": 0.25, "h2": 0.75}
        assert scoring._load(["h1"], "injection:other") == {}

    def test_nothing_to_store_writes_nothing(self, broken_db):
        scoring._store([])

    def test_a_touch_marks_a_stale_row_seen(self, use_pg):
        scoring._store([row("h1")])
        use_pg.execute(text("UPDATE content_scores SET last_seen_at = now() - interval '3 days'"))
        assert scoring._load(["h1"], SCORER)["h1"]["stale"] is True
        scoring._touch(["h1"], SCORER)
        assert ContentScoresRepository(use_pg).get_many(["h1"], SCORER)["h1"]["stale"] is False

    def test_an_unreachable_database_is_a_miss_and_never_raises(self, broken_db):
        scoring._store([row("h1")])
        scoring._touch(["h1"], SCORER)
        assert scoring._load(["h1"], SCORER) == {}


class TestAllowlists:
    def test_each_sources_owner_allowlist_in_one_read(self, use_pg):
        repo = SourcesRepository(use_pg)
        a = repo.create("a", user_id="alice", metadata={"injection_review": {"allowed": ["h1", "h2"]}})
        b = repo.create("b", user_id="alice")
        allowed = scoring.allowed_hashes([str(a["id"]), str(b["id"]), None])
        assert allowed.get(str(a["id"])) == {"h1", "h2"}
        assert not allowed.get(str(b["id"]))

    def test_no_sources_reads_nothing(self, broken_db):
        assert scoring.allowed_hashes([None, ""]) == {}

    def test_an_unreadable_allowlist_is_empty(self, broken_db):
        assert scoring.allowed_hashes(["s1"]) == {}


class TestQueueing:
    def test_texts_and_touches_go_to_their_tasks(self, monkeypatch):
        from docsgpt.api.user import tasks

        score_task, touch_task = MagicMock(), MagicMock()
        monkeypatch.setattr(tasks, "score_injection_texts", score_task)
        monkeypatch.setattr(tasks, "touch_content_scores", touch_task)
        scoring._queue(["a"])
        scoring._touch_later(["h1"], SCORER)
        score_task.delay.assert_called_once_with(["a"])
        touch_task.delay.assert_called_once_with(["h1"], SCORER)

    def test_a_broker_failure_on_a_touch_never_raises(self, monkeypatch):
        from docsgpt.api.user import tasks

        touch_task = MagicMock()
        touch_task.delay.side_effect = ConnectionError("broker down")
        monkeypatch.setattr(tasks, "touch_content_scores", touch_task)
        scoring._touch_later(["h1"], SCORER)
