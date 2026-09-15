"""The docker CLI calls behind ``docsgpt up``."""

from __future__ import annotations

import http.client
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Optional

MIN_COMPOSE = (2, 24, 0)
DAEMON_START_SECONDS = 120


class DeployError(Exception):
    """A problem the user can act on; the command prints it without a traceback."""


def run(args: Sequence[str], *, cwd: Optional[Path] = None, capture: bool = False, check: bool = True):
    """Run a command, streaming its output unless ``capture``; with ``check`` a failure raises DeployError."""
    try:
        result = subprocess.run(list(args), cwd=cwd, text=True, capture_output=capture, check=False)
    except FileNotFoundError as exc:
        raise DeployError(f"{args[0]} is not installed or not on PATH") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip() if capture else ""
        message = f"`{' '.join(args)}` failed with exit code {result.returncode}"
        raise DeployError(f"{message}: {detail}" if detail else message)
    return result


def _parse_version(text: str) -> Optional[tuple[int, ...]]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(part) for part in match.groups()) if match else None


class Docker:
    """Docker and Docker Compose, through their command-line tools."""

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess] = run,
        which: Callable[[str], Optional[str]] = shutil.which,
        sleep: Callable[[float], None] = time.sleep,
        platform: str = sys.platform,
    ) -> None:
        self._run = runner
        self._which = which
        self._sleep = sleep
        self._platform = platform

    def preflight(self, interactive: bool = False) -> None:
        """Make sure Docker is installed and running and Compose is new enough, starting Docker Desktop on macOS."""
        if not self._which("docker"):
            raise DeployError("Docker is not installed. Get it from https://docs.docker.com/get-docker/ and run this again.")
        if not self.daemon_running():
            self._start_daemon()
        result = self._run(["docker", "compose", "version", "--short"], capture=True, check=False)
        version = _parse_version(result.stdout) if result.returncode == 0 else None
        if version is None:
            raise DeployError(
                "Docker Compose v2 is not available (`docker compose version` failed). "
                "Install the Compose plugin: https://docs.docker.com/compose/install/"
            )
        if version < MIN_COMPOSE:
            found = ".".join(str(part) for part in version)
            raise DeployError(f"Docker Compose {found} is too old; DocsGPT needs 2.24 or newer.")

    def daemon_running(self) -> bool:
        return self._run(["docker", "info"], capture=True, check=False).returncode == 0

    def _start_daemon(self) -> None:
        if self._platform == "darwin":
            print("Docker is not running; starting Docker Desktop ...", file=sys.stderr)
            self._run(["open", "-a", "Docker"], check=False)
            for _ in range(DAEMON_START_SECONDS // 2):
                self._sleep(2)
                if self.daemon_running():
                    return
            raise DeployError("Docker Desktop did not start within two minutes. Start it and run this again.")
        if self._platform.startswith("linux"):
            raise DeployError("Docker is not running. Start it with `sudo systemctl start docker` and run this again.")
        raise DeployError("Docker is not running. Start Docker Desktop and run this again.")

    def compose(self, directory: Path, *args: str, capture: bool = False, check: bool = True):
        """``docker compose <args>`` in ``directory``, which holds the Compose file and its ``.env``."""
        return self._run(["docker", "compose", *args], cwd=directory, capture=capture, check=check)

    def volume_exists(self, name: str) -> bool:
        return self._run(["docker", "volume", "inspect", name], capture=True, check=False).returncode == 0

    def project_dirs(self, project: str) -> set[Path]:
        """The folders containers of Compose project ``project`` were started from."""
        result = self._run(
            [
                "docker", "ps", "-a",
                "--filter", f"label=com.docker.compose.project={project}",
                "--format", '{{.Label "com.docker.compose.project.working_dir"}}',
            ],
            capture=True,
            check=False,
        )
        if result.returncode != 0:
            return set()
        return {Path(line.strip()) for line in result.stdout.splitlines() if line.strip()}


def wait_healthy(
    url: str,
    timeout: float,
    *,
    opener: Callable = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Poll ``url`` until it answers 2xx (True) or ``timeout`` seconds pass (False); tries at least once."""
    deadline = clock() + timeout
    while True:
        try:
            with opener(url, timeout=5) as response:
                if 200 <= response.status < 300:
                    return True
        except (OSError, http.client.HTTPException):
            pass
        if clock() >= deadline:
            return False
        sleep(2)


def lan_ip() -> str:
    """This machine's address on its network, or ``localhost``. No packet is sent."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 80))
            return probe.getsockname()[0]
        except OSError:
            return "localhost"
