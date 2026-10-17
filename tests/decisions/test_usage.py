"""Usage counts: increments per feature, mode, model version and status, written as upserts, reset after a fork."""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import docsgpt.decisions as decisions
from docsgpt.decisions import usage

TODAY_KEY = ("injection_input", "local", "v", "ok")


def _count(status="ok", **values):
    defaults = {"states": 2, "answered": 2, "ms": 10.0, "queue_ms": 1.0}
    usage.count("injection_input", "local", "v", status, **{**defaults, **values})


def _pending():
    return {key[1:]: row for key, row in usage._counts.items()}


@pytest.fixture
def stored(monkeypatch):
    """The rows a flush writes, instead of a database."""
    written = []
    repo = MagicMock()
    repo.add.side_effect = lambda rows: written.extend(rows) or len(rows)

    @contextmanager
    def session():
        yield MagicMock()

    monkeypatch.setattr("docsgpt.storage.db.session.db_session", session)
    monkeypatch.setattr(
        "docsgpt.storage.db.repositories.decision_usage.DecisionUsageRepository", lambda conn: repo
    )
    return written


@pytest.mark.unit
class TestCount:
    def test_calls_add_up_per_key(self):
        _count()
        _count(states=3, answered=1, ms=5.0, queue_ms=0.5)
        _count(status="timeout", answered=0)
        assert _pending() == {
            TODAY_KEY: [2, 5, 3, 15.0, 1.5],
            ("injection_input", "local", "v", "timeout"): [1, 2, 0, 10.0, 1.0],
        }

    def test_counts_are_filed_under_the_utc_day(self):
        _count()
        (key,) = usage._counts
        assert key[0] == datetime.now(timezone.utc).date()

    def test_no_model_is_filed_under_an_empty_version(self):
        usage.count("f", "api", None, "unavailable", states=1, answered=0, ms=1.0, queue_ms=0.0)
        assert next(iter(usage._counts))[3] == ""

    def test_tests_never_start_the_timer(self, monkeypatch):
        started = []
        monkeypatch.setattr(usage.threading, "Timer", lambda *a: started.append(a))
        _count()
        assert started == []

    def test_a_process_writes_once_a_minute(self, monkeypatch):
        timers = []

        class Timer:
            def __init__(self, seconds, fn):
                self.seconds, self.fn, self.daemon = seconds, fn, False
                timers.append(self)

            def start(self):
                pass

        monkeypatch.setattr(usage, "FLUSH_SECONDS", 60.0)
        monkeypatch.setattr(usage, "_timer", None)
        monkeypatch.setattr(usage, "_exit_hook", True)
        monkeypatch.setattr(usage.threading, "Timer", Timer)
        _count()
        _count()
        assert len(timers) == 1 and timers[0].seconds == 60.0 and timers[0].daemon


@pytest.mark.unit
class TestFlush:
    def test_writes_increments_and_empties(self, stored):
        _count()
        assert usage.flush() == 1
        assert usage._counts == {}
        (row,) = stored
        assert {k: row[k] for k in ("feature", "mode", "model_version", "status")} == {
            "feature": "injection_input", "mode": "local", "model_version": "v", "status": "ok",
        }
        assert [row[c] for c in usage.COUNTERS] == [1, 2, 2, 10.0, 1.0]
        assert usage.flush() == 0

    def test_a_failed_write_keeps_the_counts(self, monkeypatch):
        @contextmanager
        def broken():
            raise RuntimeError("database down")
            yield

        monkeypatch.setattr("docsgpt.storage.db.session.db_session", broken)
        _count()
        assert usage.flush() == 0
        _count()
        assert _pending()[TODAY_KEY][0] == 2

    def test_rows_hold_no_text(self, stored):
        _count()
        usage.flush()
        assert set(stored[0]) == {"day", "feature", "mode", "model_version", "status", *usage.COUNTERS}


@pytest.mark.unit
def test_counts_do_not_cross_a_fork():
    _count()
    decisions.reset()
    assert usage._counts == {}
