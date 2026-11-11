"""An agent's gap summary (``docsgpt/drafter/gaps.py``) against a real Postgres."""

from __future__ import annotations

import datetime

import pytest

from docsgpt.drafter import gaps
from docsgpt.drafter.gaps import agent_gaps, DAYS, NEEDED, shown_count, window
from docsgpt.storage.db.repositories.conversation_labels import SUMMARY_GAP_TYPES
from tests.drafter import insights_seed as seed

TOPICS = [{"id": "returns01", "name": "Returns", "description": "Refunds and claims.", "overlap": False},
          {"id": "orders001", "name": "Orders", "description": "Where is my order.", "overlap": False}]


@pytest.fixture(autouse=True)
def _insights_on(monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
    monkeypatch.setattr("docsgpt.decisions.available", lambda: True)


def _busy(conn, n=NEEDED, **analytics):
    """An agent with ``n`` analysed conversations of no gap."""
    bot = seed.agent(conn, **analytics)
    for _ in range(n):
        seed.turn(conn, str(bot["id"]))
    return bot


@pytest.mark.unit
class TestShape:
    def test_off_on_this_instance(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", False)
        assert agent_gaps(pg_conn, _busy(pg_conn)) == {
            "available": False, "reason": "off_on_this_instance", "conversations": 0, "needed": NEEDED,
            "days": DAYS, "rows": []}

    def test_off_for_the_agent(self, pg_conn):
        result = agent_gaps(pg_conn, _busy(pg_conn, enabled=False))
        assert result["available"] is False and result["reason"] == "agent_off" and result["conversations"] == 0

    def test_not_enough_counts_analysed_conversations(self, pg_conn):
        bot = _busy(pg_conn, n=NEEDED - 1)
        seed.turn(pg_conn, str(bot["id"]), days_ago=DAYS + 2)
        result = agent_gaps(pg_conn, bot)
        assert (result["available"], result["reason"], result["conversations"]) == (False, "not_enough", NEEDED - 1)
        assert result["rows"] == []

    def test_rows_by_gap_type_without_a_topic_question(self, pg_conn):
        bot = _busy(pg_conn)
        for p in (0.9, 0.8, 0.8):
            seed.turn(pg_conn, str(bot["id"]), gap={"confidently ungrounded": p, "other": 0.9})
        result = agent_gaps(pg_conn, bot)
        assert result["available"] is True and result["reason"] is None
        assert result["conversations"] == NEEDED + 3
        # 2.5 rounds up, as the Insights page shows it; nothing was labelled before, so no previous figure
        assert result["rows"] == [{"topic": None, "gap_type": "confidently ungrounded", "expected": 3,
                                   "turns": NEEDED + 3, "previous": None}]

    def test_rows_by_topic_with_the_previous_period(self, pg_conn):
        bot = _busy(pg_conn, topics=TOPICS)
        aid = str(bot["id"])
        for _ in range(3):
            seed.turn(pg_conn, aid, gap={"needs account data": 0.9}, topics={"Orders": 1.0})
        seed.turn(pg_conn, aid, gap={"docs missing": 0.9}, topics={"Returns": 1.0})
        seed.turn(pg_conn, aid, gap={"needs account data": 0.9}, topics={"Orders": 1.0}, days_ago=DAYS + 5)
        rows = agent_gaps(pg_conn, bot)["rows"]
        assert rows == [
            {"topic": "Orders", "gap_type": "needs account data", "expected": 3, "turns": 3, "previous": 1},
            {"topic": "Returns", "gap_type": "docs missing", "expected": 1, "turns": 1, "previous": 0},
        ]

    def test_at_most_ten_rows(self, pg_conn):
        bot = _busy(pg_conn, topics=TOPICS)
        aid = str(bot["id"])
        every = {gap: 0.9 for gap in SUMMARY_GAP_TYPES}
        for topic in ("Orders", "Returns"):
            seed.turn(pg_conn, aid, gap=every, topics={topic: 1.0})
        assert len(agent_gaps(pg_conn, bot)["rows"]) == gaps.MAX_ROWS


@pytest.mark.unit
def test_window_and_rounding():
    now = datetime.datetime(2026, 11, 9, 15, 30, tzinfo=datetime.timezone.utc)
    start, end = window(30, now)
    assert start == datetime.datetime(2026, 10, 11, tzinfo=datetime.timezone.utc)
    assert end.date() == now.date() and end.hour == 23
    assert [shown_count(v) for v in (0.5, 1.49, 2.5, None)] == [1, 1, 3, 0]
