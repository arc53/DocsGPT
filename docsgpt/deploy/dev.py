"""``docsgpt dev``: this checkout's API, worker and UI as children of one terminal.

``docsgpt up --native`` installs services meant to outlive the shell. Development wants the
opposite: processes rooted in the checkout, restarting when a file is saved, logging into one
terminal, and gone when Ctrl-C lands. This module decides which processes to run and supervises
them; nothing here imports the app itself.
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, TextIO

from docsgpt.deploy.docker import DeployError

MOCK_LLM_PORT = 8090
UI_PORT = 5173
STOP_GRACE = 10.0

# One colour per child so a glance at the terminal says who is talking.
COLOURS = {"api": "\033[36m", "worker": "\033[35m", "ui": "\033[32m", "llm": "\033[33m"}
RESET = "\033[0m"
WIDTH = 6


@dataclass
class Child:
    """One process ``docsgpt dev`` runs."""

    name: str
    command: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)


def watchfiles_available() -> bool:
    """Whether the worker can be restarted on save; it arrives with uvicorn's standard extras."""
    try:
        import watchfiles  # noqa: F401
    except ImportError:
        return False
    return True


def _reloading_command(command: list[str], watched: Path) -> list[str]:
    """``command`` under watchfiles, restarted when a Python file under ``watched`` changes."""
    return [sys.executable, "-m", "watchfiles", "--filter", "python", shlex.join(command), str(watched)]


def plan(
    args,
    checkout: Path,
    *,
    watching: Optional[bool] = None,
    launcher: Optional[list[str]] = None,
) -> list[Child]:
    """The children to run, in the order they should start."""
    from docsgpt.deploy import stack

    launcher = launcher or [sys.executable, "-m", "docsgpt"]
    watching = watchfiles_available() if watching is None else watching
    package = checkout / "docsgpt"
    environment = {"DOCSGPT_HOME": str(checkout)}
    children: list[Child] = []

    if getattr(args, "mock_llm", False):
        script = checkout / "scripts" / "mock_llm.py"
        if not script.is_file():
            raise DeployError(f"{script} is missing, so there is no mock LLM to run.")
        children.append(
            Child(
                name="llm",
                command=[sys.executable, str(script), "--port", str(MOCK_LLM_PORT)],
                cwd=checkout,
                env=dict(environment),
            )
        )
        # The children read these from the environment, so the checkout's .env is left alone.
        chosen = stack.provider_settings(
            "openai-compatible", model="mock", base_url=f"http://127.0.0.1:{MOCK_LLM_PORT}/v1"
        )
        environment.update({key: value for key, value in chosen.items() if value is not None})

    api = [*launcher, "api", "--host", args.host, "--port", str(args.port)]
    if getattr(args, "reload", True):
        api.append("--reload")
    children.append(Child(name="api", command=api, cwd=checkout, env=dict(environment)))

    if getattr(args, "worker", True):
        worker = [*launcher, "worker", "-l", getattr(args, "loglevel", "INFO")]
        if getattr(args, "reload", True) and watching:
            worker = _reloading_command(worker, package)
        children.append(Child(name="worker", command=worker, cwd=checkout, env=dict(environment)))

    if getattr(args, "ui", False):
        frontend = checkout / "frontend"
        if not (frontend / "node_modules").is_dir():
            raise DeployError(
                f"the frontend has no node_modules yet. Run `npm install --include=dev` in {frontend} "
                "and try again, or leave --ui off."
            )
        if not shutil.which("npm"):
            raise DeployError("npm is not on PATH, so the frontend dev server cannot start.")
        children.append(Child(name="ui", command=["npm", "run", "dev"], cwd=frontend, env=dict(environment)))

    return children


def _line(name: str, text: str, colour: bool) -> str:
    """One output line, prefixed with the child that wrote it."""
    label = name.ljust(WIDTH)
    if colour:
        return f"{COLOURS.get(name, '')}{label}{RESET} | {text}"
    return f"{label} | {text}"


def _pump(child: Child, process, out: TextIO, lock: threading.Lock, colour: bool) -> None:
    """Copy one child's output to ``out``, a line at a time, prefixed."""
    stream = process.stdout
    if stream is None:
        return
    for text in stream:
        with lock:
            out.write(_line(child.name, text.rstrip("\n"), colour))
            out.write("\n")
            out.flush()


def _signal(process, number: int) -> None:
    """Signal a child and, on POSIX, everything it started."""
    try:
        if os.name == "nt":
            process.terminate()
            return
        os.killpg(os.getpgid(process.pid), number)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _stop(running: list[tuple[Child, object]], grace: float, sleep: Callable[[float], None]) -> None:
    """Interrupt the children, then insist if they are still there.

    A second Ctrl-C lands while this is waiting. It means "stop waiting", not "give up": the wait
    ends and the children are killed, rather than the interrupt escaping and leaving them running.
    """
    for _, process in running:
        if process.poll() is None:
            _signal(process, signal.SIGINT)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(process.poll() is None for _, process in running):
        try:
            sleep(0.1)
        except KeyboardInterrupt:
            break
    for _, process in running:
        if process.poll() is None:
            _signal(process, signal.SIGKILL)


def run(
    children: list[Child],
    *,
    out: TextIO = sys.stdout,
    spawn: Callable[..., object] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    grace: float = STOP_GRACE,
    colour: Optional[bool] = None,
) -> int:
    """Start the children and keep them running until one exits or the terminal interrupts."""
    colour = out.isatty() if colour is None else colour
    lock = threading.Lock()
    running: list[tuple[Child, object]] = []
    try:
        for child in children:
            process = spawn(
                child.command,
                cwd=str(child.cwd),
                env={**os.environ, **child.env},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                # Its own session, so Ctrl-C reaches this process and the children are stopped in order.
                start_new_session=os.name != "nt",
            )
            running.append((child, process))
            threading.Thread(target=_pump, args=(child, process, out, lock, colour), daemon=True).start()

        while True:
            for child, process in running:
                code = process.poll()
                if code is not None:
                    with lock:
                        out.write(_line(child.name, f"exited with {code}", colour))
                        out.write("\n")
                        out.flush()
                    return code or 1
            sleep(0.2)
    except KeyboardInterrupt:
        with lock:
            out.write("\nStopping ...\n")
            out.flush()
        return 0
    finally:
        _stop(running, grace, sleep)
