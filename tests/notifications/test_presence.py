"""Presence: tab reports, watching, open tabs, and failing open when Redis is gone."""

from __future__ import annotations

import pytest

from docsgpt.core.settings import settings
from docsgpt.events.keys import connection_leases_key
from docsgpt.notifications import presence

CID = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
NOW = 1_000_000.0


@pytest.fixture(autouse=True)
def _leases_on(monkeypatch):
    monkeypatch.setattr(settings, "SSE_MAX_CONCURRENT_PER_USER", 8)
    monkeypatch.setattr(settings, "SSE_KEEPALIVE_SECONDS", 15)


class TestReport:
    def test_stores_one_entry_per_tab_with_a_ttl(self, fake_redis):
        assert presence.report("u1", "t1", CID.upper(), True, now=NOW)
        assert presence.report("u1", "t2", None, False, now=NOW)
        tabs = {t["tab_id"]: t for t in presence.tabs("u1", now=NOW)}
        assert tabs["t1"]["conversation_id"] == CID
        assert tabs["t1"]["visible"] is True
        assert tabs["t2"]["conversation_id"] is None
        assert fake_redis.expires[presence.presence_key("u1")] == presence.PRESENCE_TTL_SECONDS

    def test_closing_removes_the_tab(self, fake_redis):
        presence.report("u1", "t1", CID, True, now=NOW)
        assert presence.report("u1", "t1", CID, True, closing=True, now=NOW)
        assert presence.tabs("u1", now=NOW) == []

    def test_reports_go_stale(self, fake_redis):
        presence.report("u1", "t1", CID, True, now=NOW)
        assert presence.tabs("u1", now=NOW + presence.PRESENCE_TTL_SECONDS - 1)
        assert presence.tabs("u1", now=NOW + presence.PRESENCE_TTL_SECONDS + 1) == []

    def test_tabs_are_bounded(self, fake_redis, monkeypatch):
        monkeypatch.setattr(presence, "MAX_TABS", 3)
        presence.report("u1", "stale", None, False, now=NOW - 1000)
        for i in range(4):
            presence.report("u1", f"t{i}", None, True, now=NOW + i)
        kept = {t["tab_id"] for t in presence.tabs("u1", now=NOW + 4)}
        assert kept == {"t1", "t2", "t3"}

    def test_garbage_entries_are_ignored(self, fake_redis):
        fake_redis.hashes[presence.presence_key("u1")] = {b"bad": b"not json", b"t1": b'{"visible": true, "at": 1}'}
        assert presence.tabs("u1", now=2) == [{"tab_id": "t1", "conversation_id": None, "visible": True, "at": 1.0}]

    def test_without_redis(self, monkeypatch):
        monkeypatch.setattr("docsgpt.notifications.presence.get_redis_instance", lambda: None)
        assert presence.report("u1", "t1", CID, True) is False
        assert presence.tabs("u1") is None

    def test_redis_errors_are_swallowed(self, fake_redis):
        fake_redis.fail = True
        assert presence.report("u1", "t1", CID, True) is False
        assert presence.report("u1", "t1", CID, True, closing=True) is False
        assert presence.tabs("u1") is None


class TestIsWatching:
    def test_a_visible_tab_on_the_conversation(self, fake_redis):
        presence.report("u1", "t1", CID, True, now=NOW)
        assert presence.is_watching("u1", CID, now=NOW)
        assert presence.is_watching("u1", CID.upper(), now=NOW)
        assert not presence.is_watching("u1", OTHER, now=NOW)
        assert not presence.is_watching("u2", CID, now=NOW)

    def test_a_hidden_tab_is_not_watching(self, fake_redis):
        presence.report("u1", "t1", CID, False, now=NOW)
        assert not presence.is_watching("u1", CID, now=NOW)

    def test_a_tab_that_stopped_reporting_is_not_watching(self, fake_redis):
        presence.report("u1", "t1", CID, True, now=NOW)
        assert not presence.is_watching("u1", CID, now=NOW + 60)

    def test_unknown_is_not_watching(self, fake_redis):
        fake_redis.fail = True
        assert not presence.is_watching("u1", CID)
        assert not presence.is_watching("", CID)
        assert not presence.is_watching("u1", None)


class TestHasOpenTab:
    def test_a_visible_tab_elsewhere(self, fake_redis):
        presence.report("u1", "t1", OTHER, True, now=NOW)
        assert presence.has_open_tab("u1", now=NOW)

    def test_a_hidden_tab_counts_through_its_event_stream(self, fake_redis):
        presence.report("u1", "t1", CID, False, now=NOW)
        assert not presence.has_open_tab("u1", now=NOW)
        fake_redis.zadd(connection_leases_key("u1"), {"lease": NOW - 10})
        assert presence.has_open_tab("u1", now=NOW)

    def test_a_stream_alone_counts_without_any_report(self, fake_redis):
        fake_redis.zadd(connection_leases_key("u1"), {"lease": NOW - 5})
        assert presence.has_open_tab("u1", now=NOW)

    def test_a_stale_lease_does_not_count(self, fake_redis):
        fake_redis.zadd(connection_leases_key("u1"), {"lease": NOW - 3600})
        assert not presence.has_open_tab("u1", now=NOW)

    def test_without_leases_any_fresh_report_counts(self, fake_redis, monkeypatch):
        monkeypatch.setattr(settings, "SSE_MAX_CONCURRENT_PER_USER", 0)
        assert not presence.has_open_tab("u1", now=NOW)
        presence.report("u1", "t1", None, False, now=NOW)
        assert presence.has_open_tab("u1", now=NOW)

    def test_unknown_is_no_tab(self, fake_redis):
        presence.report("u1", "t1", None, False, now=NOW)
        fake_redis.fail = True
        assert not presence.has_open_tab("u1", now=NOW)
        assert not presence.has_open_tab("", now=NOW)

    def test_a_failing_lease_read_is_no_tab(self, fake_redis, monkeypatch):
        presence.report("u1", "t1", None, False, now=NOW)
        monkeypatch.setattr(fake_redis, "zcount", lambda *a: (_ for _ in ()).throw(ConnectionError("x")))
        assert not presence.has_open_tab("u1", now=NOW)
