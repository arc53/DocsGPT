"""Optional dependency extras and the one place their install hints come from.

Heavy or niche packages are not installed by default. Each extra maps to a
pyproject extra and to an exported ``application/requirements-<extra>.txt``,
so a missing module can always be explained with the exact command to run.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from types import ModuleType
from typing import Dict, Tuple

#: Extra name -> top-level modules it provides. Keep in sync with
#: ``[project.optional-dependencies]`` in pyproject.toml.
EXTRAS: Dict[str, Tuple[str, ...]] = {
    "docling": ("docling", "rapidocr"),
    "milvus": ("pymilvus",),
}

_MODULE_TO_EXTRA: Dict[str, str] = {
    module: extra for extra, modules in EXTRAS.items() for module in modules
}


def install_hint(extra: str) -> str:
    """Install command for ``extra``, for error messages and logs."""
    return (
        f"pip install -r application/requirements-{extra}.txt "
        f"(or: uv sync --extra {extra}; Docker: --build-arg EXTRAS={extra})"
    )


def extra_for(module: str) -> str | None:
    """Extra that provides top-level module ``module``, if any."""
    return _MODULE_TO_EXTRA.get(module.split(".")[0])


def is_available(module: str) -> bool:
    """Whether ``module`` can be imported, without importing it."""
    root = module.split(".")[0]
    if root in sys.modules:
        return sys.modules[root] is not None
    try:
        return importlib.util.find_spec(root) is not None
    except (ImportError, ValueError):
        return False


def missing_message(module: str, purpose: str | None = None) -> str:
    """Human-readable explanation that ``module`` is absent and how to add it."""
    extra = extra_for(module)
    what = f"{module} is not installed"
    if purpose:
        what += f" ({purpose})"
    if extra:
        return f"{what}. It is part of the optional '{extra}' extra: {install_hint(extra)}"
    return f"{what}. Install it with: pip install {module}"


def require(module: str, purpose: str | None = None) -> ModuleType:
    """Import ``module`` or raise ``ImportError`` naming the extra to install.

    Args:
        module: Importable module path, e.g. ``"pymilvus"``.
        purpose: Short note on what needed it, included in the error.

    Returns:
        The imported module.

    Raises:
        ImportError: With the install hint when the module is absent.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(missing_message(module, purpose)) from exc
