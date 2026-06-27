"""Build a Daytona snapshot preloaded with the artifact-render libraries.

The Daytona managed sandbox backend (``SANDBOX_BACKEND=daytona``) creates each
session from a snapshot. The default snapshot is a plain Python image, so the
``artifact`` tool's renderers — which ``import`` ``python-pptx`` / ``python-docx``
/ ``openpyxl`` / ``reportlab`` inside the sandbox — fail with
``render failed: ExecutionError``. This script bakes those libraries into a
snapshot once; point ``DAYTONA_SNAPSHOT`` at its name to fix rendering on Daytona.

Usage::

    # Reads DAYTONA_API_KEY / DAYTONA_API_URL / DAYTONA_TARGET from .env (settings):
    python scripts/build_daytona_snapshot.py
    python scripts/build_daytona_snapshot.py --name docsgpt-artifacts-py312 --python 3.12

Then set in .env::

    DAYTONA_SNAPSHOT=docsgpt-artifacts-py312

Keep the pins in sync with the backend venv (python-pptx / openpyxl / lxml /
pillow are in application/requirements.txt; python-docx and reportlab arrive
transitively) so the Daytona render output matches the Jupyter-backend output.
"""

from __future__ import annotations

import argparse
import sys

# Render libraries imported by the artifact tool's renderers, pinned to the
# versions installed in the backend venv as of this writing.
RENDER_PINS = [
    "python-pptx==1.0.2",
    "python-docx==1.2.0",
    "openpyxl==3.1.5",
    "reportlab==4.5.1",
    "lxml==6.0.2",
    "pillow==11.3.0",
]

DEFAULT_NAME = "docsgpt-artifacts-py312"
DEFAULT_PYTHON = "3.12"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments for the snapshot name and Python series."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default=DEFAULT_NAME, help="snapshot name (default: %(default)s)")
    parser.add_argument("--python", default=DEFAULT_PYTHON, help="Python series, e.g. 3.12")
    parser.add_argument(
        "--force", action="store_true", help="rebuild even if a snapshot with that name exists"
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Build (or skip) the snapshot and print the value to set as DAYTONA_SNAPSHOT."""
    args = _parse_args(argv)

    from application.core.settings import settings

    if not settings.DAYTONA_API_KEY:
        print("DAYTONA_API_KEY is not set (check .env).", file=sys.stderr)
        return 2

    from daytona import (
        CreateSnapshotParams,
        Daytona,
        DaytonaConfig,
        DaytonaConflictError,
        Image,
    )

    cfg: dict[str, object] = {"api_key": settings.DAYTONA_API_KEY}
    if settings.DAYTONA_API_URL:
        cfg["api_url"] = settings.DAYTONA_API_URL
    if settings.DAYTONA_TARGET:
        cfg["target"] = settings.DAYTONA_TARGET
    client = Daytona(DaytonaConfig(**cfg))

    if not args.force:
        try:
            existing = client.snapshot.get(args.name)
            print(f"snapshot {args.name!r} already exists (state={getattr(existing, 'state', '?')}).")
            print(f"set DAYTONA_SNAPSHOT={args.name}")
            return 0
        except Exception as exc:  # noqa: BLE001 - "not found" is the happy path; build it
            if type(exc).__name__ != "DaytonaNotFoundError" and "not found" not in str(exc).lower():
                print(f"warning: get({args.name!r}) probe: {type(exc).__name__}: {exc}", file=sys.stderr)

    image = Image.debian_slim(args.python).pip_install(RENDER_PINS)
    print(f"building snapshot {args.name!r} (python {args.python}) with: {', '.join(RENDER_PINS)}")
    print("--- build logs ---")
    try:
        snap = client.snapshot.create(
            CreateSnapshotParams(name=args.name, image=image), on_logs=print, timeout=600
        )
    except DaytonaConflictError:
        print(f"snapshot {args.name!r} already exists (conflict) — reuse it or pass --force a new name.")
        return 0
    print("--- created ---")
    print(f"name={getattr(snap, 'name', args.name)} state={getattr(snap, 'state', '?')}")
    print(f"\nNow set in .env:\n    DAYTONA_SNAPSHOT={args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
