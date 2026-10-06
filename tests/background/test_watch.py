"""Job watch: patterns that wake mid-run, progress, heartbeats."""

from __future__ import annotations

import time

import pytest

from docsgpt.background import continuation, jobs, watch
from docsgpt.background.context import BackgroundContext
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository


class TestNormalize:
    def test_cleans_and_bounds(self):
        spec = watch.normalize(
            {
                "patterns": ["Error", "(", "x" * 300, *[f"p{i}" for i in range(9)]],
                "progress_regex": "P (\\d+)%",
                "heartbeat_s": 5,
            }
        )
        assert spec["patterns"] == ["Error", "p0", "p1", "p2", "p3"]
        assert spec["progress_regex"] == "P (\\d+)%"
        assert spec["heartbeat_s"] == 60

    def test_nothing_usable(self):
        assert watch.normalize({"patterns": ["("], "heartbeat_s": 0}) is None
        assert watch.normalize("Error") is None
        assert watch.normalize({"patterns": "Traceback"}) == {"patterns": ["Traceback"]}


class TestProgress:
    def test_last_match_and_percent(self):
        spec = {"progress_regex": "PROGRESS (\\d+)%"}
        progress = watch.progress_from(spec, "PROGRESS 10%\nwork\nPROGRESS 55%\n")
        assert progress == {"last": "PROGRESS 55%", "percent": 55}
        assert watch.progress_from(spec, "nothing") is None
        assert watch.progress_from({"progress_regex": "step \\w+"}, "step one") == {"last": "step one"}

    def test_catastrophic_pattern_is_abandoned(self):
        started = time.monotonic()
        assert watch.progress_from({"progress_regex": "(a+)+$"}, "a" * 40 + "b") is None
        assert time.monotonic() - started < 2


def _running_job(conversation_id, message_id, spec, *, auto_resume=True):
    context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=message_id)
    context._auto_resume = auto_resume
    row, _ = jobs.create_job(
        context, tool_name="code_executor", action_name="run_code", journal_key=f"k-{time.monotonic_ns()}",
        arguments={}, runner="sandbox", watch=spec,
    )
    return row


def _reload(engine, job_id):
    with engine.connect() as conn:
        return BackgroundJobsRepository(conn).get(job_id)


@pytest.fixture()
def wakes(monkeypatch):
    sent = []
    monkeypatch.setattr("docsgpt.background.wake.wake_conversation", lambda **kw: sent.append(kw))
    monkeypatch.setattr(watch, "publish_job_updated", lambda row: None)
    return sent


class TestObserve:
    def test_pattern_wakes_once_per_new_output(self, bg_db, conversation, wakes):
        job = _running_job(*conversation, {"patterns": ["Traceback"]})
        watch.observe_output(job, "start\n", 6)
        assert wakes == []
        output = "start\nTraceback (most recent call last):\n  boom\n"
        watch.observe_output(_reload(bg_db, job["id"]), output, len(output))
        assert len(wakes) == 1
        assert wakes[0]["source"] == "job"
        assert wakes[0]["payload"]["line"] == "Traceback (most recent call last):"
        assert wakes[0]["dedupe_key"].startswith(f"job:{job['id']}:watch:")
        assert "still running" in wakes[0]["body"]
        assert "don't predict how it will end" in wakes[0]["body"]
        assert "cancel it with check_job" in wakes[0]["body"]
        # The same output again is not new.
        watch.observe_output(_reload(bg_db, job["id"]), output, len(output))
        assert len(wakes) == 1
        assert _reload(bg_db, job["id"])["output_tail"] == output

    def test_strikes_and_lifetime_cap_turn_patterns_off(self, bg_db, conversation, wakes, monkeypatch):
        job = _running_job(*conversation, {"patterns": ["E"]})
        size = 0
        for _ in range(5):
            size += 2
            watch.observe_output(_reload(bg_db, job["id"]), "E\n" * (size // 2), size)
        state = _reload(bg_db, job["id"])["external"]["watch_state"]
        assert len(wakes) == 1
        assert state["strikes"] == 3
        assert state["patterns_off"] is True

        job2 = _running_job(conversation[0], None, {"patterns": ["E"]})
        monkeypatch.setattr(watch, "MIN_WAKE_GAP_SECONDS", 0)
        size = 0
        for _ in range(12):
            size += 2
            watch.observe_output(_reload(bg_db, job2["id"]), "E\n" * (size // 2), size)
        assert len([w for w in wakes if w["ref_id"] == job2["id"]]) == watch.MAX_PATTERN_WAKES

    def test_progress_updates_without_waking(self, bg_db, conversation, wakes):
        job = _running_job(*conversation, {"progress_regex": "PROGRESS (\\d+)%"})
        watch.observe_output(job, "PROGRESS 40%\n", 13)
        assert wakes == []
        progress = _reload(bg_db, job["id"])["progress"]
        assert progress["percent"] == 40
        assert progress["last"] == "PROGRESS 40%"

    def test_heartbeat_sends_new_output(self, bg_db, conversation, wakes, monkeypatch):
        job = _running_job(*conversation, {"heartbeat_s": 60})
        monkeypatch.setattr(watch, "job_start", lambda row: time.time() - 120)
        watch.observe_output(job, "line 1\nline 2\n", 14)
        assert len(wakes) == 1
        assert wakes[0]["payload"]["output"] == "line 1\nline 2\n"
        assert wakes[0]["dedupe_key"] == f"job:{job['id']}:heartbeat:14"
        # Within the interval nothing is sent.
        watch.observe_output(_reload(bg_db, job["id"]), "line 1\nline 2\nline 3\n", 21)
        assert len(wakes) == 1

    def test_poll_only_jobs_never_wake(self, bg_db, conversation, wakes):
        job = _running_job(*conversation, {"patterns": ["E"]}, auto_resume=False)
        watch.observe_output(job, "E\n", 2)
        assert wakes == []


class TestFinalProgress:
    def test_a_non_detached_job_reads_progress_from_its_result(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        job = _running_job(*conversation, {"progress_regex": "done (\\d+)%"})
        jobs.complete_from_tool(job["id"], tool=object(), action_name="a", parameters={}, value="done 100%")
        assert _reload(bg_db, job["id"])["progress"]["percent"] == 100


def test_watch_wakes_do_not_take_the_final_result():
    assert continuation.is_final_job_event({"source": "job", "ref_id": "j", "dedupe_key": "job:j:final"})
    assert not continuation.is_final_job_event({"source": "job", "ref_id": "j", "dedupe_key": "job:j:watch:5:E"})
    assert continuation.is_final_job_event({"source": "lost", "ref_id": "j", "dedupe_key": "job:j:final"})
