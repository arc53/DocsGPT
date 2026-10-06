"""The device runner's poll chain, against a real database and an in-memory device broker."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.background import device_runner, jobs, reconciler
from docsgpt.background.context import BackgroundContext
from docsgpt.devices.broker import DeviceBroker
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.devices import DevicesRepository
from tests.devices.conftest import FakeRedis

DEVICE_ID = "dev_bg"


@pytest.fixture()
def fake_redis():
    return FakeRedis()


@pytest.fixture()
def broker(monkeypatch, fake_redis):
    monkeypatch.setattr("docsgpt.devices.broker.get_redis_instance", lambda: fake_redis)
    instance = DeviceBroker()
    monkeypatch.setattr(device_runner, "_broker", lambda: instance)
    return instance


@pytest.fixture()
def polls(monkeypatch):
    queued = []
    monkeypatch.setattr(device_runner, "enqueue_poll", lambda job_id, countdown: queued.append((job_id, countdown)))
    return queued


@pytest.fixture()
def delivered(monkeypatch):
    out = []
    monkeypatch.setattr(jobs, "_deliver", out.append)
    return out


@pytest.fixture()
def published(monkeypatch):
    out = []
    monkeypatch.setattr(device_runner, "publish_job_updated", out.append)
    return out


@pytest.fixture()
def device(bg_db):
    with bg_db.begin() as conn:
        DevicesRepository(conn).create(
            DEVICE_ID, "u1", "build box", machine_pubkey_fingerprint="fp", token_hash="th"
        )
    _seen(bg_db, seconds_ago=1)
    _caps(bg_db, "cancel")
    return DEVICE_ID


def _caps(engine, value):
    with engine.begin() as conn:
        conn.execute(text("UPDATE devices SET capabilities = :c WHERE id = :id"), {"c": value, "id": DEVICE_ID})


def _seen(engine, *, seconds_ago):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE devices SET last_seen_at = now() - make_interval(secs => :s) WHERE id = :id"),
            {"s": seconds_ago, "id": DEVICE_ID},
        )


def _start(bg_db, conversation, broker, *, timeout_ms=60_000, watch=None, dispatched_ago=0.0):
    conversation_id, message_id = conversation
    context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=message_id)
    context._auto_resume = True
    row, _ = jobs.create_job(
        context,
        tool_name="remote_device",
        action_name="run_command",
        journal_key=f"{message_id}:c1",
        arguments={"command": "make"},
        watch=watch,
    )
    broker.dispatch_invocation(
        DEVICE_ID, "u1", {"invocation_id": "inv_1", "action": "run_command", "params": {"command": "make"}}
    )
    external = {
        "invocation_id": "inv_1",
        "device_id": DEVICE_ID,
        "device_name": "build box",
        "timeout_ms": timeout_ms,
        "dispatched_at": time.time() - dispatched_ago,
    }
    assert device_runner.detach_job(str(row["id"]), external) is True
    return str(row["id"])


def _started(fake_redis, *, seconds_ago):
    """Pretend the device took the command ``seconds_ago``."""
    fake_redis.hashes["dev:inv:inv_1"]["started_at"] = repr(time.time() - seconds_ago).encode()


def _job(bg_db, job_id):
    with bg_db.connect() as conn:
        return BackgroundJobsRepository(conn).get(job_id)


def _set(bg_db, job_id, **columns):
    sets = ", ".join(f"{name} = :{name}" for name in columns)
    with bg_db.begin() as conn:
        conn.execute(text(f"UPDATE background_jobs SET {sets} WHERE id = CAST(:id AS uuid)"), {**columns, "id": job_id})


def _merge_external(bg_db, job_id, fields):
    with bg_db.begin() as conn:
        BackgroundJobsRepository(conn).merge_external(job_id, fields)


class TestDetach:
    def test_moves_the_job_and_keeps_the_command_for_its_lifetime(
        self, bg_db, conversation, device, broker, fake_redis, polls, monkeypatch
    ):
        monkeypatch.setattr("docsgpt.core.settings.settings.DEVICE_JOB_MAX_SECONDS", 1800)
        job_id = _start(bg_db, conversation, broker)
        job = _job(bg_db, job_id)
        assert job["runner"] == "device"
        assert job["lease_owner"] is None
        lifetime = datetime.fromisoformat(str(job["deadline_at"])) - datetime.fromisoformat(str(job["started_at"]))
        assert lifetime.total_seconds() == pytest.approx(1800, abs=1)
        assert job["external"]["invocation_id"] == "inv_1"
        assert job["external"]["cursor"] == "0-0"
        assert polls == [(job_id, device_runner.FIRST_POLL_SECONDS)]
        assert fake_redis.ttls["dev:inv:inv_1"] == device_runner.key_ttl_seconds()
        assert fake_redis.ttls["dev:cmd:dev_bg"] >= device_runner.key_ttl_seconds()

    def test_a_finished_job_is_not_moved(self, bg_db, conversation, device, broker, polls):
        job_id = _start(bg_db, conversation, broker)
        jobs.finalize(job_id, status="cancelled", deliver=False)
        assert device_runner.detach_job(job_id, {"invocation_id": "inv_1"}) is False


class TestPoll:
    def test_running_output_reaches_the_job_and_polls_again(
        self, bg_db, conversation, device, broker, polls, delivered
    ):
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "building 1/3\n"})
        assert device_runner.poll_job(job_id) == {"state": "running"}
        job = _job(bg_db, job_id)
        assert job["status"] == "working"
        assert job["output_tail"] == "building 1/3\n"
        assert job["external"]["out_chars"] == len("building 1/3\n")
        assert job["external"]["cursor"] != "0-0"
        assert polls[-1][0] == job_id
        broker.submit_output_chunk("inv_1", {"stream": "stderr", "chunk": "warn\n"})
        device_runner.poll_job(job_id)
        assert _job(bg_db, job_id)["output_tail"] == "building 1/3\nwarn\n"

    def test_a_reported_command_finishes_the_job_with_the_foreground_result(
        self, bg_db, conversation, device, broker, fake_redis, polls, delivered
    ):
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "done\n"})
        broker.submit_output_chunk("inv_1", {"stream": "control", "exit_code": 2, "duration_ms": 900})
        state = device_runner.poll_job(job_id)
        assert state == {"state": "finished", "status": "completed"}
        job = _job(bg_db, job_id)
        result = json.loads(job["result"]["text"])
        assert result == {
            "exit_code": 2,
            "stdout": "done\n",
            "stderr": "",
            "duration_ms": 900,
            "device_name": "build box",
            "error": None,
        }
        assert job["output_tail"] == "done\n"
        assert [row["id"] for row in delivered] == [job["id"]]
        # The broker state is gone once the job has the result.
        assert "dev:inv:inv_1" not in fake_redis.hashes

    def test_a_denied_command_fails(self, bg_db, conversation, device, broker, polls, delivered):
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "denied", "denied_by_safety")
        assert device_runner.poll_job(job_id)["status"] == "failed"
        assert json.loads(_job(bg_db, job_id)["result"]["text"])["error"] == "denied"

    def test_watch_patterns_read_the_device_output(
        self, bg_db, conversation, device, broker, polls, delivered, monkeypatch
    ):
        woken = []
        monkeypatch.setattr("docsgpt.background.wake.wake_conversation", lambda **kw: woken.append(kw))
        job_id = _start(
            bg_db, conversation, broker, watch={"patterns": ["FAILED"], "progress_regex": r"step (\d+)%"}
        )
        broker.submit_ack("inv_1", "accepted")
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "step 40%\n"})
        device_runner.poll_job(job_id)
        assert _job(bg_db, job_id)["progress"]["percent"] == 40
        assert woken == []
        broker.submit_output_chunk("inv_1", {"stream": "stderr", "chunk": "test_x FAILED\n"})
        device_runner.poll_job(job_id)
        assert len(woken) == 1
        assert woken[0]["source"] == "job"
        assert woken[0]["payload"]["line"] == "test_x FAILED"

    def test_an_offline_device_shows_waiting_then_resumes(
        self, bg_db, conversation, device, broker, polls, published, delivered
    ):
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        _seen(bg_db, seconds_ago=device_runner.OFFLINE_AFTER_SECONDS + 30)
        assert device_runner.poll_job(job_id) == {"state": "waiting"}
        job = _job(bg_db, job_id)
        assert job["progress"]["waiting_for"] == "device"
        assert job["status_message"] == device_runner.WAITING_NOTE
        assert polls[-1] == (job_id, device_runner.OFFLINE_POLL_SECONDS)
        assert published[-1]["progress"]["waiting_for"] == "device"
        # Still offline: no second event.
        device_runner.poll_job(job_id)
        assert len(published) == 1
        _seen(bg_db, seconds_ago=1)
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "back\n"})
        assert device_runner.poll_job(job_id) == {"state": "running"}
        job = _job(bg_db, job_id)
        assert job["progress"]["waiting_for"] is None
        assert job["status_message"] == ""
        assert job["output_tail"] == "back\n"
        assert published[-1]["progress"]["waiting_for"] is None

    def test_a_connected_device_that_never_reports_loses_the_job(
        self, bg_db, conversation, device, broker, polls, delivered, fake_redis
    ):
        job_id = _start(
            bg_db, conversation, broker, timeout_ms=1000, dispatched_ago=device_runner.REPORT_GRACE_SECONDS + 10
        )
        broker.submit_ack("inv_1", "accepted")
        _started(fake_redis, seconds_ago=device_runner.REPORT_GRACE_SECONDS + 10)
        assert device_runner.poll_job(job_id) == {"state": "lost"}
        job = _job(bg_db, job_id)
        assert job["status"] == "lost"
        assert "verify before retrying" in job["error"]["message"]
        assert "never reported" in job["status_message"]
        assert [row["id"] for row in delivered] == [job["id"]]

    def test_a_device_back_from_offline_gets_the_grace_to_report(
        self, bg_db, conversation, device, broker, polls, delivered, fake_redis
    ):
        job_id = _start(
            bg_db, conversation, broker, timeout_ms=1000, dispatched_ago=device_runner.REPORT_GRACE_SECONDS + 10
        )
        broker.submit_ack("inv_1", "accepted")
        _started(fake_redis, seconds_ago=device_runner.REPORT_GRACE_SECONDS + 10)
        _merge_external(bg_db, job_id, {"offline_since": time.time() - 600})
        assert device_runner.poll_job(job_id) == {"state": "running"}
        assert _job(bg_db, job_id)["external"]["online_since"] is not None

    def test_a_command_a_connected_device_never_picks_up_is_lost_and_unqueued(
        self, bg_db, conversation, device, broker, polls, delivered, fake_redis
    ):
        job_id = _start(bg_db, conversation, broker, dispatched_ago=device_runner.REPORT_GRACE_SECONDS + 10)
        assert device_runner.poll_job(job_id) == {"state": "lost"}
        assert fake_redis.llen("dev:cmd:dev_bg") == 0
        assert "never picked the command up" in _job(bg_db, job_id)["status_message"]

    def test_an_unpaired_device_loses_the_job(self, bg_db, conversation, device, broker, polls, delivered):
        job_id = _start(bg_db, conversation, broker)
        with bg_db.begin() as conn:
            conn.execute(text("UPDATE devices SET status = 'revoked' WHERE id = :id"), {"id": DEVICE_ID})
        assert device_runner.poll_job(job_id) == {"state": "lost"}
        assert "unpaired" in _job(bg_db, job_id)["status_message"]

    def test_a_vanished_invocation_loses_the_job(self, bg_db, conversation, device, broker, fake_redis, polls,
                                                 delivered):
        job_id = _start(bg_db, conversation, broker)
        fake_redis.delete("dev:inv:inv_1")
        assert device_runner.poll_job(job_id) == {"state": "lost"}

    def test_broker_trouble_retries_then_gives_up(self, bg_db, conversation, device, broker, polls, delivered,
                                                  monkeypatch):
        job_id = _start(bg_db, conversation, broker)

        def boom(*args, **kwargs):
            raise ConnectionError("redis down")

        monkeypatch.setattr(broker, "get_invocation", boom)
        assert device_runner.poll_job(job_id) == {"state": "retry"}
        assert _job(bg_db, job_id)["status"] == "working"
        _merge_external(bg_db, job_id, {"poll_failures": device_runner.MAX_POLL_FAILURES - 1})
        assert device_runner.poll_job(job_id) == {"state": "lost"}

    def test_a_job_on_another_runner_is_left_alone(self, bg_db, conversation, device, broker, polls):
        job_id = _start(bg_db, conversation, broker)
        _set(bg_db, job_id, runner="inprocess")
        assert device_runner.poll_job(job_id) == {"state": "gone"}


class TestDeadline:
    def test_offline_at_the_deadline_is_lost(self, bg_db, conversation, device, broker, polls, delivered):
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        _seen(bg_db, seconds_ago=device_runner.OFFLINE_AFTER_SECONDS + 30)
        _set(bg_db, job_id, deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert device_runner.poll_job(job_id) == {"state": "lost", "status": "lost"}
        job = _job(bg_db, job_id)
        assert job["status"] == "lost"
        assert "time limit" in job["status_message"]

    def test_online_at_the_deadline_is_stopped_and_fails(
        self, bg_db, conversation, device, broker, fake_redis, polls, delivered
    ):
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        fake_redis.lists.pop("dev:cmd:dev_bg", None)
        _set(bg_db, job_id, deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert device_runner.poll_job(job_id) == {"state": "finished", "status": "failed"}
        job = _job(bg_db, job_id)
        assert job["status"] == "failed"
        assert job["error"]["type"] == "TimeoutError"
        queued = [json.loads(item) for item in fake_redis.lists["dev:cmd:dev_bg"]]
        assert queued == [{"type": "cancel", "action": "cancel", "invocation_id": "inv_1"}]

    def test_a_report_that_landed_at_the_deadline_still_counts(
        self, bg_db, conversation, device, broker, polls, delivered
    ):
        job_id = _start(bg_db, conversation, broker)
        broker.submit_output_chunk("inv_1", {"stream": "control", "exit_code": 0})
        row = _job(bg_db, job_id)
        assert device_runner.on_deadline(row)["status"] == "completed"

    def test_the_sweep_ends_a_device_job_past_its_deadline(
        self, bg_db, conversation, device, broker, polls, delivered, monkeypatch
    ):
        monkeypatch.setattr("docsgpt.core.settings.settings.POSTGRES_URI", "postgresql://set")
        job_id = _start(bg_db, conversation, broker)
        _seen(bg_db, seconds_ago=device_runner.OFFLINE_AFTER_SECONDS + 30)
        _set(
            bg_db,
            job_id,
            deadline_at=datetime.now(timezone.utc) - timedelta(seconds=reconciler.DEADLINE_GRACE_SECONDS + 5),
        )
        summary = reconciler.sweep()
        assert summary["lost"] == 1
        assert _job(bg_db, job_id)["status"] == "lost"

    def test_the_sweep_restarts_a_broken_poll_chain(
        self, bg_db, conversation, device, broker, polls, delivered, monkeypatch
    ):
        monkeypatch.setattr("docsgpt.core.settings.settings.POSTGRES_URI", "postgresql://set")
        job_id = _start(bg_db, conversation, broker)
        polls.clear()
        _set(
            bg_db,
            job_id,
            heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=device_runner.POLL_STALE_SECONDS + 5),
        )
        summary = reconciler.sweep()
        assert summary["revived"] == 1
        assert polls == [(job_id, 0)]
        assert _job(bg_db, job_id)["attempts"] == 1

    def test_a_chain_that_keeps_breaking_is_given_up(
        self, bg_db, conversation, device, broker, fake_redis, polls, delivered, monkeypatch
    ):
        monkeypatch.setattr("docsgpt.core.settings.settings.POSTGRES_URI", "postgresql://set")
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        _set(
            bg_db,
            job_id,
            attempts=device_runner.MAX_REVIVES,
            heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=device_runner.POLL_STALE_SECONDS + 5),
        )
        reconciler.sweep()
        assert _job(bg_db, job_id)["status"] == "lost"
        assert any(b"cancel" in item for item in fake_redis.lists.get("dev:cmd:dev_bg", []))


class TestCancel:
    def test_a_command_still_queued_never_runs(self, bg_db, conversation, device, broker, fake_redis, polls,
                                               delivered):
        from docsgpt.background.service import cancel_job

        job_id = _start(bg_db, conversation, broker)
        polls.clear()
        cancel_job(job_id, "u1")
        assert polls == [(job_id, 0)]
        assert device_runner.poll_job(job_id) == {"state": "cancelled"}
        job = _job(bg_db, job_id)
        assert job["status"] == "cancelled"
        assert job["status_message"] == "cancelled before the device started it"
        assert fake_redis.llen("dev:cmd:dev_bg") == 0

    def test_a_running_command_is_told_to_stop_and_its_confirmation_ends_the_job(
        self, bg_db, conversation, device, broker, fake_redis, polls, delivered
    ):
        from docsgpt.background.service import cancel_job

        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        fake_redis.lists.pop("dev:cmd:dev_bg", None)
        cancel_job(job_id, "u1")
        assert device_runner.poll_job(job_id) == {"state": "cancelling"}
        queued = [json.loads(item) for item in fake_redis.lists["dev:cmd:dev_bg"]]
        assert queued == [{"type": "cancel", "action": "cancel", "invocation_id": "inv_1"}]
        assert device_runner.poll_job(job_id) == {"state": "cancelling"}
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "partial\n"})
        broker.submit_output_chunk("inv_1", {"stream": "control", "exit_code": -1, "error": "cancelled"})
        assert device_runner.poll_job(job_id) == {"state": "cancelled"}
        job = _job(bg_db, job_id)
        assert job["status"] == "cancelled"
        assert json.loads(job["result"]["text"])["stdout"] == "partial\n"

    def test_an_unconfirmed_cancel_ends_the_job_with_a_warning(
        self, bg_db, conversation, device, broker, fake_redis, polls, delivered
    ):
        from docsgpt.background.service import cancel_job

        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        cancel_job(job_id, "u1")
        device_runner.poll_job(job_id)
        _merge_external(bg_db, job_id, {"cancel_sent_at": time.time() - device_runner.CANCEL_CONFIRM_SECONDS - 1})
        assert device_runner.poll_job(job_id) == {"state": "cancelled"}
        job = _job(bg_db, job_id)
        assert job["status"] == "cancelled"
        assert "did not confirm" in job["status_message"]
        # The keys stay a while for the queued cancel, on the default TTL.
        assert "dev:inv:inv_1" in fake_redis.hashes


class TestThroughTheExecutor:
    """A ``background=true`` run_command, from the model's call to the resumed result."""

    def test_background_command_becomes_a_device_job_and_finishes(
        self, bg_db, conversation, device, broker, fake_redis, polls, delivered, monkeypatch
    ):
        from unittest.mock import Mock

        from docsgpt.agents.tool_executor import ToolExecutor
        from docsgpt.agents.tools import remote_device
        from docsgpt.agents.tools.remote_device import RemoteDeviceTool

        monkeypatch.setattr(remote_device, "get_broker", lambda: broker)
        with bg_db.begin() as conn:
            conn.execute(text("UPDATE devices SET approval_mode = 'full' WHERE id = :id"), {"id": DEVICE_ID})
        conversation_id, message_id = conversation
        tool = RemoteDeviceTool(config={"device_id": DEVICE_ID}, user_id="u1")
        tools = {
            "t1": {
                "id": "00000000-0000-0000-0000-0000000000dd",
                "name": "remote_device",
                "config": {"device_id": DEVICE_ID},
                "actions": tool.get_actions_metadata(),
            }
        }
        executor = ToolExecutor(user="u1")
        executor.conversation_id = conversation_id
        executor.message_id = message_id
        context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=message_id)
        context._auto_resume = True
        executor.background = context
        executor._name_to_tool = {"run_command": ("t1", "run_command")}
        monkeypatch.setattr(executor, "_get_or_load_tool", lambda *a, **k: tool)
        call = Mock()
        call.name = "run_command"
        call.id = "c1"
        call.arguments = json.dumps({"command": "make release", "background": True})
        call.thought_signature = None

        gen = executor.execute(tools, call, "OpenAILLM")
        events = []
        while True:
            try:
                events.append(next(gen))
            except StopIteration as stop:
                payload, call_id = stop.value
                break
        assert payload["status"] == "running"
        job_id = payload["job_id"]
        assert executor.tool_calls[-1]["job_id"] == job_id

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and _job(bg_db, job_id)["runner"] != "device":
            time.sleep(0.02)
        job = _job(bg_db, job_id)
        assert job["runner"] == "device"
        assert job["args"] == {"command": "make release"}
        invocation_id = job["external"]["invocation_id"]
        assert job["external"]["timeout_ms"] == device_runner.job_max_seconds() * 1000

        broker.submit_ack(invocation_id, "accepted")
        broker.submit_output_chunk(invocation_id, {"stream": "stdout", "chunk": "released v2\n"})
        broker.submit_output_chunk(invocation_id, {"stream": "control", "exit_code": 0, "duration_ms": 5})
        assert device_runner.poll_job(job_id)["status"] == "completed"
        job = _job(bg_db, job_id)
        assert json.loads(job["result"]["text"])["stdout"] == "released v2\n"
        assert [row["id"] for row in delivered] == [job["id"]]


class TestEdges:
    def test_timestamps_read_every_shape(self):
        assert device_runner._timestamp(datetime(2026, 1, 1)) == datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        assert device_runner._timestamp("2026-01-01T00:00:00Z") == datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        assert device_runner._timestamp("2026-01-01T00:00:00") == datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        assert device_runner._timestamp("not a time") is None
        assert device_runner._timestamp(12.5) == 12.5
        assert device_runner._timestamp(None) is None

    def test_a_device_never_seen_is_offline(self, bg_db, conversation, device, broker):
        with bg_db.begin() as conn:
            conn.execute(text("UPDATE devices SET last_seen_at = NULL WHERE id = :id"), {"id": DEVICE_ID})
        assert device_runner.device_state({"external": {"device_id": DEVICE_ID}, "user_id": "u1"}) == "offline"
        assert device_runner.device_state({"external": {"device_id": "nope"}, "user_id": "u1"}) == "gone"

    def test_a_job_that_lost_its_command_fails(self, bg_db, conversation, device, broker, polls, delivered):
        job_id = _start(bg_db, conversation, broker)
        with bg_db.begin() as conn:
            conn.execute(
                text("UPDATE background_jobs SET external = '{}'::jsonb WHERE id = CAST(:id AS uuid)"), {"id": job_id}
            )
        assert device_runner.poll_job(job_id) == {"state": "failed"}

    def test_a_failed_move_keeps_the_command_where_it_is(self, bg_db, conversation, broker, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(BackgroundJobsRepository, "set_runner", boom)
        assert device_runner.detach_job("00000000-0000-0000-0000-000000000001", {"invocation_id": "x"}) is False

    def test_a_poll_that_cannot_be_queued_is_left_to_the_sweep(self, monkeypatch):
        import docsgpt.api.user.tasks as tasks

        def refuse(*args, **kwargs):
            raise ConnectionError("broker down")

        monkeypatch.setattr(tasks.poll_background_device_job, "apply_async", refuse)
        device_runner.enqueue_poll("job-1", 1)  # logged, never raised

    def test_bookkeeping_failures_never_stop_the_poll(self, bg_db, conversation, device, broker, polls, delivered,
                                                      published, monkeypatch):
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "x\n"})

        def boom(*args, **kwargs):
            raise RuntimeError("db hiccup")

        monkeypatch.setattr(BackgroundJobsRepository, "update_progress", boom)
        monkeypatch.setattr(BackgroundJobsRepository, "touch", boom)
        _seen(bg_db, seconds_ago=device_runner.OFFLINE_AFTER_SECONDS + 30)
        assert device_runner.poll_job(job_id) == {"state": "waiting"}
        assert published == []

    def test_the_deadline_check_survives_an_unreadable_broker_and_device(
        self, bg_db, conversation, device, broker, polls, delivered, monkeypatch
    ):
        job_id = _start(bg_db, conversation, broker)

        def boom(*args, **kwargs):
            raise ConnectionError("down")

        monkeypatch.setattr(broker, "get_invocation", boom)
        monkeypatch.setattr(device_runner, "device_state", boom)
        done = device_runner.on_deadline(_job(bg_db, job_id))
        assert done["status"] == "lost"

    def test_cancel_detached_without_a_command_does_nothing(self, broker):
        device_runner.cancel_detached({"external": {}})

    def test_a_failed_poll_note_that_cannot_be_written_still_retries(
        self, bg_db, conversation, device, broker, polls, monkeypatch
    ):
        job_id = _start(bg_db, conversation, broker)

        def boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(device_runner, "_merge", boom)
        assert device_runner._poll_failed(job_id, {}, ConnectionError("x")) == {"state": "retry"}



class TestClientReports:
    """What docsgpt-cli 2 reports on the control chunk (arc53/DocsGPT-cli#14)."""

    def _report(self, bg_db, conversation, broker, **control):
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        broker.accept_output_chunk("inv_1", {"stream": "stdout", "chunk": "partial\n", "seq": 0}, dedupe=True)
        broker.accept_output_chunk("inv_1", {"stream": "control", "seq": 1, **control}, dedupe=True)
        device_runner.poll_job(job_id)
        return _job(bg_db, job_id)

    def test_an_interrupted_command_is_lost_with_its_pid(self, bg_db, conversation, device, broker, polls,
                                                         delivered):
        from docsgpt.background.results import job_notices
        from docsgpt.background.wake import job_event

        job = self._report(
            bg_db, conversation, broker, exit_code=-1, error="interrupted",
            detail="host restarted while it ran; process 4242 may still be running",
        )
        assert job["status"] == "lost"
        assert job["error"]["type"] == "DeviceInterrupted" and job["error"]["pid"] == 4242
        assert "may still be running on the machine (pid 4242)" in job["error"]["message"]
        assert json.loads(job["result"]["text"])["stdout"] == "partial\n"
        assert job_notices(job) == [{"code": "device_interrupted", "pid": 4242}]
        event = job_event(job)
        assert "pid 4242" in event["body"] and "verify before retrying" in event["body"].lower()

    def test_an_interrupted_report_without_a_pid(self, bg_db, conversation, device, broker, polls, delivered):
        job = self._report(bg_db, conversation, broker, exit_code=-1, error="interrupted")
        assert job["status"] == "lost" and "pid" not in job["error"]

    def test_a_host_shutdown_fails_the_job(self, bg_db, conversation, device, broker, polls, delivered):
        from docsgpt.background.results import job_notices

        job = self._report(bg_db, conversation, broker, exit_code=143, error="host_shutdown")
        assert job["status"] == "failed" and job["error"]["type"] == "HostShutdown"
        assert job_notices(job) == [{"code": "device_shutdown"}]

    def test_a_command_cancelled_on_the_device_is_cancelled(self, bg_db, conversation, device, broker, polls,
                                                            delivered):
        job = self._report(bg_db, conversation, broker, exit_code=-1, error="cancelled")
        assert job["status"] == "cancelled"

    def test_truncated_output_is_flagged(self, bg_db, conversation, device, broker, polls, delivered):
        from docsgpt.background.results import job_notices
        from docsgpt.background.service import job_summary

        job = self._report(bg_db, conversation, broker, exit_code=0, truncated=True)
        assert job["status"] == "completed" and job["result"]["truncated"] is True
        assert json.loads(job["result"]["text"])["truncated"] is True
        assert job_notices(job) == [{"code": "output_truncated"}]
        assert job_summary(job)["notices"] == [{"code": "output_truncated"}]

    def test_a_device_whose_client_cant_cancel_says_so_at_once(
        self, bg_db, conversation, device, broker, fake_redis, polls, delivered
    ):
        from docsgpt.background.service import cancel_job

        _caps(bg_db, "")
        job_id = _start(bg_db, conversation, broker)
        broker.submit_ack("inv_1", "accepted")
        cancel_job(job_id, "u1")
        assert device_runner.poll_job(job_id) == {"state": "cancelled"}
        job = _job(bg_db, job_id)
        assert job["status"] == "cancelled" and job["error"]["type"] == "CancelUnsupported"
        assert "Update docsgpt-cli" in job["error"]["message"]

    def test_an_outbox_client_gets_longer_to_send_a_late_report(
        self, bg_db, conversation, device, broker, fake_redis, polls, delivered
    ):
        _caps(bg_db, "cancel,outbox")
        job_id = _start(bg_db, conversation, broker, timeout_ms=1000,
                        dispatched_ago=device_runner.OUTBOX_REPORT_GRACE_SECONDS + 10)
        broker.submit_ack("inv_1", "accepted")
        _started(fake_redis, seconds_ago=device_runner.REPORT_GRACE_SECONDS + 10)
        assert device_runner.poll_job(job_id) == {"state": "running"}
        _started(fake_redis, seconds_ago=device_runner.OUTBOX_REPORT_GRACE_SECONDS + 10)
        assert device_runner.poll_job(job_id) == {"state": "lost"}
