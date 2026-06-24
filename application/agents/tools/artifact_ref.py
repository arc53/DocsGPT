"""Virtual short artifact handles (``A1``, ``A2``, ...) the model can type to reference an artifact.

A ref is NOT persisted: ``A{n}`` is the n-th artifact (1-based, created_at asc) within the
caller's parent (``conversation_id`` or ``workflow_run_id``). Refs resolve only inside that
parent, never cross-tenant; resolution still goes through the parent-scoped authz gate.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from application.storage.db.base_repository import looks_like_uuid

_REF_RE = re.compile(r"^[Aa](\d+)$")


def make_ref(position: int) -> str:
    """Build the short ref string for a 1-based position (``1`` -> ``"A1"``)."""
    return f"A{position}"


def parse_ref(value: Any) -> Optional[int]:
    """Parse a short ref like ``A1``/``a2`` into its 1-based position, or None when it is not a ref."""
    if not isinstance(value, str):
        return None
    match = _REF_RE.match(value.strip())
    if match is None:
        return None
    position = int(match.group(1))
    return position if position >= 1 else None


def resolve_artifact_id(
    repo: Any,
    raw: Any,
    *,
    conversation_id: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
) -> Optional[str]:
    """Resolve a short ref or a uuid to an artifact id, scoped to the caller's parent; None otherwise."""
    position = parse_ref(raw)
    if position is not None:
        return repo.artifact_id_at_position(
            position,
            conversation_id=conversation_id,
            workflow_run_id=workflow_run_id,
        )
    if looks_like_uuid(raw):
        return str(raw).strip()
    return None
