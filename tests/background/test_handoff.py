"""Tests for the yield-then-hand-off protocol (no database: the job writes are faked)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from docsgpt.background import handoff, pool
from docsgpt.background.context import BackgroundContext


@pytest.fixture()
def ctx():
    context = BackgroundContext(user_id="u1", conversation_id="c1", origin_message_id="m1")
    context._auto_resume = True
    return context


@pytest.fixture()
def fake_jobs(monkeypatch):
    """Record job writes instead of touching Postgres."""
    state = SimpleNamespace(created=[], completed=[], caps=True, fail_create=False, done=threading.Event())

    def create_job(context, **kwargs):
        if state.fail_create:
            raise RuntimeError("db down")
        state.created.append(kwargs)
        return {"id": "job-1", "auto_resume": context.auto_resume()}, True

    def complete_from_tool(job_id, **kwargs):
        state.completed.append((job_id, kwargs))
        state.done.set()

    monkeypatch.setattr(handoff.jobs, "create_job", create_job)
    monkeypatch.setattr(handoff.jobs, "complete_from_tool", complete_from_tool)
    monkeypatch.setattr(handoff.jobs, "within_caps", lambda context: state.caps)
    monkeypatch.setattr(pool, "hold", lambda job_id: None)
    return state


def _spec(**overrides):
    fields = {"tool_name": "read_webpage", "action_name": "read", "journal_key": "m1:c1", "arguments": {"url": "u"}}
    fields.update(overrides)
    return handoff.CallSpec(**fields)


class TestSplitControls:
    def test_controls_are_removed_from_the_tool_arguments(self):
        args, controls = handoff.split_controls({"code": "x", "background": True, "watch": {"patterns": ["E"]}})
        assert args == {"code": "x"}
        assert controls == {"background": True, "watch": {"patterns": ["E"]}}

    def test_untouched_without_controls(self):
        args = {"code": "x"}
        assert handoff.split_controls(args) == (args, {})
        assert handoff.split_controls("raw") == ("raw", {})

    @pytest.mark.parametrize("value,expected", [(True, True), ("true", True), ("no", False), (None, False)])
    def test_wants_background(self, value, expected):
        assert handoff.wants_background({"background": value}) is expected


class TestEligible:
    def test_needs_a_context(self, ctx):
        executor = SimpleNamespace(background=None, headless=False, workflow_run_id=None)
        assert handoff.eligible(executor, {"name": "read_webpage"}) is False
        executor.background = ctx
        assert handoff.eligible(executor, {"name": "read_webpage"}) is True

    def test_excludes_headless_workflow_client_and_internal_tools(self, ctx):
        base = {"background": ctx, "headless": False, "workflow_run_id": None}
        assert not handoff.eligible(SimpleNamespace(**{**base, "headless": True}), {"name": "x"})
        assert not handoff.eligible(SimpleNamespace(**{**base, "workflow_run_id": "w"}), {"name": "x"})
        assert not handoff.eligible(SimpleNamespace(**base), {"name": "x", "client_side": True})
        assert not handoff.eligible(SimpleNamespace(**base), {"name": "check_job"})


    def test_a_continuation_turn_may_hand_off_though_it_is_headless(self, ctx):
        woken = BackgroundContext(user_id="u1", conversation_id="c1", origin_message_id="m2", continuation=True)
        executor = SimpleNamespace(background=woken, headless=True, workflow_run_id=None)
        assert handoff.eligible(executor, {"name": "read_webpage"}) is True
        assert not handoff.eligible(SimpleNamespace(background=woken, headless=True, workflow_run_id="w"),
                                    {"name": "read_webpage"})
        assert not handoff.eligible(executor, {"name": "monitor"})


class TestRunCall:
    def test_fast_call_returns_its_value_and_writes_no_job(self, ctx, fake_jobs):
        outcome = handoff.run_call(ctx, _spec(), object(), lambda: {"ok": 1}, yield_seconds=5)
        assert outcome.handed_off is False
        assert outcome.value == {"ok": 1}
        assert fake_jobs.created == []

    def test_fast_call_exception_propagates(self, ctx, fake_jobs):
        def boom():
            raise ValueError("bad")

        with pytest.raises(ValueError, match="bad"):
            handoff.run_call(ctx, _spec(), object(), boom, yield_seconds=5)
        assert fake_jobs.created == []

    def test_slow_call_is_handed_off_and_finished_by_the_pool_thread(self, ctx, fake_jobs):
        release = threading.Event()

        def slow():
            release.wait(5)
            return "late result"

        tool = object()
        outcome = handoff.run_call(ctx, _spec(parameters={"url": "u"}), tool, slow, yield_seconds=0.05)
        assert outcome.handed_off is True
        assert outcome.payload["status"] == "running"
        assert outcome.payload["job_id"] == "job-1"
        assert "resumed automatically" in outcome.payload["note"]
        assert fake_jobs.created[0]["journal_key"] == "m1:c1"
        assert fake_jobs.completed == []
        release.set()
        assert fake_jobs.done.wait(5)
        job_id, kwargs = fake_jobs.completed[0]
        assert job_id == "job-1"
        assert kwargs["value"] == "late result"
        assert kwargs["error"] is None
        assert kwargs["tool"] is tool
        assert kwargs["parameters"] == {"url": "u"}

    def test_slow_call_that_raises_records_the_error_on_the_job(self, ctx, fake_jobs):
        release = threading.Event()

        def slow():
            release.wait(5)
            raise RuntimeError("upstream 502")

        outcome = handoff.run_call(ctx, _spec(), object(), slow, yield_seconds=0.05)
        assert outcome.handed_off is True
        release.set()
        assert fake_jobs.done.wait(5)
        assert isinstance(fake_jobs.completed[0][1]["error"], RuntimeError)

    def test_over_the_cap_the_call_stays_in_the_foreground(self, ctx, fake_jobs):
        fake_jobs.caps = False

        def slow():
            time.sleep(0.2)
            return "done"

        outcome = handoff.run_call(ctx, _spec(), object(), slow, yield_seconds=0.01)
        assert outcome.handed_off is False
        assert outcome.value == "done"
        assert fake_jobs.created == []

    def test_a_failed_job_write_keeps_the_call_in_the_foreground(self, ctx, fake_jobs):
        fake_jobs.fail_create = True

        def slow():
            time.sleep(0.2)
            return "done"

        outcome = handoff.run_call(ctx, _spec(), object(), slow, yield_seconds=0.01)
        assert outcome.handed_off is False
        assert outcome.value == "done"
        assert fake_jobs.completed == []

    def test_a_call_that_finished_at_the_boundary_is_not_handed_off(self, ctx, fake_jobs, monkeypatch):
        finished = threading.Event()

        def quick():
            finished.set()
            return "made it"

        real_caps = handoff.jobs.within_caps

        def slow_caps(context):
            # The call finishes while the request thread decides.
            finished.wait(5)
            time.sleep(0.05)
            return real_caps(context)

        monkeypatch.setattr(handoff.jobs, "within_caps", slow_caps)
        started = threading.Event()

        def gated():
            started.set()
            time.sleep(0.05)
            return quick()

        outcome = handoff.run_call(ctx, _spec(), object(), gated, yield_seconds=0.001)
        assert outcome.handed_off is False
        assert outcome.value == "made it"
        assert fake_jobs.created == []

    def test_explicit_background_hands_off_at_once(self, ctx, fake_jobs):
        release = threading.Event()
        outcome = handoff.run_call(ctx, _spec(), object(), lambda: release.wait(5) and "x", yield_seconds=0)
        assert outcome.handed_off is True
        release.set()
        assert fake_jobs.done.wait(5)

    def test_a_full_pool_runs_the_call_inline(self, ctx, fake_jobs, monkeypatch):
        monkeypatch.setattr(pool, "try_submit", lambda fn: None)
        caller = threading.current_thread()
        seen = []
        outcome = handoff.run_call(ctx, _spec(), object(), lambda: seen.append(threading.current_thread()) or 1)
        assert outcome.value == 1
        assert seen == [caller]
