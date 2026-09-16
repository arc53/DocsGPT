"""`docsgpt up --native`: run the server without Docker, supervised by the system's service manager."""

import json
import plistlib
import types

import pytest

from docsgpt.deploy import envfile, native
from docsgpt.deploy.docker import DeployError

from .test_commands import FakePrompter, _context, _run


class FakeServices:
    """A stand-in for launchd/systemd: records what would be installed and started."""

    name = "fake"

    def __init__(self, running=()):
        self.units = {}
        self.started = []
        self.stopped = []
        self.removed = []
        self.running = set(running)

    def install(self, unit):
        self.units[unit.name] = unit

    def start(self, name):
        self.started.append(name)
        self.running.add(name)

    def stop(self, name):
        self.stopped.append(name)
        self.running.discard(name)

    def remove(self, name):
        self.removed.append(name)
        self.running.discard(name)

    def is_running(self, name):
        return name in self.running


def _native_context(services=None, migrated=None, **overrides):
    context = _context(**overrides)
    context.services = services or FakeServices()
    context.run = lambda args, env=None: (migrated.append(args) if migrated is not None else None) or 0
    return context


class TestNativeUp:
    def test_writes_settings_for_the_given_postgres_and_redis(self, tmp_path):
        context = _native_context()
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes",
                "--postgres-uri", "postgresql://docsgpt:pw@localhost:5432/docsgpt",
                "--redis-url", "redis://localhost:6379"]
        assert _run(argv, context) == 0

        env = envfile.read(tmp_path / ".env")
        assert env["POSTGRES_URI"] == "postgresql://docsgpt:pw@localhost:5432/docsgpt"
        assert env["CELERY_BROKER_URL"] == "redis://localhost:6379/0"
        assert env["CELERY_RESULT_BACKEND"] == "redis://localhost:6379/1"
        assert env["CACHE_REDIS_URL"] == "redis://localhost:6379/2"
        assert env["INTERNAL_KEY"], "the worker needs it to hand indexes to the API"
        assert env["API_URL"] == "http://127.0.0.1:7091"
        assert "DOCSGPT_IMAGE_TAG" not in env, "nothing here runs an image"

    def test_records_the_mode_so_the_other_commands_can_tell(self, tmp_path):
        assert _run(["up", "--native", "--dir", str(tmp_path), "--yes",
                     "--postgres-uri", "postgresql://localhost/docsgpt"], _native_context()) == 0
        record = json.loads((tmp_path / "install.json").read_text())
        assert record["mode"] == "native"
        assert record["version"] == "0.21.0"

    def test_migrates_before_starting_the_services(self, tmp_path):
        migrated = []
        services = FakeServices()
        context = _native_context(services=services, migrated=migrated)
        assert _run(["up", "--native", "--dir", str(tmp_path), "--yes",
                     "--postgres-uri", "postgresql://localhost/docsgpt"], context) == 0
        assert any("migrate" in " ".join(call) for call in migrated), migrated
        assert services.started == ["docsgpt-api", "docsgpt-worker"]

    def test_the_units_run_this_interpreter_with_the_stack_as_its_home(self, tmp_path):
        services = FakeServices()
        assert _run(["up", "--native", "--dir", str(tmp_path), "--yes",
                     "--postgres-uri", "postgresql://localhost/docsgpt"], _native_context(services)) == 0
        api = services.units["docsgpt-api"]
        worker = services.units["docsgpt-worker"]
        assert api.arguments[1:] == ["api", "--host", "127.0.0.1", "--port", "7091"]
        assert worker.arguments[1:] == ["worker"]
        for unit in (api, worker):
            assert unit.environment["DOCSGPT_HOME"] == str(tmp_path)
            assert unit.working_directory == str(tmp_path)
            assert unit.log_file.endswith(".log")

    def test_the_migration_targets_the_stack_not_the_working_directory(self, tmp_path):
        """`docsgpt up --native` run from a checkout must not migrate the checkout's database."""
        calls = []
        context = _native_context()
        context.run = lambda args, env=None: calls.append((args, env)) or 0
        assert _run(["up", "--native", "--dir", str(tmp_path), "--yes",
                     "--postgres-uri", "postgresql://localhost/docsgpt"], context) == 0
        arguments, environment = calls[0]
        assert arguments[1] == "migrate"
        assert environment["DOCSGPT_HOME"] == str(tmp_path)
        assert environment["DOCSGPT_ENV_FILE"] == str(tmp_path / ".env")

    def test_a_redis_database_in_the_url_moves_the_three_up(self, tmp_path):
        """Sharing a Redis: `/5` puts the broker, the backend and the cache on 5, 6 and 7."""
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes",
                "--postgres-uri", "postgresql://localhost/docsgpt", "--redis-url", "redis://localhost:6379/5"]
        assert _run(argv, _native_context()) == 0
        env = envfile.read(tmp_path / ".env")
        assert env["CELERY_BROKER_URL"] == "redis://localhost:6379/5"
        assert env["CELERY_RESULT_BACKEND"] == "redis://localhost:6379/6"
        assert env["CACHE_REDIS_URL"] == "redis://localhost:6379/7"

    def test_a_later_up_keeps_the_port_the_install_was_given(self, tmp_path):
        """`docsgpt up` with no --port must not move an install from its port back to 7091."""
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--port", "7099",
                "--postgres-uri", "postgresql://localhost/docsgpt"]
        assert _run(argv, _native_context()) == 0

        services = FakeServices()
        assert _run(["up", "--dir", str(tmp_path), "--yes"], _native_context(services)) == 0
        env = envfile.read(tmp_path / ".env")
        assert env["DOCSGPT_PORT"] == "7099"
        assert env["API_URL"] == "http://127.0.0.1:7099"
        assert services.units["docsgpt-api"].arguments[-1] == "7099"

    def test_a_database_url_is_required(self, tmp_path):
        with pytest.raises(DeployError, match="--postgres-uri"):
            _run(["up", "--native", "--dir", str(tmp_path), "--yes"], _native_context())

    def test_asks_for_the_urls_when_there_is_a_terminal(self, tmp_path):
        prompter = FakePrompter(["postgresql://localhost/docsgpt", "redis://localhost:6379", "docsgpt"])
        context = _native_context(interactive=True, prompter=prompter)
        assert _run(["up", "--native", "--dir", str(tmp_path)], context) == 0
        env = envfile.read(tmp_path / ".env")
        assert env["POSTGRES_URI"] == "postgresql://localhost/docsgpt"
        assert env["CELERY_BROKER_URL"] == "redis://localhost:6379/0"
        assert env["LLM_PROVIDER"] == "docsgpt"
        assert prompter.questions[0].startswith("PostgreSQL URL")

    def test_an_unhealthy_start_points_at_the_logs(self, tmp_path, capsys):
        context = _native_context(healthy=False)
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/docsgpt"]
        assert _run(argv, context) == 1
        assert "docsgpt logs" in capsys.readouterr().err


class TestNativeLifecycle:
    def _installed(self, tmp_path, services):
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/docsgpt"]
        assert _run(argv, _native_context(services)) == 0

    def test_status_reports_the_native_services(self, tmp_path, capsys):
        services = FakeServices()
        self._installed(tmp_path, services)
        assert _run(["status", "--dir", str(tmp_path)], _native_context(services)) == 0
        out = capsys.readouterr().out
        assert "native" in out.lower()
        assert "docsgpt-api" in out

    def test_down_stops_them_and_leaves_the_settings(self, tmp_path):
        services = FakeServices()
        self._installed(tmp_path, services)
        assert _run(["down", "--dir", str(tmp_path)], _native_context(services)) == 0
        assert services.stopped == ["docsgpt-worker", "docsgpt-api"], "the worker goes first"
        assert (tmp_path / ".env").is_file()

    def test_uninstall_removes_the_services(self, tmp_path):
        services = FakeServices()
        self._installed(tmp_path, services)
        assert _run(["uninstall", "--yes", "--dir", str(tmp_path)], _native_context(services)) == 0
        assert sorted(services.removed) == ["docsgpt-api", "docsgpt-worker"]

    def test_docker_commands_refuse_a_native_install(self, tmp_path, capsys):
        self._installed(tmp_path, FakeServices())
        assert _run(["logs", "--dir", str(tmp_path)], _native_context()) == 0, "logs work in both modes"


class FakeLaunchctl:
    """launchctl, with a bootout that takes `unload_polls` polls to take effect."""

    def __init__(self, unload_polls=1, state="running"):
        self.calls = []
        self.loaded = True
        self.unload_polls = unload_polls
        self.state = state

    def __call__(self, args, capture_output=False, text=False, check=False):
        self.calls.append(args)
        verb = args[1]
        if verb == "bootout":
            self.pending = self.unload_polls
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if verb == "print":
            if not self.loaded:
                return types.SimpleNamespace(returncode=113, stdout="", stderr="Could not find service")
            if getattr(self, "pending", 0) > 0:
                self.pending -= 1
                if self.pending == 0:
                    self.loaded = False
                return types.SimpleNamespace(returncode=0, stdout="\tstate = running\n", stderr="")
            return types.SimpleNamespace(returncode=0, stdout=f"\tstate = {self.state}\n", stderr="")
        if verb == "bootstrap":
            if self.loaded:
                return types.SimpleNamespace(returncode=5, stdout="", stderr="Bootstrap failed: 5: Input/output error")
            self.loaded = True
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


class TestLaunchd:
    def _services(self, launchctl, tmp_path):
        services = native.LaunchdServices(runner=launchctl, home=tmp_path)
        services.poll_interval = 0
        return services

    def test_start_waits_for_the_old_job_to_unload_before_bootstrapping(self, tmp_path):
        """launchctl bootout returns early; bootstrapping too soon fails with 'Bootstrap failed: 5'."""
        launchctl = FakeLaunchctl(unload_polls=3)
        services = self._services(launchctl, tmp_path)
        services.directory.mkdir(parents=True, exist_ok=True)
        services.start("docsgpt-api")
        verbs = [call[1] for call in launchctl.calls]
        assert verbs[0] == "bootout"
        assert verbs[-1] == "bootstrap"
        assert verbs.count("print") >= 1, "it polled until the label stopped resolving"
        assert verbs.index("bootstrap") > max(index for index, verb in enumerate(verbs) if verb == "print")

    def test_stop_returns_only_once_the_job_is_gone(self, tmp_path):
        launchctl = FakeLaunchctl(unload_polls=2)
        self._services(launchctl, tmp_path).stop("docsgpt-api")
        assert not launchctl.loaded

    def test_a_job_that_will_not_unload_is_reported(self, tmp_path):
        launchctl = FakeLaunchctl(unload_polls=10_000)
        services = self._services(launchctl, tmp_path)
        services.unload_timeout = 0
        with pytest.raises(DeployError, match="still loaded"):
            services.stop("docsgpt-api")

    def test_a_loaded_but_not_running_job_is_not_running(self, tmp_path):
        """`launchctl print` answers for a crashed service too, so status must read its state."""
        services = self._services(FakeLaunchctl(state="not running"), tmp_path)
        assert services.is_running("docsgpt-api") is False
        assert self._services(FakeLaunchctl(state="running"), tmp_path).is_running("docsgpt-api") is True


class TestUnitFiles:
    def _unit(self, tmp_path):
        return native.Unit(
            name="docsgpt-api",
            arguments=["/opt/venv/bin/docsgpt", "api", "--port", "7091"],
            environment={"DOCSGPT_HOME": str(tmp_path)},
            working_directory=str(tmp_path),
            log_file=str(tmp_path / "api.log"),
        )

    def test_launchd_plist_is_valid_and_keeps_the_service_alive(self, tmp_path):
        body = native.launchd_plist(self._unit(tmp_path), label="cloud.docsgpt.api")
        parsed = plistlib.loads(body.encode())
        assert parsed["Label"] == "cloud.docsgpt.api"
        assert parsed["ProgramArguments"][1] == "api"
        assert parsed["KeepAlive"] is True
        assert parsed["EnvironmentVariables"]["DOCSGPT_HOME"] == str(tmp_path)
        assert parsed["StandardErrorPath"].endswith("api.log")

    def test_systemd_unit_restarts_and_carries_the_environment(self, tmp_path):
        body = native.systemd_unit(self._unit(tmp_path))
        assert "Restart=always" in body
        assert f'Environment="DOCSGPT_HOME={tmp_path}"' in body
        assert "ExecStart=/opt/venv/bin/docsgpt api --port 7091" in body
        assert "WantedBy=default.target" in body

    def test_an_argument_with_spaces_survives_the_systemd_unit(self, tmp_path):
        unit = self._unit(tmp_path)
        unit.arguments = ["/opt/my venv/bin/docsgpt", "api"]
        assert "ExecStart='/opt/my venv/bin/docsgpt' api" in native.systemd_unit(unit)
