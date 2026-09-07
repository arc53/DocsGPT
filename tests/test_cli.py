"""The ``docsgpt`` command dispatches to the API server, the worker and the scripts."""

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from docsgpt import cli
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


class TestApi:
    def test_gunicorn_argv(self, monkeypatch):
        run = MagicMock()
        monkeypatch.setitem(sys.modules, "gunicorn.app.wsgiapp", types.SimpleNamespace(run=run))
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(sys, "argv", ["docsgpt"])
        assert cli.main(["api", "--port", "8000", "--workers", "2"]) == 0
        run.assert_called_once_with()
        argv = sys.argv
        assert argv[0] == "gunicorn" and argv[-1] == "docsgpt.asgi:asgi_app"
        assert argv[argv.index("--bind") + 1] == "127.0.0.1:8000"
        assert argv[argv.index("-w") + 1] == "2"
        assert argv[argv.index("-k") + 1] == "docsgpt.gunicorn_worker.BoundedDrainUvicornWorker"
        assert argv[argv.index("--config") + 1] == "python:docsgpt.gunicorn_conf"

    def test_reload_uses_uvicorn(self, monkeypatch):
        uvicorn = types.SimpleNamespace(run=MagicMock())
        monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
        assert cli.main(["api", "--reload", "--host", "127.0.0.1"]) == 0
        uvicorn.run.assert_called_once_with("docsgpt.asgi:asgi_app", host="127.0.0.1", port=7091, reload=True)


class TestWorker:
    @staticmethod
    def _celery(monkeypatch):
        celery = MagicMock()
        monkeypatch.setitem(sys.modules, "docsgpt.app", types.SimpleNamespace(celery=celery))
        return celery

    def test_defaults(self, monkeypatch):
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "linux")
        assert cli.main(["worker"]) == 0
        argv = celery.worker_main.call_args.args[0]
        assert argv[:3] == ["worker", "-l", "INFO"]
        assert argv[argv.index("-Q") + 1] == cli.DEFAULT_QUEUES
        assert "-B" in argv
        assert "--pool" not in argv

    def test_options_and_the_macos_solo_pool(self, monkeypatch):
        celery = self._celery(monkeypatch)
        monkeypatch.setattr(sys, "platform", "darwin")
        assert cli.main(["worker", "--no-beat", "-Q", "embeddings", "--concurrency", "2"]) == 0
        argv = celery.worker_main.call_args.args[0]
        assert argv[argv.index("--pool") + 1] == "solo"
        assert "-B" not in argv
        assert argv[argv.index("-Q") + 1] == "embeddings"
        assert argv[argv.index("--concurrency") + 1] == "2"


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


class TestScripts:
    def test_arguments_pass_through_untouched(self, monkeypatch):
        main = MagicMock(return_value=0)
        monkeypatch.setattr("docsgpt.scripts.prefetch_models.main", main)
        assert cli.main(["prefetch-models", "--embeddings", "x", "--help"]) == 0
        main.assert_called_once_with(["--embeddings", "x", "--help"])

    def test_the_script_exit_code_is_returned(self, monkeypatch):
        monkeypatch.setattr("docsgpt.scripts.verify_offline.main", MagicMock(return_value=3))
        assert cli.main(["verify-offline"]) == 3
