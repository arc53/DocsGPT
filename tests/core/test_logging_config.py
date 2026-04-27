"""Tests for setup_logging — in particular the OTEL log-handler hand-off.

`opentelemetry-instrument` attaches an OTEL `LoggingHandler` to the root
logger before our module-level `setup_logging()` runs in `application/app.py`.
The default `dictConfig` call replaces `root.handlers`, which would silently
drop the OTEL handler. setup_logging snapshots and re-attaches OTEL handlers
when OTLP log export is enabled.
"""

from __future__ import annotations

import logging
import sys
import types

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
