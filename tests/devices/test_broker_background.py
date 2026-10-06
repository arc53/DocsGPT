"""Broker support for background device jobs: long-lived keys, cancelling, reading output from a cursor."""

from __future__ import annotations

import json

import pytest

from docsgpt.core.settings import settings


def _dispatch(broker, invocation_id="inv_1", **kwargs):
    return broker.dispatch_invocation(
        "dev_1",
        "user_1",
        {"invocation_id": invocation_id, "action": "run_command", "params": {"command": "make"}},
        **kwargs,
    )


@pytest.mark.unit
class TestLifetime:
    def test_a_background_command_keeps_its_keys_for_its_own_ttl(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker, ttl_seconds=4500)
        assert fake.ttls["dev:inv:inv_1"] == 4500
        assert fake.ttls["dev:cmd:dev_1"] == 4500
        # Output arriving later re-applies the invocation's own TTL, never the short default.
        broker.submit_ack("inv_1", "accepted")
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "x\n"})
        assert fake.ttls["dev:inv:inv_1"] == 4500
        assert fake.ttls["dev:out:inv_1"] == 4500

    def test_a_foreground_command_keeps_the_default(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker)
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "x\n"})
        assert fake.ttls["dev:inv:inv_1"] == settings.REMOTE_DEVICE_INVOCATION_TTL_SECONDS
        assert fake.ttls["dev:out:inv_1"] == settings.REMOTE_DEVICE_INVOCATION_TTL_SECONDS

    def test_extend_then_retire(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker)
        assert broker.extend_invocation("inv_1", 4000) is True
        assert fake.ttls["dev:inv:inv_1"] == 4000
        assert fake.ttls["dev:cmd:dev_1"] == 4000
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "x\n"})
        assert fake.ttls["dev:out:inv_1"] == 4000
        broker.retire_invocation("inv_1")
        default = settings.REMOTE_DEVICE_INVOCATION_TTL_SECONDS
        assert fake.ttls["dev:inv:inv_1"] == default
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "y\n"})
        assert fake.ttls["dev:out:inv_1"] == default

    def test_extending_a_gone_invocation_says_so(self, broker_env):
        broker, _ = broker_env
        assert broker.extend_invocation("inv_missing", 4000) is False

    def test_a_ttl_below_the_default_never_shortens_it(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker, ttl_seconds=5)
        assert fake.ttls["dev:inv:inv_1"] == settings.REMOTE_DEVICE_INVOCATION_TTL_SECONDS


@pytest.mark.unit
class TestCancel:
    def test_a_command_the_device_never_took_is_taken_off_the_queue(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker)
        assert broker.request_cancel("inv_1") == "unqueued"
        assert fake.llen("dev:cmd:dev_1") == 0

    def test_a_running_command_gets_a_cancel_envelope(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker)
        assert broker.claim_ticket("dev_1", 30)
        session = broker.register_session("dev_1", "user_1")
        assert broker.next_command(session, timeout=0.01)["invocation_id"] == "inv_1"
        broker.submit_ack("inv_1", "accepted")
        assert broker.request_cancel("inv_1") == "sent"
        queued = [json.loads(item) for item in fake.lists["dev:cmd:dev_1"]]
        assert queued == [{"type": "cancel", "action": "cancel", "invocation_id": "inv_1"}]
        assert broker.next_command(session, timeout=0.01)["type"] == "cancel"

    def test_a_cancel_for_a_reaped_invocation_is_dropped(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker)
        broker.submit_ack("inv_1", "accepted")
        fake.lists.pop("dev:cmd:dev_1", None)
        broker.request_cancel("inv_1")
        broker.cleanup_invocation("inv_1")
        session = broker.register_session("dev_1", "user_1")
        assert broker.next_command(session, timeout=0.01) is None

    def test_an_unknown_invocation_is_gone(self, broker_env):
        broker, _ = broker_env
        assert broker.request_cancel("inv_missing") == "gone"


@pytest.mark.unit
class TestReadOutput:
    def test_reads_from_a_cursor_without_blocking(self, broker_env):
        broker, _ = broker_env
        _dispatch(broker)
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "a\n"})
        broker.submit_output_chunk("inv_1", {"stream": "stderr", "chunk": "b\n"})
        chunks, cursor = broker.read_output("inv_1")
        assert [c["chunk"] for c in chunks] == ["a\n", "b\n"]
        assert broker.read_output("inv_1", cursor) == ([], cursor)
        broker.submit_output_chunk("inv_1", {"stream": "control", "exit_code": 0})
        chunks, _ = broker.read_output("inv_1", cursor)
        assert chunks == [{"stream": "control", "exit_code": 0}]

    def test_junk_entries_are_skipped(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker)
        fake.xadd("dev:out:inv_1", {"c": "not json"})
        fake.xadd("dev:out:inv_1", {"c": json.dumps({"stream": "other"})})
        broker.submit_output_chunk("inv_1", {"stream": "stdout", "chunk": "ok"})
        chunks, _ = broker.read_output("inv_1")
        assert chunks == [{"stream": "stdout", "chunk": "ok"}]


@pytest.mark.unit
class TestStrictRead:
    def test_strict_raises_without_redis(self, monkeypatch):
        from docsgpt.devices.broker import DeviceBroker

        monkeypatch.setattr("docsgpt.devices.broker.get_redis_instance", lambda: None)
        broker = DeviceBroker()
        assert broker.get_invocation("inv_1") is None
        with pytest.raises(RuntimeError):
            broker.get_invocation("inv_1", strict=True)

    def test_acked_after_the_device_answers(self, broker_env):
        broker, _ = broker_env
        _dispatch(broker)
        assert broker.get_invocation("inv_1").acked is False
        broker.submit_ack("inv_1", "accepted")
        assert broker.get_invocation("inv_1").acked is True
