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


def _stream(fake, invocation_id="inv_1"):
    return [json.loads(fields[b"c"]) for _id, fields in fake.streams.get(f"dev:out:{invocation_id}", [])]


@pytest.mark.unit
class TestResentReports:
    """docsgpt-cli's outbox delivers at least once: a batch whose 200 was lost is sent again."""

    def test_an_outbox_clients_chunks_count_once_by_seq(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker)
        batch = [{"stream": "stdout", "chunk": f"line {n}\n", "seq": n} for n in range(3)]
        assert [broker.accept_output_chunk("inv_1", c, dedupe=True) for c in batch] == ["accepted"] * 3
        # The same batch again, then a batch overlapping it.
        assert [broker.accept_output_chunk("inv_1", c, dedupe=True) for c in batch] == ["duplicate"] * 3
        overlap = batch[2:] + [{"stream": "stderr", "chunk": "warn\n", "seq": 3}]
        assert [broker.accept_output_chunk("inv_1", c, dedupe=True) for c in overlap] == ["duplicate", "accepted"]
        assert [c["seq"] for c in _stream(fake)] == [0, 1, 2, 3]
        assert broker.get_invocation("inv_1").stdout_bytes == len("line 0\nline 1\nline 2\n")

    def test_an_older_client_is_not_deduplicated_by_seq(self, broker_env):
        # It posts stdout and stderr from two goroutines, so its seqs can arrive out of order; it never resends.
        broker, fake = broker_env
        _dispatch(broker)
        assert broker.accept_output_chunk("inv_1", {"stream": "stderr", "chunk": "b", "seq": 5}) == "accepted"
        assert broker.accept_output_chunk("inv_1", {"stream": "stdout", "chunk": "a", "seq": 4}) == "accepted"
        assert [c["chunk"] for c in _stream(fake)] == ["b", "a"]

    def test_the_final_report_is_taken_once_whatever_the_client(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker)
        first = {"stream": "control", "exit_code": 2, "duration_ms": 10, "seq": 9}
        assert broker.accept_output_chunk("inv_1", first) == "accepted"
        assert broker.accept_output_chunk("inv_1", {**first, "exit_code": 0}) == "duplicate"
        assert broker.accept_output_chunk("inv_1", {**first, "seq": 10}, dedupe=True) == "duplicate"
        inv = broker.get_invocation("inv_1")
        assert inv.completed and inv.exit_code == 2
        assert [c["stream"] for c in _stream(fake)] == ["control"]

    def test_a_device_report_after_a_server_side_denial_still_lands(self, broker_env):
        broker, fake = broker_env
        _dispatch(broker)
        broker.submit_ack("inv_1", "denied", "denied_by_safety")
        control = {"stream": "control", "exit_code": 0, "error": "command_blocked_by_denylist", "seq": 0}
        assert broker.accept_output_chunk("inv_1", control, dedupe=True) == "accepted"
        assert [c.get("error") for c in _stream(fake)] == ["denied", "command_blocked_by_denylist"]

    def test_truncation_and_detail_are_kept_on_the_invocation(self, broker_env):
        broker, _ = broker_env
        _dispatch(broker)
        broker.accept_output_chunk("inv_1", {
            "stream": "control", "exit_code": -1, "error": "interrupted", "truncated": True,
            "detail": "daemon restarted; process 4242 may still be running", "seq": 3,
        })
        inv = broker.get_invocation("inv_1")
        assert inv.truncated is True and "4242" in inv.detail and inv.error == "interrupted"

    def test_junk_numbers_do_not_break_a_report(self, broker_env):
        broker, _ = broker_env
        _dispatch(broker)
        assert broker.accept_output_chunk(
            "inv_1", {"stream": "control", "exit_code": "nope", "duration_ms": True}
        ) == "accepted"
        inv = broker.get_invocation("inv_1")
        assert inv.completed and inv.exit_code is None and inv.duration_ms is None

    def test_an_unknown_invocation_or_no_redis_is_unknown(self, broker_env, monkeypatch):
        broker, _ = broker_env
        assert broker.accept_output_chunk("inv_x", {"stream": "stdout", "chunk": "a"}) == "unknown"
        assert broker.submit_output_chunk("inv_x", {"stream": "stdout", "chunk": "a"}) is False
        monkeypatch.setattr("docsgpt.devices.broker.get_redis_instance", lambda: None)
        assert broker.accept_output_chunk("inv_1", {"stream": "stdout", "chunk": "a"}) == "unknown"

    def test_two_copies_of_a_batch_racing_land_once(self, broker_env):
        import threading

        broker, fake = broker_env
        _dispatch(broker)
        batch = [{"stream": "stdout", "chunk": f"{n}\n", "seq": n} for n in range(50)]
        batch.append({"stream": "control", "exit_code": 0, "seq": 50})

        def send():
            for chunk in batch:
                broker.accept_output_chunk("inv_1", chunk, dedupe=True)

        threads = [threading.Thread(target=send) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert [c["seq"] for c in _stream(fake)] == list(range(51))
