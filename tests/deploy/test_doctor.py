"""`docsgpt doctor`, `restart`, following native logs, and settings that apply themselves."""

import socket

import pytest

from docsgpt.deploy import commands, envfile
from docsgpt.deploy.docker import DeployError

from .test_commands import FakeDocker, _context, _run
from .test_native import FakeServices, _names, _native_context


def _installed_native(tmp_path, services):
    argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/d"]
    assert _run(argv, _native_context(services)) == 0


class TestDevCommand:
    def _checkout(self, monkeypatch, tmp_path):
        from docsgpt.core import paths

        monkeypatch.setattr(paths, "checkout_root", lambda: tmp_path)

    def _free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def test_an_installed_package_is_pointed_at_native_mode(self, monkeypatch):
        """`dev` runs the code you are editing; there is none to edit outside a checkout."""
        from docsgpt.core import paths

        monkeypatch.setattr(paths, "checkout_root", lambda: None)
        with pytest.raises(DeployError, match="source checkout"):
            _run(["dev"], _context())

    def test_a_busy_port_is_refused_before_anything_starts(self, monkeypatch, tmp_path):
        from docsgpt.deploy import dev as dev_module

        self._checkout(monkeypatch, tmp_path)
        started = []
        monkeypatch.setattr(dev_module, "run", lambda children, **kwargs: started.append(children) or 0)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            port = held.getsockname()[1]
            with pytest.raises(DeployError, match="already in use"):
                _run(["dev", "--port", str(port)], _context())
        assert started == [], "nothing is spawned when the port is taken"

    def test_it_runs_the_children_it_planned_and_says_where(self, monkeypatch, tmp_path, capsys):
        from docsgpt.deploy import dev as dev_module

        self._checkout(monkeypatch, tmp_path)
        started = []
        monkeypatch.setattr(dev_module, "run", lambda children, **kwargs: started.append(children) or 0)
        port = self._free_port()
        assert _run(["dev", "--port", str(port)], _context()) == 0
        assert [child.name for child in started[0]] == ["api", "worker"]
        printed = capsys.readouterr().out
        assert f"http://127.0.0.1:{port}" in printed
        assert "Ctrl-C" in printed


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


class FakeCursor:
    """Answers doctor's three queries in order: server version, whether the table is there, the revision."""

    def __init__(self, version, table, revision):
        self.answers = [(version,), (table,), (revision,) if revision else None]
        self.given = 0
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)

    def fetchone(self):
        answer = self.answers[self.given]
        self.given += 1
        return answer

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


def _postgres_answering(monkeypatch, version="16.2", table="alembic_version", revision="0031_x", head="0031_x"):
    import psycopg

    cursor = FakeCursor(version, table, revision)
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: FakeConnection(cursor))
    monkeypatch.setattr(commands, "_migration_head", lambda: head)
    return cursor


class TestPostgresCheck:
    def test_at_head(self, monkeypatch):
        _postgres_answering(monkeypatch)
        check = commands._check_postgres("postgresql://localhost/d")
        assert check.level == "ok"
        assert "16.2" in check.detail and "0031_x" in check.detail

    def test_the_revision_comes_from_the_schema_that_was_checked(self, monkeypatch):
        """to_regclass looks in public, so the second query must not resolve through search_path."""
        cursor = _postgres_answering(monkeypatch)
        commands._check_postgres("postgresql://localhost/d")
        revision_query = [statement for statement in cursor.statements if "version_num" in statement]
        assert revision_query and all("public.alembic_version" in statement for statement in revision_query)

    def test_a_database_with_no_schema_yet(self, monkeypatch):
        """The commonest first-run state: the database exists, nothing has been migrated into it."""
        _postgres_answering(monkeypatch, table=None, revision=None)
        check = commands._check_postgres("postgresql://localhost/d")
        assert check.level == "fail"
        assert "docsgpt migrate" in check.detail

    def test_a_schema_behind_this_version(self, monkeypatch):
        _postgres_answering(monkeypatch, revision="0029_old", head="0031_x")
        check = commands._check_postgres("postgresql://localhost/d")
        assert check.level == "fail"
        assert "0029_old" in check.detail and "0031_x" in check.detail
        assert "docsgpt migrate" in check.detail

    def test_a_database_that_does_not_answer(self, monkeypatch):
        import psycopg

        def refuse(*args, **kwargs):
            raise psycopg.OperationalError("connection refused")

        monkeypatch.setattr(psycopg, "connect", refuse)
        check = commands._check_postgres("postgresql://localhost/d")
        assert check.level == "fail"
        assert "connection refused" in check.detail

    def test_a_database_password_is_never_printed(self, monkeypatch):
        """psycopg quotes the connection string it was given, which carries the password."""
        import psycopg

        uri = "postgresql://docsgpt:hunter2@db.example.com:5432/docsgpt"

        def refuse(*args, **kwargs):
            raise psycopg.OperationalError(f'connection to "{uri}" failed: timeout expired')

        monkeypatch.setattr(psycopg, "connect", refuse)
        check = commands._check_postgres(uri)
        assert check.level == "fail"
        assert "hunter2" not in check.detail
        assert "db.example.com:5432" in check.detail, "the endpoint still has to be identifiable"
        assert "timeout expired" in check.detail, "and the reason has to survive the scrubbing"

    def test_without_a_uri_at_all(self):
        check = commands._check_postgres(None)
        assert check.level == "fail"
        assert "POSTGRES_URI" in check.detail


class TestRedisCheck:
    def test_every_database_answering(self, monkeypatch):
        import redis

        monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url, **k: type("R", (), {"ping": lambda self: True})()))
        check = commands._check_redis({"broker": "redis://localhost:6379/0", "cache": "redis://localhost:6379/2"})
        assert check.level == "ok"
        assert "2" in check.detail

    def test_the_one_that_does_not_answer_is_named(self, monkeypatch):
        """Three URLs usually differ only by database number, so the message has to say which."""
        import redis

        def from_url(cls, url, **kwargs):
            class Client:
                def ping(self):
                    raise ConnectionError(f"no route to {url}")

            return Client()

        monkeypatch.setattr(redis.Redis, "from_url", classmethod(from_url))
        check = commands._check_redis({"cache": "redis://localhost:6379/2"})
        assert check.level == "fail"
        assert "cache" in check.detail and "6379/2" in check.detail

    def test_a_password_in_the_url_is_never_printed(self, monkeypatch):
        """doctor output goes into terminals, CI logs and pasted issue reports."""
        import redis

        def from_url(cls, url, **kwargs):
            class Client:
                def ping(self):
                    # redis-py quotes the URL it was handed, which is how the credentials got out.
                    raise ConnectionError(f"no route to {url}")

            return Client()

        monkeypatch.setattr(redis.Redis, "from_url", classmethod(from_url))
        check = commands._check_redis({"broker": "rediss://default:sUpErSeCrEt@redis.example.com:6380/0"})
        assert check.level == "fail"
        assert "sUpErSeCrEt" not in check.detail
        assert "default" not in check.detail
        assert "redis.example.com:6380/0" in check.detail, "the endpoint still has to be identifiable"

    def test_a_malformed_url_is_not_echoed_either(self):
        assert commands._endpoint("redis://[::1") == "the configured URL"

    def test_without_any_redis_configured(self):
        assert commands._check_redis({}).level == "fail"


class TestMigrationHead:
    def test_it_finds_the_revision_this_package_ships(self):
        """No database needed: this is the alembic.ini path resolution, which breaks silently."""
        head = commands._migration_head()
        assert head, "the packaged alembic.ini should resolve to a revision"
        assert head[0].isdigit(), head


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

    def test_a_hand_edited_port_is_reported_not_raised(self, tmp_path, monkeypatch):
        """Doctor exists to explain a broken setup, so it must not traceback on one."""
        self._only(
            monkeypatch,
            commands.Check("postgres", "ok", "fine"),
            commands.Check("redis", "ok", "fine"),
        )
        (tmp_path / ".env").write_text("DOCSGPT_PORT=seven thousand\n", encoding="utf-8")
        with pytest.raises(DeployError, match="not a port number"):
            _run(["doctor", "--dir", str(tmp_path)], _context())

    def test_it_says_which_settings_file_it_read(self, tmp_path, capsys, monkeypatch):
        self._only(
            monkeypatch,
            commands.Check("postgres", "ok", "fine"),
            commands.Check("redis", "ok", "fine"),
        )
        (tmp_path / ".env").write_text("LLM_PROVIDER=docsgpt\n", encoding="utf-8")
        _run(["doctor", "--dir", str(tmp_path)], _context())
        assert str(tmp_path / ".env") in capsys.readouterr().out
