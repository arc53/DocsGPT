"""Build the Daytona sandbox snapshot from the sandbox package manifest.

The Daytona managed sandbox backend (``SANDBOX_BACKEND=daytona``) creates each
session from a snapshot. Daytona's default image is plain Python, so the
``artifact`` tool's renderers and the libraries and tools ``code_executor``
code reaches for are missing there. This script builds a snapshot with the
same contents as the self-hosted runner image -- both come from
``docsgpt/sandbox/manifest.py``:

* the Python libraries (pandas, matplotlib, python-docx, python-pptx, openpyxl,
  reportlab, pypdf, pdfplumber, pytesseract, requests, ...),
* tesseract, poppler-utils, ffmpeg, headless LibreOffice and Chromium, and
  fonts for Latin, Arabic, Devanagari and CJK text,
* Node.js 24 from the official tarball, checked against the pinned SHA-256,
* the ``office-convert``, ``html-to-pdf`` and ``html-screenshot`` helpers and
  the image smoke test.

Sandboxes made from the snapshot get 2 vCPU, 2 GiB RAM and 6 GiB disk by
default, double Daytona's 1/1/3: LibreOffice and Chromium need the room.

Usage::

    # Reads DAYTONA_API_KEY / DAYTONA_API_URL / DAYTONA_TARGET from .env (settings):
    python scripts/build_daytona_snapshot.py
    python scripts/build_daytona_snapshot.py --smoke      # then run the smoke test in a sandbox
    python scripts/build_daytona_snapshot.py --dockerfile # print the image, no API call
    python scripts/build_daytona_snapshot.py --name my-snapshot --cpu 4 --memory 4 --disk 10

Then set in .env::

    DAYTONA_SNAPSHOT=docsgpt-sandbox-py312-v2

A snapshot's contents and resources are fixed once built, so a change to the
manifest means a new name: bump the ``-vN`` suffix of ``DEFAULT_NAME``, build
it and switch ``DAYTONA_SNAPSHOT``. Snapshots built by earlier versions of this
script (``docsgpt-artifacts-py312``, ``docsgpt-sandbox-py312``) lack most of
the tools above.
"""

from __future__ import annotations

import argparse
import base64
import posixpath
import sys
from pathlib import Path
from typing import Any, List, Optional

from docsgpt.sandbox import manifest

DEFAULT_NAME = "docsgpt-sandbox-py312-v2"
DEFAULT_PYTHON = "3.12"
DEFAULT_CPU = 2
DEFAULT_MEMORY_GIB = 2
DEFAULT_DISK_GIB = 6

SMOKE_COMMAND = "python /opt/docsgpt/smoke_test.py"
# Seconds the smoke test may run inside the sandbox; LibreOffice and Chromium
# cold starts dominate it.
SMOKE_TIMEOUT = 600

_SANDBOX_DIR = Path(__file__).resolve().parents[1] / "deployment" / "sandbox"


def _positive_int(value: str) -> int:
    """argparse type for a resource size: an integer above zero."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: Arguments without the program name.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default=DEFAULT_NAME, help="snapshot name (default: %(default)s)")
    parser.add_argument("--python", default=DEFAULT_PYTHON, help="Python series, e.g. 3.12")
    parser.add_argument("--cpu", type=_positive_int, default=DEFAULT_CPU, help="vCPUs per sandbox (default: 2)")
    parser.add_argument(
        "--memory", type=_positive_int, default=DEFAULT_MEMORY_GIB, help="GiB of RAM per sandbox (default: 2)"
    )
    parser.add_argument(
        "--disk", type=_positive_int, default=DEFAULT_DISK_GIB, help="GiB of disk per sandbox (default: 6)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0,
        help="seconds to wait for the build before giving up; 0 waits until it finishes (default: 0)",
    )
    parser.add_argument("--force", action="store_true", help="build even if a snapshot with that name exists")
    parser.add_argument(
        "--smoke", action="store_true", help="after building, run the image smoke test in a sandbox from the snapshot"
    )
    parser.add_argument(
        "--dockerfile", action="store_true", help="print the image's Dockerfile and exit (no API call)"
    )
    return parser.parse_args(argv)


def _embed(image: Any, data: bytes, dest: str, mode: str) -> Any:
    """Write ``data`` to ``dest`` in the image from a base64 RUN line.

    ``Image.add_local_file`` would COPY from an archive path derived from the
    local absolute path, which breaks when the checkout sits under a directory
    with spaces; the files are small, so they travel inline instead.
    """
    encoded = base64.b64encode(data).decode("ascii")
    return image.run_commands(
        f"mkdir -p {posixpath.dirname(dest)} && echo {encoded} | base64 -d > {dest} && chmod {mode} {dest}"
    )


def build_image(python: str) -> Any:
    """Return the snapshot's ``daytona.Image``, built from the sandbox manifest.

    Args:
        python: Python series for ``Image.debian_slim`` (Debian 12 with build tools, so pip can build sdists).

    Returns:
        The image definition.
    """
    from daytona import Image

    image = (
        Image.debian_slim(python)
        .env(dict(manifest.ENV))
        .run_commands(manifest.install_system_one_liner())
        .pip_install(list(manifest.pip_specs()), extra_options="--no-cache-dir")
    )
    for name, source in manifest.HELPERS.items():
        image = _embed(image, (_SANDBOX_DIR / source).read_bytes(), f"/usr/local/bin/{name}", "0755")
    image = _embed(image, (_SANDBOX_DIR / "smoke_test.py").read_bytes(), "/opt/docsgpt/smoke_test.py", "0644")
    return _embed(image, manifest.render_manifest_json().encode(), "/opt/docsgpt/manifest.json", "0644")


def make_client() -> Any:
    """Return a Daytona client configured from settings (.env)."""
    from daytona import Daytona, DaytonaConfig

    from docsgpt.core.settings import settings

    cfg: dict[str, object] = {"api_key": settings.DAYTONA_API_KEY}
    if settings.DAYTONA_API_URL:
        cfg["api_url"] = settings.DAYTONA_API_URL
    if settings.DAYTONA_TARGET:
        cfg["target"] = settings.DAYTONA_TARGET
    return Daytona(DaytonaConfig(**cfg))


def run_smoke(client: Any, name: str) -> int:
    """Run the baked smoke test in a sandbox created from snapshot ``name``, then delete the sandbox.

    Args:
        client: Daytona client.
        name: Snapshot name.

    Returns:
        0 when every check passed, 1 otherwise.
    """
    from daytona import CreateSandboxFromSnapshotParams

    print(f"--- smoke test in a sandbox from {name!r} ---")
    sandbox = client.create(CreateSandboxFromSnapshotParams(snapshot=name), timeout=300)
    try:
        response = sandbox.process.exec(SMOKE_COMMAND, timeout=SMOKE_TIMEOUT)
        print(response.result)
        return 0 if response.exit_code == 0 else 1
    finally:
        client.delete(sandbox)


def main(argv: Optional[List[str]] = None) -> int:
    """Build (or skip) the snapshot, optionally smoke-test it, and print the value to set as DAYTONA_SNAPSHOT.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    args = parse_args(sys.argv[1:] if argv is None else argv)
    image = build_image(args.python)
    if args.dockerfile:
        print(image.dockerfile(), end="")
        return 0

    from docsgpt.core.settings import settings

    if not settings.DAYTONA_API_KEY:
        print("DAYTONA_API_KEY is not set (check .env).", file=sys.stderr)
        return 2

    from daytona import CreateSnapshotParams, DaytonaConflictError, Resources

    client = make_client()

    if not args.force:
        try:
            existing = client.snapshot.get(args.name)
            print(f"snapshot {args.name!r} already exists (state={getattr(existing, 'state', '?')}).")
            print(f"set DAYTONA_SNAPSHOT={args.name}")
            return run_smoke(client, args.name) if args.smoke else 0
        except Exception as exc:  # noqa: BLE001 - "not found" is the happy path; build it
            if type(exc).__name__ != "DaytonaNotFoundError" and "not found" not in str(exc).lower():
                print(f"warning: get({args.name!r}) probe: {type(exc).__name__}: {exc}", file=sys.stderr)

    resources = Resources(cpu=args.cpu, memory=args.memory, disk=args.disk)
    print(
        f"building snapshot {args.name!r} (python {args.python}, {args.cpu} vCPU, {args.memory} GiB RAM, "
        f"{args.disk} GiB disk)\n  pip: {', '.join(manifest.pip_specs())}\n"
        f"  apt: {', '.join(manifest.apt_package_names())}\n  node: {manifest.NODE['version']}"
    )
    print("--- build logs ---")
    try:
        snap = client.snapshot.create(
            CreateSnapshotParams(name=args.name, image=image, resources=resources),
            on_logs=print,
            timeout=args.timeout,
        )
    except DaytonaConflictError:
        print(f"snapshot {args.name!r} already exists (conflict) — reuse it or pass a new --name.")
        return 0
    print("--- created ---")
    print(f"name={getattr(snap, 'name', args.name)} state={getattr(snap, 'state', '?')}")
    print(f"\nNow set in .env:\n    DAYTONA_SNAPSHOT={args.name}")
    if args.smoke:
        return run_smoke(client, args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
