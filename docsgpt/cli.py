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

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7091


def _announce_home() -> None:
    """Say where runtime data and the env file come from; the API and the worker must agree."""
    from docsgpt.core.paths import env_file, home_dir

    print(f"docsgpt: data home {home_dir()} (env file {env_file()})", file=sys.stderr)


def _gunicorn_options(host: str, port: int, workers: int) -> dict:
    """The image's gunicorn flags (docsgpt/Dockerfile CMD), as settings."""
    options = {
        "bind": f"{host}:{port}",
        "workers": workers,
        "worker_class": "docsgpt.gunicorn_worker.BoundedDrainUvicornWorker",
        "timeout": 180,
        "graceful_timeout": 120,
        "keepalive": 5,
        "max_requests": 5000,
        "max_requests_jitter": 500,
    }
    if os.path.isdir("/dev/shm"):
        options["worker_tmp_dir"] = "/dev/shm"
    return options


def _gunicorn_application(options: dict):
    """A gunicorn application configured in code rather than from sys.argv.

    gunicorn records sys.argv at start and re-executes it on SIGUSR2 (the
    zero-downtime upgrade), so sys.argv has to stay the ``docsgpt api ...``
    invocation: the console script is what a re-exec must run again.
    """
    from gunicorn.app.base import Application

    class DocsGPTApplication(Application):
        def init(self, parser, opts, args):
            return None

        def load_config(self):
            self.load_config_from_module_name_or_filename("python:docsgpt.gunicorn_conf")
            for key, value in options.items():
                self.cfg.set(key, value)

        def load(self):
            from docsgpt.asgi import asgi_app

            return asgi_app

    return DocsGPTApplication()


def _api(args: argparse.Namespace) -> int:
    """Serve the ASGI app: gunicorn with the bounded-drain uvicorn worker, or uvicorn when reloading."""
    _announce_home()
    if args.reload or sys.platform == "win32":
        import uvicorn

        uvicorn.run("docsgpt.asgi:asgi_app", host=args.host, port=args.port, reload=args.reload)
        return 0

    _gunicorn_application(_gunicorn_options(args.host, args.port, args.workers)).run()
    return 0


def _celery(argv: list[str]) -> int:
    """Run a celery subcommand on the app and return its exit code (usage errors print usage)."""
    import click

    from docsgpt.app import celery

    try:
        code = celery.start(argv)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    return int(code or 0)


def _worker(args: argparse.Namespace) -> int:
    """Run the Celery worker, with the beat scheduler embedded unless ``--no-beat`` (or on Windows)."""
    _announce_home()
    windows = sys.platform == "win32"
    argv = ["worker", "-l", args.loglevel]
    if args.queues:
        argv += ["-Q", args.queues]
    if args.concurrency:
        argv += ["--concurrency", str(args.concurrency)]
    if args.beat and windows:
        print("docsgpt: the embedded scheduler is not available on Windows; run `docsgpt beat` separately.", file=sys.stderr)
    elif args.beat:
        argv.append("-B")
    pool = args.pool or ("solo" if sys.platform in ("darwin", "win32") else None)
    if pool:
        argv += ["--pool", pool]
    return _celery(argv)


def _beat(args: argparse.Namespace) -> int:
    """Run the beat scheduler on its own (Windows, or a worker started with ``--no-beat``)."""
    _announce_home()
    return _celery(["beat", "-l", args.loglevel])


def _migrate(args: argparse.Namespace) -> int:
    """Create the Postgres database if asked and migrate it to head."""
    from docsgpt.core.settings import settings
    from docsgpt.storage.db.bootstrap import ensure_database_ready

    _announce_home()
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
    api.add_argument("--host", default=DEFAULT_HOST, help="interface to listen on (default: localhost; 0.0.0.0 for all)")
    api.add_argument("--port", type=int, default=DEFAULT_PORT)
    api.add_argument("--workers", type=int, default=1, help="gunicorn worker processes (default: 1)")
    api.add_argument("--reload", action="store_true", help="development mode: uvicorn with auto-reload")
    api.set_defaults(func=_api)

    worker = commands.add_parser("worker", help="run the Celery worker (and the scheduler)")
    worker.add_argument("-Q", "--queues", help="queues to consume (default: every configured queue)")
    worker.add_argument("--concurrency", type=int, help="worker processes (default: one per CPU)")
    worker.add_argument("--pool", help="celery pool (default: prefork; solo on macOS and Windows)")
    worker.add_argument("-l", "--loglevel", default="INFO")
    worker.add_argument("--no-beat", dest="beat", action="store_false", help="do not embed the beat scheduler")
    worker.set_defaults(func=_worker)

    beat = commands.add_parser("beat", help="run the beat scheduler on its own")
    beat.add_argument("-l", "--loglevel", default="INFO")
    beat.set_defaults(func=_beat)

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
