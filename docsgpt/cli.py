"""The ``docsgpt`` command: run the API, the worker and the maintenance scripts,
or run and manage DocsGPT on Docker (``docsgpt up``).

Every subcommand imports what it needs when it runs, so ``docsgpt --help``
stays instant and does not touch the database.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from typing import Optional, Sequence

from docsgpt.version import __version__

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7091

# How often ``docsgpt analytics backfill`` retries while a scheduled sweep holds the lock; tests replace _sleep.
BACKFILL_POLL_SECONDS = 10
_sleep = time.sleep

# Where ``docsgpt worker`` defaults to Celery's solo pool: one task at a time, in the worker process itself.
SOLO_POOL_PLATFORMS = ("darwin", "win32")


def default_pool(platform: Optional[str] = None) -> Optional[str]:
    """The pool ``docsgpt worker`` picks when ``--pool`` is not given: solo on macOS and Windows, else Celery's.

    Args:
        platform: A ``sys.platform`` value; this machine's when omitted.

    Returns:
        ``"solo"``, or ``None`` for Celery's default (prefork).
    """
    return "solo" if (platform or sys.platform) in SOLO_POOL_PLATFORMS else None


def needs_analytics_worker(platform: Optional[str] = None) -> bool:
    """Whether a default ``docsgpt worker`` here leaves the analytics queue to ``docsgpt worker --analytics``.

    A solo pool runs one task at a time, and an analytics sweep holds it for minutes, so the query embeddings
    behind it would time out. ``docsgpt up --native`` installs the analytics worker where this holds, and
    ``docsgpt dev`` starts it there while ``DECISION_ANALYTICS_ENABLED`` is on.

    Args:
        platform: A ``sys.platform`` value; this machine's when omitted.

    Returns:
        True where the default pool is solo.
    """
    return default_pool(platform) == "solo"


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

        from docsgpt.core.paths import package_dir

        # Watch the package, not the working directory: a checkout also holds .venv, node_modules
        # and the data the app writes (indexes/, inputs/), which restarts the server mid-ingest.
        uvicorn.run(
            "docsgpt.asgi:asgi_app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            reload_dirs=[str(package_dir())] if args.reload else None,
        )
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
    """Run the Celery worker, with the beat scheduler embedded unless ``--no-beat`` (or on Windows).

    A solo-pool worker with no ``-Q`` consumes every queue but ``ANALYTICS_QUEUE``: a sweep would hold its one
    slot for minutes. ``--analytics`` runs the worker that takes that queue instead, without the scheduler.

    Args:
        args: The parsed ``docsgpt worker`` options.

    Returns:
        Celery's exit code.
    """
    from docsgpt.core.settings import settings

    _announce_home()
    windows = sys.platform == "win32"
    pool = args.pool or default_pool()
    argv = ["worker", "-l", args.loglevel]
    if args.analytics:
        # Its own node name: next to the main worker on one host, a second celery@host clashes.
        argv += ["-Q", settings.ANALYTICS_QUEUE, "-n", "analytics@%h"]
    elif args.queues:
        argv += ["-Q", args.queues]
    elif pool == "solo" and settings.ANALYTICS_QUEUE not in _shared_queues(settings):
        argv += ["-X", settings.ANALYTICS_QUEUE]
        if settings.DECISION_ANALYTICS_ENABLED:
            print(
                "docsgpt: the solo pool leaves conversation analytics to `docsgpt worker --analytics`; run it "
                "next to this one (docsgpt dev and docsgpt up --native do).",
                file=sys.stderr,
            )
    concurrency = args.concurrency or (1 if args.analytics and pool != "solo" else None)
    if concurrency:
        argv += ["--concurrency", str(concurrency)]
    beat = args.beat and not args.analytics  # One scheduler is enough; the main worker embeds it.
    if beat and windows:
        print("docsgpt: the embedded scheduler is not available on Windows; run `docsgpt beat` separately.", file=sys.stderr)
    elif beat:
        argv.append("-B")
    if pool:
        argv += ["--pool", pool]
    return _celery(argv)


def _shared_queues(settings) -> set[str]:
    """The queues other than analytics a worker consumes; excluding analytics must not drop one of them."""
    return {"docsgpt", settings.DOCUMENT_PARSE_QUEUE, settings.EMBEDDINGS_QUEUE}


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
    "grant-admin": ("grant_admin", "grant, revoke or list the admin role (AUTH_TYPE=oidc)"),
    "ocr-check": ("ocr_check", "send one page to the configured OCR engine and report what came back"),
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
    decider = up.add_mutually_exclusive_group()
    decider.add_argument("--decider", dest="decider", action="store_const", const=True,
                         help="serve the decision model from a container of its own instead of the API process")
    decider.add_argument("--no-decider", dest="decider", action="store_const", const=False,
                         help="remove that container; the API process holds the model again")
    up.set_defaults(docling=None, decider=None)
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

    doctor = stack_command("doctor", "doctor", "check what this machine needs to run DocsGPT")
    doctor.add_argument("--postgres-uri", help="check this database instead of the one in .env")
    doctor.add_argument("--redis-url", help="check this Redis instead of the one in .env")

    restart = stack_command("restart", "restart", "restart the services, changing nothing else")
    restart.add_argument("services", nargs="*", help="services to restart, e.g. api worker")

    env = stack_command("env", "env", "show, get or set the stack's settings")
    env_actions = env.add_subparsers(dest="env_action", metavar="<action>")
    get = env_actions.add_parser("get", help="print one setting")
    get.add_argument("key")
    set_ = env_actions.add_parser("set", help="set settings (KEY=VALUE ...)")
    set_.add_argument("pairs", nargs="+", metavar="KEY=VALUE")
    set_.add_argument("--no-restart", dest="restart", action="store_false",
                      help="do not restart a running native install afterwards")

    dev = commands.add_parser("dev", help="run this checkout's API, worker and UI with reload")
    dev.add_argument("--host", default=DEFAULT_HOST, help="interface for the API (default: localhost)")
    dev.add_argument("--port", type=int, default=DEFAULT_PORT, help="port for the API (default: 7091)")
    dev.add_argument("--ui", action="store_true", help="also run the frontend dev server")
    dev.add_argument("--mock-llm", action="store_true",
                     help="run the mock LLM and point DocsGPT at it, so no API key is needed")
    dev.add_argument("--no-worker", dest="worker", action="store_false", help="do not run the Celery worker")
    dev.add_argument("--no-reload", dest="reload", action="store_false",
                     help="do not restart the API and worker when a file changes")
    dev.add_argument("-l", "--loglevel", default="INFO", help="worker log level (default: INFO)")
    dev.set_defaults(func=_deploy("dev"), deploy=True)


def _connectors(args: argparse.Namespace) -> int:
    """``docsgpt connectors reencrypt``: move every stored credential onto the current key.

    Rewrites connections, then the secrets saved on tools and custom models.
    Anything neither ENCRYPTION_SECRET_KEY nor ENCRYPTION_SECRET_KEY_PREVIOUS
    opens is left as it is and counted.
    """
    if getattr(args, "connectors_action", None) != "reencrypt":
        print("usage: docsgpt connectors reencrypt", file=sys.stderr)
        return 2
    from docsgpt.connectors.service import reencrypt_all, reencrypt_saved_secrets

    counts = reencrypt_all()
    print(
        f"docsgpt: re-encrypted {counts['rewritten']} connection(s), "
        f"{counts['current']} already current, {counts['failed']} unreadable",
        file=sys.stderr,
    )
    if counts["failed"]:
        print(
            "docsgpt: unreadable connections were marked 'Reconnect needed'; "
            "their owners must reconnect them.",
            file=sys.stderr,
        )
    saved = reencrypt_saved_secrets()
    print(
        f"docsgpt: re-encrypted {saved['rewritten']} tool and custom-model secret(s), "
        f"{saved['current']} already current, {saved['failed']} unreadable",
        file=sys.stderr,
    )
    if saved["failed"]:
        print(
            "docsgpt: unreadable tool and custom-model secrets were left unchanged; set the key they were "
            "saved with as ENCRYPTION_SECRET_KEY_PREVIOUS and run this again, or have their owners enter them again.",
            file=sys.stderr,
        )
    if counts["failed"] or saved["failed"]:
        return 1
    print("docsgpt: everything is on the current key; ENCRYPTION_SECRET_KEY_PREVIOUS can be removed.", file=sys.stderr)
    return 0


def _decisions_status() -> int:
    """This machine's decision-model settings and files, without loading the model.

    A running server's load state, speed and feature verdicts are in its
    /api/admin/decisions; this command reports what that server would use.
    In API mode it asks the decision server once, so the model, status and
    speed are the server's.
    """
    from docsgpt import decisions
    from docsgpt.decisions import files
    from docsgpt.decisions.client import runtime
    from docsgpt.decisions.models import lookup, select

    answered = decisions.get_decider().probe()
    report = decisions.status()
    if answered is None:
        for key in ("status", "reason", "speed"):  # this process never loads the model: they say nothing here
            report.pop(key, None)
    else:
        report["server"] = "answered" if answered else "no answer"
    spec = ((report.get("model") and lookup(report["model"])) or select(runtime())) if report["mode"] != "none" else None
    if spec is not None:
        # in API mode this process only needs the tokenizer; the server holds the model
        folder = files.local_onnx_dir(spec) if report["mode"] == "local" else files.local_tokenizer(spec)
        report["revision"] = files.revision(spec)
        report["files"] = str(folder) if folder else None
    print(json.dumps(report, indent=2))
    return 0


def _decisions(args: argparse.Namespace) -> int:
    """``docsgpt decisions prefetch``: download the decision model's pinned files into DECISION_CACHE_DIR.

    For offline and air-gapped installs, and to avoid the download the first
    decision feature turned on would otherwise start. ``docsgpt decisions
    status`` reports the settings and whether the files are here.
    """
    action = getattr(args, "decisions_action", None)
    if action == "status":
        return _decisions_status()
    if action != "prefetch":
        print("usage: docsgpt decisions prefetch|status", file=sys.stderr)
        return 2
    from docsgpt.decisions import files
    from docsgpt.decisions.models import select

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    runtime = getattr(args, "runtime", "onnx")
    spec = select(runtime)
    if spec is None:
        print("docsgpt: DECISION_MODEL names a model this version does not know", file=sys.stderr)
        return 2
    try:
        folder = files.ensure_torch(spec) if runtime == "torch" else files.ensure_onnx(spec)
    except files.FilesUnavailable as exc:
        print(f"docsgpt: {exc}", file=sys.stderr)
        return 1
    print(f"docsgpt: decision model {spec.id} ({runtime}) at {files.revision(spec)} is in {folder}", file=sys.stderr)
    return 0


def _analytics(args: argparse.Namespace) -> int:
    """``docsgpt analytics backfill``: label the last N days of conversations now, in the foreground.

    The same sweep the worker runs every ANALYTICS_SWEEP_SECONDS, without its
    time budget. Like a worker it calls the model where it runs (the decider,
    the API process or the remote endpoint) at background priority and never
    loads it here; it does nothing while DECISION_ANALYTICS_ENABLED is off.
    ``--dry-run`` prints the unlabelled messages and a time estimate instead.
    """
    if getattr(args, "analytics_action", None) != "backfill":
        print("usage: docsgpt analytics backfill --days N [--agent ID] [--dry-run] [--no-wait]", file=sys.stderr)
        return 2
    if args.agent:
        try:
            uuid.UUID(args.agent)
        except ValueError:
            print("docsgpt: --agent must be an agent id", file=sys.stderr)
            return 2
    from docsgpt.core.settings import settings

    days = args.days if args.days is not None else settings.ANALYTICS_BACKFILL_DAYS
    if not 1 <= days <= settings.ANALYTICS_RETENTION_DAYS:
        # Older labels are purged by retention, so they would be labelled again and again.
        print(f"docsgpt: --days must be 1 to ANALYTICS_RETENTION_DAYS ({settings.ANALYTICS_RETENTION_DAYS})",
              file=sys.stderr)
        return 2
    import docsgpt.celery_init as celery_init
    from docsgpt.analytics import tasks

    # Calls go where a worker's go: in local mode, to the API process's model.
    celery_init._mark_worker_process()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.dry_run:
        print(json.dumps(tasks.backfill_estimate(days, args.agent), indent=2))
        return 0
    if not tasks.enabled():
        print("docsgpt: DECISION_ANALYTICS_ENABLED is off (or DECISION_MODE=none); nothing to label", file=sys.stderr)
        return 1
    report = _sweep_when_free(tasks, days, args.agent, wait=not args.no_wait)
    print(json.dumps(report, indent=2))
    return 0 if report.get("stopped") in (None, "budget") and "skipped" not in report else 1


def _sweep_when_free(tasks, days: int, agent_id: Optional[str], wait: bool) -> dict:
    """Run the backfill sweep, waiting while a scheduled sweep holds the lock.

    The wait is bounded by one scheduled sweep's lease (its budget, one model call, and a minute), after which
    a lock still held is reported rather than waited on.

    Args:
        tasks: ``docsgpt.analytics.tasks``.
        days: Days back to label.
        agent_id: Only this agent's conversations, or every agent's.
        wait: Retry while the lock is held; ``False`` returns the first ``{"skipped": "locked"}``.

    Returns:
        The sweep's report.
    """
    from docsgpt.core.settings import settings

    bound = settings.ANALYTICS_SWEEP_BUDGET_SECONDS + settings.DECISION_BACKGROUND_TIMEOUT + 60
    waited = 0
    while True:
        report = tasks.sweep(budget_seconds=None, days=days, agent_id=agent_id)
        if report.get("skipped") != "locked" or not wait:
            return report
        if waited >= bound:
            print(f"docsgpt: a sweep is still running after {waited} s; try again later", file=sys.stderr)
            return report
        if not waited:
            print("docsgpt: a scheduled sweep is running; waiting for it to finish", file=sys.stderr)
        _sleep(BACKFILL_POLL_SECONDS)
        waited += BACKFILL_POLL_SECONDS


def _decide_server(args: argparse.Namespace) -> int:
    """Serve the decision model over ``/v1/decide`` in this process; see ``docsgpt.decisions.server``."""
    from docsgpt.decisions import server

    _announce_home()
    return server.serve(args.host, args.port, args.device)


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
    queues = worker.add_mutually_exclusive_group()
    queues.add_argument(
        "-Q", "--queues",
        help="queues to consume (default: every configured queue; on the solo pool, all but ANALYTICS_QUEUE)",
    )
    queues.add_argument(
        "--analytics", action="store_true",
        help="consume only ANALYTICS_QUEUE, without the scheduler: the worker that runs next to a solo-pool one",
    )
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

    connectors = commands.add_parser(
        "connectors", help="manage stored credentials (connections, tool and custom-model secrets)"
    )
    connector_actions = connectors.add_subparsers(dest="connectors_action", metavar="<action>")
    connector_actions.add_parser(
        "reencrypt",
        help=(
            "rewrite connections, tool and custom-model secrets with ENCRYPTION_SECRET_KEY "
            "(after a key rotation; then ENCRYPTION_SECRET_KEY_PREVIOUS can go)"
        ),
    )
    connectors.set_defaults(func=_connectors)

    decisions = commands.add_parser("decisions", help="manage the decision model's files")
    decision_actions = decisions.add_subparsers(dest="decisions_action", metavar="<action>")
    prefetch = decision_actions.add_parser(
        "prefetch", help="download the pinned decision model into DECISION_CACHE_DIR (for offline installs)"
    )
    prefetch.add_argument(
        "--runtime", choices=("onnx", "torch"), default="onnx",
        help="onnx (default: the API and the decider on CPU) or torch (decide-server --device mps|cuda)",
    )
    decision_actions.add_parser(
        "status", help="show the decision model settings, feature modes and whether its files are downloaded"
    )
    decisions.set_defaults(func=_decisions)

    analytics = commands.add_parser("analytics", help="conversation analytics: label past conversations now")
    analytics_actions = analytics.add_subparsers(dest="analytics_action", metavar="<action>")
    backfill = analytics_actions.add_parser(
        "backfill", help="label the last N days of conversations in the foreground (the sweep without its budget)"
    )
    backfill.add_argument("--days", type=int, help="days back to label (default: ANALYTICS_BACKFILL_DAYS)")
    backfill.add_argument("--agent", help="only this agent's conversations (its id)")
    backfill.add_argument(
        "--dry-run", action="store_true", help="print the unlabelled messages and a time estimate; label nothing"
    )
    backfill.add_argument(
        "--no-wait", action="store_true", help="exit at once if a scheduled sweep is running, instead of waiting"
    )
    analytics.set_defaults(func=_analytics)

    decide_server = commands.add_parser(
        "decide-server", help="serve the decision model over HTTP (/v1/decide) for the API and the worker"
    )
    decide_server.add_argument(
        "--host", default=DEFAULT_HOST, help="interface to listen on (default: localhost; others need DECISION_KEY)"
    )
    decide_server.add_argument("--port", type=int, default=7095)
    decide_server.add_argument(
        "--device", choices=("cpu", "mps", "cuda"),
        help="cpu (ONNX), or mps / cuda with the decisions-torch extra (default: DECISION_DEVICE, else cpu)",
    )
    decide_server.set_defaults(func=_decide_server)

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
