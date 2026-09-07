"""The ``docsgpt`` command: run the API, the worker and the maintenance scripts.

Every subcommand imports what it needs when it runs, so ``docsgpt --help``
stays instant and does not touch the database.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional, Sequence

from docsgpt.version import __version__

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7091
DEFAULT_QUEUES = "docsgpt,parsing,embeddings"


def _api(args: argparse.Namespace) -> int:
    """Serve the ASGI app: gunicorn with the bounded-drain uvicorn worker, or uvicorn when reloading."""
    if args.reload or sys.platform == "win32":
        import uvicorn

        uvicorn.run("docsgpt.asgi:asgi_app", host=args.host, port=args.port, reload=args.reload)
        return 0

    from gunicorn.app.wsgiapp import run as gunicorn_run

    argv = [
        "gunicorn",
        "-w", str(args.workers),
        "-k", "docsgpt.gunicorn_worker.BoundedDrainUvicornWorker",
        "--bind", f"{args.host}:{args.port}",
        "--timeout", "180",
        "--graceful-timeout", "120",
        "--keep-alive", "5",
        "--max-requests", "5000",
        "--max-requests-jitter", "500",
        "--config", "python:docsgpt.gunicorn_conf",
    ]
    if os.path.isdir("/dev/shm"):
        argv += ["--worker-tmp-dir", "/dev/shm"]
    argv.append("docsgpt.asgi:asgi_app")
    sys.argv = argv
    gunicorn_run()
    return 0


def _worker(args: argparse.Namespace) -> int:
    """Run the Celery worker (with the beat scheduler unless ``--no-beat``)."""
    from docsgpt.app import celery

    argv = ["worker", "-l", args.loglevel, "-Q", args.queues]
    if args.concurrency:
        argv += ["--concurrency", str(args.concurrency)]
    if args.beat:
        argv.append("-B")
    pool = args.pool or ("solo" if sys.platform == "darwin" else None)
    if pool:
        argv += ["--pool", pool]
    celery.worker_main(argv)
    return 0


def _migrate(args: argparse.Namespace) -> int:
    """Create the Postgres database if asked and migrate it to head."""
    from docsgpt.core.settings import settings
    from docsgpt.storage.db.bootstrap import ensure_database_ready

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not settings.POSTGRES_URI:
        print("POSTGRES_URI is not set; nothing to migrate.", file=sys.stderr)
        return 2
    ensure_database_ready(
        settings.POSTGRES_URI,
        create_db=args.create_db,
        migrate=True,
        logger=logging.getLogger("docsgpt.migrate"),
    )
    return 0


# Maintenance scripts keep their own argument parsers; the command hands
# everything after the script name to them untouched (argparse would try to
# interpret the options itself).
SCRIPTS = {
    "prefetch-models": ("prefetch_models", "download the embedding, tokenizer and parser models"),
    "verify-offline": ("verify_offline", "check that the install runs with networking off"),
    "reembed": ("reembed", "re-embed every index with the configured embedding model"),
}


def _run_script(module: str, argv: list[str]) -> int:
    import importlib

    return int(importlib.import_module(f"docsgpt.scripts.{module}").main(argv) or 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docsgpt", description="DocsGPT: private AI for agents, assistants and search.")
    parser.add_argument("--version", action="version", version=f"docsgpt {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    api = commands.add_parser("api", help="serve the HTTP API")
    api.add_argument("--host", default=DEFAULT_HOST)
    api.add_argument("--port", type=int, default=DEFAULT_PORT)
    api.add_argument("--workers", type=int, default=1, help="gunicorn worker processes (default: 1)")
    api.add_argument("--reload", action="store_true", help="development mode: uvicorn with auto-reload")
    api.set_defaults(func=_api)

    worker = commands.add_parser("worker", help="run the Celery worker (and the scheduler)")
    worker.add_argument("-Q", "--queues", default=DEFAULT_QUEUES, help=f"queues to consume (default: {DEFAULT_QUEUES})")
    worker.add_argument("--concurrency", type=int, help="worker processes (default: one per CPU)")
    worker.add_argument("--pool", help="celery pool (default: prefork; solo on macOS)")
    worker.add_argument("-l", "--loglevel", default="INFO")
    worker.add_argument("--no-beat", dest="beat", action="store_false", help="do not embed the beat scheduler")
    worker.set_defaults(func=_worker)

    migrate = commands.add_parser("migrate", help="create the database if needed and run the migrations")
    migrate.add_argument("--no-create", dest="create_db", action="store_false", help="fail instead of creating a missing database")
    migrate.set_defaults(func=_migrate)

    for name, (module, help_text) in SCRIPTS.items():
        commands.add_parser(name, help=f"{help_text} (docsgpt.scripts.{module})", add_help=False)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in SCRIPTS:
        return _run_script(SCRIPTS[argv[0]][0], argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
