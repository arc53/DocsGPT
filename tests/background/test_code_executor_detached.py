"""code_executor in a background-capable turn: detached runs, the hand-off to a poller, identical payloads."""

from __future__ import annotations

import threading

import pytest

from docsgpt.agents.tools import code_executor as ce
from docsgpt.agents.tools.code_executor import CodeExecutorTool, PreparedRun
from docsgpt.background import handoff
from docsgpt.sandbox.base import DetachedState, ExecResult, OpenedSession


class _Manager:
    """A manager with an exec path and a detached path that report the same result."""

    def __init__(self, result: ExecResult, *, polls_before_done: int = 0, created: bool = False):
        self.result = result
        self.polls_before_done = polls_before_done
        self.created = created
        self.closed = []
        self.started = []
        self.polls = 0
        self.cancelled = []
        self.exec_calls = 0

    def open_session(self, session_id, ttl=None):
        return OpenedSession(session_id, self.created)

    def put_file(self, session_id, path, data):
        pass

    def list_files(self, session_id):
        return []

    def exec(self, session_id, code, timeout=None):
        self.exec_calls += 1
        return self.result

    def close(self, session_id):
        self.closed.append(session_id)

    def supports_detached(self):
        return True

    def start_detached(self, session_id, code, timeout, key):
        self.started.append((session_id, code, timeout, key))
        return {"backend": "daytona", "sandbox_id": "sb", "cmd_id": "cmd", "process_session": f"docsgpt-job-{key}"}

    def poll_detached(self, session_id, run, with_output=False):
        self.polls += 1
        if self.polls > self.polls_before_done:
            return DetachedState(done=True, result=self.result, output=self.result.stdout)
        return DetachedState(done=False)

    def cancel_detached(self, session_id, run):
        self.cancelled.append(run)


class _Call:
    """A stand-in for ``handoff.CallHandle``."""

    def __init__(self, *, explicit=False, handoff_after_polls=None, manager=None, accept=True):
        self.key = "k1"
        self.explicit = explicit
        self.handoff_after_polls = handoff_after_polls
        self.manager = manager
        self.accept = accept
        self.detached_with = None

    def handoff_requested(self):
        if self.handoff_after_polls is None:
            return False
        return self.manager.polls >= self.handoff_after_polls

    def wait(self, seconds):
        pass

    def detach(self, external):
        self.detached_with = external
        return self.accept


@pytest.fixture()
def tool():
    config = {"conversation_id": "conv-1", "tool_id": "t1", "message_id": "m1"}
    return CodeExecutorTool(tool_config=config, user_id="u1")


def _use(monkeypatch, manager, *, backend="daytona", call=None):
    monkeypatch.setattr(ce.SandboxCreator, "get_manager", classmethod(lambda cls: manager))
    monkeypatch.setattr(ce.settings, "SANDBOX_BACKEND", backend)
    monkeypatch.setattr(CodeExecutorTool, "_background_call", staticmethod(lambda: call))


def _ok():
    return ExecResult(status="ok", stdout="hello\n")


class TestDetachedRun:
    def test_payload_is_identical_to_an_exec_run(self, tool, monkeypatch):
        manager = _Manager(_ok())
        _use(monkeypatch, manager, call=None)
        via_exec = tool.execute_action("run_code", code="print('hello')", capture_artifacts=False)
        assert manager.exec_calls == 1

        manager = _Manager(_ok(), polls_before_done=2)
        call = _Call(manager=manager)
        _use(monkeypatch, manager, call=call)
        via_detached = CodeExecutorTool(
            tool_config={"conversation_id": "conv-1", "tool_id": "t1", "message_id": "m1"}, user_id="u1"
        ).execute_action("run_code", code="print('hello')", capture_artifacts=False)
        assert manager.exec_calls == 0
        assert manager.started[0][3] == "k1"
        assert via_detached == via_exec

    def test_hand_off_detaches_and_keeps_the_session(self, tool, monkeypatch):
        manager = _Manager(_ok(), polls_before_done=50)
        call = _Call(manager=manager, handoff_after_polls=1)
        _use(monkeypatch, manager, call=call)
        out = tool.execute_action("run_code", code="import time", persist=False, capture_artifacts=False)
        assert out is handoff.DETACHED
        # persist=false: the poller closes the session once the run ends, not the turn.
        assert manager.closed == []
        state = call.detached_with
        assert state["session_id"] == "conv-1"
        assert state["run"]["cmd_id"] == "cmd"
        assert state["tool"] == {
            "config": {"tool_id": "t1", "conversation_id": "conv-1", "message_id": "m1"},
            "user_id": "u1",
        }
        restored = PreparedRun.from_state(state["finish"])
        assert restored.code == "import time"
        assert restored.keep_alive is False

    def test_a_refused_detach_keeps_polling_here(self, tool, monkeypatch):
        manager = _Manager(_ok(), polls_before_done=3)
        call = _Call(manager=manager, handoff_after_polls=1, accept=False)
        _use(monkeypatch, manager, call=call)
        out = tool.execute_action("run_code", code="x=1", capture_artifacts=False)
        assert out["status"] == "ok"

    def test_jupyter_runs_in_the_kernel_unless_background_was_asked(self, tool, monkeypatch):
        manager = _Manager(_ok())
        _use(monkeypatch, manager, backend="jupyter", call=_Call(manager=manager))
        tool.execute_action("run_code", code="x=1", capture_artifacts=False)
        assert manager.exec_calls == 1 and manager.started == []

        manager = _Manager(_ok())
        _use(monkeypatch, manager, backend="jupyter", call=_Call(manager=manager, explicit=True))
        tool.execute_action("run_code", code="x=1", capture_artifacts=False)
        assert manager.exec_calls == 0 and len(manager.started) == 1

    def test_a_failed_start_reports_an_error(self, tool, monkeypatch):
        manager = _Manager(_ok())

        def broken(*args, **kwargs):
            raise RuntimeError("toolbox 502")

        manager.start_detached = broken
        _use(monkeypatch, manager, call=_Call(manager=manager))
        out = tool.execute_action("run_code", code="x=1", capture_artifacts=False)
        assert out["status"] == "error"
        assert "toolbox 502" in out["error"]

    def test_repeated_poll_failures_stop_the_run(self, tool, monkeypatch):
        manager = _Manager(_ok())

        def flaky(*args, **kwargs):
            raise IOError("unreachable")

        manager.poll_detached = flaky
        _use(monkeypatch, manager, call=_Call(manager=manager))
        out = tool.execute_action("run_code", code="x=1", capture_artifacts=False)
        assert out["status"] == "error"
        assert len(manager.cancelled) == 1


class TestPreparedRun:
    def test_round_trip(self):
        run = PreparedRun(
            session_id="s",
            code="x" * 30_000,
            timeout=120.0,
            clamped=True,
            asked_timeout=5000,
            outputs=["*.csv"],
            pre_signatures={"a.txt": (3, "abc")},
            inputs_loaded=["inputs/a"],
            session_created=True,
            keep_alive=False,
        )
        restored = PreparedRun.from_state(run.to_state())
        assert len(restored.code) == 20_000
        assert restored.pre_signatures == {"a.txt": (3, "abc")}
        assert restored.timeout == 120.0
        assert restored.asked_timeout == 5000
        assert restored.outputs == ["*.csv"]


class TestCallHandle:
    def test_wait_wakes_on_hand_off(self):
        flight = handoff._Flight()
        call = handoff.CallHandle(flight, explicit=False, watch=None)
        assert call.handoff_requested() is False
        timer = threading.Timer(0.05, lambda: (setattr(flight, "job_id", "j"), flight.job_ready.set()))
        timer.start()
        call.wait(5)
        assert call.handoff_requested() is True

    def test_detach_without_a_job_is_refused(self):
        call = handoff.CallHandle(handoff._Flight(), explicit=False, watch=None)
        assert call.detach({}) is False


def test_a_timeout_in_a_background_capable_turn_points_to_background():
    tool = CodeExecutorTool({}, "u1")
    timed_out = ExecResult(status="error", error_name="TimeoutError", error_value="execution exceeded 60s")
    plain = tool._shape_payload(timed_out, [], [], timeout=60.0)["error"]
    capable = tool._shape_payload(timed_out, [], [], timeout=60.0, background_capable=True)["error"]
    assert "nohup" in plain
    assert "background=true" in capable and "nohup" not in capable


def _timed_out():
    return ExecResult(status="error", error_name="TimeoutError", error_value="execution exceeded 60s")


class TestBackgroundRunTimeouts:
    """A run already in the background that hits its cap is reported, never re-run on the model's own."""

    def test_an_explicit_background_run_without_a_timeout_gets_the_job_maximum(self, tool, monkeypatch):
        monkeypatch.setattr(ce.settings, "BACKGROUND_JOB_MAX_SECONDS", 900)
        monkeypatch.setattr(ce.settings, "SANDBOX_EXEC_MAX_TIMEOUT", 1000)
        manager = _Manager(_ok())
        _use(monkeypatch, manager, call=_Call(manager=manager, explicit=True))
        tool.execute_action("run_code", code="x=1", capture_artifacts=False)
        assert manager.started[0][2] == 900

    def test_the_job_maximum_never_exceeds_the_sandbox_cap(self, tool, monkeypatch):
        monkeypatch.setattr(ce.settings, "BACKGROUND_JOB_MAX_SECONDS", 5000)
        monkeypatch.setattr(ce.settings, "SANDBOX_EXEC_MAX_TIMEOUT", 1000)
        manager = _Manager(_ok())
        _use(monkeypatch, manager, call=_Call(manager=manager, explicit=True))
        tool.execute_action("run_code", code="x=1", capture_artifacts=False)
        assert manager.started[0][2] == 1000

    def test_an_explicit_timeout_and_a_foreground_run_keep_theirs(self, tool, monkeypatch):
        manager = _Manager(_ok())
        _use(monkeypatch, manager, call=_Call(manager=manager, explicit=True))
        tool.execute_action("run_code", code="x=1", timeout=120, capture_artifacts=False)
        assert manager.started[0][2] == 120

        manager = _Manager(_ok())
        _use(monkeypatch, manager, call=_Call(manager=manager))
        tool.execute_action("run_code", code="x=1", capture_artifacts=False)
        assert manager.started[0][2] == float(ce.settings.SANDBOX_EXEC_TIMEOUT)

    def test_a_background_run_that_timed_out_is_reported_not_rerun(self, tool, monkeypatch):
        manager = _Manager(_timed_out())
        _use(monkeypatch, manager, call=_Call(manager=manager, explicit=True))
        out = tool.execute_action("run_code", code="import time; time.sleep(999)", timeout=60, capture_artifacts=False)
        assert "only if the user asks" in out["error"]
        assert "run it again with background=true" not in out["error"]
        assert not any("rerun it with a larger" in hint for hint in out.get("hint", []))

    def test_a_handed_off_run_finished_by_the_poller_is_a_background_run(self, tool):
        run = PreparedRun(session_id="s", code="x", timeout=60.0, background_capable=True, background=True)
        out = tool.finish_run(_Manager(_timed_out()), run, _timed_out())
        assert "only if the user asks" in out["error"]
        assert not any("rerun it with a larger" in hint for hint in out.get("hint", []))

    def test_a_foreground_timeout_still_offers_more_room(self, tool):
        run = PreparedRun(session_id="s", code="x", timeout=60.0, background_capable=True)
        out = tool.finish_run(_Manager(_timed_out()), run, _timed_out())
        assert "background=true" in out["error"]
        assert any("rerun it with a larger" in hint for hint in out.get("hint", []))


def test_the_descriptions_say_how_long_a_background_run_may_take():
    from docsgpt.background.schema import add_background_params

    params = {"type": "object", "properties": {}}
    add_background_params("code_executor", params)
    assert "job maximum" in params["properties"]["background"]["description"]
    timeout = CodeExecutorTool._timeout_parameter_description()
    assert "background runs too" in timeout
    assert "above the expected duration" in timeout
