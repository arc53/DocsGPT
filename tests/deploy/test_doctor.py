"""`docsgpt doctor`, `restart`, following native logs, and settings that apply themselves."""

import argparse
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

    @pytest.mark.parametrize("port", ["0", "-1", "70000"])
    def test_a_port_argparse_accepts_but_a_socket_cannot_use(self, monkeypatch, tmp_path, port):
        """argparse takes any integer: 0 would serve on an ephemeral port while printing 0."""
        from docsgpt.deploy import dev as dev_module

        self._checkout(monkeypatch, tmp_path)
        started = []
        monkeypatch.setattr(dev_module, "run", lambda children, **kwargs: started.append(children) or 0)
        with pytest.raises(DeployError, match="not a port number"):
            _run(["dev", "--port", port], _context())
        assert started == []

    def test_a_busy_mock_llm_port_is_refused_before_anything_starts(self, monkeypatch, tmp_path):
        """It starts first and the rest are pointed at it, so a clash cannot wait until spawn time."""
        from docsgpt.deploy import dev as dev_module

        self._checkout(monkeypatch, tmp_path)
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "mock_llm.py").write_text("", encoding="utf-8")
        started = []
        monkeypatch.setattr(dev_module, "run", lambda children, **kwargs: started.append(children) or 0)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            monkeypatch.setattr(dev_module, "MOCK_LLM_PORT", held.getsockname()[1])
            with pytest.raises(DeployError, match="mock LLM cannot bind"):
                _run(["dev", "--mock-llm", "--port", str(self._free_port())], _context())
        assert started == [], "nothing is spawned when the mock LLM has nowhere to listen"

    def test_the_api_cannot_be_given_the_mock_llm_port(self, monkeypatch, tmp_path):
        """Both free-port checks pass here: the port is free, and then two children want it."""
        from docsgpt.deploy import dev as dev_module

        self._checkout(monkeypatch, tmp_path)
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "mock_llm.py").write_text("", encoding="utf-8")
        started = []
        monkeypatch.setattr(dev_module, "run", lambda children, **kwargs: started.append(children) or 0)
        monkeypatch.setattr(dev_module, "MOCK_LLM_PORT", self._free_port())
        with pytest.raises(DeployError, match="mock LLM listens"):
            _run(["dev", "--mock-llm", "--port", str(dev_module.MOCK_LLM_PORT)], _context())
        assert started == [], "nothing is spawned when the two would collide"

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


class TestLogsTransition:
    def test_a_line_written_between_the_read_and_the_follow_is_not_lost(self, tmp_path, capsys, monkeypatch):
        """The read and the follow used to open the file twice, and whatever landed between was gone."""
        services = FakeServices()
        argv = ["up", "--native", "--dir", str(tmp_path), "--yes", "--postgres-uri", "postgresql://localhost/d"]
        assert _run(argv, _native_context(services)) == 0
        logs = tmp_path / "logs"
        (logs / "api.log").write_text("first\n", encoding="utf-8")

        def sleep(_):
            raise KeyboardInterrupt

        original = commands._follow

        def follow(logs_dir, wanted, handles=None):
            # Written after the read, before following starts.
            (logs / "api.log").open("a", encoding="utf-8").write("during\n")
            monkeypatch.setattr(commands.time, "sleep", sleep)
            return original(logs_dir, wanted, handles)

        monkeypatch.setattr(commands, "_follow", follow)
        assert _run(["logs", "-f", "api", "--dir", str(tmp_path)], _native_context(services)) == 0
        printed = capsys.readouterr().out
        assert "first" in printed
        assert "during" in printed, "the line written during the handover has to appear"


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

    def test_a_provider_base_url_is_printed_without_its_credentials(self):
        """An OpenAI-compatible endpoint can carry userinfo, and doctor prints its detail."""
        check = commands._check_provider(
            {"LLM_PROVIDER": "openai", "API_KEY": "x",
             "OPENAI_BASE_URL": "https://someone:sEcReTtOkEn@models.example.com/v1"}
        )
        assert check.level == "ok"
        assert "sEcReTtOkEn" not in check.detail
        assert "someone" not in check.detail
        assert "models.example.com" in check.detail

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

    def test_both_queries_resolve_the_same_table(self, monkeypatch):
        """Alembic sets no version_table_schema, so the table follows search_path; asserting a
        schema in one query and not the other is how doctor called a migrated database empty."""
        cursor = _postgres_answering(monkeypatch)
        commands._check_postgres("postgresql://localhost/d")
        looked_up = [statement for statement in cursor.statements if "to_regclass" in statement]
        read = [statement for statement in cursor.statements if "version_num" in statement]
        assert looked_up and read
        assert all("public." not in statement for statement in looked_up + read), (
            "neither query may pin a schema alembic never promised"
        )

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
        # Compared against what the sanitiser produced, not a host substring: asking whether a URL
        # contains a host is the check CodeQL warns about, and it is not what this test means.
        assert check.detail.startswith(f"cannot connect to {commands._endpoint(uri)}")
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
        url = "rediss://default:sUpErSeCrEt@redis.example.com:6380/0"
        check = commands._check_redis({"broker": url})
        assert check.level == "fail"
        assert "sUpErSeCrEt" not in check.detail
        assert "default" not in check.detail
        assert check.detail.startswith(f"broker ({commands._endpoint(url)}) does not answer")

    @pytest.mark.parametrize("url", ["redis://[::1", "redis://localhost:not-a-port/0"])
    def test_a_malformed_url_is_not_echoed_either(self, url):
        """urlsplit raises on the first; on the second it succeeds and .port raises on access."""
        assert commands._endpoint(url) == "the configured URL"

    def test_a_failure_on_a_url_with_an_unparsable_port_is_still_a_check(self, monkeypatch):
        """The check catches the client error and then formats it, which is where this raised."""
        import redis

        def from_url(cls, url, **kwargs):
            class Client:
                def ping(self):
                    raise ConnectionError(f"no route to {url}")

            return Client()

        monkeypatch.setattr(redis.Redis, "from_url", classmethod(from_url))
        check = commands._check_redis({"broker": "redis://localhost:not-a-port/0"})
        assert check.level == "fail", "a bad port is a finding, not a traceback"
        assert "the configured URL" in check.detail

    def test_without_any_redis_configured(self):
        assert commands._check_redis({}).level == "fail"


class TestMigrationHead:
    def test_it_finds_the_revision_this_package_ships(self):
        """No database needed: this is the alembic.ini path resolution, which breaks silently."""
        head = commands._migration_head()
        assert head, "the packaged alembic.ini should resolve to a revision"
        assert head[0].isdigit(), head


class TestRedisSelection:
    def test_redis_url_replaces_every_endpoint(self):
        """Overriding only the broker would still ping a stale backend, and one failure fails all."""
        args = argparse.Namespace(redis_url="redis://given:6379/5")
        stale = {
            "CELERY_BROKER_URL": "redis://old:6379/0",
            "CELERY_RESULT_BACKEND": "redis://old:6379/1",
            "CACHE_REDIS_URL": "redis://old:6379/2",
        }
        chosen = commands._redis_to_check(args, stale)
        assert set(chosen) == {"broker", "results", "cache"}
        assert all("old" not in url for url in chosen.values()), chosen
        assert chosen["broker"].endswith("/5") and chosen["cache"].endswith("/7")

    def test_without_the_flag_the_settings_are_used(self):
        args = argparse.Namespace(redis_url=None)
        chosen = commands._redis_to_check(args, {"CELERY_BROKER_URL": "redis://localhost:6379/0"})
        assert chosen == {"broker": "redis://localhost:6379/0"}


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
