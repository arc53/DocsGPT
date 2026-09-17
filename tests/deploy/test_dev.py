"""`docsgpt dev`: the checkout's processes as children of one terminal."""

import argparse
import io
import signal
import sys
from pathlib import Path

import pytest

from docsgpt.deploy import dev
from docsgpt.deploy.docker import DeployError


def _args(**overrides):
    values = {"host": "127.0.0.1", "port": 7091, "ui": False, "mock_llm": False,
              "worker": True, "reload": True, "loglevel": "INFO"}
    values.update(overrides)
    return argparse.Namespace(**values)


def _named(children):
    return [child.name for child in children]


class FakeProcess:
    """A child that produces the given lines and is done."""

    def __init__(self, lines=(), code=None):
        self.stdout = iter(list(lines))
        self.code = code
        self.pid = -1

    def poll(self):
        return self.code

    def terminate(self):
        self.code = self.code if self.code is not None else -15


class TestPlan:
    def test_the_api_and_worker_run_from_the_checkout(self, tmp_path):
        children = dev.plan(_args(), tmp_path, watching=False)
        assert _named(children) == ["api", "worker"]
        api, worker = children
        assert api.command[-6:-1] == ["api", "--host", "127.0.0.1", "--port", "7091"]
        assert api.command[-1] == "--reload"
        assert worker.command[-2:] == ["-l", "INFO"]
        for child in children:
            assert child.cwd == tmp_path
            assert child.env["DOCSGPT_HOME"] == str(tmp_path), "the checkout is the data home, not ~/.docsgpt"

    def test_the_worker_restarts_on_save_when_watchfiles_is_there(self, tmp_path):
        """Celery has no reloader of its own, so it is wrapped in one."""
        worker = dev.plan(_args(), tmp_path, watching=True)[1]
        assert "watchfiles" in worker.command
        assert str(tmp_path / "docsgpt") in worker.command, "it watches the package, not the whole checkout"
        assert "docsgpt worker" in " ".join(worker.command)

    def test_without_watchfiles_the_worker_still_runs(self, tmp_path):
        worker = dev.plan(_args(), tmp_path, watching=False)[1]
        assert "watchfiles" not in " ".join(worker.command)

    def test_no_reload_leaves_both_alone(self, tmp_path):
        children = dev.plan(_args(reload=False), tmp_path, watching=True)
        assert "--reload" not in children[0].command
        assert "watchfiles" not in " ".join(children[1].command)

    def test_no_worker(self, tmp_path):
        assert _named(dev.plan(_args(worker=False), tmp_path, watching=False)) == ["api"]

    def test_the_mock_llm_starts_first_and_the_others_are_pointed_at_it(self, tmp_path):
        """A dev loop that needs no API key: the mock has to be up before the API asks it anything."""
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "mock_llm.py").write_text("", encoding="utf-8")
        children = dev.plan(_args(mock_llm=True), tmp_path, watching=False)
        assert _named(children) == ["llm", "api", "worker"]
        api = children[1]
        assert api.env["LLM_PROVIDER"] == "openai"
        assert api.env["OPENAI_BASE_URL"] == f"http://127.0.0.1:{dev.MOCK_LLM_PORT}/v1"
        assert api.env["API_KEY"], "the client wants some key, even a placeholder"
        assert "OPENAI_BASE_URL" not in children[0].env, "the mock itself does not need pointing at itself"

    def test_a_missing_mock_llm_script_is_reported(self, tmp_path):
        with pytest.raises(DeployError, match="mock LLM"):
            dev.plan(_args(mock_llm=True), tmp_path, watching=False)

    def test_the_ui_needs_its_dependencies(self, tmp_path):
        (tmp_path / "frontend").mkdir()
        with pytest.raises(DeployError, match="node_modules"):
            dev.plan(_args(ui=True), tmp_path, watching=False)

    def test_the_ui_needs_npm_on_path(self, tmp_path, monkeypatch):
        (tmp_path / "frontend" / "node_modules").mkdir(parents=True)
        monkeypatch.setattr(dev.shutil, "which", lambda name: None)
        with pytest.raises(DeployError, match="npm"):
            dev.plan(_args(ui=True), tmp_path, watching=False)

    def test_the_ui_runs_in_the_frontend_directory(self, tmp_path, monkeypatch):
        (tmp_path / "frontend" / "node_modules").mkdir(parents=True)
        monkeypatch.setattr(dev.shutil, "which", lambda name: "/usr/local/bin/npm")
        children = dev.plan(_args(ui=True), tmp_path, watching=False)
        ui = children[-1]
        assert ui.name == "ui"
        assert ui.command == ["npm", "run", "dev"]
        assert ui.cwd == tmp_path / "frontend"


class TestRun:
    def _spawn(self, processes):
        made = iter(processes)

        def spawn(command, **kwargs):
            return next(made)

        return spawn

    def test_output_is_prefixed_with_the_child_that_wrote_it(self, tmp_path):
        out = io.StringIO()
        children = [dev.Child(name="api", command=["true"], cwd=tmp_path)]
        code = dev.run(children, out=out, spawn=self._spawn([FakeProcess(["hello\n"], code=0)]),
                       sleep=lambda _: None, colour=False)
        assert "api    | hello" in out.getvalue()
        assert code == 1, "a child that ends by itself ends the session, however it exited"

    def test_a_failing_child_returns_its_code(self, tmp_path):
        out = io.StringIO()
        children = [dev.Child(name="api", command=["false"], cwd=tmp_path)]
        code = dev.run(children, out=out, spawn=self._spawn([FakeProcess(code=2)]),
                       sleep=lambda _: None, colour=False)
        assert code == 2
        assert "exited with 2" in out.getvalue()

    def test_an_interrupt_stops_quietly(self, tmp_path):
        out = io.StringIO()

        def sleep(_):
            raise KeyboardInterrupt

        children = [dev.Child(name="api", command=["sleep"], cwd=tmp_path)]
        code = dev.run(children, out=out, spawn=self._spawn([FakeProcess()]), sleep=sleep, colour=False)
        assert code == 0
        assert "Stopping" in out.getvalue()

    def test_a_second_interrupt_during_shutdown_still_kills(self, tmp_path, monkeypatch):
        """Ctrl-C twice is what you press when it did not die; it must not leave children behind."""
        sent = []
        monkeypatch.setattr(dev, "_signal", lambda process, number: sent.append(number))

        def sleep(_):
            raise KeyboardInterrupt

        children = [dev.Child(name="api", command=["sleep"], cwd=tmp_path)]
        code = dev.run(children, out=io.StringIO(), spawn=self._spawn([FakeProcess()]),
                       sleep=sleep, colour=False, grace=5)
        assert code == 0
        assert signal.SIGINT in sent
        assert signal.SIGKILL in sent, "the second interrupt escalates instead of escaping"

    def test_children_get_the_checkout_environment(self, tmp_path, monkeypatch):
        seen = {}

        def spawn(command, **kwargs):
            seen.update(kwargs)
            return FakeProcess(code=0)

        monkeypatch.setenv("SOMETHING_ELSE", "kept")
        children = [dev.Child(name="api", command=["x"], cwd=tmp_path, env={"DOCSGPT_HOME": str(tmp_path)})]
        dev.run(children, out=io.StringIO(), spawn=spawn, sleep=lambda _: None, colour=False)
        assert seen["env"]["DOCSGPT_HOME"] == str(tmp_path)
        assert seen["env"]["SOMETHING_ELSE"] == "kept", "the shell's environment is kept, not replaced"
        assert seen["cwd"] == str(tmp_path)
        assert seen["start_new_session"] is (sys.platform != "win32")


class TestReloadingCommand:
    def test_an_interpreter_path_with_spaces_survives(self):
        command = dev._reloading_command(["/opt/my venv/bin/python", "-m", "docsgpt", "worker"], Path("/srv/pkg"))
        assert "'/opt/my venv/bin/python' -m docsgpt worker" in command
        assert command[-1] == "/srv/pkg"
