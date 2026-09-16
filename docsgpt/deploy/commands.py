"""``docsgpt up`` and the commands that manage the stack it starts."""

from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from docsgpt.deploy import backup as backup_format
from docsgpt.deploy import envfile, stack
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


def _run_command(args: list[str]) -> int:
    try:
        return subprocess.call(args)
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
    run: Callable[[list[str]], int] = _run_command
    exec_up: Callable[[list[str]], int] = _exec_command

    @classmethod
    def default(cls, args) -> "Context":
        from docsgpt.version import __version__

        interactive = sys.stdin.isatty() and not getattr(args, "yes", False)
        return cls(docker=Docker(), prompter=Prompter(), interactive=interactive, version=__version__)


def _installed(directory: Path) -> Optional[dict[str, str]]:
    """The stack's settings, or None (with a message) when there is no install in ``directory``."""
    if not (directory / stack.COMPOSE_FILE).is_file():
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


def up(args, context: Optional[Context] = None) -> int:
    """Install or update the stack in its directory and start it."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
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
    context.docker.compose(directory, *_EVERY_PROFILE, "down")
    return 0


def status(args, context: Optional[Context] = None) -> int:
    """Version, address, containers and whether the API answers (exit 1 when it does not)."""
    context = context or Context.default(args)
    directory = stack.stack_dir(args.dir)
    env = _installed(directory)
    if env is None:
        return 1
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
    options = (["--follow"] if args.follow else []) + (["--tail", str(args.tail)] if args.tail else [])
    return context.docker.compose(directory, "logs", *options, *args.services, check=False).returncode


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
    address = stack.url(env, context.lan_ip())
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
    print(f"Saved to {env_path}. Run `docsgpt up` to apply.")
    return 0


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

    out_dir = Path(args.out).expanduser() if args.out else directory / "backups"
    taken_at = datetime.now(timezone.utc)
    target = out_dir / backup_format.archive_name(taken_at)
    image = _stack_image(env)

    print("Pausing the backend and the worker so the database and the files match ...")
    context.docker.compose(directory, "stop", "backend", "worker")
    try:
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


def restore(args, context: Optional[Context] = None) -> int:
    """Put a backup's database and data volumes back over this install."""
    context = context or Context.default(args)
    archive = Path(args.archive).expanduser()
    manifest = backup_format.read_manifest(archive)
    backup_format.check_version(manifest, context.version, args.force)
    # Everything the archive declares is checked here, while DocsGPT is still up.
    volumes = backup_format.validate(archive, manifest)

    directory = stack.stack_dir(args.dir)
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
    print("Stopping the stack ...")
    context.docker.compose(directory, *_EVERY_PROFILE, "down")

    with tempfile.TemporaryDirectory() as workspace:
        work = Path(workspace)
        backup_format.extract(archive, work)
        for name in volumes:
            tar_path = work / backup_format.volume_member(name)
            if not tar_path.is_file():
                raise DeployError(f"{archive} is missing the {name} volume it says it contains")
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
        return context.exec_up(["docsgpt", "up", "--dir", str(stack.stack_dir(args.dir))])
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
