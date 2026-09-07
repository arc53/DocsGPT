"""``application`` is now ``docsgpt``; this alias keeps the old name importable for one release.

Every ``import application.x.y`` resolves to the already-imported ``docsgpt.x.y``
module object, so there is exactly one settings object, one Celery app and one
Flask app however a process refers to them. Entry points such as
``celery -A application.app.celery`` and ``uvicorn application.asgi:asgi_app``
keep working; update them to ``docsgpt.…`` before the alias is removed.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
import warnings

_OLD = __name__
_NEW = "docsgpt"


class _AliasLoader(importlib.abc.Loader):
    """Hand back the ``docsgpt`` module instead of executing anything."""

    def __init__(self, target: str) -> None:
        self._target = target

    def create_module(self, spec):
        return importlib.import_module(self._target)

    def exec_module(self, module) -> None:
        return None


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Resolve ``application.<path>`` to ``docsgpt.<path>``."""

    def find_spec(self, name, path=None, target=None):
        if name != _OLD and not name.startswith(_OLD + "."):
            return None
        new_name = _NEW + name[len(_OLD):]
        spec = importlib.util.find_spec(new_name)
        if spec is None:
            return None
        return importlib.util.spec_from_loader(
            name, _AliasLoader(new_name), is_package=spec.submodule_search_locations is not None
        )


warnings.warn(
    "The 'application' package was renamed to 'docsgpt'. Update imports and entry points "
    "(celery -A docsgpt.app.celery, uvicorn docsgpt.asgi:asgi_app); this alias will be removed.",
    FutureWarning,
    stacklevel=2,
)
sys.meta_path.insert(0, _AliasFinder())
sys.modules[_OLD] = importlib.import_module(_NEW)
