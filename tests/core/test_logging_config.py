"""Tests for setup_logging — in particular the OTEL log-handler hand-off.

`opentelemetry-instrument` attaches an OTEL `LoggingHandler` to the root
logger before our module-level `setup_logging()` runs in `application/app.py`.
The default `dictConfig` call replaces `root.handlers`, which would silently
drop the OTEL handler. setup_logging snapshots and re-attaches OTEL handlers
when OTLP log export is enabled.
"""

from __future__ import annotations

import logging
import pathlib
import sys
import types
from unittest.mock import Mock

import pytest

from application.core.logging_config import setup_logging


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Snapshot/restore the root logger so tests don't leak handlers."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def _make_fake_otel_handler() -> logging.Handler:
    """Build a Handler whose class lives in a module starting with 'opentelemetry'.

    Mirrors how the real `opentelemetry.sdk._logs.LoggingHandler` would be
    detected without needing the OTEL SDK installed in the test env.
    """
    fake_module = types.ModuleType("opentelemetry.fake_sdk._logs")
    sys.modules.setdefault(fake_module.__name__, fake_module)

    class FakeOtelHandler(logging.Handler):
        pass

    FakeOtelHandler.__module__ = fake_module.__name__
    return FakeOtelHandler()


@pytest.mark.unit
class TestSetupLogging:

    def test_default_keeps_only_console_handler(self, monkeypatch):
        monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        logging.getLogger().handlers = []

        setup_logging()

        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        assert isinstance(handlers[0], logging.StreamHandler)

    def test_preserves_otel_handler_when_otlp_logs_enabled(self, monkeypatch):
        monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp")
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)

        otel_handler = _make_fake_otel_handler()
        logging.getLogger().handlers = [otel_handler]

        setup_logging()

        handlers = logging.getLogger().handlers
        assert otel_handler in handlers, (
            "OTEL handler must survive setup_logging when OTLP log export is on"
        )
        assert any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, type(otel_handler))
            for h in handlers
        ), "console handler should still be installed alongside the OTEL handler"

    def test_does_not_preserve_when_sdk_disabled(self, monkeypatch):
        monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp")
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

        otel_handler = _make_fake_otel_handler()
        logging.getLogger().handlers = [otel_handler]

        setup_logging()

        handlers = logging.getLogger().handlers
        assert otel_handler not in handlers, (
            "When OTEL_SDK_DISABLED=true the handler should not be preserved"
        )

    def test_does_not_preserve_when_logs_exporter_unset(self, monkeypatch):
        monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)

        otel_handler = _make_fake_otel_handler()
        logging.getLogger().handlers = [otel_handler]

        setup_logging()

        handlers = logging.getLogger().handlers
        assert otel_handler not in handlers


class TestAlembicDoesNotSilenceApplicationLoggers:
    """A boot that applies a migration must not switch off app logging.

    ``alembic/env.py`` calls ``logging.config.fileConfig``, whose
    ``disable_existing_loggers`` defaults to True and whose ini names only
    ``root``/``sqlalchemy``/``alembic`` — so every ``application.*`` logger
    imported before it is disabled. ``app.py`` calls ``setup_logging()`` at
    line 16 but ``ensure_database_ready()`` at line 58, so the web tier never
    re-enables them: on the one boot where a schema upgrade happened, it
    logs nothing for the rest of the process's life. k8s sets
    ``AUTO_MIGRATE=false``, but every docker-compose variant leaves it on.
    """

    @pytest.mark.unit
    def test_env_py_opts_out_of_disable_existing_loggers(self):
        """AST, not a grep: the kwarg has to be on the real call."""
        import ast
        import pathlib

        source = pathlib.Path("application/alembic/env.py").read_text()
        calls = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "fileConfig"
        ]
        assert calls, "env.py no longer calls fileConfig"
        for call in calls:
            kwargs = {kw.arg: kw.value for kw in call.keywords}
            assert "disable_existing_loggers" in kwargs
            assert kwargs["disable_existing_loggers"].value is False

    @pytest.mark.unit
    def test_the_flag_is_what_keeps_application_loggers_alive(self, tmp_path):
        """Pins the mechanism, in a subprocess so pytest's own logging survives.

        ``fileConfig`` mutates global logging state, so this cannot run
        in-process without wrecking every later test's log capture.
        """
        import subprocess
        import sys

        probe = tmp_path / "probe.py"
        probe.write_text(
            "import logging\n"
            "from logging.config import fileConfig\n"
            "log = logging.getLogger('application.api.answer.routes.stream')\n"
            "fileConfig('application/alembic.ini', disable_existing_loggers=True)\n"
            "kept = logging.getLogger('application.api.answer.routes.stream')\n"
            "print('default_disables', kept.disabled)\n"
            "kept.disabled = False\n"
            "fileConfig('application/alembic.ini', disable_existing_loggers=False)\n"
            "print('flag_preserves', not kept.disabled)\n"
        )
        out = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "default_disables True" in out
        assert "flag_preserves True" in out


@pytest.mark.unit
class TestMigrationsDoNotClobberAppLogging:
    """An in-process ``alembic upgrade`` must not take application logging down.

    ``app.py`` calls ``setup_logging()`` before ``ensure_database_ready()``, so
    ``env.py``'s ``fileConfig`` runs against an already-configured root logger.
    ``fileConfig`` rebuilds root from ``[logger_root]`` (level WARNING, a stderr
    handler), which drops every ``application.*`` INFO record and detaches the
    OTEL handler and context filter for the life of the process —
    ``disable_existing_loggers=False`` does not prevent it, since that flag only
    governs whether existing loggers are switched off.
    """

    def test_bootstrap_tells_env_py_to_leave_logging_alone(self, monkeypatch):
        from logging.config import fileConfig

        from application.storage.db import bootstrap

        # Skip the best-effort revision precheck; it needs a live DB. It is
        # wrapped in try/except, so raising here lands on the "upgrade anyway"
        # path we actually want to exercise.
        monkeypatch.setattr(
            "alembic.script.ScriptDirectory.from_config",
            Mock(side_effect=RuntimeError("no db")),
        )

        root = logging.getLogger()
        root.handlers = []
        setup_logging()
        marker = logging.NullHandler()
        root.addHandler(marker)
        before_level = root.level

        seen = {}

        def fake_upgrade(cfg, revision):
            # Stand in for env.py, which guards its fileConfig on this key.
            seen["configure_logger"] = cfg.attributes.get("configure_logger", True)
            if seen["configure_logger"]:
                fileConfig(cfg.config_file_name, disable_existing_loggers=False)

        monkeypatch.setattr(
            "alembic.command.upgrade", fake_upgrade, raising=False
        )
        bootstrap._run_migrations(logging.getLogger("test"))

        assert seen["configure_logger"] is False
        assert root.level == before_level
        assert marker in root.handlers
        assert logging.getLogger("application.probe").isEnabledFor(logging.INFO)

    def test_env_py_honours_the_opt_out(self):
        """The other half of the contract lives in env.py's module-level guard."""
        env_py = (
            pathlib.Path(__file__).resolve().parents[2]
            / "application"
            / "alembic"
            / "env.py"
        )
        source = env_py.read_text()
        assert 'config.attributes.get("configure_logger", True)' in source
