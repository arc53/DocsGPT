"""Gunicorn config — keeps uvicorn's access log in NCSA format."""

from __future__ import annotations

import logging

# NCSA common log format:
#   %(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"
# Uvicorn's access formatter exposes a ``client_addr``/``request_line``/
# ``status_code`` trio but not the full NCSA field set, so we re-derive
# what we can.
_NCSA_FMT = (
    '%(client_addr)s - - [%(asctime)s] "%(request_line)s" %(status_code)s'
)

logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "ncsa_access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": _NCSA_FMT,
            "datefmt": "%d/%b/%Y:%H:%M:%S %z",
            "use_colors": False,
        },
        "default": {
            "format": "[%(asctime)s] [%(process)d] [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "access": {
            "class": "logging.StreamHandler",
            "formatter": "ncsa_access",
            "stream": "ext://sys.stdout",
        },
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {
            "handlers": ["default"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["access"],
            "level": "INFO",
            "propagate": False,
        },
        "gunicorn.error": {
            "handlers": ["default"],
            "level": "INFO",
            "propagate": False,
        },
        "gunicorn.access": {
            "handlers": ["access"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {"handlers": ["default"], "level": "INFO"},
}


def on_starting(server):  # pragma: no cover — gunicorn hook
    """Ensure gunicorn's own loggers use the configured handlers."""
    logging.config.dictConfig(logconfig_dict)
