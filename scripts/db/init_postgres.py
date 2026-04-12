"""One-shot bootstrap: run all Alembic migrations against POSTGRES_URI.

Intended use:

  * local dev, after setting ``POSTGRES_URI`` in ``.env``::

        python scripts/db/init_postgres.py

  * CI, as a step before running the pytest suite.

  * Docker image build or container start, if the operator wants the
    migrations applied automatically on first boot.

This script is a thin wrapper around ``alembic upgrade head``. It exists
separately so the same command is discoverable from the repo root without
remembering the ``-c application/alembic.ini`` invocation.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "application" / "alembic.ini"


def main() -> int:
    """Apply every pending migration up to ``head``.

    Returns:
        ``0`` on success, ``1`` on failure. Non-zero is propagated as the
        process exit code so CI jobs fail loudly.
    """
    if not ALEMBIC_INI.exists():
        print(f"alembic.ini not found at {ALEMBIC_INI}", file=sys.stderr)
        return 1

    cfg = Config(str(ALEMBIC_INI))
    # Make `script_location` resolve correctly when invoked from any cwd.
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))

    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 — surface everything to the operator
        print(f"alembic upgrade failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
