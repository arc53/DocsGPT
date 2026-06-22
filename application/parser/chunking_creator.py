"""String-keyed registry for chunking strategies.

Mirrors ``RetrieverCreator``: features register new strategies (``recursive``,
``markdown``, ``parent_child``, ...) without touching the dispatch site. The
classic strategy is registered under ``classic_chunk`` by ``chunking.py``.
"""

from __future__ import annotations

from typing import Type


class ChunkerCreator:
    chunkers: dict[str, Type] = {}
    _strategies_loaded: bool = False

    @classmethod
    def _ensure_builtin(cls) -> None:
        """Register built-in chunkers if they are not registered yet.

        Self-bootstraps so ``create_chunker`` works regardless of import order:
        ``application.parser.chunking`` registers ``classic_chunk`` and
        ``application.parser.chunking_strategies`` registers ``recursive`` /
        ``markdown`` / ``parent_child``.
        """
        if not cls.chunkers:
            import application.parser.chunking  # noqa: F401  (registers classic_chunk)
        if not cls._strategies_loaded:
            cls._strategies_loaded = True
            import application.parser.chunking_strategies  # noqa: F401

    @classmethod
    def create_chunker(cls, strategy: str, *args, **kwargs):
        """Instantiate the chunker registered under ``strategy``.

        Args:
            strategy: Registry key (e.g. ``classic_chunk``).
            *args: Positional args forwarded to the chunker constructor.
            **kwargs: Keyword args forwarded to the chunker constructor.

        Returns:
            A chunker instance exposing ``chunk(documents) -> List[Document]``.

        Raises:
            ValueError: If no chunker is registered for ``strategy``.
        """
        cls._ensure_builtin()
        key = (strategy or "classic_chunk").lower()
        chunker_class = cls.chunkers.get(key)
        if not chunker_class:
            raise ValueError(f"No chunker class found for strategy {strategy}")
        return chunker_class(*args, **kwargs)

    @classmethod
    def register(cls, key: str, chunker_class: Type) -> None:
        """Register ``chunker_class`` under ``key`` (idempotent)."""
        cls.chunkers[key] = chunker_class
