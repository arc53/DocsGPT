"""Tests for the tick pipeline: dispatch, quiet ticks, checks, the judge, failures, the breaker and events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.monitors import judge, tick
from docsgpt.monitors.checks import Content
from docsgpt.monitors.fetch import SourceError, SourceRevoked, SourceUnreachable
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.trigger_links import TriggerHitsRepository, TriggerLinksRepository

THRESHOLD = {"type": "threshold", "value_path": "", "op": "<", "value": 90.0}


def make_monitor(engine, conversation_id, **overrides):
    """A monitor row as ``service.create`` would leave it, with a baseline taken."""
    now = datetime.now(timezone.utc)
    source = overrides.pop("source", {"type": "webpage", "url": "https://shop.example.com/acmeb"})
    spec = {
        "source": source,
        "check": overrides.pop("check", THRESHOLD),
        "condition": overrides.pop("condition", None),
        "interval_seconds": 900,
        "max_wakes": overrides.get("max_wakes", 1),
        "on_match": "tell me the price",
    }
    fields = dict(
        user_id="u1",
        conversation_id=conversation_id,
        agent_id=None,
        description="ACMEB below $90",
        source_type=source["type"],
        spec=spec,
        on_match="tell me the price",
        end_at=now + timedelta(days=7),
        next_run_at=now - timedelta(seconds=5),
        max_wakes=1,
        interval_seconds=900 if source["type"] in ("webpage", "tool") else None,
        state={"hash": Content(text="Price: $95").digest, "check": {"holds": False, "key": "", "epoch": 0}},
        token_budget=None,
        check_count=1,
        last_checked_at=now - timedelta(minutes=15),
    )
    fields.update(overrides)
    with engine.begin() as conn:
        return MonitorsRepository(conn).create(**fields)


def reload(engine, monitor_id):
    with engine.connect() as conn:
        return MonitorsRepository(conn).get_internal(monitor_id)


@pytest.fixture()
def page(monkeypatch):
    holder = {"value": Content(text="Price: $95"), "calls": 0}

    def fetch(url, css_selector=None):
        holder["calls"] += 1
        value = holder["value"]
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(tick, "fetch_webpage", fetch)
    return holder


@pytest.fixture()
def no_judge(monkeypatch):
    def refuse(**kwargs):
        raise AssertionError("the judge must not run")

    monkeypatch.setattr(judge, "judge", refuse)


@pytest.fixture()
def queued(monkeypatch):
    """Celery fan-out, recorded instead of sent."""
    calls = {"ticks": [], "hits": [], "events": []}
    import docsgpt.api.user.tasks as tasks

    monkeypatch.setattr(tasks.run_monitor_tick, "apply_async", lambda args, **kw: calls["ticks"].append(args))
    monkeypatch.setattr(tasks.process_trigger_hit, "apply_async", lambda args, **kw: calls["hits"].append(args))
    monkeypatch.setattr(tasks.process_monitor_event, "apply_async", lambda args, **kw: calls["events"].append(args))
    return calls


class TestDispatch:
    def test_due_monitor_is_advanced_and_fanned_out(self, mon_db, conversation_id, queued, events):
        due = make_monitor(mon_db, conversation_id)
        later = make_monitor(mon_db, conversation_id, next_run_at=datetime.now(timezone.utc) + timedelta(hours=1))
        counts = tick.dispatch_due_monitors()
        assert counts["ticked"] == 1 and queued["ticks"] == [[due["id"]]]
        advanced = reload(mon_db, due["id"])["next_run_at"]
        assert advanced > datetime.now(timezone.utc) + timedelta(minutes=14)
        assert advanced.minute not in (0, 30)
        assert reload(mon_db, later["id"])["next_run_at"] > datetime.now(timezone.utc)
        # The same slot is never handed out twice.
        assert tick.dispatch_due_monitors()["ticked"] == 0

    def test_expired_monitor_ends_and_says_so_once(self, mon_db, conversation_id, queued, wakes, events):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        monitor = make_monitor(mon_db, conversation_id, end_at=past, next_run_at=past)
        assert tick.dispatch_due_monitors()["expired"] == 1
        after = reload(mon_db, monitor["id"])
        assert after["status"] == "completed" and after["paused_reason"] == "expired"
        assert len(wakes) == 1 and "expired" in wakes[0]["title"]
        assert wakes[0]["dedupe_key"] == f"monitor:{monitor['id']}:expired:end"
        assert tick.dispatch_due_monitors()["expired"] == 0 and len(wakes) == 1

    def test_paused_monitor_past_its_expiry_ends_quietly(self, mon_db, conversation_id, queued, wakes, events):
        monitor = make_monitor(mon_db, conversation_id)
        with mon_db.begin() as conn:
            MonitorsRepository(conn).finish(monitor["id"], "paused")
            conn.execute(
                text("UPDATE schedules SET end_at = now() - interval '1 minute' WHERE id = CAST(:id AS uuid)"),
                {"id": monitor["id"]},
            )
        tick.dispatch_due_monitors()
        assert reload(mon_db, monitor["id"])["status"] == "completed" and wakes == []

    def test_approval_expiry_says_nobody_decided(self, mon_db, conversation_id, queued, wakes, events):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        make_monitor(
            mon_db,
            conversation_id,
            source={"type": "approval", "question": "Q"},
            check=None,
            end_at=past,
            next_run_at=past,
        )
        tick.dispatch_due_monitors()
        assert wakes[0]["source"] == "approval" and "Nobody decided" in wakes[0]["body"]

    def test_lost_deliveries_are_requeued(self, mon_db, conversation_id, queued):
        monitor = make_monitor(mon_db, conversation_id, source={"type": "webhook", "signature": "none"}, check=None)
        with mon_db.begin() as conn:
            link = TriggerLinksRepository(conn).create(
                monitor_id=monitor["id"],
                user_id="u1",
                conversation_id=conversation_id,
                token_hash="h1",
                kind="webhook",
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                max_hits=10,
            )
            hit = TriggerHitsRepository(conn).insert(str(link["id"]), "k1", {"body": {}})
            conn.execute(
                text("UPDATE trigger_hits SET received_at = now() - interval '10 minutes' WHERE id = :id"),
                {"id": hit["id"]},
            )
        assert tick.dispatch_due_monitors()["requeued"] == 1
        assert queued["hits"] == [[str(hit["id"]), 0]]


class TestPolledTick:
    def test_unchanged_content_is_a_quiet_tick(self, mon_db, conversation_id, page, wakes, events, no_judge):
        monitor = make_monitor(mon_db, conversation_id, condition="price is low")
        assert tick.run_tick(monitor["id"]) == {"state": "quiet"}
        after = reload(mon_db, monitor["id"])
        assert after["check_count"] == 2 and after["last_changed_at"] is None and wakes == []
        assert events[-1]["payload"]["monitor_id"] == monitor["id"]
        assert events[-1]["payload"]["last_checked_at"] is not None

    def test_a_change_that_does_not_cross_stays_quiet(self, mon_db, conversation_id, page, wakes, events, no_judge):
        monitor = make_monitor(mon_db, conversation_id, condition="price is low")
        page["value"] = Content(text="Price: $93")
        assert tick.run_tick(monitor["id"]) == {"state": "checked"}
        after = reload(mon_db, monitor["id"])
        assert after["last_changed_at"] is not None and after["monitor_state"]["check"]["value"] == 93.0
        assert wakes == []

    def test_crossing_wakes_once_and_finishes(self, mon_db, conversation_id, page, wakes, events):
        monitor = make_monitor(mon_db, conversation_id)
        page["value"] = Content(text="Price: $88.50")
        assert tick.run_tick(monitor["id"]) == {"state": "woken"}
        assert len(wakes) == 1
        wake = wakes[0]
        assert wake["source"] == "monitor" and wake["ref_id"] == monitor["id"]
        assert wake["conversation_id"] == conversation_id and wake["title"] == "ACMEB below $90"
        assert wake["dedupe_key"].startswith(f"monitor:{monitor['id']}:")
        assert wake["payload"]["value"] == 88.5 and wake["payload"]["url"] == "https://shop.example.com/acmeb"
        assert "tell me the price" in wake["body"] and "last wake" in wake["body"]
        after = reload(mon_db, monitor["id"])
        assert after["wake_count"] == 1 and after["status"] == "completed"
        assert after["approval"] is None
        assert events[-1]["payload"]["status"] == "completed" and events[-1]["payload"]["wakes_left"] == 0

    def test_keeps_holding_does_not_wake_again(self, mon_db, conversation_id, page, wakes, events):
        monitor = make_monitor(mon_db, conversation_id, max_wakes=5)
        page["value"] = Content(text="Price: $88")
        tick.run_tick(monitor["id"])
        page["value"] = Content(text="Price: $87")
        assert tick.run_tick(monitor["id"]) == {"state": "checked"}
        page["value"] = Content(text="Price: $95")
        tick.run_tick(monitor["id"])
        page["value"] = Content(text="Price: $85")
        assert tick.run_tick(monitor["id"]) == {"state": "woken"}
        assert len(wakes) == 2 and wakes[0]["dedupe_key"] != wakes[1]["dedupe_key"]
        after = reload(mon_db, monitor["id"])
        assert after["wake_count"] == 2 and after["status"] == "active"

    def test_a_remembered_wake_key_is_not_delivered_again(self, mon_db, conversation_id, page, wakes, events):
        monitor = make_monitor(mon_db, conversation_id, max_wakes=3)
        page["value"] = Content(text="Price: $88")
        tick.run_tick(monitor["id"])
        key = wakes[0]["dedupe_key"]
        with mon_db.begin() as conn:
            repo = MonitorsRepository(conn)
            state = repo.get_internal(monitor["id"])["monitor_state"]
            state["hash"] = "different"
            state["check"] = {"holds": False, "epoch": 0, "key": ""}
            repo.update(monitor["id"], {"monitor_state": state})
        assert tick.run_tick(monitor["id"]) == {"state": "duplicate"}
        assert len(wakes) == 1 and key in reload(mon_db, monitor["id"])["monitor_state"]["wake_keys"]

    def test_lease_keeps_two_ticks_apart(self, mon_db, conversation_id, page, wakes):
        monitor = make_monitor(mon_db, conversation_id)
        with mon_db.begin() as conn:
            MonitorsRepository(conn).acquire_tick(monitor["id"], stale_seconds=900)
        assert tick.run_tick(monitor["id"]) == {"state": "busy"}
        assert page["calls"] == 0

    def test_inactive_monitors_are_skipped(self, mon_db, conversation_id, page):
        monitor = make_monitor(mon_db, conversation_id)
        with mon_db.begin() as conn:
            MonitorsRepository(conn).finish(monitor["id"], "cancelled")
        assert tick.run_tick(monitor["id"]) == {"state": "skipped"} and page["calls"] == 0

    def test_tool_source_replays_with_placeholders(self, mon_db, conversation_id, monkeypatch, wakes, events):
        seen = {}

        def run_call(**kwargs):
            seen.update(kwargs)
            return Content(text='{"items": [{"id": 1}, {"id": 2}]}', data={"items": [{"id": 1}, {"id": 2}]})

        from docsgpt.monitors import sources

        monkeypatch.setattr(sources, "run_call", run_call)
        approval = {"tool_id": "t1", "action": "list", "args_hash": "h", "required": False}
        monitor = make_monitor(
            mon_db,
            conversation_id,
            approval=approval,
            source={"type": "tool", "tool": "list_issues", "args": {"q": "after:{{last_checked_date}}"}},
            check={"type": "new_items", "items_path": "items", "id_field": "id"},
            state={"hash": "old", "check": {"holds": False, "epoch": 0, "key": "", "seen": ["1"]}},
        )
        assert tick.run_tick(monitor["id"]) == {"state": "woken"}
        assert seen["approval"] == approval and seen["args_template"] == {"q": "after:{{last_checked_date}}"}
        assert seen["placeholders"]["last_checked_at"] is not None
        assert wakes[0]["payload"]["new_count"] == 1 and wakes[0]["payload"]["tool"] == "list_issues"

    def test_tool_source_without_its_approval_pauses(self, mon_db, conversation_id, wakes, events):
        monitor = make_monitor(mon_db, conversation_id, source={"type": "tool", "tool": "x", "args": {}})
        assert tick.run_tick(monitor["id"]) == {"state": "paused"}
        assert reload(mon_db, monitor["id"])["status"] == "paused" and "paused" in wakes[0]["title"]


class TestFailures:
    def test_unreachable_is_skipped_then_pauses_after_the_grace(
        self, mon_db, conversation_id, page, wakes, events, monkeypatch
    ):
        monitor = make_monitor(mon_db, conversation_id)
        page["value"] = SourceUnreachable("timeout")
        assert tick.run_tick(monitor["id"]) == {"state": "unreachable"}
        after = reload(mon_db, monitor["id"])
        assert after["unreachable_since"] is not None and after["consecutive_failure_count"] == 0
        assert after["check_count"] == 1 and wakes == []
        assert tick.run_tick(monitor["id"]) == {"state": "unreachable"}
        assert reload(mon_db, monitor["id"])["unreachable_since"] == after["unreachable_since"]
        later = datetime.now(timezone.utc) + timedelta(seconds=settings.MONITOR_UNREACHABLE_GRACE_SECONDS + 5)
        monkeypatch.setattr(tick, "_now", lambda: later)
        with mon_db.begin() as conn:
            conn.execute(
                text("UPDATE schedules SET end_at = now() + interval '30 days' WHERE id = CAST(:id AS uuid)"),
                {"id": monitor["id"]},
            )
        assert tick.run_tick(monitor["id"]) == {"state": "paused"}
        assert reload(mon_db, monitor["id"])["status"] == "paused"
        assert len(wakes) == 1 and "can't be reached" in wakes[0]["body"]
        assert wakes[0]["dedupe_key"].startswith(f"monitor:{monitor['id']}:unreachable:")

    def test_recovering_clears_the_unreachable_streak(self, mon_db, conversation_id, page, events):
        monitor = make_monitor(mon_db, conversation_id)
        page["value"] = SourceUnreachable("timeout")
        tick.run_tick(monitor["id"])
        page["value"] = Content(text="Price: $95")
        assert tick.run_tick(monitor["id"]) == {"state": "quiet"}
        after = reload(mon_db, monitor["id"])
        assert after["unreachable_since"] is None and after["last_error"] is None

    def test_three_errors_pause_and_wake_once(self, mon_db, conversation_id, page, wakes, events):
        monitor = make_monitor(mon_db, conversation_id)
        page["value"] = SourceError("HTTP 404")
        assert [tick.run_tick(monitor["id"])["state"] for _ in range(3)] == ["error", "error", "paused"]
        after = reload(mon_db, monitor["id"])
        assert after["status"] == "paused" and after["paused_reason"] == "repeated errors"
        assert len(wakes) == 1 and "HTTP 404" in wakes[0]["body"]

    def test_a_good_check_resets_the_streak(self, mon_db, conversation_id, page, events):
        monitor = make_monitor(mon_db, conversation_id)
        page["value"] = SourceError("HTTP 404")
        tick.run_tick(monitor["id"])
        tick.run_tick(monitor["id"])
        page["value"] = Content(text="Price: $95")
        tick.run_tick(monitor["id"])
        assert reload(mon_db, monitor["id"])["consecutive_failure_count"] == 0

    def test_content_that_no_longer_fits_the_check_counts_as_an_error(self, mon_db, conversation_id, page, events):
        monitor = make_monitor(mon_db, conversation_id)
        page["value"] = Content(text="Sold out")
        assert tick.run_tick(monitor["id"]) == {"state": "error"}
        assert "doesn't fit" in reload(mon_db, monitor["id"])["last_error"]

    def test_a_revoked_source_pauses_at_once(self, mon_db, conversation_id, page, wakes, events):
        monitor = make_monitor(mon_db, conversation_id)
        page["value"] = SourceRevoked("the device's pairing was revoked")
        assert tick.run_tick(monitor["id"]) == {"state": "paused"}
        assert "pairing was revoked" in wakes[0]["body"]


class TestJudge:
    def _judged(self, monkeypatch, *results):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            value = results[min(len(calls), len(results)) - 1]
            if isinstance(value, BaseException):
                raise value
            return value

        monkeypatch.setattr(judge, "judge", fake)
        return calls

    def _monitor(self, mon_db, conversation_id, **extra):
        return make_monitor(
            mon_db, conversation_id, check={"type": "changed"}, condition="mentions a Series B", max_wakes=3, **extra
        )

    def test_judge_runs_only_after_the_check_and_no_match_is_quiet(
        self, mon_db, conversation_id, page, wakes, events, monkeypatch
    ):
        calls = self._judged(monkeypatch, judge.Verdict(False, "no funding news", "none", 50))
        monitor = self._monitor(mon_db, conversation_id)
        assert tick.run_tick(monitor["id"]) == {"state": "quiet"} and calls == []
        page["value"] = Content(text="We hired a CFO")
        assert tick.run_tick(monitor["id"]) == {"state": "checked"}
        assert len(calls) == 1 and calls[0]["condition"] == "mentions a Series B"
        assert calls[0]["content"] == "We hired a CFO" and wakes == []
        assert reload(mon_db, monitor["id"])["judge_tokens"] == 50

    def test_a_match_wakes_and_the_same_fact_is_not_reported_twice(
        self, mon_db, conversation_id, page, wakes, events, monkeypatch
    ):
        verdict = judge.Verdict(True, "They announced a $40M Series B", "series b $40m", 80)
        self._judged(monkeypatch, verdict, verdict)
        monitor = self._monitor(mon_db, conversation_id)
        page["value"] = Content(text="Series B: $40M")
        assert tick.run_tick(monitor["id"]) == {"state": "woken"}
        assert wakes[0]["payload"]["summary"] == "They announced a $40M Series B"
        page["value"] = Content(text="Series B: $40M (updated)")
        assert tick.run_tick(monitor["id"]) == {"state": "duplicate"}
        assert len(wakes) == 1

    def test_judge_failures_keep_the_change_and_count_toward_the_pause(
        self, mon_db, conversation_id, page, wakes, events, monkeypatch
    ):
        self._judged(monkeypatch, judge.JudgeError("the judge call failed"))
        monitor = self._monitor(mon_db, conversation_id)
        page["value"] = Content(text="Something new")
        assert tick.run_tick(monitor["id"]) == {"state": "retry"}
        after = reload(mon_db, monitor["id"])
        assert after["monitor_state"]["hash"] == Content(text="Price: $95").digest
        assert after["consecutive_failure_count"] == 1 and "judged" in after["last_error"]
        assert tick.run_tick(monitor["id"]) == {"state": "retry"}
        assert tick.run_tick(monitor["id"]) == {"state": "paused"}
        assert reload(mon_db, monitor["id"])["status"] == "paused" and len(wakes) == 1

    def test_budget_used_up_pauses(self, mon_db, conversation_id, page, wakes, events, monkeypatch):
        self._judged(monkeypatch, AssertionError("must not run"))
        monitor = self._monitor(mon_db, conversation_id, token_budget=100)
        with mon_db.begin() as conn:
            MonitorsRepository(conn).add_judge_tokens(monitor["id"], 100)
        page["value"] = Content(text="Something new")
        assert tick.run_tick(monitor["id"]) == {"state": "paused"}
        assert "token budget" in wakes[0]["body"]

    def test_quota_used_up_waits_without_a_strike(self, mon_db, conversation_id, page, wakes, events, monkeypatch):
        self._judged(monkeypatch, AssertionError("must not run"))
        from docsgpt.quotas.service import QuotaService

        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, user, bucket="direct", now=None: object()))
        monitor = self._monitor(mon_db, conversation_id)
        page["value"] = Content(text="Something new")
        assert tick.run_tick(monitor["id"]) == {"state": "retry"}
        after = reload(mon_db, monitor["id"])
        assert after["consecutive_failure_count"] == 0 and "quota" in after["last_error"] and wakes == []


class TestBreaker:
    def test_too_many_wakes_in_an_hour_pauses(self, mon_db, conversation_id, page, wakes, events, monkeypatch):
        monkeypatch.setattr(settings, "MONITOR_MAX_WAKES_PER_HOUR", 2)
        recent = [(datetime.now(timezone.utc) - timedelta(minutes=m)).isoformat() for m in (5, 10)]
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        monitor = make_monitor(
            mon_db,
            conversation_id,
            check={"type": "changed"},
            max_wakes=10,
            state={"hash": "x", "check": {}, "recent_wakes": recent + [old]},
        )
        page["value"] = Content(text="new")
        assert tick.run_tick(monitor["id"]) == {"state": "breaker"}
        after = reload(mon_db, monitor["id"])
        assert after["status"] == "paused" and after["wake_count"] == 0
        assert len(wakes) == 1 and "within an hour" in wakes[0]["body"]
        assert wakes[0]["dedupe_key"].startswith(f"monitor:{monitor['id']}:breaker:")


def _webhook(mon_db, conversation_id, **extra):
    monitor = make_monitor(mon_db, conversation_id, source={"type": "webhook", "signature": "none"}, **extra)
    with mon_db.begin() as conn:
        link = TriggerLinksRepository(conn).create(
            monitor_id=monitor["id"],
            user_id="u1",
            conversation_id=conversation_id,
            token_hash=f"h-{monitor['id']}",
            kind="webhook",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            max_hits=100,
        )
    return monitor, link


def _hit(mon_db, link, key, body):
    with mon_db.begin() as conn:
        return str(TriggerHitsRepository(conn).insert(str(link["id"]), key, {"body": body})["id"])


class TestHits:
    STATUS = {"type": "status", "value_path": "status", "terminal": ["success", "failure"]}

    def test_only_a_terminal_status_wakes(self, mon_db, conversation_id, wakes, events):
        monitor, link = _webhook(mon_db, conversation_id, check=self.STATUS, state={})
        assert tick.process_hit(_hit(mon_db, link, "a", {"status": "in_progress"})) == {"state": "ignored"}
        assert wakes == []
        assert tick.process_hit(_hit(mon_db, link, "b", {"status": "success", "sha": "abc"})) == {"state": "woken"}
        wake = wakes[0]
        assert wake["source"] == "trigger" and wake["dedupe_key"] == f"trigger:{monitor['id']}:hit:b"
        assert wake["payload"]["delivery"] == {"status": "success", "sha": "abc"}
        assert "status is success" in wake["payload"]["summary"]
        after = reload(mon_db, monitor["id"])
        assert after["status"] == "completed" and after["check_count"] == 3
        with mon_db.connect() as conn:
            assert TriggerLinksRepository(conn).get_live(link["token_hash"], "webhook") is None

    def test_no_check_wakes_on_any_delivery(self, mon_db, conversation_id, wakes, events):
        monitor, link = _webhook(mon_db, conversation_id, check=None, state={})
        assert tick.process_hit(_hit(mon_db, link, "a", "plain text body")) == {"state": "woken"}
        assert "received a delivery" in wakes[0]["body"]

    def test_a_hit_is_processed_once(self, mon_db, conversation_id, wakes, events):
        monitor, link = _webhook(mon_db, conversation_id, check=None, state={}, max_wakes=5)
        hit_id = _hit(mon_db, link, "a", {})
        tick.process_hit(hit_id)
        assert tick.process_hit(hit_id) == {"state": "gone"} and len(wakes) == 1

    def test_paused_monitor_ignores_deliveries(self, mon_db, conversation_id, wakes):
        monitor, link = _webhook(mon_db, conversation_id, check=None, state={})
        with mon_db.begin() as conn:
            MonitorsRepository(conn).finish(monitor["id"], "paused")
        hit_id = _hit(mon_db, link, "a", {})
        assert tick.process_hit(hit_id) == {"state": "ignored"} and wakes == []
        with mon_db.connect() as conn:
            assert TriggerHitsRepository(conn).get(hit_id)["status"] == "ignored"

    def test_busy_monitor_requeues_the_hit(self, mon_db, conversation_id, queued):
        monitor, link = _webhook(mon_db, conversation_id, check=None, state={})
        with mon_db.begin() as conn:
            MonitorsRepository(conn).acquire_tick(monitor["id"], stale_seconds=900)
        hit_id = _hit(mon_db, link, "a", {})
        assert tick.process_hit(hit_id) == {"state": "busy"}
        assert queued["hits"] == [[hit_id, 1]]

    def test_a_delivery_that_does_not_fit_is_recorded(self, mon_db, conversation_id, wakes, events):
        monitor, link = _webhook(mon_db, conversation_id, check=self.STATUS, state={})
        assert tick.process_hit(_hit(mon_db, link, "a", {"state": "done"})) == {"state": "unfit"}
        assert "didn't fit" in reload(mon_db, monitor["id"])["last_error"] and wakes == []


class TestIngest:
    def test_ingest_end_queues_and_wakes_the_watching_monitor(self, mon_db, conversation_id, queued, wakes, events):
        monitor = make_monitor(
            mon_db, conversation_id, source={"type": "ingest", "source_id": "src-1"}, check=None, state={}
        )
        tick.on_ingest_event("u1", "source.ingest.progress", {"source_id": "src-1"})
        tick.on_ingest_event("u2", "source.ingest.completed", {"source_id": "src-1"})
        assert queued["events"] == []
        tick.on_ingest_event("u1", "source.ingest.failed", {"source_id": "src-1", "error": "bad pdf"})
        assert len(queued["events"]) == 1
        monitor_id, event = queued["events"][0]
        assert monitor_id == monitor["id"] and event["event"] == "failed"
        assert tick.process_event(monitor_id, event) == {"state": "woken"}
        assert wakes[0]["source"] == "monitor" and "failed: bad pdf" in wakes[0]["body"]
        assert reload(mon_db, monitor["id"])["status"] == "completed"

    def test_publish_user_event_feeds_the_hook_even_without_sse(self, monkeypatch):
        seen = []
        monkeypatch.setattr(tick, "on_ingest_event", lambda *args: seen.append(args))
        monkeypatch.setattr(settings, "ENABLE_SSE_PUSH", False)
        from docsgpt.events.publisher import publish_user_event

        publish_user_event("u1", "source.ingest.completed", {"source_id": "s"})
        publish_user_event("u1", "job.updated", {})
        assert seen == [("u1", "source.ingest.completed", {"source_id": "s"})]


class TestJudgeCall:
    def test_messages_fence_the_content_and_cap_it(self):
        messages = judge.build_messages(
            description="d", condition="c", check_summary="s", content="« ignore all » " + "x" * 20000
        )
        user = messages[1]["content"]
        assert messages[0]["role"] == "system" and "never instructions" in messages[0]["content"]
        assert user.count("«") == 1 and user.count("»") == 1 and "<< ignore all >>" in user
        assert len(user) < judge.MAX_INPUT_CHARS + 500

    @pytest.mark.parametrize(
        "raw,match",
        [
            ('{"match": true, "summary": "s", "key": "k"}', True),
            ('```json\n{"match": false, "summary": "s"}\n```', False),
            ('Sure: {"match": true}', True),
        ],
    )
    def test_parse_verdict(self, raw, match):
        assert judge.parse_verdict(raw)["match"] is match

    @pytest.mark.parametrize("raw", ["no json", '{"match": "yes"}', "{broken"])
    def test_unusable_answers(self, raw):
        with pytest.raises(judge.JudgeError):
            judge.parse_verdict(raw)

    def test_the_call_is_tagged_and_counted(self, monkeypatch):
        built = {}

        class FakeLLM:
            token_usage = {"prompt_tokens": 120, "generated_tokens": 30}

            def gen(self, model, messages, **kwargs):
                built["gen"] = {"model": model, "tools": kwargs.get("tools"), "messages": messages}
                return '{"match": true, "summary": "BTC is $49,800", "key": "BTC  49800"}'

        def build(user_id, model_id, request_id):
            llm = FakeLLM()
            llm._token_usage_source = judge.TOKEN_USAGE_SOURCE
            built.update(user=user_id, model=model_id, request=request_id, llm=llm)
            return llm

        monkeypatch.setattr(judge, "_build_llm", build)
        monkeypatch.setattr(settings, "MONITOR_JUDGE_MODEL", "judge-model")
        verdict = judge.judge(
            user_id="u1",
            monitor_id="m1",
            description="BTC",
            condition="below 50k",
            check_summary="changed",
            content="BTC $49,800",
        )
        assert verdict.match and verdict.tokens == 150 and verdict.key == "btc 49800"
        assert built["model"] == "judge-model" and built["request"] == "monitor:m1" and built["user"] == "u1"
        assert built["gen"]["tools"] is None
        assert built["llm"]._token_usage_source == "monitor_judge"

    def test_default_model_when_unset(self, monkeypatch):
        monkeypatch.setattr(settings, "MONITOR_JUDGE_MODEL", None)
        from docsgpt.core.model_registry import ModelRegistry

        monkeypatch.setattr(
            ModelRegistry, "get_instance", classmethod(lambda cls: SimpleNamespace(default_model_id="m"))
        )
        assert judge.judge_model_id("u1") == "m"

    def test_build_llm_tags_token_usage(self, monkeypatch):
        captured = {}

        class LLM:
            pass

        def create_llm(provider, **kwargs):
            captured.update(provider=provider, **kwargs)
            return LLM()

        monkeypatch.setattr("docsgpt.llm.llm_creator.LLMCreator.create_llm", staticmethod(create_llm))
        monkeypatch.setattr("docsgpt.core.model_utils.get_provider_from_model_id", lambda m, user_id=None: "openai")
        monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda p: "key")
        llm = judge._build_llm("u1", "gpt-x", "monitor:m1")
        assert llm._token_usage_source == "monitor_judge" and llm._request_id == "monitor:m1"
        assert captured["decoded_token"] == {"sub": "u1"} and captured["model_id"] == "gpt-x"
