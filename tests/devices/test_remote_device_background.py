"""``run_command`` as a background job: it follows its command, then hands it to the device runner."""

from __future__ import annotations

import threading
import time

import pytest

from docsgpt.agents.tools import remote_device
from docsgpt.agents.tools.remote_device import RemoteDeviceTool, clamp_timeout_ms
from docsgpt.background.handoff import DETACHED
from docsgpt.background.schema import add_background_params
from docsgpt.core.settings import settings

DEVICE = {"id": "dev_1", "user_id": "u1", "name": "laptop", "status": "active", "approval_mode": "full"}


class _Handle:
    """What a running tool sees of its background call."""

    def __init__(self, *, explicit=False, handed_off=False, accept=True):
        self.explicit = explicit
        self.handed_off = handed_off
        self.accept = accept
        self.detached = []

    def handoff_requested(self):
        return self.handed_off

    def wait(self, seconds):
        time.sleep(min(seconds, 0.01))

    def detach(self, external, *, runner="sandbox"):
        self.detached.append((runner, external))
        return self.accept


class _Ctx:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def tool(broker_env, monkeypatch):
    broker, fake = broker_env
    monkeypatch.setattr(remote_device, "get_broker", lambda: broker)
    monkeypatch.setattr(remote_device, "db_session", _Ctx)
    monkeypatch.setattr(remote_device, "db_readonly", _Ctx)

    class _Audit:
        def __init__(self, conn):
            pass

        def record_dispatch(self, **kwargs):
            pass

    class _Patterns:
        def __init__(self, conn):
            pass

        def has_pattern(self, *args):
            return False

    monkeypatch.setattr(remote_device, "DeviceAuditLogRepository", _Audit)
    monkeypatch.setattr(remote_device, "DeviceAutoApprovePatternsRepository", _Patterns)
    monkeypatch.setattr(RemoteDeviceTool, "_load_device", lambda self: dict(DEVICE))
    instance = RemoteDeviceTool(config={"device_id": "dev_1"}, user_id="u1")
    return instance, broker, fake


def _with_handle(monkeypatch, handle):
    monkeypatch.setattr(RemoteDeviceTool, "_background_call", staticmethod(lambda: handle))


def _invocation_id(fake):
    keys = [key for key in fake.hashes if key.startswith("dev:inv:")]
    assert len(keys) == 1
    return keys[0].split(":", 2)[2]


class TestTimeout:
    def test_foreground_cap_and_default(self):
        assert clamp_timeout_ms(None) == 30_000
        assert clamp_timeout_ms("junk") == 30_000
        assert clamp_timeout_ms(10**9) == 600_000
        assert clamp_timeout_ms(0) == 30_000
        assert clamp_timeout_ms(-5) == 1

    def test_background_goes_to_the_device_job_maximum(self, monkeypatch):
        monkeypatch.setattr(settings, "DEVICE_JOB_MAX_SECONDS", 3600)
        assert clamp_timeout_ms(None, background=True) == 3_600_000
        assert clamp_timeout_ms(10**9, background=True) == 3_600_000
        assert clamp_timeout_ms(900_000, background=True) == 900_000


class TestFollow:
    def test_a_quick_command_returns_its_result_in_the_turn(self, tool, monkeypatch):
        instance, broker, fake = tool
        handle = _Handle()
        _with_handle(monkeypatch, handle)

        def device():
            for _ in range(200):
                if any(key.startswith("dev:inv:") for key in fake.hashes):
                    break
                time.sleep(0.005)
            inv = _invocation_id(fake)
            broker.submit_ack(inv, "accepted")
            broker.submit_output_chunk(inv, {"stream": "stdout", "chunk": "hi\n"})
            broker.submit_output_chunk(inv, {"stream": "control", "exit_code": 0, "duration_ms": 3})

        worker = threading.Thread(target=device)
        worker.start()
        result = instance.execute_action("run_command", command="echo hi")
        worker.join()
        assert result == {
            "exit_code": 0,
            "stdout": "hi\n",
            "stderr": "",
            "duration_ms": 3,
            "device_name": "laptop",
            "error": None,
        }
        assert handle.detached == []
        assert not any(key.startswith("dev:inv:") for key in fake.hashes)

    def test_a_handed_off_command_moves_to_the_device_runner(self, tool, monkeypatch):
        instance, broker, fake = tool
        handle = _Handle(handed_off=True)
        _with_handle(monkeypatch, handle)
        result = instance.execute_action("run_command", command="make test", timeout_ms=120_000)
        assert result is DETACHED
        runner, external = handle.detached[0]
        assert runner == "device"
        assert external["invocation_id"] == _invocation_id(fake)
        assert external["device_id"] == "dev_1"
        assert external["device_name"] == "laptop"
        assert external["timeout_ms"] == 120_000
        assert external["dispatched_at"] <= time.time()
        # The command keeps its broker state for the poller.
        assert fake.llen("dev:cmd:dev_1") == 1

    def test_a_refused_detach_keeps_following(self, tool, monkeypatch):
        instance, broker, fake = tool
        handle = _Handle(handed_off=True, accept=False)
        _with_handle(monkeypatch, handle)

        def device():
            time.sleep(0.05)
            inv = _invocation_id(fake)
            broker.submit_output_chunk(inv, {"stream": "control", "exit_code": 1})

        worker = threading.Thread(target=device)
        worker.start()
        result = instance.execute_action("run_command", command="false")
        worker.join()
        assert result["exit_code"] == 1
        assert handle.detached

    def test_an_explicit_background_command_gets_the_job_lifetime(self, tool, monkeypatch):
        monkeypatch.setattr(settings, "DEVICE_JOB_MAX_SECONDS", 1200)
        instance, broker, fake = tool
        handle = _Handle(explicit=True, handed_off=True)
        _with_handle(monkeypatch, handle)
        assert instance.execute_action("run_command", command="./backup.sh") is DETACHED
        _runner, external = handle.detached[0]
        assert external["timeout_ms"] == 1_200_000
        inv = _invocation_id(fake)
        assert fake.ttls[f"dev:inv:{inv}"] == 1200 + remote_device.KEY_MARGIN_SECONDS
        queued = fake.lists["dev:cmd:dev_1"][0]
        assert b'"timeout_ms": 1200000' in queued

    def test_a_failed_dispatch_reports_at_once(self, tool, monkeypatch):
        instance, broker, fake = tool
        handle = _Handle(handed_off=True)
        _with_handle(monkeypatch, handle)
        monkeypatch.setattr("docsgpt.devices.broker.get_redis_instance", lambda: None)
        result = instance.execute_action("run_command", command="ls")
        assert result["error"] == "device broker unavailable"
        assert handle.detached == []

    def test_the_tool_supports_detached_runs(self, tool):
        instance, _broker, _fake = tool
        assert instance.supports_detached() is True


class TestSchema:
    def test_run_command_offers_background_and_watch(self):
        params = {"type": "object", "properties": {"command": {"type": "string"}}}
        add_background_params("remote_device", params)
        assert params["properties"]["background"]["type"] == "boolean"
        assert "device" in params["properties"]["background"]["description"]
        assert "patterns" in params["properties"]["watch"]["properties"]

    def test_other_tools_get_no_watch(self):
        params = {"type": "object", "properties": {}}
        add_background_params("mcp_tool", params)
        assert "watch" not in params["properties"]
