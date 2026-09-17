"""The ``docsgpt`` command: run the API, the worker and the maintenance scripts,
or run and manage DocsGPT on Docker (``docsgpt up``).

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
    """Create the data home and say where data and the env file come from; the API and the worker must agree."""
    from pathlib import Path

    from docsgpt.core import paths

    home = paths.home_dir()
    home.mkdir(parents=True, exist_ok=True)
    env = paths.env_file()
    print(f"docsgpt: data home {home} (env file {env})", file=sys.stderr)
    # Up to 0.20 an installed package used the working directory as its home.
    chosen = os.environ.get(paths.HOME_ENV) or os.environ.get(paths.ENV_FILE_ENV) or paths.checkout_root()
    stray = Path.cwd() / ".env"
    if not chosen and stray.is_file() and stray.resolve() != env.resolve():
        print(
            f"docsgpt: {stray} is not used; settings come from {env}. "
            f"Move the file there, or set DOCSGPT_HOME={Path.cwd()} to keep using this directory.",
            file=sys.stderr,
        )


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


def _deploy(name: str):
    """A subcommand handler that imports ``docsgpt.deploy.commands`` only when it runs."""

    def handler(args: argparse.Namespace, context=None) -> int:
        from docsgpt.deploy import commands

        return getattr(commands, name)(args, context)

    return handler


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


def _add_deploy_commands(commands) -> None:
    """``docsgpt up`` and the commands that manage the Docker stack it runs."""
    from docsgpt.deploy.stack import EXPOSURES, PROVIDERS

    def stack_command(name: str, handler: str, help_text: str) -> argparse.ArgumentParser:
        parser = commands.add_parser(name, help=help_text)
        parser.add_argument("--dir", help="stack directory (default: DOCSGPT_HOME, else ~/.docsgpt/server)")
        parser.set_defaults(func=_deploy(handler), deploy=True)
        return parser

    up = stack_command("up", "up", "install or update DocsGPT on Docker and start it")
    up.add_argument("--expose", choices=EXPOSURES, help="who can reach it: local (default), network or domain")
    up.add_argument("--domain", help="public domain served over HTTPS by Caddy (implies --expose domain)")
    up.add_argument("--port", type=int, help="host port for the UI and API (default: 7091)")
    up.add_argument("--provider", choices=list(PROVIDERS), help="model provider (default: the DocsGPT public API)")
    up.add_argument("--api-key", help="the provider's API key (or set DOCSGPT_API_KEY)")
    up.add_argument("--model", help="model name (required for openai-compatible)")
    up.add_argument("--base-url", help="base URL of an OpenAI-compatible server")
    docling = up.add_mutually_exclusive_group()
    docling.add_argument("--docling", dest="docling", action="store_const", const=True,
                         help="run the image with the docling parser engine and OCR (several GB larger)")
    docling.add_argument("--no-docling", dest="docling", action="store_const", const=False,
                         help="go back to the default image")
    up.set_defaults(docling=None)
    up.add_argument("--image-tag", help="image tag to run instead of this package's version, e.g. develop")
    up.add_argument("--native", action="store_true",
                    help="run the API and worker as services on this machine instead of on Docker")
    up.add_argument("--postgres-uri", help="native mode: the PostgreSQL DocsGPT should use")
    up.add_argument("--redis-url", help="native mode: the Redis for the queue and the cache (default: localhost:6379)")
    up.add_argument("-y", "--yes", action="store_true", help="ask nothing: use the flags, then the defaults")
    up.add_argument("--reconfigure", action="store_true", help="ask the setup questions again")
    up.add_argument("--adopt", action="store_true", help="take over a DocsGPT stack started from another folder")
    up.add_argument("--no-open", action="store_true", help="do not open the browser after the first install")
    up.add_argument("--timeout", type=int, default=300, help="seconds to wait for the API to answer (default: 300)")

    stack_command("down", "down", "stop the Docker stack (data and settings stay)")
    stack_command("status", "status", "show the stack's version, address, containers and health")

    logs = stack_command("logs", "logs", "show the stack's logs")
    logs.add_argument("-f", "--follow", action="store_true", help="keep printing new lines")
    logs.add_argument("--tail", type=int, help="only the last N lines of each service")
    logs.add_argument("services", nargs="*", help="services to show, e.g. backend worker")

    stack_command("token", "token", "print the access token (installs reachable beyond this computer)")
    stack_command("open", "open_ui", "open DocsGPT in the browser")

    upgrade = stack_command("upgrade", "upgrade", "upgrade the package and restart the stack on the new version")
    upgrade.add_argument("--version", help="version to install (default: the latest release)")

    uninstall = stack_command("uninstall", "uninstall", "remove the Docker stack")
    uninstall.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    uninstall.add_argument("--purge", action="store_true", help="also delete the settings and all data")

    backup = stack_command("backup", "backup", "write a backup of the database and the uploaded data")
    backup.add_argument("--out", help="directory for the archive (default: <stack>/backups)")
    backup.add_argument("--with-settings", action="store_true",
                        help="include .env in the archive; it holds this install's secrets")

    restore = stack_command("restore", "restore", "restore a backup over this install")
    restore.add_argument("archive", help="the .tar.gz written by `docsgpt backup`")
    restore.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    restore.add_argument("--force", action="store_true", help="restore a backup taken with a newer DocsGPT")
    restore.add_argument("--timeout", type=int, default=300,
                         help="seconds to wait for the API afterwards (default: 300)")

    env = stack_command("env", "env", "show, get or set the stack's settings")
    env_actions = env.add_subparsers(dest="env_action", metavar="<action>")
    get = env_actions.add_parser("get", help="print one setting")
    get.add_argument("key")
    set_ = env_actions.add_parser("set", help="set settings (KEY=VALUE ...); run `docsgpt up` to apply")
    set_.add_argument("pairs", nargs="+", metavar="KEY=VALUE")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docsgpt", description="DocsGPT: private AI for agents, assistants and search.")
    parser.add_argument("--version", action="version", version=f"docsgpt {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    _add_deploy_commands(commands)

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
    if not getattr(args, "deploy", False):
        return args.func(args)
    from docsgpt.deploy.docker import DeployError

    try:
        return args.func(args)
    except DeployError as exc:
        print(f"docsgpt: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
