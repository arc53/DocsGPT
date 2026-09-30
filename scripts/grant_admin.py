"""Kept for older guides: runs ``docsgpt grant-admin`` (docsgpt/scripts/grant_admin.py).

Use ``docsgpt grant-admin <user_id> [--revoke | --list | --force]`` instead; it
also works from the Docker image (``python -m docsgpt grant-admin ...``) and a
pip install, which do not ship this ``scripts/`` directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the checkout importable regardless of the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docsgpt.scripts.grant_admin import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
