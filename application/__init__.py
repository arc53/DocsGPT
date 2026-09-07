"""``application`` is now ``docsgpt``; this alias keeps the old name importable for one release.

Every ``import application.x.y`` resolves to the already-imported ``docsgpt.x.y``
module object, so there is exactly one settings object, one Celery app and one
Flask app however a process refers to them. Entry points such as
``celery -A application.app.celery``, ``uvicorn application.asgi:asgi_app`` and
``python -m application.scripts.<name>`` keep working; update them to
``docsgpt.…`` before the alias is removed.
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
    """Hand back the ``docsgpt`` module object; delegate code access to its real loader."""

    def __init__(self, target: str, target_spec) -> None:
        self._target = target
        self._target_spec = target_spec
        self._original_spec = None

    def create_module(self, spec):
        module = importlib.import_module(self._target)
        self._original_spec = module.__spec__
        return module

    def exec_module(self, module) -> None:
        # The import machinery stamps the alias spec on the shared module
        # object; put the real one back so importlib.reload and __spec__-based
        # lookups keep addressing the module by its docsgpt name.
        if self._original_spec is not None:
            module.__spec__ = self._original_spec

    # runpy (``python -m application.x``) reads the code through the loader.
    def get_code(self, fullname):
        return self._target_spec.loader.get_code(self._target)

    def get_source(self, fullname):
        return self._target_spec.loader.get_source(self._target)

    def get_filename(self, fullname):
        return self._target_spec.loader.get_filename(self._target)

    def is_package(self, fullname):
        return self._target_spec.submodule_search_locations is not None


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Resolve ``application.<path>`` to ``docsgpt.<path>``."""

    def find_spec(self, name, path=None, target=None):
        if name != _OLD and not name.startswith(_OLD + "."):
            return None
        new_name = _NEW + name[len(_OLD):]
        target_spec = importlib.util.find_spec(new_name)
        if target_spec is None:
            return None
        return importlib.util.spec_from_loader(name, _AliasLoader(new_name, target_spec))


warnings.warn(
    "The 'application' package was renamed to 'docsgpt'. Update imports and entry points "
    "(celery -A docsgpt.app.celery, uvicorn docsgpt.asgi:asgi_app); this alias will be removed.",
    FutureWarning,
    stacklevel=2,
)
sys.meta_path.insert(0, _AliasFinder())
sys.modules[_OLD] = importlib.import_module(_NEW)
