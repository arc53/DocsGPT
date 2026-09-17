"""``docsgpt up`` and the commands that manage the stack it starts."""

from __future__ import annotations

import getpass
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from docsgpt.deploy import backup as backup_format
from docsgpt.deploy import envfile, native, stack
from docsgpt.deploy.docker import DeployError, Docker, lan_ip, wait_healthy

PROJECT = "docsgpt"
DATABASE_VOLUME = f"{PROJECT}_postgres_data"
_MOVING_TAGS = ("latest", "develop")
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Commands that stop or remove services name every profile, so Caddy goes too
# even when COMPOSE_PROFILES no longer enables it.
_EVERY_PROFILE = ("--profile", "https")

EXPOSURE_CHOICES = [
    ("local", "Only this computer"),
    ("network", "Other machines on the network (plain HTTP, access token)"),
    ("domain", "A domain name with HTTPS (Caddy certificate, access token)"),
]


class Prompter:
    """Questions on the terminal. The installer hands its terminal to ``docsgpt up``."""

    def choose(self, question: str, options: list[tuple[str, str]], default: str) -> str:
        keys = [key for key, _ in options]
        print(question)
        for number, (key, label) in enumerate(options, 1):
            print(f"  {number}) {label}{' (default)' if key == default else ''}")
        while True:
            answer = input(f"Choose 1-{len(options)} [{keys.index(default) + 1}]: ").strip()
            if not answer:
                return default
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return keys[int(answer) - 1]
            if answer in keys:
                return answer
            print("Enter one of the numbers above.")

    def text(self, question: str, default: Optional[str] = None, secret: bool = False) -> str:
        ask = getpass.getpass if secret else input
        while True:
            answer = ask(f"{question}{f' [{default}]' if default else ''}: ").strip()
            if answer:
                return answer
            if default:
                return default

    def confirm(self, question: str, default: bool = False) -> bool:
        answer = input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        return default if not answer else answer in ("y", "yes")


def detect_installer() -> str:
    """How this ``docsgpt`` was installed: ``uv`` (uv tool), ``pipx`` or ``pip``."""
    prefix = Path(sys.prefix)
    if (prefix / "uv-receipt.toml").is_file():
        return "uv"
    if "pipx" in prefix.parts:
        return "pipx"
    return "pip"


def _run_command(args: list[str], env: Optional[Mapping[str, str]] = None) -> int:
    """Run ``args``; ``env`` adds to this process's environment rather than replacing it."""
    try:
        return subprocess.call(args, env={**os.environ, **env} if env else None)
    except FileNotFoundError as exc:
        raise DeployError(f"{args[0]} is not on PATH") from exc


def _exec_command(argv: list[str]) -> int:
    """Replace this process with ``argv`` (the upgraded ``docsgpt``); Windows runs it and waits."""
    executable = shutil.which(argv[0]) or argv[0]
    if sys.platform == "win32":
        return subprocess.call([executable, *argv[1:]])
    os.execv(executable, [executable, *argv[1:]])
    return 0  # not reached


@dataclass
class Context:
    """What the commands talk to; tests replace the parts that touch Docker, the terminal or the network."""

    docker: Any
    prompter: Any
    interactive: bool
    version: str
    lan_ip: Callable[[], str] = lan_ip
    wait: Callable[[str, float], bool] = wait_healthy
    open_browser: Callable[[str], Any] = webbrowser.open
    installer: Callable[[], str] = detect_installer
    run: Callable[..., int] = _run_command
    exec_up: Callable[[list[str]], int] = _exec_command
    services: Any = None

    @classmethod
    def default(cls, args) -> "Context":
        from docsgpt.version import __version__

        interactive = sys.stdin.isatty() and not getattr(args, "yes", False)
        return cls(docker=Docker(), prompter=Prompter(), interactive=interactive, version=__version__)

    def service_manager(self):
        """The launchd or systemd wrapper, made on first use so Docker installs never touch it."""
        if self.services is None:
            self.services = native.services_for_platform()
        return self.services


def _record(directory: Path) -> dict:
    """What ``install.json`` says about this install (empty when there is none)."""
    path = directory / stack.RECORD_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _mode(directory: Path) -> str:
    """``native`` or ``docker``, from the install record."""
    return "native" if _record(directory).get("mode") == "native" else "docker"


def _installed(directory: Path) -> Optional[dict[str, str]]:
    """The stack's settings, or None (with a message) when there is no install in ``directory``."""
    installed = (directory / stack.COMPOSE_FILE).is_file() or _mode(directory) == "native"
    if not installed:
        print(f"No DocsGPT install in {directory}. Run `docsgpt up` first, or pass --dir.", file=sys.stderr)
        return None
    return envfile.read(directory / ".env")


def _current_provider(env: Mapping[str, str]) -> str:
    name = env.get("LLM_PROVIDER", "docsgpt")
    if name == "openai" and env.get("OPENAI_BASE_URL"):
        return "openai-compatible"
    return name if name in stack.PROVIDERS else "docsgpt"


def _check_other_stacks(args, context: Context, directory: Path) -> bool:
    """True when containers of the project were started from another folder and ``up`` takes them over."""
    others = {path for path in context.docker.project_dirs(PROJECT) if path.resolve() != directory.resolve()}
    if not others:
        return False
    if args.adopt:
        return True
    where = ", ".join(sorted(str(path) for path in others))
    question = (
        f"Docker already runs a DocsGPT stack started from {where}; it uses the same data volumes. "
        f"Manage it from {directory} instead?"
    )
    if context.interactive and context.prompter.confirm(question, default=False):
        return True
    raise DeployError(
        f"Docker already runs a DocsGPT stack started from {where}. Stop it with `docker compose down` "
        f"in that folder, or run again with --adopt to manage it from {directory}."
    )


def _choose_provider(args, context: Context, existing: Mapping[str, str], ask: bool):
    name = args.provider
    if name is None and ask:
        name = context.prompter.choose("Which model provider?", list(stack.PROVIDERS.items()), _current_provider(existing))
    if name is None:
        return None
    api_key = args.api_key or os.environ.get("DOCSGPT_API_KEY")
    model, base_url = args.model, args.base_url
    if context.interactive:
        if name == "openai-compatible":
            base_url = base_url or context.prompter.text(
                "Server base URL (Ollama on this machine: http://host.docker.internal:11434/v1)"
            )
            model = model or context.prompter.text("Model name")
        elif name != "docsgpt" and not api_key:
            api_key = context.prompter.text(f"{stack.PROVIDERS[name]} API key", secret=True)
    try:
        return stack.provider_settings(name, api_key=api_key, model=model, base_url=base_url)
    except ValueError as exc:
        raise DeployError(str(exc)) from exc


def _redis_urls(base: str) -> dict[str, str]:
    """Celery's broker and result backend, and the cache, on three consecutive databases of one Redis.

    They start at database 0, or at the one the URL names: ``redis://host:6379/5`` puts them on 5, 6
    and 7, which is how one Redis is shared with something that already uses the first databases.
    Everything else in the URL is kept — TLS, credentials, and query parameters such as the
    ``ssl_cert_reqs`` that a rediss:// endpoint usually needs.
    """
    try:
        parts = urlsplit(base)
    except ValueError as exc:
        # urlsplit raises on things like redis://[::1 ; that is a typo, not a crash.
        raise DeployError(f"the Redis URL {base!r} could not be read: {exc}") from exc
    try:
        port = parts.port  # a non-numeric or out-of-range port raises here, not when the URL is split
    except ValueError as exc:
        raise DeployError(
            f"the Redis URL {base!r} has an unusable port: {exc}. Pass a URL like "
            "redis://host:6379 or redis://host:6379/5."
        ) from exc
    if port == 0:
        # urlsplit is happy with it, since 0 is inside the range, but nothing can connect to it.
        raise DeployError(
            f"the Redis URL {base!r} has an unusable port: 0. Pass a URL like "
            "redis://host:6379 or redis://host:6379/5."
        )
    if parts.scheme not in ("redis", "rediss"):
        raise DeployError(
            f"the Redis URL {base!r} should start with redis:// or rediss://, with any options as "
            "query parameters, so the broker, the result backend and the cache can be given a "
            "database each."
        )
    path = parts.path.rstrip("/").lstrip("/")
    if path and not (path.isascii() and path.isdigit()):
        raise DeployError(
            f"the Redis URL {base!r} has {path!r} where a database number would go. Pass a URL like "
            "redis://host:6379 or redis://host:6379/5."
        )
    try:
        first = int(path) if path else 0
    except ValueError as exc:
        # Python refuses to convert a digit string past its conversion limit, and that is a typo
        # rather than a crash.
        raise DeployError(
            f"the Redis URL {base!r} has a database number too long to read. Pass a URL like "
            "redis://host:6379 or redis://host:6379/5."
        ) from exc
    return {
        key: urlunsplit((parts.scheme, parts.netloc, f"/{first + offset}", parts.query, parts.fragment))
        for key, offset in (("CELERY_BROKER_URL", 0), ("CELERY_RESULT_BACKEND", 1), ("CACHE_REDIS_URL", 2))
    }


def _docsgpt_launcher() -> list[str]:
    """How to start DocsGPT from another process: the command on PATH, or this interpreter and the module.

    A unit has to name something that can be executed, and ``sys.argv[0]`` often cannot be: under
    ``python -m docsgpt``, or pytest, it is a module file. Falling back to the running interpreter
    works wherever the package is importable, which it must be to have got here.
    """
    found = shutil.which("docsgpt")
    if found:
        # Absolute: PATH can hold relative entries, and a unit file needs a program it can exec.
        return [str(Path(found).resolve())]
    candidate = Path(sys.argv[0]).resolve()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return [str(candidate)]
    if sys.executable:
        return [sys.executable, "-m", "docsgpt"]
    raise DeployError(
        "could not work out how to start docsgpt for the services. "
        "Install it with `uv tool install docsgpt` (or `pip install docsgpt`) and run this again."
    )


def _refuse_docker_only_options(args) -> None:
    """Options that only mean something to the Docker stack, refused rather than quietly ignored."""
    if getattr(args, "domain", None) or getattr(args, "expose", None) in ("network", "domain"):
        raise DeployError(
            "a native install serves on 127.0.0.1 only, so --domain, --expose network and "
            "--expose domain have nothing to act on here. Put a reverse proxy in front of it, or run "
            "the Docker stack with `docsgpt up --expose ...`, which brings its own Caddy for a domain."
        )
    if getattr(args, "docling", None):
        raise DeployError(
            "--docling selects a Docker image variant, which a native install does not use. Install the "
            'parser engine into this environment instead, with `uv tool install "docsgpt[docling]"` or '
            '`pip install "docsgpt[docling]"`, then run `docsgpt up --native` again.'
        )


def _port_number(value: object, source: str) -> int:
    """A port from the command line or a hand-edited .env, or a DeployError naming where it came from."""
    text = str(value)
    if not (text.isascii() and text.isdigit() and 0 < int(text) < 65536):
        raise DeployError(f"{source} is {value!r}, which is not a port number between 1 and 65535.")
    return int(text)


def _service_names(directory: Path) -> tuple[str, str]:
    """This install's service names; an install elsewhere gets its own, so the two cannot collide."""
    return native.service_names(directory, stack.stack_dir(None))


def _port_is_free(port: int) -> bool:
    """Whether the loopback port can still be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _refuse_busy_port(directory: Path, port: int, services, names: tuple[str, str]) -> None:
    """Whatever holds the port would answer the health check while these services failed to bind.

    The one exception is this install's own API holding the port it is recorded on. Ownership is not
    inferred from the install having some service running: asking for a different port that something
    else holds is how a move to a new port would look, and the API would fail to bind it.
    """
    if _port_is_free(port):
        return
    record = _record(directory)
    api_service = names[0]
    owns_the_port = (
        record.get("mode") == "native"
        and str(record.get("port") or "") == str(port)
        and services.is_running(api_service)
    )
    if owns_the_port:
        return
    raise DeployError(
        f"port {port} is already in use by something other than this install's API. It would fail to "
        f"bind while the health check answered from whatever holds the port, so the install would "
        f"look healthy and be dead. Free the port, stop this install first with `docsgpt down` if it "
        f"is the one holding it on another port, or choose another port with --port."
    )


def _refuse_other_docker_stack(context: Context, directory: Path, port: int) -> None:
    """A Docker stack elsewhere on this port would answer the health check the native API failed."""
    try:
        others = {path for path in context.docker.project_dirs(PROJECT) if path.resolve() != directory.resolve()}
    except DeployError:
        return  # No Docker on this machine to ask, which is a fair reason to run natively.
    for other in sorted(others):
        other_port = envfile.read(other / ".env").get("DOCSGPT_PORT") or str(stack.DEFAULT_PORT)
        if str(other_port) == str(port):
            raise DeployError(
                f"Docker already runs a DocsGPT stack from {other} on port {port}, which a native "
                f"install would try to bind as well: the health check here could answer from that "
                f"stack while these services failed to start. Stop it with `docsgpt down --dir "
                f"{other}`, or give this install another port with --port."
            )


def _native_port(env: Mapping[str, str]) -> str:
    """The port a native install listens on."""
    return str(env.get("DOCSGPT_PORT") or stack.DEFAULT_PORT)


def _native_address(env: Mapping[str, str]) -> str:
    """Where a native install answers: its units bind 127.0.0.1, whatever DOCSGPT_BIND says."""
    return f"http://localhost:{_native_port(env)}"


def _native_up(args, context: Context, directory: Path) -> int:
    """Run the API and the worker as services on this machine, against an existing Postgres and Redis."""
    _refuse_docker_only_options(args)
    services = context.service_manager()
    env_path = directory / ".env"
    existing = envfile.read(env_path)
    record = _record(directory)
    configured = bool(record)

    postgres = args.postgres_uri or existing.get("POSTGRES_URI")
    redis = args.redis_url or ""
    ask = context.interactive and (not configured or args.reconfigure)
    if not postgres and ask:
        postgres = context.prompter.text("PostgreSQL URL (postgresql://user:password@host:5432/docsgpt)")
    if not redis and ask:
        redis = context.prompter.text("Redis URL", default="redis://localhost:6379")
    if not postgres:
        raise DeployError(
            "native mode needs a database: pass --postgres-uri postgresql://user:password@host:5432/docsgpt "
            "(Redis defaults to redis://localhost:6379)."
        )

    # An install keeps the port it was given: a later `up` with no --port must not move it back to the default.
    if args.port:
        port = _port_number(args.port, "--port")
    elif existing.get("DOCSGPT_PORT"):
        port = _port_number(existing["DOCSGPT_PORT"], f"DOCSGPT_PORT in {env_path}")
    else:
        port = stack.DEFAULT_PORT

    names = _service_names(directory)
    _refuse_other_docker_stack(context, directory, port)
    _refuse_busy_port(directory, port, services, names)

    updates: dict[str, Optional[str]] = {
        "POSTGRES_URI": postgres,
        "API_URL": f"http://127.0.0.1:{port}",
        "DOCSGPT_PORT": str(port),
    }
    if redis or "CELERY_BROKER_URL" not in existing:
        updates.update(_redis_urls(redis or "redis://localhost:6379"))
    for key in ("INTERNAL_KEY", "JWT_SECRET_KEY"):
        if not existing.get(key):
            updates[key] = secrets.token_hex(32)
    if "VITE_API_STREAMING" not in existing:
        updates["VITE_API_STREAMING"] = "true"
    provider = _choose_provider(args, context, existing, ask)
    if provider:
        updates.update(provider)
    elif "LLM_PROVIDER" not in existing:
        updates.update(stack.provider_settings("docsgpt"))

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "logs").mkdir(exist_ok=True)
    envfile.update(env_path, updates)

    launcher = _docsgpt_launcher()
    print("Applying database migrations ...")
    # The child reads the stack's settings, not a .env in whatever directory this was run from.
    stack_env = {"DOCSGPT_HOME": str(directory), "DOCSGPT_ENV_FILE": str(env_path)}
    if context.run([*launcher, "migrate"], stack_env) != 0:
        raise DeployError("`docsgpt migrate` failed; check the database URL and that the server is reachable.")

    # The record goes in before the services: if one fails to start, this is still a native install
    # that status, down and uninstall can see and clean up, rather than orphaned units.
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = record or {"installed_at": now}
    record.update(version=context.version, mode="native", port=port, updated_at=now)
    (directory / stack.RECORD_FILE).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    for unit in native.units_for(directory, launcher, port, directory, names):
        services.install(unit)
    for name in names:
        print(f"Starting {name} ...")
        services.start(name)

    health = f"http://127.0.0.1:{port}/api/health"
    print("Waiting for DocsGPT to answer ...")
    if not context.wait(health, args.timeout):
        print(
            f"DocsGPT did not answer at {health} within {args.timeout} seconds. "
            "See what happened with `docsgpt logs`.",
            file=sys.stderr,
        )
        return 1

    print(f"\nDocsGPT is running at http://localhost:{port}")
    print(f"Services: {', '.join(names)} under {services.name}")
    print(f"Settings: {env_path}")
    print("Manage it with: docsgpt status | logs | down | uninstall")
    return 0


def up(args, context: Optional[Context] = None) -> int:
    """Install or update the stack in its directory and start it."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    if getattr(args, "native", False) or _mode(directory) == "native":
        if _mode(directory) != "native" and (directory / stack.COMPOSE_FILE).is_file():
            raise DeployError(
                f"{directory} holds a Docker install. Native services would run beside its containers "
                "on the same port, and down, status and uninstall would stop seeing them. Stop it "
                "first with `docsgpt down` (and `docsgpt uninstall` to remove it), or pass --dir to "
                "put the native install somewhere else."
            )
        return _native_up(args, context, directory)
    env_path = directory / ".env"
    record_path = directory / stack.RECORD_FILE
    existing = envfile.read(env_path)
    configured = record_path.is_file()

    context.docker.preflight(context.interactive)
    # Compose keeps containers whose configuration did not change, and with them the other
    # folder's working-directory label; recreating them all makes the takeover complete.
    recreate = ["--force-recreate"] if _check_other_stacks(args, context, directory) else []

    ask = context.interactive and (not configured or args.reconfigure)
    expose, domain = args.expose, args.domain
    if ask and expose is None and domain is None:
        expose = context.prompter.choose("Who should reach DocsGPT?", EXPOSURE_CHOICES, stack.exposure(existing))
    if expose == "domain" and not domain:
        if not context.interactive:
            raise DeployError("--expose domain needs --domain")
        domain = context.prompter.text("Domain name (its DNS must point at this machine)", existing.get("DOCSGPT_DOMAIN"))
    provider = _choose_provider(args, context, existing, ask)

    image_tag = args.image_tag or context.version
    try:
        updates = stack.plan(
            existing,
            image_tag=image_tag,
            fresh_database=not context.docker.volume_exists(DATABASE_VOLUME),
            expose=expose,
            domain=domain,
            port=args.port,
            provider=provider,
            docling=args.docling,
        )
    except ValueError as exc:
        raise DeployError(str(exc)) from exc

    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(stack.compose_source(), directory / stack.COMPOSE_FILE)
    envfile.update(env_path, updates)
    env = envfile.read(env_path)

    if stack.exposure(existing) == "domain" and stack.exposure(env) != "domain":
        # With the https profile off, `up --remove-orphans` would leave Caddy running on ports 80 and 443.
        context.docker.compose(directory, *_EVERY_PROFILE, "rm", "--stop", "--force", "caddy", check=False)
    if stack.exposure(env) == "network":
        print(
            "DocsGPT will listen on every interface over plain HTTP: its access token travels as "
            "readable text. Use `docsgpt up --domain <name>` for HTTPS outside a trusted network.",
            file=sys.stderr,
        )
    up_args = ["up", "-d", "--remove-orphans", *recreate]
    if image_tag in _MOVING_TAGS:
        up_args += ["--pull", "always"]
    print(f"Starting DocsGPT {image_tag} from {directory} ...")
    context.docker.compose(directory, *up_args)

    health = stack.health_url(env)
    print("Waiting for DocsGPT to answer (the first start also sets up the database) ...")
    if not context.wait(health, args.timeout):
        print(
            f"DocsGPT did not answer at {health} within {args.timeout} seconds. "
            "See what happened with `docsgpt logs backend`.",
            file=sys.stderr,
        )
        return 1

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = json.loads(record_path.read_text(encoding="utf-8")) if configured else {"installed_at": now}
    record.update(version=context.version, image_tag=image_tag, updated_at=now)
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    address = stack.url(env, context.lan_ip())
    mode = stack.exposure(env)
    print(f"\nDocsGPT is running at {address}")
    if env.get("AUTH_TYPE") == "simple_jwt" and env.get("JWT_SECRET_KEY"):
        print("Access token (the page asks for it; `docsgpt token` prints it again):")
        print(f"  {stack.simple_jwt_token(env['JWT_SECRET_KEY'])}")
    if mode == "domain":
        print("Caddy gets the certificate when it starts: DNS must point at this machine and ports 80 and 443 be open.")
    print(f"Settings: {env_path}  (change the model provider or access with `docsgpt up --reconfigure`)")
    print("Manage it with: docsgpt status | logs | upgrade | down | uninstall")
    if context.interactive and not configured and not args.no_open and mode == "local":
        context.open_browser(address)
    return 0


def down(args, context: Optional[Context] = None) -> int:
    """Stop the stack; data and settings stay."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    if _installed(directory) is None:
        return 1
    if _mode(directory) == "native":
        services = context.service_manager()
        # The worker goes first: it talks to the API, not the other way round.
        for name in reversed(_service_names(directory)):
            services.stop(name)
        return 0
    context.docker.compose(directory, *_EVERY_PROFILE, "down")
    return 0


def status(args, context: Optional[Context] = None) -> int:
    """Version, address, containers and whether the API answers (exit 1 when it does not)."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    env = _installed(directory)
    if env is None:
        return 1
    if _mode(directory) == "native":
        services = context.service_manager()
        # Against a LAN bind, stack.url and stack.health_url would advertise and poll an address
        # nothing listens on, and status would call a healthy install dead.
        port = _native_port(env)
        print(f"DocsGPT {_record(directory).get('version', 'unknown')} in {directory} (native, {services.name})")
        print(f"Address: {_native_address(env)}")
        for name in _service_names(directory):
            print(f"  {name}: {'running' if services.is_running(name) else 'stopped'}")
        healthy = context.wait(f"http://127.0.0.1:{port}/api/health", 0)
        print("API: answering" if healthy else "API: not answering (see `docsgpt logs`)")
        return 0 if healthy else 1

    tag = env.get("DOCSGPT_IMAGE_TAG", "unknown") + env.get("DOCSGPT_IMAGE_VARIANT", "")
    print(f"DocsGPT {tag} in {directory}")
    print(f"Address: {stack.url(env, context.lan_ip())} ({stack.exposure(env)})")
    context.docker.compose(directory, "ps", check=False)
    healthy = context.wait(stack.health_url(env), 0)
    print("API: answering" if healthy else "API: not answering (see `docsgpt logs backend`)")
    return 0 if healthy else 1


def logs(args, context: Optional[Context] = None) -> int:
    """``docker compose logs`` for the stack."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    if _installed(directory) is None:
        return 1
    if _mode(directory) == "native":
        logs_dir = directory / "logs"
        wanted = args.services or ["api", "worker"]
        for service in wanted:
            path = logs_dir / f"{service}.log"
            print(f"=== {path}")
            if path.is_file():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                print("\n".join(lines[-args.tail:] if args.tail else lines))
            else:
                print("(nothing logged yet)")
        if args.follow:
            return _follow(logs_dir, wanted)
        return 0
    options = (["--follow"] if args.follow else []) + (["--tail", str(args.tail)] if args.tail else [])
    return context.docker.compose(directory, "logs", *options, *args.services, check=False).returncode


def _follow(logs_dir: Path, services: list) -> int:
    """Print new lines from each service's log until the terminal interrupts, prefixed by service."""
    handles: dict = {}
    try:
        while True:
            for service in services:
                if service not in handles:
                    path = logs_dir / f"{service}.log"
                    if not path.is_file():
                        continue
                    handle = path.open("r", encoding="utf-8", errors="replace")
                    handle.seek(0, os.SEEK_END)
                    handles[service] = handle
                for line in handles[service].readlines():
                    print(f"{service:<6} | {line.rstrip()}")
            sys.stdout.flush()
            time.sleep(0.3)
    except KeyboardInterrupt:
        return 0
    finally:
        for handle in handles.values():
            handle.close()


def token(args, context: Optional[Context] = None) -> int:
    """Print the access token of a ``simple_jwt`` install."""
    directory = stack.stack_dir(args.dir)
    env = _installed(directory)
    if env is None:
        return 1
    if env.get("AUTH_TYPE") != "simple_jwt" or not env.get("JWT_SECRET_KEY"):
        print(f"This install has no access token (AUTH_TYPE={env.get('AUTH_TYPE') or 'none'}).", file=sys.stderr)
        return 1
    print(stack.simple_jwt_token(env["JWT_SECRET_KEY"]))
    return 0


def open_ui(args, context: Optional[Context] = None) -> int:
    """Open DocsGPT in the browser."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    env = _installed(directory)
    if env is None:
        return 1
    # A native install answers on loopback only, so stack.url would hand the browser a LAN address
    # or a domain that nothing behind this command is serving.
    native_install = _mode(directory) == "native"
    address = _native_address(env) if native_install else stack.url(env, context.lan_ip())
    print(address)
    context.open_browser(address)
    return 0


def env(args, context: Optional[Context] = None) -> int:
    """Show where the settings are, or get and set them."""
    env_path = stack.stack_dir(args.dir) / ".env"
    if args.env_action is None:
        print(env_path)
        return 0
    if args.env_action == "get":
        values = envfile.read(env_path)
        if args.key not in values:
            print(f"{args.key} is not set in {env_path}", file=sys.stderr)
            return 1
        print(values[args.key])
        return 0
    updates = {}
    for pair in args.pairs:
        key, separator, value = pair.partition("=")
        if not separator or not _KEY.match(key):
            raise DeployError(f"expected KEY=VALUE, got {pair!r}")
        updates[key] = value
    try:
        envfile.update(env_path, updates)
    except ValueError as exc:
        raise DeployError(str(exc)) from exc
    print(f"Saved to {env_path}.")
    directory = stack.stack_dir(args.dir)
    if _mode(directory) == "native" and getattr(args, "restart", True):
        context = context or Context.default(args)
        services = context.service_manager()
        names = _service_names(directory)
        if any(services.is_running(name) for name in names):
            for name in reversed(names):
                services.stop(name)
            for name in names:
                services.start(name)
            print("Restarted the services, so the change is live.")
            return 0
    print("Run `docsgpt up` to apply.")
    return 0


def dev(args, context: Optional[Context] = None) -> int:
    """Run this checkout's API, worker and UI as children of this terminal."""
    from docsgpt.core import paths
    from docsgpt.deploy import dev as dev_module

    checkout = paths.checkout_root()
    if checkout is None:
        raise DeployError(
            "`docsgpt dev` runs the code in a source checkout, and this is an installed package. "
            "Clone the repository and run it from there, or use `docsgpt up --native` to run this copy."
        )
    if not _port_is_free(args.port):
        raise DeployError(
            f"port {args.port} is already in use, so the API cannot bind it. Stop what is on it "
            f"(a previous `docsgpt dev`, or `docsgpt down` for an install), or pass --port."
        )
    if getattr(args, "mock_llm", False) and not _port_is_free(dev_module.MOCK_LLM_PORT):
        # It starts first and the others are pointed at it, so a busy port here would surface as the
        # API talking to someone else's server, or as a child exiting once everything else is up.
        raise DeployError(
            f"port {dev_module.MOCK_LLM_PORT} is already in use, so the mock LLM cannot bind it. "
            "Stop what is on it, or leave --mock-llm off and point DocsGPT at a real provider."
        )
    children = dev_module.plan(args, checkout)
    print(f"DocsGPT from {checkout}")
    for child in children:
        print(f"  {child.name:<6} {' '.join(child.command)}")
    print(f"\nAPI     http://{args.host}:{args.port}")
    if getattr(args, "ui", False):
        print(f"UI      http://localhost:{dev_module.UI_PORT}")
    print("Ctrl-C stops everything.\n")
    return dev_module.run(children)


@dataclass
class Check:
    """One line of ``docsgpt doctor``: what was looked at and what came back."""

    name: str
    level: str
    detail: str


MARKS = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}


def _migration_head() -> Optional[str]:
    """The newest revision shipped with this package, or None when alembic cannot say."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ImportError:
        return None
    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    if not ini.is_file():
        return None
    config = Config(str(ini))
    config.set_main_option("script_location", str(ini.parent / "alembic"))
    try:
        return ScriptDirectory.from_config(config).get_current_head()
    except Exception:  # noqa: BLE001 - a broken script directory is a doctor finding, not a crash
        return None


def _check_postgres(uri: Optional[str]) -> Check:
    """Connect, and say whether the schema is the one this version expects."""
    if not uri:
        return Check("postgres", "fail", "POSTGRES_URI is not set")
    try:
        import psycopg
    except ImportError:
        return Check("postgres", "fail", "the psycopg driver is not installed")
    try:
        with psycopg.connect(uri, connect_timeout=5) as connection, connection.cursor() as cursor:
            cursor.execute("select current_setting('server_version')")
            version = cursor.fetchone()[0]
            cursor.execute("select to_regclass('public.alembic_version')")
            applied = cursor.fetchone()[0] is not None
            current = None
            if applied:
                # public, like the to_regclass check above: search_path could resolve another one.
                cursor.execute("select version_num from public.alembic_version")
                row = cursor.fetchone()
                current = row[0] if row else None
    except (psycopg.Error, OSError, ValueError) as exc:
        return Check("postgres", "fail", f"cannot connect to {_endpoint(uri)}: {_scrub(str(exc).strip(), uri)}")
    head = _migration_head()
    if not current:
        return Check("postgres", "fail", f"PostgreSQL {version}, no schema yet; run `docsgpt migrate`")
    if head and current != head:
        return Check("postgres", "fail", f"PostgreSQL {version} at {current}, this version wants {head}; "
                                         "run `docsgpt migrate`")
    return Check("postgres", "ok", f"PostgreSQL {version}, schema at {current}")


def _endpoint(url: str) -> str:
    """A URL without its credentials: this ends up on a terminal, in CI logs and in issues."""
    try:
        parts = urlsplit(url)
        # .port is a property that parses on access, so it raises separately from the split itself.
        host, port, scheme, path = parts.hostname or "", parts.port, parts.scheme, parts.path
    except ValueError:
        return "the configured URL"
    if port:
        host = f"{host}:{port}"
    return f"{scheme}://{host}{path}" if host else "the configured URL"


def _scrub(text: str, url: Optional[str]) -> str:
    """Client errors quote the URL they were handed, credentials and all, so take them back out."""
    if not url:
        return text
    text = text.replace(url, _endpoint(url))
    try:
        parts = urlsplit(url)
    except ValueError:
        return text
    for secret in (parts.password, parts.username):
        if secret:
            text = text.replace(secret, "...")
    return text


def _check_redis(urls: Mapping[str, str]) -> Check:
    """Ping every Redis the settings name; they are usually one server, three databases."""
    if not urls:
        return Check("redis", "fail", "no Redis is configured (CELERY_BROKER_URL)")
    try:
        import redis
    except ImportError:
        return Check("redis", "fail", "the redis client is not installed")
    for label, url in sorted(urls.items()):
        try:
            redis.Redis.from_url(url, socket_connect_timeout=3).ping()
        except Exception as exc:  # noqa: BLE001 - every client error here is the same finding
            return Check(
                "redis", "fail", f"{label} ({_endpoint(url)}) does not answer: {_scrub(str(exc).strip(), url)}"
            )
    return Check("redis", "ok", f"answering on {len(urls)} database(s)")


def _check_provider(env: Mapping[str, str]) -> Check:
    """Whether a model provider is set up well enough to answer a question."""
    provider = env.get("LLM_PROVIDER") or "docsgpt"
    if provider == "docsgpt":
        return Check("provider", "ok", "the DocsGPT public API (no key needed)")
    if not (env.get("API_KEY") or env.get("OPENAI_API_KEY")):
        return Check("provider", "fail", f"{provider} is configured but no API_KEY is set")
    return Check("provider", "ok", f"{provider}{' at ' + env['OPENAI_BASE_URL'] if env.get('OPENAI_BASE_URL') else ''}")


def doctor(args, context: Optional[Context] = None) -> int:
    """Check what DocsGPT needs on this machine, and say what is missing."""
    from docsgpt.core import paths

    if args.dir:
        env_path = stack.stack_dir(args.dir) / ".env"
    else:
        try:
            env_path = paths.env_file()
        except FileNotFoundError as exc:
            raise DeployError(str(exc)) from exc
    env = envfile.read(env_path)
    checks = [
        Check("settings", "ok" if env_path.is_file() else "warn",
              f"{env_path}" if env_path.is_file() else f"{env_path} does not exist yet; defaults are in use"),
        _check_postgres(args.postgres_uri or env.get("POSTGRES_URI")),
        _check_redis({
            key: value for key, value in (
                ("broker", args.redis_url or env.get("CELERY_BROKER_URL")),
                ("results", env.get("CELERY_RESULT_BACKEND")),
                ("cache", env.get("CACHE_REDIS_URL")),
            ) if value
        }),
        _check_provider(env),
    ]

    # The one command that exists to explain a broken setup must not fall over on one.
    port = _port_number(env["DOCSGPT_PORT"], f"DOCSGPT_PORT in {env_path}") if env.get("DOCSGPT_PORT") \
        else stack.DEFAULT_PORT
    if _port_is_free(port):
        checks.append(Check("port", "ok", f"{port} is free"))
    else:
        checks.append(Check("port", "warn", f"{port} is in use, which is expected if DocsGPT is running"))

    directory = stack.stack_dir(args.dir)
    if _mode(directory) == "native":
        services = context.service_manager() if context else native.services_for_platform()
        names = _service_names(directory)
        running = [name for name in names if services.is_running(name)]
        level = "ok" if len(running) == len(names) else "warn"
        checks.append(Check("services", level, f"{len(running)} of {len(names)} running ({', '.join(names)})"))

    for check in checks:
        print(f"[{MARKS[check.level]}] {check.name:<9} {check.detail}")
    failed = [check for check in checks if check.level == "fail"]
    if failed:
        print(f"\n{len(failed)} problem(s) to fix before DocsGPT will work.", file=sys.stderr)
    return 1 if failed else 0


def _chosen_services(names: tuple[str, str], wanted: list) -> list:
    """The services the user asked for, given either short names (api) or full ones."""
    if not wanted:
        return list(names)
    chosen = []
    for ask in wanted:
        match = [name for name in names if name == ask or name.removeprefix("docsgpt-").startswith(ask)]
        if not match:
            raise DeployError(f"{ask!r} is not a service of this install; it has {', '.join(names)}.")
        chosen.extend(match)
    return chosen


def restart(args, context: Optional[Context] = None) -> int:
    """Restart the services, changing nothing else."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    if _installed(directory) is None:
        return 1
    if _mode(directory) == "native":
        services = context.service_manager()
        chosen = _chosen_services(_service_names(directory), list(args.services))
        for name in reversed(chosen):
            services.stop(name)
        for name in chosen:
            services.start(name)
        print(f"Restarted {', '.join(chosen)}.")
        return 0
    return context.docker.compose(directory, "restart", *args.services, check=False).returncode


def _stack_image(env: Mapping[str, str]) -> str:
    """The image this install runs; the volume tars go through it, so nothing extra is pulled."""
    tag = env.get("DOCSGPT_IMAGE_TAG") or "latest"
    return f"arc53/docsgpt:{tag}{env.get('DOCSGPT_IMAGE_VARIANT', '')}"


def backup(args, context: Optional[Context] = None) -> int:
    """Write a dump of the database and a tar of each data volume into one archive."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    env = _installed(directory)
    if env is None:
        return 1
    if _mode(directory) == "native":
        raise DeployError(
            f"{directory} is a native install: its database and its files are not in Docker volumes, so there is nothing here to archive. Back up the PostgreSQL that POSTGRES_URI points at with pg_dump, and copy the indexes, inputs and vectors folders from the data home."
        )

    out_dir = Path(args.out).expanduser() if args.out else directory / "backups"
    taken_at = datetime.now(timezone.utc)
    target = out_dir / backup_format.archive_name(taken_at)
    image = _stack_image(env)

    try:
        print("Pausing the backend and the worker so the database and the files match ...")
        context.docker.compose(directory, "stop", "backend", "worker")
        _write_backup(args, context, directory, env, target, image, taken_at)
    finally:
        print("Starting the backend and the worker again ...")
        context.docker.compose(directory, "up", "-d", "backend", "worker")

    size = target.stat().st_size / 1_000_000
    print(f"\nBackup written to {target} ({size:.1f} MB)")
    if args.with_settings:
        print("It contains .env, so it holds this install's secrets: keep it somewhere private.")
    else:
        print("Settings are not in it; `docsgpt backup --with-settings` includes .env, secrets and all.")
    print(f"Restore it with: docsgpt restore {target}")
    return 0


def _write_backup(args, context: Context, directory: Path, env, target: Path, image: str, taken_at) -> None:
    """Dump the database and the data volumes into ``target``, with the writers stopped."""
    with tempfile.TemporaryDirectory() as workspace:
        work = Path(workspace)
        dump = work / backup_format.DUMP
        print("Dumping the database ...")
        with dump.open("w", encoding="utf-8") as handle:
            context.docker.compose(
                directory, "exec", "-T", "postgres",
                "pg_dump", "--clean", "--if-exists", "-U", "docsgpt", "-d", "docsgpt",
                stdout=handle,
            )
        volume_tars = {}
        for name in backup_format.DATA_VOLUMES:
            print(f"Archiving the {name} volume ...")
            tar_path = work / f"{name}.tar"
            context.docker.export_volume(f"{PROJECT}_{name}", tar_path, image)
            volume_tars[name] = tar_path
        manifest = {
            "format": backup_format.FORMAT,
            "created_at": taken_at.isoformat(timespec="seconds"),
            "version": context.version,
            "image_tag": env.get("DOCSGPT_IMAGE_TAG", ""),
            "volumes": list(backup_format.DATA_VOLUMES),
            "settings_included": bool(args.with_settings),
        }
        settings = directory / ".env" if args.with_settings else None
        backup_format.write_archive(target, dump=dump, volume_tars=volume_tars, manifest=manifest, settings=settings)


def _restore_data(context: Context, directory: Path, archive: Path, volumes: list, image: str) -> None:
    """Put the archive's volumes and database back, with the stack stopped."""
    with tempfile.TemporaryDirectory() as workspace:
        work = Path(workspace)
        backup_format.extract(archive, work)
        # Read every volume tar through before replacing any of them: a damaged third tar must not
        # be discovered with the first two already swapped in.
        tars = {}
        for name in volumes:
            tar_path = work / backup_format.volume_member(name)
            if not tar_path.is_file():
                raise DeployError(f"{archive} is missing the {name} volume it says it contains")
            backup_format.check_volume_tar(name, tar_path)
            tars[name] = tar_path
        for name, tar_path in tars.items():
            print(f"Restoring the {name} volume ...")
            context.docker.import_volume(f"{PROJECT}_{name}", tar_path, image)

        dump = work / backup_format.DUMP
        if not dump.is_file():
            raise DeployError(f"{archive} is missing its database dump")
        print("Starting the database ...")
        context.docker.compose(directory, "up", "-d", "--wait", "postgres")
        print("Restoring the database ...")
        with dump.open("r", encoding="utf-8") as handle:
            context.docker.compose(
                directory, "exec", "-T", "postgres",
                "psql", "--quiet", "--set", "ON_ERROR_STOP=on", "-U", "docsgpt", "-d", "docsgpt",
                stdin=handle,
            )


def restore(args, context: Optional[Context] = None) -> int:
    """Put a backup's database and data volumes back over this install."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    if _mode(directory) == "native":
        raise DeployError(
            f"{directory} is a native install: its database and its files are not in Docker volumes, so there is nothing here to archive. Back up the PostgreSQL that POSTGRES_URI points at with pg_dump, and copy the indexes, inputs and vectors folders from the data home. `docsgpt restore` puts back what `docsgpt backup` wrote for a Docker install."
        )
    archive = Path(args.archive).expanduser()
    manifest = backup_format.read_manifest(archive)
    backup_format.check_version(manifest, context.version, args.force)
    # Everything the archive declares is checked here, while DocsGPT is still up.
    volumes = backup_format.validate(archive, manifest)

    env = _installed(directory)
    if env is None:
        return 1

    taken_at = manifest.get("created_at", "an unknown time")
    if not args.yes:
        if not context.interactive:
            raise DeployError("restore needs --yes when there is no terminal to confirm on")
        question = f"Replace the data in {directory} with the backup from {taken_at}? This cannot be undone."
        if not context.prompter.confirm(question, default=False):
            print("Nothing restored.")
            return 1

    image = _stack_image(env)
    try:
        print("Stopping the stack ...")
        context.docker.compose(directory, *_EVERY_PROFILE, "down")
        _restore_data(context, directory, archive, volumes, image)
    except BaseException:
        # The stack is down by now. A corrupt payload inside an otherwise well-formed archive, or a
        # statement psql refuses, must not leave DocsGPT stopped: start it again, then report.
        print("The restore failed. Starting DocsGPT again ...", file=sys.stderr)
        context.docker.compose(directory, "up", "-d", "--remove-orphans", check=False)
        raise

    print("Starting DocsGPT ...")
    context.docker.compose(directory, "up", "-d", "--remove-orphans")
    if not context.wait(stack.health_url(env), args.timeout):
        print("DocsGPT did not answer after the restore. See `docsgpt logs backend`.", file=sys.stderr)
        return 1
    print(f"\nRestored the backup from {taken_at}. DocsGPT is running at {stack.url(env, context.lan_ip())}")
    return 0


def _uninstall_hint(installer: str) -> str:
    return {"uv": "uv tool uninstall docsgpt", "pipx": "pipx uninstall docsgpt"}.get(installer, "pip uninstall docsgpt")


def upgrade(args, context: Optional[Context] = None) -> int:
    """Upgrade the package, then run the new version's ``docsgpt up``."""
    context = context or Context.default(args)
    spec = f"docsgpt=={args.version}" if args.version else "docsgpt"
    installer = context.installer()
    if installer == "uv":
        if context.run(["uv", "tool", "install", "--force", spec]) != 0:
            raise DeployError(f"uv could not install {spec}")
        # The same launcher the service units get: a bare name is not always on PATH to exec.
        return context.exec_up([*_docsgpt_launcher(), "up", "--dir", str(stack.stack_dir(args.dir))])
    command = f"pipx install --force {spec}" if installer == "pipx" else f"pip install -U {spec}"
    print(f"Upgrade the package with `{command}`, then run `docsgpt up` to move the stack to it.", file=sys.stderr)
    return 1


def uninstall(args, context: Optional[Context] = None) -> int:
    """Remove the containers and the stack files; ``--purge`` also deletes settings and data."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    if _installed(directory) is None:
        return 1
    if args.purge:
        what = "containers, settings and data (documents, conversations, the database)"
    else:
        what = "containers (the settings in .env and the data volumes are kept)"
    if not args.yes:
        if not context.interactive:
            raise DeployError("uninstall needs --yes when there is no terminal to confirm on")
        if not context.prompter.confirm(f"Remove the DocsGPT {what} in {directory}?", default=False):
            print("Nothing removed.")
            return 1
    if _mode(directory) == "native":
        services = context.service_manager()
        for name in reversed(_service_names(directory)):
            services.remove(name)
        print(f"Removed the {', '.join(_service_names(directory))} services.")
        if args.purge:
            shutil.rmtree(directory)
            print(f"Removed {directory}. The database and Redis it used are untouched.")
        else:
            (directory / stack.RECORD_FILE).unlink(missing_ok=True)
            print(f"Settings stay in {directory / '.env'}; the database and Redis are untouched.")
        print(f"To remove the docsgpt command too: {_uninstall_hint(context.installer())}")
        return 0

    context.docker.compose(directory, *_EVERY_PROFILE, "down", "--remove-orphans", *(["-v"] if args.purge else []))
    if args.purge:
        shutil.rmtree(directory)
        print(f"Removed DocsGPT and its data from {directory}.")
    else:
        for name in (stack.COMPOSE_FILE, stack.RECORD_FILE):
            (directory / name).unlink(missing_ok=True)
        print(f"Removed the containers. Settings stay in {directory / '.env'} and data in the Docker volumes.")
    print(f"To remove the docsgpt command too: {_uninstall_hint(context.installer())}")
    return 0
