import logging
import os
from logging.config import dictConfig


def _otlp_logs_enabled() -> bool:
    """Return True when the user has opted in to OTLP log export.

    Gated by the standard OTEL env vars so no project-specific knob is needed:
    set ``OTEL_LOGS_EXPORTER=otlp`` (and leave ``OTEL_SDK_DISABLED`` unset or
    false) to flip it on. When false, ``setup_logging`` keeps its original
    console-only behavior.
    """
    exporter = os.getenv("OTEL_LOGS_EXPORTER", "").strip().lower()
    disabled = os.getenv("OTEL_SDK_DISABLED", "false").strip().lower() == "true"
    return exporter == "otlp" and not disabled


def setup_logging() -> None:
    """Configure the root logger with a stdout console handler.

    When OTLP log export is enabled, ``opentelemetry-instrument`` attaches a
    ``LoggingHandler`` to the root logger before this function runs. The
    ``dictConfig`` call below replaces ``root.handlers`` with the console
    handler, which would silently drop the OTEL handler. To make OTLP log
    export work without forcing every contributor to opt in, snapshot the
    OTEL handlers up front and re-attach them after ``dictConfig``.
    """
    preserved_handlers: list[logging.Handler] = []
    if _otlp_logs_enabled():
        preserved_handlers = [
            h
            for h in logging.getLogger().handlers
            if h.__class__.__module__.startswith("opentelemetry")
        ]

    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
            }
        },
        "root": {
            "level": "INFO",
            "handlers": ["console"],
        },
    })

    if preserved_handlers:
        root = logging.getLogger()
        for handler in preserved_handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
