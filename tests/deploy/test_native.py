"""`docsgpt up --native`: run the server without Docker, supervised by the system's service manager."""

import json
import plistlib
import sys
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
        assert api.arguments[-5:] == ["api", "--host", "127.0.0.1", "--port", "7091"]
        assert worker.arguments[-1] == "worker"
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
        assert arguments[-1] == "migrate", "the launcher can be an interpreter and -m docsgpt"
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

    def test_it_refuses_to_run_beside_a_docker_install(self, tmp_path):
        """Native services on the same port would orphan the containers from down/status/uninstall."""
        assert _run(["up", "--yes", "--dir", str(tmp_path)], _context()) == 0
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/d"]
        with pytest.raises(DeployError, match="holds a Docker install"):
            _run(argv, _native_context())

    def test_without_the_command_on_path_the_services_run_the_module(self, tmp_path, monkeypatch):
        """A unit must name something executable; argv[0] is a module file under `python -m`."""
        monkeypatch.setattr("docsgpt.deploy.commands.shutil.which", lambda name: None)
        monkeypatch.setattr(sys, "argv", [str(tmp_path / "not-a-program")])
        services = FakeServices()
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/d"]
        assert _run(argv, _native_context(services)) == 0
        assert services.units["docsgpt-api"].arguments[:3] == [sys.executable, "-m", "docsgpt"]

    def test_a_failed_start_leaves_an_install_the_other_commands_can_clean_up(self, tmp_path):
        """Without the record, half-started units are orphaned: status, down and uninstall refuse the dir."""
        class FailingStart(FakeServices):
            def start(self, name):
                super().start(name)
                if name == "docsgpt-worker":
                    raise DeployError("systemctl could not start docsgpt-worker")

        services = FailingStart()
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/d"]
        with pytest.raises(DeployError, match="could not start"):
            _run(argv, _native_context(services))
        assert json.loads((tmp_path / "install.json").read_text())["mode"] == "native"
        assert _run(["uninstall", "--yes", "--dir", str(tmp_path)], _native_context(services)) == 0
        assert sorted(services.removed) == ["docsgpt-api", "docsgpt-worker"]

    def test_docker_only_options_are_refused_rather_than_ignored(self, tmp_path):
        """Asking for network exposure and silently getting loopback is the worst of both."""
        base = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/d"]
        with pytest.raises(DeployError, match="127.0.0.1 only"):
            _run([*base, "--expose", "network"], _native_context())
        with pytest.raises(DeployError, match="127.0.0.1 only"):
            _run([*base, "--domain", "docs.example.com"], _native_context())
        with pytest.raises(DeployError, match=r"docsgpt\[docling\]"):
            _run([*base, "--docling"], _native_context())
        assert not (tmp_path / ".env").exists(), "it refuses before writing anything"

    def test_the_options_that_describe_what_native_already_does_are_kept(self, tmp_path):
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/d",
                "--expose", "local", "--no-docling"]
        assert _run(argv, _native_context()) == 0

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

    def test_status_checks_the_address_the_services_actually_listen_on(self, tmp_path):
        """A LAN DOCSGPT_BIND would have status poll an address the native units never bind."""
        services = FakeServices()
        self._installed(tmp_path, services)
        envfile.update(tmp_path / ".env", {"DOCSGPT_BIND": "192.168.1.50"})
        checked = []
        context = _native_context(services)
        context.wait = lambda url, timeout: checked.append(url) or True
        assert _run(["status", "--dir", str(tmp_path)], context) == 0
        assert checked == ["http://127.0.0.1:7091/api/health"]

    def test_open_hands_the_browser_the_address_that_answers(self, tmp_path, capsys):
        """stack.url would offer a LAN address, but the native units listen on loopback only."""
        services = FakeServices()
        self._installed(tmp_path, services)
        envfile.update(tmp_path / ".env", {"DOCSGPT_BIND": "192.168.1.50"})
        opened = []
        context = _native_context(services)
        context.open_browser = lambda url: opened.append(url)
        assert _run(["open", "--dir", str(tmp_path)], context) == 0
        assert opened == ["http://localhost:7091"]
        assert "192.168.1.50" not in capsys.readouterr().out

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

    def test_backup_says_why_there_is_nothing_to_archive(self, tmp_path):
        """Its data is not in Docker volumes, so compose would fail with no configuration file."""
        self._installed(tmp_path, FakeServices())
        with pytest.raises(DeployError, match="native install"):
            _run(["backup", "--dir", str(tmp_path)], _native_context())

    def test_restore_refuses_before_it_touches_anything(self, tmp_path):
        self._installed(tmp_path, FakeServices())
        with pytest.raises(DeployError, match="native install"):
            _run(["restore", str(tmp_path / "any.tar.gz"), "--dir", str(tmp_path), "--yes"], _native_context())


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


class FakeSystemctl:
    """systemctl, recording what it was asked to do."""

    def __init__(self, active=True):
        self.calls = []
        self.active = active

    def __call__(self, args, capture_output=False, text=False, check=False):
        self.calls.append(args)
        code = 0 if (args[2] != "is-active" or self.active) else 3
        return types.SimpleNamespace(returncode=code, stdout="", stderr="")

    @property
    def verbs(self):
        return [call[2] for call in self.calls]


class TestSystemd:
    def _services(self, systemctl, tmp_path):
        return native.SystemdServices(runner=systemctl, home=tmp_path)

    def test_install_writes_the_unit_and_reloads(self, tmp_path):
        systemctl = FakeSystemctl()
        services = self._services(systemctl, tmp_path)
        services.install(native.units_for(tmp_path, ["/venv/bin/docsgpt"], 7091, tmp_path)[0])
        unit = tmp_path / ".config" / "systemd" / "user" / "docsgpt-api.service"
        assert "ExecStart=/venv/bin/docsgpt api" in unit.read_text()
        assert systemctl.verbs == ["daemon-reload"]

    def test_start_restarts_so_a_rewritten_unit_takes_effect(self, tmp_path):
        """`enable --now` starts nothing when the unit is already active: it would keep the old ExecStart."""
        systemctl = FakeSystemctl()
        self._services(systemctl, tmp_path).start("docsgpt-api")
        assert "restart" in systemctl.verbs, systemctl.verbs
        assert systemctl.verbs.index("enable") < systemctl.verbs.index("restart")
        assert "--now" not in [argument for call in systemctl.calls for argument in call]

    def test_stop_and_remove(self, tmp_path):
        systemctl = FakeSystemctl()
        services = self._services(systemctl, tmp_path)
        services.install(native.units_for(tmp_path, ["/venv/bin/docsgpt"], 7091, tmp_path)[0])
        unit = tmp_path / ".config" / "systemd" / "user" / "docsgpt-api.service"
        services.stop("docsgpt-api")
        assert unit.is_file(), "stopping keeps the unit"
        services.remove("docsgpt-api")
        assert not unit.exists()
        assert systemctl.verbs[-1] == "daemon-reload", "systemd is told the unit is gone"

    def test_is_running_asks_systemd(self, tmp_path):
        assert self._services(FakeSystemctl(active=True), tmp_path).is_running("docsgpt-api") is True
        assert self._services(FakeSystemctl(active=False), tmp_path).is_running("docsgpt-api") is False

    def test_a_stop_that_fails_is_not_reported_as_success(self, tmp_path):
        """`down` saying it stopped while the service still runs is worse than an error."""
        class Failing(FakeSystemctl):
            def __call__(self, args, **kwargs):
                self.calls.append(args)
                return types.SimpleNamespace(returncode=1, stdout="", stderr="Failed to stop docsgpt-api")

        with pytest.raises(DeployError, match="Failed to stop"):
            self._services(Failing(), tmp_path).stop("docsgpt-api")

    def test_a_removal_that_fails_keeps_the_unit_file(self, tmp_path):
        """uninstall must not drop the unit file and the record while systemd still runs the service."""
        class Failing(FakeSystemctl):
            def __call__(self, args, **kwargs):
                self.calls.append(args)
                code = 1 if args[2] == "disable" else 0
                return types.SimpleNamespace(returncode=code, stdout="", stderr="Failed to disable")

        services = self._services(Failing(), tmp_path)
        services.install(native.units_for(tmp_path, ["/venv/bin/docsgpt"], 7091, tmp_path)[0])
        with pytest.raises(DeployError, match="Failed to disable"):
            services.remove("docsgpt-api")
        assert (tmp_path / ".config" / "systemd" / "user" / "docsgpt-api.service").is_file()

    def test_removing_a_unit_that_is_already_gone_is_harmless(self, tmp_path):
        systemctl = FakeSystemctl()
        self._services(systemctl, tmp_path).remove("docsgpt-api")
        assert "disable" not in systemctl.verbs, "nothing to disable when the unit file is gone"

    def test_an_explicit_home_wins_over_xdg_config_home(self, tmp_path, monkeypatch):
        """home is how a caller redirects the unit directory; the environment must not override it."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        services = native.SystemdServices(runner=FakeSystemctl(), home=tmp_path)
        assert services.directory == tmp_path / ".config" / "systemd" / "user"

    def test_xdg_config_home_is_used_when_no_home_is_given(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        services = native.SystemdServices(runner=FakeSystemctl())
        assert services.directory == tmp_path / "xdg" / "systemd" / "user"

    def test_a_failing_systemctl_is_reported(self, tmp_path):
        class Failing(FakeSystemctl):
            def __call__(self, args, **kwargs):
                self.calls.append(args)
                return types.SimpleNamespace(returncode=1, stdout="", stderr="Failed to enable unit")

        with pytest.raises(DeployError, match="Failed to enable unit"):
            self._services(Failing(), tmp_path).start("docsgpt-api")


class TestPlatformChoice:
    def test_each_platform_gets_its_service_manager(self):
        assert isinstance(native.services_for_platform("darwin"), native.LaunchdServices)
        assert isinstance(native.services_for_platform("linux"), native.SystemdServices)

    def test_windows_says_what_to_do_instead(self):
        with pytest.raises(DeployError, match="Windows"):
            native.services_for_platform("win32")


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

    def test_a_directory_with_spaces_and_quotes_survives_the_systemd_unit(self, tmp_path):
        """--dir is free-form, and this repo itself lives under a path with a space in it."""
        odd = '/srv/my "odd" dir'
        unit = native.Unit(
            name="docsgpt-api",
            arguments=["/venv/bin/docsgpt", "api"],
            environment={"DOCSGPT_HOME": odd},
            working_directory=odd,
            log_file="/srv/api.log",
        )
        body = native.systemd_unit(unit)
        assert 'WorkingDirectory="/srv/my \\"odd\\" dir"' in body
        assert 'Environment="DOCSGPT_HOME=/srv/my \\"odd\\" dir"' in body

    def test_a_newline_in_a_path_is_refused_rather_than_quoted(self, tmp_path):
        """A service file is line-based: quoting cannot hold a newline, it would add a directive."""
        unit = native.Unit(
            name="docsgpt-api",
            arguments=["/venv/bin/docsgpt", "api"],
            environment={"DOCSGPT_HOME": str(tmp_path)},
            working_directory="/srv/x\nExecStart=/bin/sh -c evil",
            log_file="/srv/api.log",
        )
        with pytest.raises(DeployError, match="control character"):
            native.systemd_unit(unit)
        with pytest.raises(DeployError, match="control character"):
            native.launchd_plist(unit)

    def test_a_newline_in_the_environment_is_refused(self, tmp_path):
        unit = native.Unit(
            name="docsgpt-api",
            arguments=["/venv/bin/docsgpt", "api"],
            environment={"DOCSGPT_HOME": "/srv/x\nEnvironment=EVIL=1"},
            working_directory=str(tmp_path),
            log_file="/srv/api.log",
        )
        with pytest.raises(DeployError, match="control character"):
            native.systemd_unit(unit)

    def test_an_argument_with_spaces_survives_the_systemd_unit(self, tmp_path):
        unit = self._unit(tmp_path)
        unit.arguments = ["/opt/my venv/bin/docsgpt", "api"]
        assert "ExecStart='/opt/my venv/bin/docsgpt' api" in native.systemd_unit(unit)
