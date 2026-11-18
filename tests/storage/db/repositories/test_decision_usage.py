"""Tests for DecisionUsageRepository against a real Postgres instance."""

from __future__ import annotations

import datetime

from sqlalchemy import text

from docsgpt.storage.db.repositories.decision_usage import DecisionUsageRepository

TODAY = datetime.date.today()


def _row(**overrides):
    base = {
        "day": TODAY, "feature": "injection_input", "mode": "local", "model_version": "v2", "status": "ok",
        "calls": 1, "states": 2, "answered": 2, "ms_total": 210.5, "queue_ms_total": 3.0,
    }
    base.update(overrides)
    return base


class TestAdd:
    def test_increments_add_up_on_one_row(self, pg_conn):
        repo = DecisionUsageRepository(pg_conn)
        assert repo.add([_row()]) == 1
        repo.add([_row(calls=2, states=3, answered=1, ms_total=1.5, queue_ms_total=0.5)])
        rows = pg_conn.execute(text("SELECT calls, states, answered, ms_total, queue_ms_total FROM decision_usage"))
        assert [tuple(r) for r in rows] == [(3, 5, 3, 212.0, 3.5)]

    def test_each_key_has_its_own_row(self, pg_conn):
        repo = DecisionUsageRepository(pg_conn)
        repo.add([_row(), _row(status="timeout"), _row(mode="api"), _row(model_version=None),
                  _row(day=TODAY - datetime.timedelta(days=1))])
        assert pg_conn.execute(text("SELECT count(*) FROM decision_usage")).scalar() == 5

    def test_nothing_to_add(self, pg_conn):
        assert DecisionUsageRepository(pg_conn).add([]) == 0


class TestTotals:
    def test_sums_a_day_range_per_feature(self, pg_conn):
        repo = DecisionUsageRepository(pg_conn)
        yesterday = TODAY - datetime.timedelta(days=1)
        repo.add([_row(), _row(day=yesterday), _row(day=TODAY - datetime.timedelta(days=5)),
                  _row(feature="rag_rerank"), _row(status="unavailable", answered=0)])

        totals = repo.totals(yesterday, TODAY, feature="injection_input")

        assert totals == [
            {"feature": "injection_input", "mode": "local", "model_version": "v2", "status": "ok",
             "calls": 2, "states": 4, "answered": 4, "ms_total": 421.0, "queue_ms_total": 6.0},
            {"feature": "injection_input", "mode": "local", "model_version": "v2", "status": "unavailable",
             "calls": 1, "states": 2, "answered": 0, "ms_total": 210.5, "queue_ms_total": 3.0},
        ]
        assert {t["feature"] for t in repo.totals(yesterday, TODAY)} == {"injection_input", "rag_rerank"}


class TestPurge:
    def test_deletes_days_past_the_window(self, pg_conn):
        repo = DecisionUsageRepository(pg_conn)
        repo.add([_row(day=TODAY - datetime.timedelta(days=100)), _row(day=TODAY - datetime.timedelta(days=89)),
                  _row()])
        assert repo.purge_older_than(90) == 1
        assert pg_conn.execute(text("SELECT count(*) FROM decision_usage")).scalar() == 2
