"""The ``docsgpt`` command dispatches to the API server, the worker and the scripts."""

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import click
import pytest

from docsgpt import cli
from docsgpt.core.paths import package_dir
from docsgpt.version import __version__


class TestTopLevel:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--version"])
        assert exc.value.code == 0
        assert capsys.readouterr().out.strip() == f"docsgpt {__version__}"

    def test_no_command_prints_help(self, capsys):
        assert cli.main([]) == 2
        assert "worker" in capsys.readouterr().out

    def test_importing_the_cli_does_not_boot_the_app(self):
        """``docsgpt --help`` must not import the Flask app, Celery or settings."""
        code = (
            "import sys, docsgpt.cli; "
            "loaded = {m for m in sys.modules if m in ('docsgpt.app', 'docsgpt.core.settings', 'celery', 'flask')}; "
            "assert not loaded, loaded"
        )
        subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], check=True)


class TestModuleEntrypoint:
    def test_python_m_docsgpt_runs_the_cli(self):
        """`python -m docsgpt` is what a native service falls back to when the script is not on PATH."""
        result = subprocess.run(
            [sys.executable, "-m", "docsgpt", "--version"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == f"docsgpt {__version__}"


class TestHome:
    @staticmethod
    def _installed(monkeypatch, tmp_path):
        """An installed package (no checkout) with the default home under tmp_path."""
        from docsgpt.core import paths

        monkeypatch.delenv(paths.HOME_ENV, raising=False)
        monkeypatch.delenv(paths.ENV_FILE_ENV, raising=False)
        monkeypatch.setattr(paths, "checkout_root", lambda: None)
        monkeypatch.setattr(paths, "default_home", lambda: tmp_path / "home")
        return tmp_path / "home"

    def test_the_home_is_created_and_announced(self, monkeypatch, tmp_path, capsys):
        home = self._installed(monkeypatch, tmp_path)
        monkeypatch.chdir(tmp_path)
        cli._announce_home()
        assert home.is_dir()
        assert f"data home {home}" in capsys.readouterr().err

    def test_an_env_file_left_in_the_working_directory_is_pointed_out(self, monkeypatch, tmp_path, capsys):
        """Up to 0.20 an installed package read .env from the working directory."""
        home = self._installed(monkeypatch, tmp_path)
        work = tmp_path / "work"
        work.mkdir()
        (work / ".env").write_text("LLM_PROVIDER=openai\n")
        monkeypatch.chdir(work)
        cli._announce_home()
        err = capsys.readouterr().err
        assert f"{work / '.env'} is not used" in err
        assert f"DOCSGPT_HOME={work}" in err
        assert str(home) in err

    def test_no_warning_when_the_home_is_chosen_explicitly(self, monkeypatch, tmp_path, capsys):
        from docsgpt.core import paths

        self._installed(monkeypatch, tmp_path)
        (tmp_path / ".env").write_text("LLM_PROVIDER=openai\n")
        monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "elsewhere"))
        monkeypatch.chdir(tmp_path)
        cli._announce_home()
        assert "is not used" not in capsys.readouterr().err

    def test_no_warning_when_the_working_directory_is_the_home(self, monkeypatch, tmp_path, capsys):
        home = self._installed(monkeypatch, tmp_path)
        home.mkdir()
        (home / ".env").write_text("LLM_PROVIDER=openai\n")
        monkeypatch.chdir(home)
        cli._announce_home()
        assert "is not used" not in capsys.readouterr().err


class TestApi:
    def test_gunicorn_runs_with_the_image_settings_and_leaves_argv_alone(self, monkeypatch, capsys):
        application = MagicMock()
        factory = MagicMock(return_value=application)
        monkeypatch.setattr(cli, "_gunicorn_application", factory)
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(sys, "argv", ["/venv/bin/docsgpt", "api", "--port", "8000"])
        assert cli.main(["api", "--port", "8000", "--workers", "2"]) == 0
        application.run.assert_called_once_with()
        options = factory.call_args.args[0]
        assert options["bind"] == "127.0.0.1:8000"
        assert options["workers"] == 2
        assert options["worker_class"] == "docsgpt.gunicorn_worker.BoundedDrainUvicornWorker"
        assert options["max_requests"] == 5000
        # gunicorn re-executes sys.argv on SIGUSR2; it must still be the docsgpt invocation.
        assert sys.argv == ["/venv/bin/docsgpt", "api", "--port", "8000"]
        assert "data home" in capsys.readouterr().err

    def test_the_gunicorn_application_carries_the_settings_and_the_log_config(self):
        app = cli._gunicorn_application(cli._gunicorn_options("127.0.0.1", 8001, 3))
        assert app.cfg.bind == ["127.0.0.1:8001"]
        assert app.cfg.workers == 3
        assert app.cfg.worker_class_str == "docsgpt.gunicorn_worker.BoundedDrainUvicornWorker"
        assert app.cfg.keepalive == 5
        assert app.cfg.graceful_timeout == 120
        assert "ncsa_access" in app.cfg.logconfig_dict["formatters"], "docsgpt.gunicorn_conf was loaded"

    def test_reload_uses_uvicorn(self, monkeypatch):
        uvicorn = types.SimpleNamespace(run=MagicMock())
        monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
        assert cli.main(["api", "--reload", "--host", "127.0.0.1"]) == 0
        uvicorn.run.assert_called_once_with(
            "docsgpt.asgi:asgi_app", host="127.0.0.1", port=7091, reload=True,
            reload_dirs=[str(package_dir())],
        )

    def test_reload_watches_the_package_not_the_working_directory(self, monkeypatch, tmp_path):
        """A checkout also holds .venv, node_modules and the indexes and inputs the app writes to,
        so watching the working directory restarts the server mid-ingest."""
        uvicorn = types.SimpleNamespace(run=MagicMock())
        monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
        monkeypatch.chdir(tmp_path)
        assert cli.main(["api", "--reload"]) == 0
        watched = uvicorn.run.call_args.kwargs["reload_dirs"]
        assert watched == [str(package_dir())]
        assert str(tmp_path) not in watched

    def test_without_reload_nothing_is_watched(self, monkeypatch):
        uvicorn = types.SimpleNamespace(run=MagicMock())
        monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
        monkeypatch.setattr(sys, "platform", "win32")
        assert cli.main(["api"]) == 0
        assert uvicorn.run.call_args.kwargs["reload_dirs"] is None


class TestWorker:
    @staticmethod
    def _celery(monkeypatch, start=None):
        celery = MagicMock()
        celery.start = start or MagicMock(return_value=0)
        monkeypatch.setitem(sys.modules, "docsgpt.app", types.SimpleNamespace(celery=celery))
        return celery

    def test_defaults_consume_every_configured_queue(self, monkeypatch, capsys):
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "linux")
        assert cli.main(["worker"]) == 0
        argv = celery.start.call_args.args[0]
        assert argv[:3] == ["worker", "-l", "INFO"]
        assert "-Q" not in argv, "a bare worker honours EMBEDDINGS_QUEUE and DOCUMENT_PARSE_QUEUE"
        assert "-B" in argv
        assert "--pool" not in argv
        assert "data home" in capsys.readouterr().err

    def test_options_and_the_macos_solo_pool(self, monkeypatch):
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")
        assert cli.main(["worker", "--no-beat", "-Q", "embeddings", "--concurrency", "2"]) == 0
        argv = celery.start.call_args.args[0]
        assert argv[argv.index("--pool") + 1] == "solo"
        assert "-B" not in argv
        assert argv[argv.index("-Q") + 1] == "embeddings"
        assert argv[argv.index("--concurrency") + 1] == "2"

    def test_windows_runs_solo_without_the_embedded_scheduler(self, monkeypatch, capsys):
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "win32")
        assert cli.main(["worker"]) == 0
        argv = celery.start.call_args.args[0]
        assert "-B" not in argv
        assert argv[argv.index("--pool") + 1] == "solo"
        assert "docsgpt beat" in capsys.readouterr().err

    def test_the_solo_pool_leaves_the_analytics_queue_alone(self, monkeypatch, capsys):
        """A sweep holds a solo worker for minutes, and query embeddings queued behind it time out."""
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_ANALYTICS_ENABLED", True)
        assert cli.main(["worker"]) == 0
        argv = celery.start.call_args.args[0]
        assert argv[argv.index("--pool") + 1] == "solo"
        assert argv[argv.index("-X") + 1] == "analytics"
        assert "-Q" not in argv, "every other queue is still consumed"
        assert "-B" in argv, "the scheduler still runs embedded"
        assert "docsgpt worker --analytics" in capsys.readouterr().err

    def test_the_solo_pool_leaves_the_analytics_queue_alone_with_analytics_off(self, monkeypatch, capsys):
        """``docsgpt dev`` then starts no analytics worker, and the queue gets nothing to hold."""
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_ANALYTICS_ENABLED", False)
        assert cli.main(["worker"]) == 0
        assert celery.start.call_args.args[0][celery.start.call_args.args[0].index("-X") + 1] == "analytics"
        assert "docsgpt worker --analytics" not in capsys.readouterr().err

    def test_a_shared_prefork_pool_keeps_the_analytics_queue(self, monkeypatch):
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "linux")
        assert cli.main(["worker"]) == 0
        assert "-X" not in celery.start.call_args.args[0]

    def test_explicit_queues_on_the_solo_pool_are_left_as_given(self, monkeypatch):
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")
        assert cli.main(["worker", "-Q", "docsgpt,analytics"]) == 0
        argv = celery.start.call_args.args[0]
        assert "-X" not in argv
        assert argv[argv.index("-Q") + 1] == "docsgpt,analytics"

    @pytest.mark.parametrize("shared", ["docsgpt", "ingest"])
    def test_an_analytics_queue_shared_with_another_is_not_excluded(self, monkeypatch, shared):
        """Excluding it would drop the queue it shares, such as ``docsgpt`` or ``ingest``."""
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr("docsgpt.core.settings.settings.ANALYTICS_QUEUE", shared)
        assert cli.main(["worker"]) == 0
        assert "-X" not in celery.start.call_args.args[0]

    def test_the_analytics_worker_consumes_only_its_queue_without_the_scheduler(self, monkeypatch):
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr("docsgpt.core.settings.settings.ANALYTICS_QUEUE", "labels")
        assert cli.main(["worker", "--analytics"]) == 0
        argv = celery.start.call_args.args[0]
        assert argv[argv.index("-Q") + 1] == "labels"
        assert "-B" not in argv, "one scheduler is enough, and the main worker embeds it"
        assert "-X" not in argv
        assert argv[argv.index("--pool") + 1] == "solo"

    def test_the_analytics_worker_runs_one_process_on_prefork(self, monkeypatch):
        """Sweeps are single-flight under a lock, so more processes would only hold memory."""
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "linux")
        assert cli.main(["worker", "--analytics"]) == 0
        argv = celery.start.call_args.args[0]
        assert argv[argv.index("--concurrency") + 1] == "1"

    def test_the_analytics_worker_has_its_own_node_name(self, monkeypatch):
        """Beside the main worker on one host, a shared celery@host name clashes and inspect replies collide."""
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")
        assert cli.main(["worker", "--analytics"]) == 0
        argv = celery.start.call_args.args[0]
        assert argv[argv.index("-n") + 1] == "analytics@%h"
        assert cli.main(["worker"]) == 0
        assert "-n" not in celery.start.call_args.args[0], "the main worker keeps Celery's default name"

    def test_the_analytics_worker_takes_no_queue_list(self, monkeypatch, capsys):
        self._celery(monkeypatch)
        with pytest.raises(SystemExit) as exc:
            cli.main(["worker", "--analytics", "-Q", "docsgpt"])
        assert exc.value.code == 2

    def test_the_worker_exit_code_is_returned(self, monkeypatch):
        self._celery(monkeypatch, start=MagicMock(return_value=1))
        monkeypatch.setattr(sys, "platform", "linux")
        assert cli.main(["worker"]) == 1

    def test_a_usage_error_prints_usage_instead_of_a_traceback(self, monkeypatch, capsys):
        self._celery(monkeypatch, start=MagicMock(side_effect=click.UsageError("No such option: --bogus")))
        monkeypatch.setattr(sys, "platform", "linux")
        assert cli.main(["worker"]) == 2
        assert "No such option" in capsys.readouterr().err


class TestBeat:
    def test_runs_the_scheduler_alone(self, monkeypatch):
        celery = MagicMock()
        celery.start = MagicMock(return_value=0)
        monkeypatch.setitem(sys.modules, "docsgpt.app", types.SimpleNamespace(celery=celery))
        assert cli.main(["beat", "-l", "DEBUG"]) == 0
        assert celery.start.call_args.args[0] == ["beat", "-l", "DEBUG"]


class TestMigrate:
    def test_runs_the_bootstrap(self, monkeypatch):
        ensure = MagicMock()
        monkeypatch.setattr("docsgpt.storage.db.bootstrap.ensure_database_ready", ensure)
        monkeypatch.setattr("docsgpt.core.settings.settings.POSTGRES_URI", "postgresql://docsgpt@localhost/docsgpt")
        assert cli.main(["migrate", "--no-create"]) == 0
        assert ensure.call_args.args[0] == "postgresql://docsgpt@localhost/docsgpt"
        assert ensure.call_args.kwargs["create_db"] is False
        assert ensure.call_args.kwargs["migrate"] is True

    def test_without_a_database_uri(self, monkeypatch, capsys):
        monkeypatch.setattr("docsgpt.core.settings.settings.POSTGRES_URI", None)
        assert cli.main(["migrate"]) == 2
        assert "POSTGRES_URI" in capsys.readouterr().err


class TestConnectorsReencrypt:
    def _counts(self, monkeypatch, connections, saved):
        monkeypatch.setattr("docsgpt.connectors.service.reencrypt_all", lambda: connections)
        monkeypatch.setattr("docsgpt.connectors.service.reencrypt_saved_secrets", lambda: saved)

    def test_rewrites_connections_and_saved_secrets(self, monkeypatch, capsys):
        self._counts(
            monkeypatch,
            {"rewritten": 2, "current": 1, "failed": 0},
            {"rewritten": 3, "current": 4, "failed": 0},
        )
        assert cli.main(["connectors", "reencrypt"]) == 0
        err = capsys.readouterr().err
        assert "re-encrypted 2 connection(s), 1 already current, 0 unreadable" in err
        assert "re-encrypted 3 tool and custom-model secret(s), 4 already current, 0 unreadable" in err
        assert "ENCRYPTION_SECRET_KEY_PREVIOUS can be removed" in err

    def test_unreadable_saved_secrets_fail_the_run_and_keep_the_previous_key(self, monkeypatch, capsys):
        self._counts(
            monkeypatch,
            {"rewritten": 0, "current": 0, "failed": 0},
            {"rewritten": 0, "current": 0, "failed": 2},
        )
        assert cli.main(["connectors", "reencrypt"]) == 1
        err = capsys.readouterr().err
        assert "left unchanged" in err
        assert "can be removed" not in err

    def test_help_names_what_it_rewrites(self):
        # argparse wraps long help at hyphens; undo that before matching.
        help_text = " ".join(cli.build_parser().format_help().split()).replace("- ", "-")
        assert "tool and custom-model secrets" in help_text


AGENT = "5f0c8a52-3f3e-4f55-9a0e-6f8d2c1b7a90"


class TestAnalyticsBackfill:
    @pytest.fixture(autouse=True)
    def _restore_the_worker_flag(self, monkeypatch):
        monkeypatch.setattr("docsgpt.celery_init._IS_WORKER_PROCESS", False)

    def test_without_an_action_prints_usage(self, capsys):
        assert cli.main(["analytics"]) == 2
        assert "docsgpt analytics backfill --days N" in capsys.readouterr().err

    def test_zero_days_are_refused_not_replaced_by_the_default(self, capsys):
        assert cli.main(["analytics", "backfill", "--days", "0", "--dry-run"]) == 2
        assert "--days must be 1 to ANALYTICS_RETENTION_DAYS" in capsys.readouterr().err

    def test_days_past_retention_are_refused(self, capsys):
        assert cli.main(["analytics", "backfill", "--days", "365"]) == 2
        assert "ANALYTICS_RETENTION_DAYS (90)" in capsys.readouterr().err

    def test_dry_run_prints_the_estimate_and_calls_like_a_worker(self, monkeypatch, capsys):
        import json

        import docsgpt.celery_init as celery_init
        from docsgpt.analytics import tasks

        seen = []

        def estimate(days, agent_id):
            seen.append((days, agent_id, celery_init.in_worker()))
            return {"messages": 3}

        monkeypatch.setattr(tasks, "backfill_estimate", estimate)
        monkeypatch.setattr(tasks, "sweep", lambda **kwargs: pytest.fail("a dry run labels nothing"))
        assert cli.main(["analytics", "backfill", "--days", "3", "--agent", AGENT, "--dry-run"]) == 0
        assert json.loads(capsys.readouterr().out) == {"messages": 3}
        assert seen == [(3, AGENT, True)]

    @pytest.mark.parametrize("dry_run", [[], ["--dry-run"]])
    def test_an_agent_that_is_not_an_id_is_refused(self, monkeypatch, capsys, dry_run):
        """It would reach the database as a failed uuid cast and a traceback."""
        from docsgpt.analytics import tasks

        monkeypatch.setattr(tasks, "enabled", lambda: True)
        monkeypatch.setattr(tasks, "sweep", lambda **kwargs: pytest.fail("not an agent id"))
        monkeypatch.setattr(tasks, "backfill_estimate", lambda *args: pytest.fail("not an agent id"))
        assert cli.main(["analytics", "backfill", "--agent", "support-bot", *dry_run]) == 2
        assert "docsgpt: --agent must be an agent id" in capsys.readouterr().err

    def test_does_nothing_while_the_switch_is_off(self, monkeypatch, capsys):
        from docsgpt.analytics import tasks

        monkeypatch.setattr(tasks, "enabled", lambda: False)
        monkeypatch.setattr(tasks, "sweep", lambda **kwargs: pytest.fail("the switch is off"))
        assert cli.main(["analytics", "backfill"]) == 1
        assert "DECISION_ANALYTICS_ENABLED is off" in capsys.readouterr().err

    def test_runs_the_sweep_without_a_budget(self, monkeypatch, capsys):
        from docsgpt.analytics import tasks

        calls = []
        monkeypatch.setattr(tasks, "enabled", lambda: True)
        monkeypatch.setattr("docsgpt.core.settings.settings.ANALYTICS_BACKFILL_DAYS", 7)
        monkeypatch.setattr(tasks, "sweep", lambda **kwargs: calls.append(kwargs) or {"messages": 2, "stopped": None})
        assert cli.main(["analytics", "backfill", "--agent", AGENT]) == 0
        assert calls == [{"budget_seconds": None, "days": 7, "agent_id": AGENT}]
        monkeypatch.setattr(tasks, "sweep", lambda **kwargs: {"stopped": "unavailable"})
        assert cli.main(["analytics", "backfill"]) == 1

    def test_waits_for_a_scheduled_sweep_to_finish(self, monkeypatch, capsys):
        """The scheduled sweep holds the lock for minutes during a backlog, which is when a backfill is run."""
        import json

        from docsgpt.analytics import tasks

        reports = iter([{"skipped": "locked"}, {"skipped": "locked"}, {"messages": 5, "stopped": None}])
        slept = []
        monkeypatch.setattr(tasks, "enabled", lambda: True)
        monkeypatch.setattr(tasks, "sweep", lambda **kwargs: next(reports))
        monkeypatch.setattr(cli, "_sleep", slept.append)
        assert cli.main(["analytics", "backfill"]) == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"messages": 5, "stopped": None}
        assert captured.err.count("a scheduled sweep is running; waiting") == 1, "said once, not per retry"
        assert slept == [cli.BACKFILL_POLL_SECONDS] * 2

    def test_no_wait_gives_up_while_a_sweep_runs(self, monkeypatch, capsys):
        from docsgpt.analytics import tasks

        monkeypatch.setattr(tasks, "enabled", lambda: True)
        monkeypatch.setattr(tasks, "sweep", lambda **kwargs: {"skipped": "locked"})
        monkeypatch.setattr(cli, "_sleep", lambda seconds: pytest.fail("--no-wait does not wait"))
        assert cli.main(["analytics", "backfill", "--no-wait"]) == 1
        assert '"skipped": "locked"' in capsys.readouterr().out

    def test_the_wait_is_bounded_by_one_scheduled_sweep(self, monkeypatch, capsys):
        """A lock still held after a whole sweep's lease means something else is wrong; say so and stop."""
        from docsgpt.analytics import tasks

        slept = []
        monkeypatch.setattr(tasks, "enabled", lambda: True)
        monkeypatch.setattr(tasks, "sweep", lambda **kwargs: {"skipped": "locked"})
        monkeypatch.setattr(cli, "_sleep", slept.append)
        monkeypatch.setattr("docsgpt.core.settings.settings.ANALYTICS_SWEEP_BUDGET_SECONDS", 240)
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_BACKGROUND_TIMEOUT", 120)
        assert cli.main(["analytics", "backfill"]) == 1
        assert sum(slept) >= 240 + 120 + 60
        assert sum(slept) < 240 + 120 + 60 + cli.BACKFILL_POLL_SECONDS
        assert "still running" in capsys.readouterr().err


class TestDecisions:
    def test_prefetch_downloads_the_selected_model(self, monkeypatch, tmp_path, capsys):
        from docsgpt.decisions import files

        calls = []
        monkeypatch.setattr(files, "ensure_onnx", lambda spec: calls.append(spec.id) or tmp_path / "onnx")
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODEL", None)
        assert cli.main(["decisions", "prefetch"]) == 0
        assert calls == ["arc53/arc-decide-0.4b-v0.2"]
        assert str(tmp_path / "onnx") in capsys.readouterr().err

    def test_prefetch_failure_is_an_error_not_a_traceback(self, monkeypatch, capsys):
        from docsgpt.decisions import files

        def offline(spec):
            raise files.FilesUnavailable("offline", "HF_HUB_OFFLINE is set")

        monkeypatch.setattr(files, "ensure_onnx", offline)
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODEL", None)
        assert cli.main(["decisions", "prefetch"]) == 1
        assert "HF_HUB_OFFLINE is set" in capsys.readouterr().err

    def test_an_unknown_model_is_refused(self, monkeypatch, capsys):
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODEL", "someone/else")
        assert cli.main(["decisions", "prefetch"]) == 2
        assert "DECISION_MODEL" in capsys.readouterr().err

    def test_without_an_action_prints_usage(self, capsys):
        assert cli.main(["decisions"]) == 2
        assert "docsgpt decisions prefetch|status" in capsys.readouterr().err

    def test_status_reports_settings_and_files_without_loading(self, monkeypatch, tmp_path, capsys):
        import json

        from docsgpt import decisions
        from docsgpt.decisions import files

        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODE", None)
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODEL", None)
        monkeypatch.setattr(files, "local_onnx_dir", lambda spec: tmp_path)
        assert cli.main(["decisions", "status"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["mode"] == "local" and report["model"] == "arc53/arc-decide-0.4b-v0.2"
        assert report["files"] == str(tmp_path) and report["revision"]
        assert "speed" not in report and "status" not in report
        assert decisions.get_decider()._backend is None

    def test_status_in_api_mode_reports_the_tokenizer(self, monkeypatch, tmp_path, capsys):
        import json

        from docsgpt.decisions import files

        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODE", None)
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODEL", None)
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_BASE_URL", "http://decider:7095")
        monkeypatch.setattr(files, "local_tokenizer", lambda spec: tmp_path / "tokenizer.json")
        monkeypatch.setattr(files, "local_onnx_dir", lambda spec: pytest.fail("API mode needs no model files"))
        monkeypatch.setattr("docsgpt.decisions.client.DecisionClient.probe", lambda self, timeout=5.0: False)
        assert cli.main(["decisions", "status"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["mode"] == "api" and report["model"] == "arc53/arc-decide-0.6b-v0.1"
        assert report["files"] == str(tmp_path / "tokenizer.json") and report["server"] == "no answer"

    def test_status_in_api_mode_reports_the_servers_model(self, monkeypatch, tmp_path, capsys):
        import json

        from docsgpt import decisions
        from docsgpt.decisions import files
        from docsgpt.decisions.backends.http import DecideBackend
        from docsgpt.decisions.models import V02
        from tests.decisions.fakes import FakeDecideServer

        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODE", None)
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODEL", None)
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_BASE_URL", "http://decider:7095")
        monkeypatch.setattr(files, "local_tokenizer", lambda spec: tmp_path / spec.id / "tokenizer.json")
        server = FakeDecideServer({"name": V02.id, "revision": V02.revision, "prompt_hash": V02.prompt_hash,
                                   "calibration": V02.calibration, "runtime": "onnx-int8", "status": "ready"})
        decider = decisions.get_decider()
        monkeypatch.setattr(decider, "_new_backend", lambda: DecideBackend(transport=server.transport()))
        assert cli.main(["decisions", "status"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert (report["model"], report["runtime"], report["status"]) == (V02.id, "onnx-int8", "ready")
        assert report["server"] == "answered" and report["files"] == str(tmp_path / V02.id / "tokenizer.json")
        assert server.paths(models=True) == ["/v1/models"]
        decider._backend.close()

    def test_status_when_off(self, capsys):
        import json

        assert cli.main(["decisions", "status"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["mode"] == "none" and "files" not in report

    def test_prefetch_for_the_torch_runtime(self, monkeypatch, tmp_path):
        from docsgpt.decisions import files

        calls = []
        monkeypatch.setattr(files, "ensure_torch", lambda spec: calls.append(spec.id) or tmp_path)
        monkeypatch.setattr(files, "ensure_onnx", lambda spec: pytest.fail("the torch runtime needs no ONNX files"))
        monkeypatch.setattr("docsgpt.core.settings.settings.DECISION_MODEL", None)
        assert cli.main(["decisions", "prefetch", "--runtime", "torch"]) == 0
        assert calls == ["arc53/arc-decide-0.4b-v0.2"]


class TestDecideServer:
    def test_runs_the_server_with_its_options(self, monkeypatch):
        served = []
        monkeypatch.setattr("docsgpt.decisions.server.serve", lambda *args: served.append(args) or 0)
        monkeypatch.setattr(cli, "_announce_home", lambda: None)
        assert cli.main(["decide-server", "--device", "mps", "--port", "7100"]) == 0
        assert served == [("127.0.0.1", 7100, "mps")]

    def test_the_device_defaults_to_the_setting(self, monkeypatch):
        served = []
        monkeypatch.setattr("docsgpt.decisions.server.serve", lambda *args: served.append(args) or 0)
        monkeypatch.setattr(cli, "_announce_home", lambda: None)
        assert cli.main(["decide-server"]) == 0
        assert served == [("127.0.0.1", 7095, None)]

    def test_an_unknown_device_is_a_usage_error(self):
        with pytest.raises(SystemExit):
            cli.main(["decide-server", "--device", "tpu"])


class TestScripts:
    def test_arguments_pass_through_untouched(self, monkeypatch):
        main = MagicMock(return_value=0)
        monkeypatch.setattr("docsgpt.scripts.prefetch_models.main", main)
        assert cli.main(["prefetch-models", "--embeddings", "x", "--help"]) == 0
        main.assert_called_once_with(["--embeddings", "x", "--help"])

    def test_the_script_exit_code_is_returned(self, monkeypatch):
        monkeypatch.setattr("docsgpt.scripts.verify_offline.main", MagicMock(return_value=3))
        assert cli.main(["verify-offline"]) == 3

    @pytest.mark.parametrize("script", ["prefetch-models", "verify-offline"])
    def test_help_is_help_not_a_model_name(self, script, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main([script, "--help"])
        assert exc.value.code == 0
        assert "models" in capsys.readouterr().out


class TestGrantAdmin:
    def test_grant_admin_is_a_command(self, monkeypatch):
        """The first-admin bootstrap must work from the image and a pip install, not only a checkout."""
        main = MagicMock(return_value=0)
        monkeypatch.setattr("docsgpt.scripts.grant_admin.main", main)
        assert cli.main(["grant-admin", "alice", "--force"]) == 0
        main.assert_called_once_with(["alice", "--force"])

    def test_listed_in_the_help(self, capsys):
        cli.build_parser().print_help()
        assert "grant-admin" in capsys.readouterr().out

    def test_help_names_the_command(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["grant-admin", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "docsgpt grant-admin" in out
        assert "--revoke" in out

    def test_checkout_script_still_runs_the_packaged_command(self):
        """``python scripts/grant_admin.py`` keeps working for anyone following an older guide."""
        result = subprocess.run(
            [sys.executable, "scripts/grant_admin.py", "--help"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True,
        )
        assert "docsgpt grant-admin" in result.stdout
