"""Tests for the Activity Redis flags: stop requests and webhook run markers."""

from __future__ import annotations

import fakeredis
import pytest

from docsgpt.activity import flags


@pytest.fixture
def redis(monkeypatch):
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(flags, "get_redis_instance", lambda: fake)
    return fake


class TestStopRequests:
    def test_round_trip(self, redis):
        assert flags.stop_requested("m1") is False
        assert flags.request_stop("m1") is True
        assert flags.stop_requested("m1") is True
        flags.clear_stop("m1")
        assert flags.stop_requested("m1") is False

    def test_expires(self, redis):
        flags.request_stop("m1")
        assert 0 < redis.ttl("activity:stop:m1") <= flags.STOP_TTL_SECONDS

    def test_without_redis_nothing_is_stored(self, monkeypatch):
        monkeypatch.setattr(flags, "get_redis_instance", lambda: None)
        assert flags.request_stop("m1") is False
        assert flags.stop_requested("m1") is False


class TestRunMarkers:
    def test_started_then_finished(self, redis):
        flags.mark_run_started("u1", "t1", {"kind": "webhook", "agent_name": "Desk"}, ttl_seconds=60)
        runs = flags.list_runs("u1")
        assert [r["id"] for r in runs] == ["t1"]
        assert runs[0]["agent_name"] == "Desk"
        flags.mark_run_finished("u1", "t1")
        assert flags.list_runs("u1") == []

    def test_a_marker_past_its_ceiling_is_ignored(self, redis):
        flags.mark_run_started("u1", "t1", {"kind": "webhook"}, ttl_seconds=60)
        later = flags.list_runs("u1")[0]["started_at"] + 61
        assert flags.list_runs("u1", now=later) == []

    def test_markers_are_per_user(self, redis):
        flags.mark_run_started("u1", "t1", {"kind": "webhook"}, ttl_seconds=60)
        assert flags.list_runs("u2") == []

    def test_without_redis_lists_nothing(self, monkeypatch):
        monkeypatch.setattr(flags, "get_redis_instance", lambda: None)
        flags.mark_run_started("u1", "t1", {"kind": "webhook"}, ttl_seconds=60)
        assert flags.list_runs("u1") == []
