"""Where DocsGPT keeps its files.

Three locations matter. The package directory holds code and the data that
ships with it (prompts, model catalogs, migrations). A checkout, when the
package is imported from one, is the directory holding ``pyproject.toml``.
The data home is where runtime data lives: ``.env``, ``inputs``, ``indexes``.

The home is ``DOCSGPT_HOME`` when set, else the checkout, else the current
directory. That keeps a source checkout and the Docker image (which runs from
``/app`` with the package beside it) behaving as before, and gives a
``pip install docsgpt`` user a home that is not ``site-packages``.
"""

from __future__ import annotations

import os
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


def home_dir() -> Path:
    """Directory for runtime data: ``DOCSGPT_HOME``, else the checkout, else cwd."""
    configured = os.environ.get(HOME_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return checkout_root() or Path.cwd()


def env_file() -> Path:
    """The ``.env`` file settings load: ``DOCSGPT_ENV_FILE``, else ``<home>/.env``."""
    configured = os.environ.get(ENV_FILE_ENV)
    if configured:
        return Path(configured).expanduser()
    return home_dir() / ".env"
