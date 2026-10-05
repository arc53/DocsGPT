"""Running DocsGPT without Docker, supervised by the system's own service manager.

The API and the worker each become one service: a launchd agent on macOS, a
systemd user unit on Linux. Both run the ``docsgpt`` command of this
installation with the stack directory as their data home, so a native install
keeps its settings in the same ``.env`` a Docker install would.

Postgres and Redis are not started here; a native install points at ones that
already run (``--postgres-uri``, ``--redis-url``).
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from docsgpt.deploy.docker import DeployError

API_SERVICE = "docsgpt-api"
WORKER_SERVICE = "docsgpt-worker"
LABEL_PREFIX = "cloud.docsgpt"


@dataclass
class Unit:
    """One supervised process, in the terms every service manager needs."""

    name: str
    arguments: list[str]
    environment: dict[str, str]
    working_directory: str
    log_file: str


def service_names(stack_directory: Path, default_directory: Path) -> tuple[str, str]:
    """This install's two service names: the plain pair for the default install, suffixed for others.

    Service managers keep one namespace for the whole user, so two installs in different directories
    would write over each other's units. These names show up in launchctl and systemctl output, so
    the usual install keeps the readable ones and only a second install carries a digest.
    """
    resolved = stack_directory.expanduser().resolve()
    if resolved == default_directory.expanduser().resolve():
        return (API_SERVICE, WORKER_SERVICE)
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:8]
    return (f"{API_SERVICE}-{digest}", f"{WORKER_SERVICE}-{digest}")


def label_for(name: str) -> str:
    """The launchd label for a service name (``docsgpt-api`` -> ``cloud.docsgpt.api``)."""
    return f"{LABEL_PREFIX}.{name.removeprefix('docsgpt-')}"


def launchd_plist(unit: Unit, label: Optional[str] = None) -> str:
    """The launchd agent for ``unit``: kept alive, with its output in the stack's log file."""
    _check_unit_values(unit)
    body = {
        "Label": label or label_for(unit.name),
        "ProgramArguments": list(unit.arguments),
        "EnvironmentVariables": dict(unit.environment),
        "WorkingDirectory": unit.working_directory,
        "StandardOutPath": unit.log_file,
        "StandardErrorPath": unit.log_file,
        "KeepAlive": True,
        "RunAtLoad": True,
        "ProcessType": "Background",
    }
    return plistlib.dumps(body).decode("utf-8")


_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def _reject_control_characters(what: str, value: str) -> None:
    """Service files are line-based, so a newline in a value adds a directive instead of text."""
    if _CONTROL_CHARACTERS.search(value):
        raise DeployError(f"{what} contains a control character, which a service file cannot carry: {value!r}")


def _check_unit_values(unit: Unit) -> None:
    """Everything bound for a service file, checked before any of it is rendered."""
    _reject_control_characters("the working directory", unit.working_directory)
    _reject_control_characters("the log file path", unit.log_file)
    for key, value in unit.environment.items():
        _reject_control_characters("an environment name", key)
        _reject_control_characters(f"the environment value for {key}", value)
    for argument in unit.arguments:
        _reject_control_characters("a command argument", argument)


def _systemd_quote(value: str) -> str:
    """A unit-file value: quoted, with backslashes, quotes and percent signs escaped for systemd."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def systemd_unit(unit: Unit) -> str:
    """The systemd user unit for ``unit``; values are quoted, so a path with spaces survives."""
    _check_unit_values(unit)
    environment = "\n".join(
        f"Environment={_systemd_quote(f'{key}={value}')}" for key, value in sorted(unit.environment.items())
    )
    # systemd expands % specifiers such as %h, so a literal percent has to be doubled everywhere.
    command = " ".join(shlex.quote(argument).replace("%", "%%") for argument in unit.arguments)
    log_file = unit.log_file.replace("%", "%%")
    return f"""[Unit]
Description=DocsGPT ({unit.name})
After=network-online.target

[Service]
Type=simple
ExecStart={command}
WorkingDirectory={_systemd_quote(unit.working_directory)}
{environment}
Restart=always
RestartSec=5
StandardOutput=append:{log_file}
StandardError=append:{log_file}

[Install]
WantedBy=default.target
"""


class LaunchdServices:
    """launchd user agents in ~/Library/LaunchAgents (macOS)."""

    name = "launchd"
    poll_interval = 0.2
    unload_timeout = 15.0

    def __init__(self, runner=subprocess.run, home: Optional[Path] = None) -> None:
        self._run = runner
        self.directory = (home or Path.home()) / "Library" / "LaunchAgents"

    def _plist(self, name: str) -> Path:
        return self.directory / f"{label_for(name)}.plist"

    def _target(self, name: str) -> str:
        return f"gui/{os.getuid()}/{label_for(name)}"

    def _print(self, name: str):
        return self._run(["launchctl", "print", self._target(name)], capture_output=True, text=True, check=False)

    def _bootout(self, name: str) -> None:
        """Unload the job and wait for it to go.

        ``bootout`` returns before launchd has finished unloading, and bootstrapping a label that is
        still on its way out fails with "Bootstrap failed: 5: Input/output error" — which is what a
        restart used to hit. Waiting for the label to stop resolving makes stop and start ordered.
        """
        self._run(["launchctl", "bootout", self._target(name)], capture_output=True, text=True, check=False)
        deadline = time.monotonic() + self.unload_timeout
        while self._print(name).returncode == 0:
            if time.monotonic() >= deadline:
                raise DeployError(f"{label_for(name)} is still loaded after {self.unload_timeout:.0f}s")
            time.sleep(self.poll_interval)

    def install(self, unit: Unit) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._plist(unit.name).write_text(launchd_plist(unit), encoding="utf-8")

    def start(self, name: str) -> None:
        # bootout first: a reinstall must pick up the new plist rather than the loaded one.
        self._bootout(name)
        result = self._run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self._plist(name))],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise DeployError(f"launchctl could not start {name}: {(result.stderr or '').strip()}")

    def stop(self, name: str) -> None:
        self._bootout(name)

    def remove(self, name: str) -> None:
        self.stop(name)
        self._plist(name).unlink(missing_ok=True)

    def is_running(self, name: str) -> bool:
        """A loaded job is not a running one: a crashed service still answers ``launchctl print``."""
        result = self._print(name)
        return result.returncode == 0 and "state = running" in (result.stdout or "")


class SystemdServices:
    """systemd user units in ~/.config/systemd/user (Linux)."""

    name = "systemd"

    def __init__(self, runner=subprocess.run, home: Optional[Path] = None) -> None:
        self._run = runner
        # An explicit home wins: it is what a caller passes to redirect the unit directory.
        if home is not None:
            root = home / ".config"
        else:
            base = os.environ.get("XDG_CONFIG_HOME")
            root = Path(base) if base else Path.home() / ".config"
        self.directory = root / "systemd" / "user"

    def _unit_file(self, name: str) -> Path:
        return self.directory / f"{name}.service"

    def _systemctl(self, *args: str, check: bool = False):
        result = self._run(["systemctl", "--user", *args], capture_output=True, text=True, check=False)
        if check and result.returncode != 0:
            raise DeployError(f"systemctl --user {' '.join(args)} failed: {(result.stderr or '').strip()}")
        return result

    def install(self, unit: Unit) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._unit_file(unit.name).write_text(systemd_unit(unit), encoding="utf-8")
        self._systemctl("daemon-reload")

    def start(self, name: str) -> None:
        # restart, not `enable --now`: --now starts nothing when the unit is already active, so a
        # reinstalled unit would keep running with the ExecStart and environment it started with.
        self._systemctl("enable", f"{name}.service", check=True)
        self._systemctl("restart", f"{name}.service", check=True)

    def stop(self, name: str) -> None:
        self._systemctl("stop", f"{name}.service", check=True)

    def remove(self, name: str) -> None:
        # Only disable a unit systemd still knows about, so removing twice stays harmless; a real
        # failure has to surface before the unit file and the install record are thrown away.
        if self._unit_file(name).is_file():
            self._systemctl("disable", "--now", f"{name}.service", check=True)
        self._unit_file(name).unlink(missing_ok=True)
        self._systemctl("daemon-reload", check=True)

    def is_running(self, name: str) -> bool:
        return self._systemctl("is-active", "--quiet", f"{name}.service").returncode == 0


def services_for_platform(platform: str = sys.platform):
    """The service manager for this machine, or a DeployError saying what to do instead."""
    if platform == "darwin":
        return LaunchdServices()
    if platform.startswith("linux"):
        return SystemdServices()
    raise DeployError(
        "native mode supervises services with launchd or systemd, which Windows does not have. "
        "Run DocsGPT on Docker with `docsgpt up`, or start `docsgpt api` and `docsgpt worker` yourself."
    )


def units_for(stack_directory: Path, launcher: list[str], port: int, home: Path,
              names: tuple[str, str]) -> list[Unit]:
    """The API and worker services for a native install in ``stack_directory``.

    ``launcher`` is how DocsGPT is started: the ``docsgpt`` command, or an interpreter and ``-m``.
    """
    environment = {"DOCSGPT_HOME": str(home)}
    api_name, worker_name = names
    return [
        Unit(
            name=api_name,
            arguments=[*launcher, "api", "--host", "127.0.0.1", "--port", str(port)],
            environment=dict(environment),
            working_directory=str(stack_directory),
            log_file=str(stack_directory / "logs" / "api.log"),
        ),
        Unit(
            name=worker_name,
            arguments=[*launcher, "worker"],
            environment=dict(environment),
            working_directory=str(stack_directory),
            log_file=str(stack_directory / "logs" / "worker.log"),
        ),
    ]
