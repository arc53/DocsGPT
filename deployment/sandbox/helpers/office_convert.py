#!/usr/bin/env python3
"""office-convert: convert an office document with headless LibreOffice.

Installed as /usr/local/bin/office-convert in the sandbox image::

    office-convert report.docx                    # -> ./report.pdf
    office-convert inputs/data.xlsx --to pdf --outdir out
    office-convert slides.pptx --to png           # first slide as an image

Each call runs soffice with its own throwaway profile. Two soffice processes
sharing one profile make the second exit 0 having written nothing, which code
in a sandbox session easily hits. The helper exits non-zero with a message
when no output file appears, prints the output path on success, and stops
soffice (and the soffice.bin it forks) after --timeout seconds.

Exit codes: 0 converted, 1 conversion failed, 2 bad arguments or input,
124 timed out, 127 LibreOffice not installed.
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

# --to value -> soffice --convert-to argument. The explicit filters pick the
# OOXML export whatever the source format is; txt is written as UTF-8.
FORMATS = {
    "pdf": "pdf",
    "docx": "docx:MS Word 2007 XML",
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "odt": "odt",
    "ods": "ods",
    "odp": "odp",
    "png": "png",
    "html": "html",
    "txt": "txt:Text (encoded):UTF8",
    "csv": "csv",
}

# Below the sandbox's 60 s per-call cap, so the caller sees this helper's
# message rather than a killed run.
DEFAULT_TIMEOUT = 45.0

_STDERR_TAIL = 1500


def _positive_float(value: str) -> float:
    """argparse type for a timeout: a number above zero."""
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: Arguments without the program name; None reads ``sys.argv``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="office-convert",
        description="Convert a document with headless LibreOffice and print the output path.",
    )
    parser.add_argument("input", help="document to convert (docx, doc, odt, rtf, xlsx, csv, pptx, html, ...)")
    parser.add_argument("--to", choices=sorted(FORMATS), default="pdf", help="output format (default: pdf)")
    parser.add_argument("--outdir", default=".", help="directory for the output file (default: current directory)")
    parser.add_argument(
        "--timeout", type=_positive_float, default=DEFAULT_TIMEOUT, help="seconds before giving up (default: 45)"
    )
    return parser.parse_args(argv)


def find_soffice() -> Optional[str]:
    """Return the LibreOffice executable on PATH, or None."""
    return shutil.which("soffice") or shutil.which("libreoffice")


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
        # The group may already be gone if soffice exited at the deadline.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def build_command(soffice: str, source: Path, fmt: str, outdir: Path, profile: Path) -> List[str]:
    """Return the soffice command converting ``source`` into ``outdir``.

    Args:
        soffice: LibreOffice executable.
        source: Absolute input path.
        fmt: A key of ``FORMATS``.
        outdir: Absolute output directory.
        profile: Empty directory for this call's LibreOffice profile.

    Returns:
        The argument list.
    """
    return [
        soffice,
        f"-env:UserInstallation={profile.as_uri()}",
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--convert-to",
        FORMATS[fmt],
        "--outdir",
        str(outdir),
        str(source),
    ]


def _mtime(path: Path) -> Optional[int]:
    """Return ``path``'s modification time in ns, or None when it does not exist."""
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def _tail(text: str) -> str:
    """Return the end of a converter's output, enough to show its error."""
    text = (text or "").strip()
    return text[-_STDERR_TAIL:]


def main(argv: Optional[List[str]] = None) -> int:
    """Convert one document; see the module docstring for usage and exit codes.

    Args:
        argv: Arguments without the program name; None reads ``sys.argv``.

    Returns:
        The process exit code.
    """
    args = parse_args(argv)
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        print(f"office-convert: input not found: {args.input}", file=sys.stderr)
        return 2
    outdir = Path(args.outdir).expanduser().resolve()
    output = outdir / f"{source.stem}.{args.to}"
    if output == source:
        print(
            f"office-convert: converting {source.name} to {args.to} in its own directory would overwrite it; "
            "pass --outdir",
            file=sys.stderr,
        )
        return 2
    soffice = find_soffice()
    if soffice is None:
        print("office-convert: LibreOffice (soffice) is not installed", file=sys.stderr)
        return 127
    outdir.mkdir(parents=True, exist_ok=True)

    before = _mtime(output)
    profile = Path(tempfile.mkdtemp(prefix="lo-"))
    try:
        try:
            result = run(build_command(soffice, source, args.to, outdir, profile), args.timeout)
        except subprocess.TimeoutExpired:
            print(f"office-convert: LibreOffice timed out after {args.timeout:g}s on {source.name}", file=sys.stderr)
            return 124
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    if result.returncode != 0:
        print(f"office-convert: soffice exited with {result.returncode}", file=sys.stderr)
        detail = _tail(result.stderr) or _tail(result.stdout)
        if detail:
            print(detail, file=sys.stderr)
        return 1
    after = _mtime(output)
    if after is None or after == before or output.stat().st_size == 0:
        print(
            f"office-convert: no output: LibreOffice did not write {output} "
            f"(is {source.name} a document it can open as {args.to}?)",
            file=sys.stderr,
        )
        detail = _tail(result.stderr) or _tail(result.stdout)
        if detail:
            print(detail, file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
