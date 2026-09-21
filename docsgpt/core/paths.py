"""Where DocsGPT keeps its files.

Three locations matter. The package directory holds code and the data that
ships with it (prompts, model catalogs, migrations). A checkout, when the
package is imported from one, is the directory holding ``pyproject.toml``.
The data home is where runtime data lives: ``.env``, ``inputs``, ``indexes``.

The home is ``DOCSGPT_HOME`` when set, else the checkout, else the default
home (``~/.docsgpt/server``, or ``/opt/docsgpt`` for root on Linux). That keeps
a source checkout and the Docker image (which pins ``DOCSGPT_HOME=/app``)
behaving as before, and gives an installed package one home no matter which
directory the command runs from. ``docsgpt up`` keeps its stack in the same
place.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HOME_ENV = "DOCSGPT_HOME"
ENV_FILE_ENV = "DOCSGPT_ENV_FILE"


def package_dir() -> Path:
    """The installed ``docsgpt`` package directory."""
    return Path(__file__).resolve().parent.parent


def checkout_root() -> Path | None:
    """The source checkout the package is imported from, or None when installed."""
    root = package_dir().parent
    return root if (root / "pyproject.toml").is_file() else None


def default_home() -> Path:
    """The home outside a checkout: ``/opt/docsgpt`` for root on Linux, else ``~/.docsgpt/server``."""
    if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0:
        return Path("/opt/docsgpt")
    return Path.home() / ".docsgpt" / "server"


def home_dir() -> Path:
    """Directory for runtime data: ``DOCSGPT_HOME``, else the checkout, else the default home."""
    configured = os.environ.get(HOME_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return checkout_root() or default_home()


def env_file() -> Path:
    """The ``.env`` file settings load: ``DOCSGPT_ENV_FILE``, else ``<home>/.env``."""
    configured = os.environ.get(ENV_FILE_ENV)
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"{ENV_FILE_ENV} is set to {path}, which is not a file")
        return path
    return home_dir() / ".env"
