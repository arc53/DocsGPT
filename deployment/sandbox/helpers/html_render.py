#!/usr/bin/env python3
"""html-to-pdf and html-screenshot: render a page with headless Chromium.

Installed twice in the sandbox image, as /usr/local/bin/html-to-pdf and
/usr/local/bin/html-screenshot; the name it is called by picks the mode::

    html-to-pdf report.html report.pdf
    html-to-pdf https://example.com page.pdf
    html-screenshot chart.html chart.png --width 1200 --height 800

The input is a local HTML file or an http(s) URL. Page size and margins come
from the page's CSS (``@page``); Chromium's date/URL header and footer are off.
Each call uses a throwaway browser profile. The helper exits non-zero with a
message when no output file appears and prints the output path on success.

Exit codes: 0 rendered, 1 rendering failed, 2 bad arguments or input,
124 timed out, 127 Chromium not installed.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

# Tried in order; the image ships chromium-headless-shell.
BROWSERS = ("chromium-headless-shell", "chromium", "chromium-browser", "google-chrome", "chrome")

DEFAULT_TIMEOUT = 45.0
# Virtual time the page gets to run scripts and timers before it is captured.
DEFAULT_WAIT_MS = 2000
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800

_MODES = {"html-to-pdf": "pdf", "html-screenshot": "screenshot"}
_STDERR_TAIL = 1500


def _positive_int(value: str) -> int:
    """argparse type for a pixel size: an integer above zero."""
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def _non_negative_int(value: str) -> int:
    """argparse type for a wait budget in ms: zero or more."""
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return parsed


def _positive_float(value: str) -> float:
    """argparse type for a timeout: a number above zero."""
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def parse_args(mode: str, prog: str, argv: Optional[List[str]]) -> argparse.Namespace:
    """Parse the command line for one mode.

    Args:
        mode: ``pdf`` or ``screenshot``.
        prog: Program name for usage messages.
        argv: Arguments without the program name.

    Returns:
        The parsed arguments.
    """
    what = "a PDF" if mode == "pdf" else "a PNG screenshot"
    parser = argparse.ArgumentParser(prog=prog, description=f"Render a web page to {what} with headless Chromium.")
    parser.add_argument("input", help="local .html file or http(s) URL")
    parser.add_argument("output", help="file to write" + (" (.pdf)" if mode == "pdf" else " (.png)"))
    if mode == "screenshot":
        parser.add_argument("--width", type=_positive_int, default=DEFAULT_WIDTH, help="viewport width in px")
        parser.add_argument("--height", type=_positive_int, default=DEFAULT_HEIGHT, help="viewport height in px")
    parser.add_argument(
        "--wait-ms",
        type=_non_negative_int,
        default=DEFAULT_WAIT_MS,
        help="virtual time for scripts and timers before capture; 0 captures at load (default: 2000)",
    )
    parser.add_argument(
        "--timeout", type=_positive_float, default=DEFAULT_TIMEOUT, help="seconds before giving up (default: 45)"
    )
    return parser.parse_args(argv)


def find_browser() -> Optional[str]:
    """Return the first Chromium executable on PATH, or None."""
    for name in BROWSERS:
        path = shutil.which(name)
        if path:
            return path
    return None


def to_url(target: str) -> str:
    """Return the URL Chromium should open for a file path or URL.

    Args:
        target: A local path, or an http, https or file URL.

    Returns:
        The URL; local paths become absolute ``file://`` URLs.

    Raises:
        ValueError: For another scheme or a local file that does not exist.
    """
    scheme = urlparse(target).scheme.lower()
    if scheme in ("http", "https", "file"):
        return target
    if scheme and len(scheme) > 1:
        raise ValueError(f"unsupported URL scheme {scheme!r}; give a local .html file or an http(s) URL")
    path = Path(target).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"input not found: {target}")
    return path.as_uri()


def run(cmd: List[str], timeout: float) -> subprocess.CompletedProcess:
    """Run ``cmd`` in its own process group, killing the whole group on timeout.

    Args:
        cmd: The command.
        timeout: Seconds to wait.

    Returns:
        The finished process with captured text output.

    Raises:
        subprocess.TimeoutExpired: When the command outlives ``timeout``.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # The group may already be gone if Chromium exited at the deadline.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def build_command(
    browser: str, mode: str, url: str, output: Path, profile: Path, args: argparse.Namespace
) -> List[str]:
    """Return the Chromium command for one render.

    Args:
        browser: Chromium executable.
        mode: ``pdf`` or ``screenshot``.
        url: Page to open.
        output: Absolute output path.
        profile: Empty directory for this call's browser profile.
        args: Parsed arguments (wait budget, viewport).

    Returns:
        The argument list.
    """
    cmd = [
        browser,
        "--headless",
        # The sandbox has no user namespaces for Chromium's own sandbox, and a
        # container's small /dev/shm crashes renderers.
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--mute-audio",
        f"--user-data-dir={profile}",
    ]
    if args.wait_ms:
        cmd.append(f"--virtual-time-budget={args.wait_ms}")
    if mode == "pdf":
        cmd += [f"--print-to-pdf={output}", "--no-pdf-header-footer"]
    else:
        cmd += [f"--screenshot={output}", f"--window-size={args.width},{args.height}", "--hide-scrollbars"]
    cmd.append(url)
    return cmd


def _tail(text: str) -> str:
    """Return the end of the browser's output, enough to show its error."""
    return (text or "").strip()[-_STDERR_TAIL:]


def _render(mode: str, prog: str, argv: Optional[List[str]]) -> int:
    """Render one page in ``mode``; returns the exit code."""
    args = parse_args(mode, prog, argv)
    try:
        url = to_url(args.input)
    except ValueError as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return 2
    browser = find_browser()
    if browser is None:
        print(f"{prog}: Chromium is not installed", file=sys.stderr)
        return 127
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # A stale file from an earlier run must not pass for this run's output.
    output.unlink(missing_ok=True)

    profile = Path(tempfile.mkdtemp(prefix="chromium-"))
    try:
        try:
            result = run(build_command(browser, mode, url, output, profile, args), args.timeout)
        except subprocess.TimeoutExpired:
            print(f"{prog}: Chromium timed out after {args.timeout:g}s on {args.input}", file=sys.stderr)
            return 124
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    if result.returncode != 0:
        print(f"{prog}: Chromium exited with {result.returncode}", file=sys.stderr)
        detail = _tail(result.stderr) or _tail(result.stdout)
        if detail:
            print(detail, file=sys.stderr)
        return 1
    if not output.is_file() or output.stat().st_size == 0:
        print(f"{prog}: no output: Chromium did not write {output}", file=sys.stderr)
        detail = _tail(result.stderr) or _tail(result.stdout)
        if detail:
            print(detail, file=sys.stderr)
        return 1
    print(output)
    return 0


def main(argv: Optional[List[str]] = None, prog: Optional[str] = None) -> int:
    """Dispatch on the command name: ``html-to-pdf`` or ``html-screenshot``.

    Args:
        argv: Arguments without the program name; None reads ``sys.argv``.
        prog: Command name; None takes it from ``sys.argv[0]``.

    Returns:
        The process exit code.
    """
    prog = prog or os.path.basename(sys.argv[0])
    if argv is None:
        argv = sys.argv[1:]
    mode = _MODES.get(prog)
    if mode is None:
        print(f"{prog}: run this as html-to-pdf or html-screenshot", file=sys.stderr)
        return 2
    return _render(mode, prog, argv)


if __name__ == "__main__":
    raise SystemExit(main())
