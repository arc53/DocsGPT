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

    def test_a_short_marker_keeps_a_longer_ones_hash_alive(self, redis):
        flags.mark_run_started("u1", "ingest:s1", {"kind": "ingest"}, ttl_seconds=6 * 3600)
        flags.mark_run_started("u1", "t1", {"kind": "webhook"}, ttl_seconds=60)
        assert redis.ttl("activity:runs:u1") > 3600


class TestIngestEvents:
    def test_queued_marks_and_the_end_clears(self, redis):
        flags.track_ingest_event(
            "u1", "source.ingest.queued",
            {"source_id": "s1", "job_name": "Carrier handbook", "operation": "upload"},
        )
        runs = flags.list_runs("u1")
        assert len(runs) == 1
        assert runs[0]["id"] == "ingest:s1"
        assert runs[0]["kind"] == "ingest"
        assert runs[0]["source_id"] == "s1"
        assert runs[0]["name"] == "Carrier handbook"
        assert runs[0]["operation"] == "upload"
        flags.track_ingest_event("u1", "source.ingest.progress", {"source_id": "s1", "current": 40})
        assert len(flags.list_runs("u1")) == 1
        flags.track_ingest_event("u1", "source.ingest.completed", {"source_id": "s1"})
        assert flags.list_runs("u1") == []

    @pytest.mark.parametrize(
        "payload, name",
        [
            ({"name": "Rates", "job_name": "job", "filename": "f.pdf"}, "Rates"),
            ({"job_name": "job", "filename": "f.pdf"}, "job"),
            ({"filename": "f.pdf"}, "f.pdf"),
        ],
    )
    def test_names_the_run(self, redis, payload, name):
        flags.track_ingest_event("u1", "source.ingest.queued", {"source_id": "s1", **payload})
        assert flags.list_runs("u1")[0]["name"] == name

    def test_a_failure_clears(self, redis):
        flags.track_ingest_event("u1", "source.ingest.queued", {"source_id": "s1"})
        flags.track_ingest_event("u1", "source.ingest.failed", {"source_id": "s1"})
        assert flags.list_runs("u1") == []

    def test_other_events_and_payloads_without_a_source_do_nothing(self, redis):
        flags.track_ingest_event("u1", "job.updated", {"source_id": "s1"})
        flags.track_ingest_event("u1", "source.ingest.queued", {})
        assert flags.list_runs("u1") == []

    def test_publishing_an_ingest_event_tracks_it(self, monkeypatch):
        from docsgpt.events import publisher

        seen = []
        monkeypatch.setattr(flags, "track_ingest_event", lambda *args: seen.append(args))
        monkeypatch.setattr(publisher.settings, "ENABLE_SSE_PUSH", False)
        publisher.publish_user_event("u1", "source.ingest.queued", {"source_id": "s1"})
        assert seen == [("u1", "source.ingest.queued", {"source_id": "s1"})]
