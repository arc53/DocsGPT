"""`docsgpt doctor`, `restart`, following native logs, and settings that apply themselves."""

import pytest

from docsgpt.deploy import commands, envfile
from docsgpt.deploy.docker import DeployError

from .test_commands import FakeDocker, _context, _run
from .test_native import FakeServices, _names, _native_context


def _installed_native(tmp_path, services):
    argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/d"]
    assert _run(argv, _native_context(services)) == 0


class TestRestart:
    def test_it_stops_and_starts_both_without_touching_settings(self, tmp_path):
        services = FakeServices()
        _installed_native(tmp_path, services)
        before = (tmp_path / ".env").read_text(encoding="utf-8")
        services.started.clear()
        services.stopped.clear()

        assert _run(["restart", "--dir", str(tmp_path)], _native_context(services)) == 0
        assert services.stopped == list(reversed(_names(tmp_path))), "the worker goes down first"
        assert services.started == list(_names(tmp_path))
        assert (tmp_path / ".env").read_text(encoding="utf-8") == before

    def test_one_service_by_its_short_name(self, tmp_path):
        services = FakeServices()
        _installed_native(tmp_path, services)
        services.started.clear()
        assert _run(["restart", "api", "--dir", str(tmp_path)], _native_context(services)) == 0
        assert services.started == [_names(tmp_path)[0]]

    def test_a_name_this_install_does_not_have(self, tmp_path):
        services = FakeServices()
        _installed_native(tmp_path, services)
        with pytest.raises(DeployError, match="not a service"):
            _run(["restart", "frontend", "--dir", str(tmp_path)], _native_context(services))

    def test_a_docker_install_restarts_its_containers(self, tmp_path):
        assert _run(["up", "--yes", "--dir", str(tmp_path)], _context()) == 0
        docker = FakeDocker()
        assert _run(["restart", "--dir", str(tmp_path)], _context(docker)) == 0
        assert ["restart"] in [args for _, args in docker.calls]


class TestEnvApplies:
    def test_a_running_native_install_restarts_itself(self, tmp_path, capsys):
        """The old advice was to run `docsgpt up` again, which reruns migrations to change one value."""
        services = FakeServices()
        _installed_native(tmp_path, services)
        services.started.clear()

        argv = ["env", "--dir", str(tmp_path), "set", "LLM_NAME=gpt-4o"]
        assert _run(argv, _native_context(services)) == 0
        assert envfile.read(tmp_path / ".env")["LLM_NAME"] == "gpt-4o"
        assert services.started == list(_names(tmp_path))
        assert "Restarted" in capsys.readouterr().out

    def test_no_restart_leaves_the_services_alone(self, tmp_path, capsys):
        services = FakeServices()
        _installed_native(tmp_path, services)
        services.started.clear()

        argv = ["env", "--dir", str(tmp_path), "set", "LLM_NAME=gpt-4o", "--no-restart"]
        assert _run(argv, _native_context(services)) == 0
        assert services.started == []
        assert "docsgpt up" in capsys.readouterr().out

    def test_a_stopped_install_is_not_started_by_a_settings_change(self, tmp_path):
        services = FakeServices()
        _installed_native(tmp_path, services)
        for name in _names(tmp_path):
            services.stop(name)
        services.started.clear()

        argv = ["env", "--dir", str(tmp_path), "set", "LLM_NAME=gpt-4o"]
        assert _run(argv, _native_context(services)) == 0
        assert services.started == [], "changing a setting does not start a stopped install"


class TestFollowLogs:
    def test_it_prints_lines_written_after_it_started(self, tmp_path, capsys, monkeypatch):
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "api.log").write_text("old line\n", encoding="utf-8")

        rounds = {"n": 0}

        def sleep(_):
            rounds["n"] += 1
            if rounds["n"] == 1:
                (logs / "api.log").open("a", encoding="utf-8").write("new line\n")
                return
            raise KeyboardInterrupt

        monkeypatch.setattr(commands.time, "sleep", sleep)
        assert commands._follow(logs, ["api"]) == 0
        printed = capsys.readouterr().out
        assert "api    | new line" in printed
        assert "old line" not in printed, "it starts at the end, like tail -f"


class TestChecks:
    def test_the_public_api_needs_no_key(self):
        check = commands._check_provider({"LLM_PROVIDER": "docsgpt"})
        assert check.level == "ok"

    def test_a_provider_without_a_key_is_a_problem(self):
        check = commands._check_provider({"LLM_PROVIDER": "openai"})
        assert check.level == "fail"
        assert "API_KEY" in check.detail

    def test_a_provider_with_a_key_and_a_base_url(self):
        check = commands._check_provider(
            {"LLM_PROVIDER": "openai", "API_KEY": "x", "OPENAI_BASE_URL": "http://localhost:8090/v1"}
        )
        assert check.level == "ok"
        assert "8090" in check.detail

    def test_services_are_named_for_the_install(self, tmp_path):
        names = _names(tmp_path)
        assert commands._chosen_services(names, []) == list(names)
        assert commands._chosen_services(names, ["worker"]) == [names[1]]
        assert commands._chosen_services(names, [names[0]]) == [names[0]]


class TestDoctor:
    def _only(self, monkeypatch, postgres, redis):
        monkeypatch.setattr(commands, "_check_postgres", lambda uri: postgres)
        monkeypatch.setattr(commands, "_check_redis", lambda urls: redis)

    def test_it_reports_every_check_and_succeeds_when_they_pass(self, tmp_path, capsys, monkeypatch):
        self._only(
            monkeypatch,
            commands.Check("postgres", "ok", "PostgreSQL 16.2, schema at 0031"),
            commands.Check("redis", "ok", "answering on 3 database(s)"),
        )
        (tmp_path / ".env").write_text("LLM_PROVIDER=docsgpt\n", encoding="utf-8")
        assert _run(["doctor", "--dir", str(tmp_path)], _context()) == 0
        out = capsys.readouterr().out
        assert "postgres" in out and "redis" in out and "provider" in out

    def test_a_failing_check_makes_it_exit_one(self, tmp_path, capsys, monkeypatch):
        self._only(
            monkeypatch,
            commands.Check("postgres", "fail", "cannot connect: refused"),
            commands.Check("redis", "ok", "answering"),
        )
        (tmp_path / ".env").write_text("LLM_PROVIDER=docsgpt\n", encoding="utf-8")
        assert _run(["doctor", "--dir", str(tmp_path)], _context()) == 1
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "1 problem" in captured.err

    def test_it_says_which_settings_file_it_read(self, tmp_path, capsys, monkeypatch):
        self._only(
            monkeypatch,
            commands.Check("postgres", "ok", "fine"),
            commands.Check("redis", "ok", "fine"),
        )
        (tmp_path / ".env").write_text("LLM_PROVIDER=docsgpt\n", encoding="utf-8")
        _run(["doctor", "--dir", str(tmp_path)], _context())
        assert str(tmp_path / ".env") in capsys.readouterr().out
