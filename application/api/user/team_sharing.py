"""Cross-cutting helpers for team resource sharing.

Centralises the polymorphic dispatch over the four shareable resource types so
the grant endpoint and the per-entity list/get/update paths share one source of
truth for "does this user own resource R?" and "what can this user see/edit via
their teams?". Every shareable repo exposes the same ``get_any(id, user_id)``
ownership accessor, which is what makes the dispatch uniform.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection

from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.prompts import PromptsRepository
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from application.storage.db.repositories.team_scope import TeamScopeRepository
from application.storage.db.repositories.user_tools import UserToolsRepository

RESOURCE_TYPES = ("agent", "source", "prompt", "tool")

_REPO_FOR_TYPE = {
    "agent": AgentsRepository,
    "source": SourcesRepository,
    "prompt": PromptsRepository,
    "tool": UserToolsRepository,
}


def is_valid_resource_type(resource_type: str) -> bool:
    return resource_type in _REPO_FOR_TYPE


def owns_resource(
    conn: Connection, resource_type: str, resource_id: str, user_id: str
) -> bool:
    """True if ``user_id`` is the OWNER of the resource.

    Dispatches to the correct repo by ``resource_type`` — this is the guard that
    stops a caller registering a grant with a mismatched ``resource_type`` /
    ``resource_id`` (the polymorphic grant table has no FK to catch it). Owners
    only — team-granted ``editor`` access does NOT make you an owner.
    """
    repo_cls = _REPO_FOR_TYPE.get(resource_type)
    if repo_cls is None:
        return False
    return repo_cls(conn).get_any(resource_id, user_id) is not None


def team_access_for(
    conn: Connection, user_id: str, resource_type: str, resource_id: str
) -> Optional[str]:
    """Strongest team access (``editor``/``viewer``) ``user_id`` has on a resource.

    None when no team grant reaches the user (they may still be the owner — that
    is a separate dual-key check at the repo).
    """
    return TeamScopeRepository(conn).effective_access(user_id, resource_type, resource_id)


def visible_ids_via_teams(
    conn: Connection, user_id: str, resource_type: str
) -> set[str]:
    """The id set of ``resource_type`` shared to any team ``user_id`` belongs to."""
    return TeamScopeRepository(conn).visible_resource_ids(user_id, resource_type)


def visible_with_access(
    conn: Connection, user_id: str, resource_type: str
) -> dict[str, str]:
    """Map ``resource_id -> strongest access`` shared to the user's teams."""
    return TeamScopeRepository(conn).visible_with_access(user_id, resource_type)


def effective_write_owner(
    conn: Connection, resource_type: str, resource_id: str, user_id: str
) -> Optional[str]:
    """The owner id to write a resource AS, or None if the caller can't write.

    Returns ``user_id`` when the caller owns the resource, or the resource's
    real ``owner_id`` when the caller holds a team ``editor`` grant — so callers
    can pass the result straight to the existing owner-scoped ``update(id, owner,
    ...)`` repo methods (which match on ``WHERE id AND user_id = :owner``) without
    a separate ownerless write path. None means viewer-only or no access → the
    route should answer 403/404. Delete is never authorized here — owner-only.
    """
    if owns_resource(conn, resource_type, resource_id, user_id):
        return user_id
    # Past the ownership check, only canonical-UUID resources can carry a team
    # grant; a legacy/non-UUID id can't, and casting it would poison the txn.
    if not looks_like_uuid(resource_id):
        return None
    grants = TeamResourceGrantsRepository(conn).list_for_resource(
        resource_type, resource_id
    )
    if not grants:
        return None
    if TeamScopeRepository(conn).can_write(user_id, resource_type, resource_id):
        # All grant rows carry the same denormalised owner_id.
        return grants[0].get("owner_id")
    return None


def can_access(
    conn: Connection, resource_type: str, resource_id: str, user_id: str
) -> bool:
    """True if ``user_id`` owns the resource OR has any team grant on it (read).

    This is the write-path gate for *referencing* a resource (e.g. attaching a
    ``source_id`` to an agent): you may reference what you own or what a team has
    shared with you directly. Transitive access *through* a shared agent is a
    separate, run-time concept and is intentionally NOT gated here.
    """
    if not resource_id:
        return True
    if owns_resource(conn, resource_type, resource_id, user_id):
        return True
    return TeamScopeRepository(conn).can_read(user_id, resource_type, resource_id)
