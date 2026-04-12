"""Common helpers shared by all repositories.

Repositories are thin wrappers around SQLAlchemy Core query construction.
They take a ``Connection`` on call and return plain ``dict`` rows during the
Mongo→Postgres cutover so that call sites don't have to change shape. Once
cutover is complete, a follow-up phase may migrate repo return types to
Pydantic DTOs (tracked in the migration plan as a post-migration item).
"""

from typing import Any, Mapping
from uuid import UUID


def row_to_dict(row: Any) -> dict:
    """Convert a SQLAlchemy ``Row`` to a plain dict with Mongo-compatible ids.

    During the migration window, API responses and downstream code still
    expect a string ``_id`` field (matching the Mongo shape). This helper
    normalizes UUID columns to strings and emits both ``id`` and ``_id`` so
    existing serializers keep working unchanged.

    Args:
        row: A SQLAlchemy ``Row`` object, or ``None``.

    Returns:
        A plain dict, or an empty dict if ``row`` is ``None``.
    """
    if row is None:
        return {}

    # Row has a ``._mapping`` attribute exposing a MappingProxy view.
    mapping: Mapping[str, Any] = row._mapping  # type: ignore[attr-defined]
    out = dict(mapping)

    if "id" in out and out["id"] is not None:
        out["id"] = str(out["id"]) if isinstance(out["id"], UUID) else out["id"]
        out["_id"] = out["id"]

    return out
