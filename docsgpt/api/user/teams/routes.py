"""Team management API: CRUD, membership, and resource-sharing grants.

Authorization model (two planes, see ``team_authz.py``):
- Any authenticated user may create a team (self-serve); the creator becomes a
  ``team_admin`` in the same transaction.
- Team detail / member list / grant list require team membership.
- Member management and team edit require ``team_admin``.
- Team deletion and owner transfer are owner-only (a global ``admin`` overrides).
- Sharing a resource requires the ``share`` action on it (the owner, or an
  editor when the owner turned on ``editors_can_share``; see
  ``resource_access.py``) and membership of the target team. Unsharing needs
  ``share`` (no membership required) or ``team_admin`` of the team. Sharing is
  additive visibility — the resource's owner is never changed.
- The team owner can't be demoted or removed, and a team keeps at least one
  admin, whichever route changes the membership (add/re-add, role change,
  removal, leave): all go through ``TeamMembersRepository.change_membership``.
  The owner transfers ownership first; only that flow changes the Owner.
- Roles are Owner (``teams.owner_id``), Admin, Editor and Viewer; writes take
  ``role: admin|editor|viewer`` (new members join as viewer). Until the UI
  moves to them (step 2), today's names stay readable and writable:
  ``team_member`` is accepted as a viewer, team payloads keep ``member_role``
  (``team_admin``/``team_member``) beside the new ``role``, the grants list
  keeps ``team_role`` in the old names beside ``role``, and member rows keep
  ``role`` in the old names beside the new ``team_role``.
- A team's own items have no per-item grants (409 ``team_item``), and a team
  that still owns items can't be deleted (409 ``team_not_empty``).

``team_id`` always comes from the URL path (never the body) — enforced by
``require_team_role`` and by reading ``team_id`` as a route kwarg here.
"""

from __future__ import annotations

import logging
import re
import uuid

from flask import Response, jsonify, make_response, request
from flask_restx import Namespace, Resource
from sqlalchemy import text

from docsgpt.api.user.authz import ROLE_ADMIN, has_role
from docsgpt.api.user.resource_access import (
    RESOURCE_TYPES,
    AccessDenied,
    ResourceAccess,
    build,
    public_settings,
    require,
    resolve,
    resource_owner,
    set_settings,
    settings_many,
    workspace_minimum,
)
from docsgpt.api.user.team_authz import (
    has_team_role,
    team_admin_required,
    team_member_required,
)
from docsgpt.api.user.team_sharing import is_valid_resource_type
from docsgpt.events.publisher import publish_user_event
from docsgpt.notifications.notify import notify_user
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import (
    ROLE_TEAM_ADMIN,
    MembershipChangeRefused,
    TeamMembersRepository,
)
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.team_scope import TeamScopeRepository
from docsgpt.storage.db.repositories.teams import TeamNotEmpty, TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.workspaces.outside import team_policy
from docsgpt.workspaces.principal import is_principal_id, principal_id
from docsgpt.workspaces.roles import (
    from_stored_role,
    legacy_member_role,
    role_at_least,
    team_role_for,
    to_stored_role,
)

logger = logging.getLogger(__name__)

teams_ns = Namespace("teams", description="Team management and resource sharing", path="/api")

_VALID_ACCESS_LEVELS = ("viewer", "editor")
_TEAM_SEARCH_LIMIT = 20
_TEAM_SEARCH_MAX = 100
_MEMBERS_PAGE_SIZE_MAX = 100


def _current_user() -> str | None:
    token = getattr(request, "decoded_token", None)
    return token.get("sub") if isinstance(token, dict) else None


def _optional_int_arg(name: str) -> int | None:
    """The query arg ``name`` as an int, or None when absent or not an integer."""
    try:
        return int(request.args.get(name, ""))
    except (TypeError, ValueError):
        return None


def _members_query() -> tuple[str | None, int | None, int]:
    """Parse ``q`` / ``page`` / ``page_size`` for the members list.

    Pagination applies only when ``page_size`` is a valid integer; it is
    clamped to 1..``_MEMBERS_PAGE_SIZE_MAX`` and ``page`` (1-based) to >= 1.

    Returns:
        ``(q, limit, offset)`` where ``q`` is None when blank and ``limit`` is
        None when the whole list is wanted.
    """
    q = (request.args.get("q") or "").strip() or None
    page_size = _optional_int_arg("page_size")
    if page_size is None:
        return q, None, 0
    limit = max(1, min(_MEMBERS_PAGE_SIZE_MAX, page_size))
    page = max(1, _optional_int_arg("page") or 1)
    return q, limit, (page - 1) * limit


def _denied(err: AccessDenied):
    """JSON response for an :class:`AccessDenied` (404 not visible, 403 not allowed)."""
    return make_response(jsonify({"success": False, "message": err.message}), err.status)


def _refusal(refused: MembershipChangeRefused):
    """JSON response for a membership change the team's invariants refuse.

    The owner changing themselves gets 400 telling them to transfer ownership
    first; anyone else touching the owner gets 403; demoting or removing the
    last admin is 409. Each carries a stable ``error`` code the UI maps to its
    own text: ``last_admin``, ``owner_must_transfer`` or ``owner_protected``.

    Args:
        refused: The refusal raised by ``change_membership``.

    Returns:
        The ``{"success": False, "error": code, "message": ...}`` response.
    """
    remove = refused.change == "remove"
    if refused.reason == MembershipChangeRefused.LAST_ADMIN:
        message = f"Cannot {'remove' if remove else 'demote'} the last team admin"
        status, code = 409, "last_admin"
    elif refused.self_change:
        message = (
            "Transfer team ownership to another member before you leave the team"
            if remove
            else "Transfer team ownership to another member before you step down as admin"
        )
        status, code = 400, "owner_must_transfer"
    else:
        message = f"The team owner can't be {'removed' if remove else 'demoted'}"
        status, code = 403, "owner_protected"
    return make_response(jsonify({"success": False, "error": code, "message": message}), status)


def _team_payload(team: dict, user: str | None, stored_role: str | None = None) -> dict:
    """Add the caller's ``role``, ``member_role`` and ``is_owner`` to a team row.

    Args:
        team: The team row.
        user: The caller.
        stored_role: The caller's strongest stored role in the team, if any.

    Returns:
        dict: The row, with ``role`` (``owner|admin|editor|viewer``, None for a
        non-member such as an instance admin), ``member_role`` (today's
        ``team_admin|team_member``) and ``is_owner`` (gates delete and transfer).
    """
    is_owner = bool(user) and team.get("owner_id") == user
    role = "owner" if is_owner else from_stored_role(stored_role)
    team["role"] = role
    team["member_role"] = legacy_member_role(role)
    team["is_owner"] = is_owner
    return team


def _member_rows(members: list[dict], owner_id: str | None) -> list[dict]:
    """Member rows with ``team_role`` (``owner|admin|editor|viewer``) and ``role`` in today's names.

    Args:
        members: ``TeamMembersRepository.list_members`` rows (stored roles).
        owner_id: ``teams.owner_id``; their rows say ``owner``.

    Returns:
        list[dict]: The same rows, changed in place.
    """
    for member in members:
        team_role = "owner" if owner_id and member.get("user_id") == owner_id else from_stored_role(member.get("role"))
        member["team_role"] = team_role
        member["role"] = legacy_member_role(team_role)
    return members


def _requested_role(data: dict, default: str | None) -> str | None:
    """The stored role a member write asks for, or None when it names no assignable role.

    Accepts ``admin|editor|viewer``, the stored names and today's ``team_member``;
    ``owner`` is never assignable (ownership is transferred).
    """
    raw = data.get("role", default)
    try:
        return to_stored_role(raw)
    except ValueError:
        return None


# Name + owner of each shareable resource, looked up unscoped by id (the grant
# row already proves it was shared; the caller's own access is computed below).
_RESOURCE_ROW_SQL = {
    "agent": "SELECT id, name, user_id FROM agents WHERE id = ANY(CAST(:ids AS uuid[]))",
    "source": "SELECT id, name, user_id FROM sources WHERE id = ANY(CAST(:ids AS uuid[]))",
    "prompt": "SELECT id, name, user_id FROM prompts WHERE id = ANY(CAST(:ids AS uuid[]))",
    "tool": (
        "SELECT id, COALESCE(NULLIF(custom_name, ''), NULLIF(display_name, ''), name) AS name, "
        "user_id FROM user_tools WHERE id = ANY(CAST(:ids AS uuid[]))"
    ),
}


def _resource_rows(conn, grants: list[dict]) -> dict[tuple[str, str], dict]:
    """``(type, id) -> {name, user_id}`` for every resource the grants point at."""
    ids_by_type: dict[str, set[str]] = {}
    for g in grants:
        ids_by_type.setdefault(g["resource_type"], set()).add(str(g["resource_id"]))
    out: dict[tuple[str, str], dict] = {}
    for rtype, ids in ids_by_type.items():
        sql = _RESOURCE_ROW_SQL.get(rtype)
        if not sql:
            continue
        for rid, name, owner in conn.execute(text(sql), {"ids": list(ids)}).fetchall():
            out[(rtype, str(rid))] = {"name": name, "user_id": owner}
    return out


def _caller_access(
    conn, user: str, grants: list[dict], rows: dict[tuple[str, str], dict]
) -> dict[tuple[str, str], ResourceAccess]:
    """The caller's live access to each granted resource, in a few bulk queries.

    Same answer as ``resource_access.resolve`` per resource (owner by the
    resource's ``user_id``, else the strongest team grant reaching the caller),
    without four queries per row.
    """
    scope = TeamScopeRepository(conn)
    out: dict[tuple[str, str], ResourceAccess] = {}
    for rtype in {g["resource_type"] for g in grants}:
        ids = sorted({str(g["resource_id"]) for g in grants if g["resource_type"] == rtype})
        via_teams = scope.visible_with_access(user, rtype)
        settings = settings_many(conn, rtype, ids)
        for rid in ids:
            row = rows.get((rtype, rid))
            if row is None:
                continue  # dangling grant: the resource is gone
            if row["user_id"] == user:
                level = "owner"
            else:
                level = via_teams.get(rid)
            if level is None:
                continue
            out[(rtype, rid)] = build(rtype, rid, level, row["user_id"], settings[rid])
    return out


# Why a grant on the team's grants list gives no access right now.
PAUSED_OWNER_LEFT = "owner_left"


def _members_among(conn, team_id: str, user_ids: set[str]) -> set[str]:
    """The ids in ``user_ids`` that are in the team now, in one query.

    Read as ``team_role_for`` reads it: any membership row, or the team's owner.

    Args:
        conn: Open connection.
        team_id: Team UUID.
        user_ids: Candidate ids.

    Returns:
        set[str]: Those in the team.
    """
    ids = sorted(u for u in user_ids if u)
    if not ids:
        return set()
    rows = conn.execute(
        text(
            "SELECT user_id FROM team_members "
            "WHERE team_id = CAST(:team_id AS uuid) AND user_id = ANY(:ids) "
            "UNION SELECT owner_id FROM teams WHERE id = CAST(:team_id AS uuid) AND owner_id = ANY(:ids)"
        ),
        {"team_id": team_id, "ids": ids},
    ).fetchall()
    return {row[0] for row in rows}


def _paused_reason(owner_id: str | None, members: set[str]) -> str | None:
    """Why a grant is paused: its owner, a person, is no longer in the team; None while it works.

    The grant gives access again once the owner is re-added.
    """
    if owner_id and not is_principal_id(owner_id) and owner_id not in members:
        return PAUSED_OWNER_LEFT
    return None


def _user_labels(conn, user_ids: set[str]) -> dict[str, str]:
    """``user_id -> email`` for the users on file with an email."""
    ids = [u for u in user_ids if u]
    if not ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT user_id, email FROM users WHERE user_id = ANY(:ids) "
            "AND email IS NOT NULL AND email <> ''"
        ),
        {"ids": ids},
    ).fetchall()
    return {uid: email for uid, email in rows}


def person_ref(user_id: str | None, labels: dict[str, str]) -> dict | None:
    """``{user_id, label}`` naming a person (their email when on file, else their id), or None for nobody.

    Args:
        user_id: The person, or None.
        labels: ``_user_labels`` for the ids in play.

    Returns:
        dict | None: The reference the payloads carry as ``paid_by`` and similar.
    """
    if not user_id:
        return None
    return {"user_id": user_id, "label": labels.get(user_id) or user_id}


def team_admin_refusal(conn, user: str | None, team_id: str) -> Response | None:
    """Refuse anyone but the team's Owner and Admins, for the team's reports.

    The instance admin gets nothing here: the reports show what members did
    in the team, which only the team's own admins may read.

    Args:
        conn: Open connection.
        user: The caller.
        team_id: The team, from the URL.

    Returns:
        A response to return (401 no caller, 404 not in the team, 403
        ``workspace_role_required`` below Admin), or None to go on.
    """
    if not user:
        return make_response(jsonify({"success": False, "message": "Authentication required"}), 401)
    role = team_role_for(conn, user, team_id)
    if role is None:
        return make_response(jsonify({"success": False, "error": "team_not_found", "message": "Not found"}), 404)
    if not role_at_least(role, "admin"):
        return make_response(
            jsonify(
                {"success": False, "error": "workspace_role_required", "message": "This needs the admin role"}
            ),
            403,
        )
    return None


#: An agent row (aliased ``a``) with some way in from outside switched on (``has_outside_access``).
OUTSIDE_ACCESS_ON_SQL = (
    "(COALESCE(a.key, '') <> '' OR (a.shared AND COALESCE(a.shared_token, '') <> '') "
    "OR COALESCE(a.incoming_webhook_token, '') <> '')"
)


def pays_for(conn, team_id: str, user_ids: list[str]) -> dict[str, dict[str, int]]:
    """What each person pays for on the team's agents.

    Args:
        conn: Open connection.
        team_id: The team.
        user_ids: The people.

    Returns:
        ``{user_id: {"schedules": n, "outside_access": n}}`` for every id:
        the running schedules they set on the team's agents, and the team
        agents with outside access on that they are the payer of.
    """
    ids = sorted({u for u in user_ids if u})
    out = {u: {"schedules": 0, "outside_access": 0} for u in ids}
    if not ids or not looks_like_uuid(str(team_id)):
        return out
    params = {"principal": principal_id(team_id), "ids": ids}
    schedules = conn.execute(
        text(
            "SELECT s.user_id, count(*) FROM schedules s JOIN agents a ON a.id = s.agent_id "
            "WHERE a.user_id = :principal AND s.user_id = ANY(:ids) AND s.status = 'active' GROUP BY s.user_id"
        ),
        params,
    ).fetchall()
    access = conn.execute(
        text(
            "SELECT a.access_payer_id, count(*) FROM agents a WHERE a.user_id = :principal "
            f"AND a.access_payer_id = ANY(:ids) AND {OUTSIDE_ACCESS_ON_SQL} GROUP BY a.access_payer_id"
        ),
        params,
    ).fetchall()
    for user_id, count in schedules:
        out[user_id]["schedules"] = int(count)
    for user_id, count in access:
        out[user_id]["outside_access"] = int(count)
    return out


def _paused_by_change(conn, team_id: str, member: str, before: str | None, after: str | None) -> dict[str, int]:
    """What a membership change pauses of what ``member`` pays for in the team.

    A schedule pauses when its setter drops below the role that manages
    schedules, outside access when its payer drops below the role the team's
    outside policy gives access details to; whatever was paused already (all
    outside access of a locked team) is not counted again.

    Args:
        conn: Open connection.
        team_id: The team.
        member: The person whose membership changed.
        before: Their team role before (API name), or None.
        after: Their team role after, or None when they left.

    Returns:
        ``{"schedules": n, "outside_access": n}``.
    """
    counts = pays_for(conn, team_id, [member])[member]
    policy = team_policy(conn, team_id)
    paused = {}
    for key, action in (("schedules", "manage_schedules"), ("outside_access", "manage_access_details")):
        needed = workspace_minimum("agent", action, policy=policy)
        lost = needed is not None and role_at_least(before, needed) and not role_at_least(after, needed)
        paused[key] = counts[key] if lost else 0
    return paused


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def payer_left_text(member_label: str, team_name: str, new_role: str | None, paused: dict[str, int]) -> str:
    """The notice the team's admins get: who changed, and what of theirs is paused.

    Args:
        member_label: The member, as people read them.
        team_name: The team's name.
        new_role: Their role now, or None when they left.
        paused: ``_paused_by_change`` counts (at least one non-zero).

    Returns:
        One sentence, e.g. "dana@x.io left Operations: 2 schedules and outside
        access on 1 agent are paused until someone takes over."
    """
    if new_role is None:
        lead = f"{member_label} left {team_name}"
    else:
        article = "an" if new_role[:1] in "aeiou" else "a"
        lead = f"{member_label} is now {article} {new_role.capitalize()} in {team_name}"
    parts = []
    if paused["schedules"]:
        parts.append(_plural(paused["schedules"], "schedule"))
    if paused["outside_access"]:
        parts.append(f"outside access on {_plural(paused['outside_access'], 'agent')}")
    verb = "are" if len(parts) > 1 or paused["schedules"] > 1 else "is"
    return f"{lead}: {' and '.join(parts)} {verb} paused until someone takes over."


def _payer_left_notice(
    conn, team_id: str, member: str, before: str | None, after: str | None, actor: str | None
) -> dict | None:
    """Work out, inside the change's transaction, the notice a removal or demotion owes the team's admins.

    Args:
        conn: Open connection, after the change.
        team_id: The team.
        member: Whose membership changed.
        before: Their stored role before.
        after: Their stored role after, or None when they left.
        actor: Who made the change; they saw what it pauses before confirming, so they aren't told again.

    Returns:
        ``{recipients, title, body, url}``, or None when the change pauses nothing, or when working it
        out fails: the notice is best-effort and never fails the change (its reads run in a savepoint).
    """
    new_role = from_stored_role(after) if after else None
    try:
        with conn.begin_nested():
            paused = _paused_by_change(conn, team_id, member, from_stored_role(before), new_role)
            if not any(paused.values()):
                return None
            team = TeamsRepository(conn).get(team_id) or {}
            label = _user_labels(conn, {member}).get(member) or member
            recipients = [u for u in TeamsRepository(conn).admin_ids(team_id) if u != actor and u != member]
    except Exception:
        logger.warning("payer_left notice failed for team=%s", team_id, exc_info=True)
        return None
    team_name = team.get("name") or "the team"
    return {
        "recipients": recipients,
        "title": f"Paused in {team_name}",
        "body": payer_left_text(label, team_name, new_role, paused),
        "url": f"/teams/{team_id}/usage",
    }


def _send_payer_left(notice: dict | None) -> None:
    """Send a ``_payer_left_notice`` after the change committed; never raises."""
    if not notice:
        return
    for recipient in notice["recipients"]:
        notify_user(
            user_id=recipient,
            conversation_id=None,
            kind="payer_left",
            title=notice["title"],
            body=notice["body"],
            url=notice["url"],
        )


def _valid_resource(resource_type, resource_id) -> bool:
    """A known shareable type and a canonical-UUID id (grants are UUID-only)."""
    return (
        is_valid_resource_type(resource_type)
        and bool(resource_id)
        and isinstance(resource_id, str)
        and looks_like_uuid(resource_id)
    )


# Metadata keys naming the user a team event acted on, most specific first.
# Lets ``_audit`` fill ``target_id`` without every call site repeating it.
_TARGET_METADATA_KEYS = ("target_user", "target_user_id", "new_owner")


def _audit(conn, actor: str | None, event: str, **metadata) -> None:
    """Append a team management event to the audit trail (best-effort).

    Runs inside the action's transaction so the audit row commits atomically
    with the change. Never raises into the request path — an audit failure must
    not fail the operation.

    Team events are filed under the acting user. When the action names another
    member (add, role change, removal, ownership transfer) that member becomes
    the row's ``target_id``; otherwise the event has no user target.
    """
    detail = {k: v for k, v in metadata.items() if v is not None}
    target = next(
        (detail[key] for key in _TARGET_METADATA_KEYS if detail.get(key)), None
    )
    try:
        # SAVEPOINT: a failed audit insert poisons the surrounding txn, so
        # nest it — on failure only the audit rolls back, not the action.
        with conn.begin_nested():
            AuthEventsRepository(conn).insert(
                user_id=actor or "unknown",
                event=event,
                ip=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
                metadata=detail,
                actor_id=actor or "unknown",
                target_id=target,
            )
    except Exception:
        logger.warning("team audit insert failed for event=%s", event, exc_info=True)


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return base or "team"


def _unique_slug(repo: TeamsRepository, base: str) -> str:
    """A slug not yet taken: ``base`` if free, else ``base-<4hex>`` until unique."""
    if not repo.slug_exists(base):
        return base
    for _ in range(8):
        candidate = f"{base}-{uuid.uuid4().hex[:4]}"
        if not repo.slug_exists(candidate):
            return candidate
    return f"{base}-{uuid.uuid4().hex}"


# --- Notifications (best-effort, fire-and-forget; never fail the request) ----
# Emitted AFTER the mutation commits, over their own read connection, so a
# name-lookup or Redis hiccup can never roll back the share/membership change.


def _resource_display_name(conn, resource_type: str, resource_id: str) -> str | None:
    """Best-effort human label for a shared resource (ownerless fetch)."""
    try:
        if resource_type == "agent":
            row = AgentsRepository(conn).get_by_id(resource_id)
        elif resource_type == "source":
            row = SourcesRepository(conn).get_by_id(resource_id)
        elif resource_type == "prompt":
            row = PromptsRepository(conn).get_for_rendering(resource_id)
        elif resource_type == "tool":
            row = UserToolsRepository(conn).get_by_id(resource_id)
        else:
            return None
        if not row:
            return None
        return row.get("custom_name") or row.get("display_name") or row.get("name")
    except Exception:
        logger.warning("resource name resolve failed (%s)", resource_type, exc_info=True)
        return None


def _notify_member_added(
    team_id: str, new_user: str | None, role: str, actor: str | None
) -> None:
    """Toast the new member that they were added to a team.

    ``role`` is the stored role; the event carries ``role`` in the API names
    and ``member_role`` in today's.
    """
    if not new_user or new_user == actor:
        return
    try:
        with db_readonly() as conn:
            team = TeamsRepository(conn).get(team_id)
        publish_user_event(
            new_user,
            "team.member_added",
            {
                "team_id": str(team_id),
                "team_name": team.get("name") if team else None,
                "role": from_stored_role(role),
                "member_role": legacy_member_role(from_stored_role(role)),
                "added_by": actor,
            },
            scope={"kind": "team", "id": str(team_id)},
        )
    except Exception:
        logger.warning("member_added notify failed", exc_info=True)


def _notify_resource_shared(
    actor: str | None,
    team_id: str,
    resource_type: str,
    resource_id: str,
    access_level: str,
    target_user_id: str | None,
) -> None:
    """Toast the recipient(s) of a share.

    Per-member share notifies just that member; whole-team share notifies every
    current member except the sharer.
    """
    try:
        with db_readonly() as conn:
            resource_name = _resource_display_name(conn, resource_type, resource_id)
            team = TeamsRepository(conn).get(team_id)
            if target_user_id:
                recipients = [target_user_id]
            else:
                members = TeamMembersRepository(conn).list_members(team_id)
                recipients = list({m["user_id"] for m in members})
        payload = {
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "resource_name": resource_name,
            "access_level": access_level,
            "team_id": str(team_id),
            "team_name": team.get("name") if team else None,
            "shared_by": actor,
        }
        for recipient in recipients:
            if recipient and recipient != actor:
                publish_user_event(
                    recipient,
                    "resource.shared",
                    payload,
                    scope={"kind": "resource", "id": str(resource_id)},
                )
    except Exception:
        logger.warning("resource_shared notify failed", exc_info=True)


@teams_ns.route("/teams")
class Teams(Resource):
    def get(self):
        """List the teams the caller belongs to, each annotated with their role."""
        user = _current_user()
        if not user:
            return {"success": False}, 401
        try:
            with db_readonly() as conn:
                teams = TeamsRepository(conn).list_for_user(user)
                roles = TeamMembersRepository(conn).roles_by_team(user)
            teams = [_team_payload(t, user, roles.get(str(t["id"]))) for t in teams]
            return make_response(jsonify({"success": True, "teams": teams}), 200)
        except Exception as err:
            logger.error("List teams failed: %s", err, exc_info=True)
            return {"success": False}, 400

    def post(self):
        """Create a team (self-serve). The creator becomes its first team_admin."""
        user = _current_user()
        if not user:
            return {"success": False}, 401
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return {"success": False, "message": "name required"}, 400
        description = data.get("description")
        try:
            with db_session() as conn:
                teams = TeamsRepository(conn)
                slug = _unique_slug(teams, _slugify(name))
                team = teams.create(name, slug, owner_id=user, description=description)
                TeamMembersRepository(conn).add_member(
                    team["id"], user, role=ROLE_TEAM_ADMIN, source="manual", granted_by=user
                )
                _audit(conn, user, "team.create", team_id=team["id"], name=name)
            _team_payload(team, user, ROLE_TEAM_ADMIN)
            return make_response(jsonify({"success": True, "team": team}), 201)
        except Exception as err:
            logger.error("Create team failed: %s", err, exc_info=True)
            return {"success": False}, 400


@teams_ns.route("/teams/<string:team_id>")
class Team(Resource):
    @team_member_required
    def get(self, team_id):
        """Team detail with members and the caller's role. Requires membership."""
        user = _current_user()
        try:
            with db_readonly() as conn:
                team = TeamsRepository(conn).get(team_id)
                if not team:
                    return {"success": False, "message": "Not found"}, 404
                members = TeamMembersRepository(conn)
                team["members"] = _member_rows(members.list_members(team_id), team.get("owner_id"))
                stored_role = members.role_for(user, team_id)
            _team_payload(team, user, stored_role)
            return make_response(jsonify({"success": True, "team": team}), 200)
        except Exception as err:
            logger.error("Get team failed: %s", err, exc_info=True)
            return {"success": False}, 400

    @team_admin_required
    def put(self, team_id):
        """Update team name/description. Requires team_admin."""
        data = request.get_json(silent=True) or {}
        fields = {k: data[k] for k in ("name", "description") if k in data}
        if not fields:
            return {"success": False, "message": "nothing to update"}, 400
        try:
            with db_session() as conn:
                updated = TeamsRepository(conn).update(team_id, fields)
            return make_response(jsonify({"success": bool(updated)}), 200)
        except Exception as err:
            logger.error("Update team failed: %s", err, exc_info=True)
            return {"success": False}, 400

    def delete(self, team_id):
        """Delete the team. Owner-only (a global admin overrides)."""
        user = _current_user()
        if not user:
            return {"success": False}, 401
        try:
            with db_session() as conn:
                team = TeamsRepository(conn).get(team_id)
                if not team:
                    return {"success": False, "message": "Not found"}, 404
                token = getattr(request, "decoded_token", None)
                if team["owner_id"] != user and not has_role(token, ROLE_ADMIN):
                    return {"success": False, "message": "Only the team owner can delete"}, 403
                try:
                    TeamsRepository(conn).delete(team_id)
                except TeamNotEmpty as not_empty:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "team_not_empty",
                                "message": "Move or delete the team's items before deleting the team",
                                "counts": not_empty.counts,
                            }
                        ),
                        409,
                    )
                _audit(conn, user, "team.delete", team_id=team_id)
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            logger.error("Delete team failed: %s", err, exc_info=True)
            return {"success": False}, 400


@teams_ns.route("/teams/<string:team_id>/members")
class TeamMembers(Resource):
    @team_member_required
    def get(self, team_id):
        """List members. Requires membership.

        Optional query args: ``q`` (case-insensitive substring over email and
        user id), ``page`` (1-based) and ``page_size`` (1..100; paginates only
        when given). ``total`` is the row count after the ``q`` filter.

        For the team's Owner and Admins each row also has ``pays_for``
        (``{schedules, outside_access}``): the running schedules the member set
        on the team's agents and the team agents whose outside access they pay
        for, which pause when they leave or lose the role.
        """
        q, limit, offset = _members_query()
        try:
            with db_readonly() as conn:
                repo = TeamMembersRepository(conn)
                team = TeamsRepository(conn).get(team_id)
                members = _member_rows(
                    repo.list_members(team_id, q=q, limit=limit, offset=offset), (team or {}).get("owner_id")
                )
                total = repo.count_members(team_id, q=q)
                if role_at_least(team_role_for(conn, _current_user(), team_id), "admin"):
                    counts = pays_for(conn, team_id, [m.get("user_id") for m in members])
                    for member in members:
                        member["pays_for"] = counts.get(member.get("user_id"), {"schedules": 0, "outside_access": 0})
            return make_response(
                jsonify({"success": True, "members": members, "total": total}), 200
            )
        except Exception as err:
            logger.error("List members failed: %s", err, exc_info=True)
            return {"success": False}, 400

    @team_admin_required
    def post(self, team_id):
        """Add a member by email (preferred) or raw user_id. Requires an Admin or the Owner.

        Body: ``email`` or ``user_id``, and ``role``: ``viewer`` (the default),
        ``editor`` or ``admin`` (``team_member`` / ``team_admin`` still work).
        The member must be a person who has signed in: anyone else, a team
        principal included, is 404. Re-adding an existing member sets their
        role, under the same owner and last-admin guard as the role change.
        """
        data = request.get_json(silent=True) or {}
        new_user = (data.get("user_id") or "").strip()
        email = (data.get("email") or "").strip()
        role = _requested_role(data, "viewer")
        if role is None:
            return {"success": False, "message": "invalid role"}, 400
        if not new_user and not email:
            return {"success": False, "message": "email or user_id required"}, 400
        not_found = {
            "success": False,
            "message": "No user found with that email (they must sign in once first)",
        }
        actor = _current_user()
        notice = None
        try:
            with db_session() as conn:
                # Resolve an email to its sub (the user must have logged in at
                # least once for their email to be on file).
                if not new_user and email:
                    user_row = UsersRepository(conn).find_by_email(email)
                    if not user_row:
                        return not_found, 404
                    new_user = user_row["user_id"]
                if is_principal_id(new_user):
                    return not_found, 404
                members = TeamMembersRepository(conn)
                before = members.role_for(new_user, team_id)
                # Re-adding an existing member is a role change: same guard.
                try:
                    members.change_membership(team_id, new_user, role, actor=actor)
                except MembershipChangeRefused as refused:
                    if refused.reason == MembershipChangeRefused.NOT_A_PERSON:
                        return not_found, 404
                    return _refusal(refused)
                if before is None:
                    _audit(
                        conn,
                        actor,
                        "team.member_add",
                        team_id=team_id,
                        target_user=new_user,
                        role=from_stored_role(role),
                    )
                elif before != role:
                    _audit_role_change(conn, actor, team_id, new_user, before, role)
                    notice = _payer_left_notice(conn, team_id, new_user, before, role, actor)
            # Post-commit, best-effort: tell the new member they were added.
            if before is None:
                _notify_member_added(team_id, new_user, role, actor)
            _send_payer_left(notice)
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            logger.error("Add member failed: %s", err, exc_info=True)
            return {"success": False}, 400


def _audit_role_change(conn, actor: str | None, team_id: str, member: str, before: str | None, after: str) -> None:
    """Record ``team.member_role_changed`` with the old and new roles (API names)."""
    _audit(
        conn,
        actor,
        "team.member_role_changed",
        team_id=team_id,
        target_user=member,
        from_role=from_stored_role(before),
        role=from_stored_role(after),
    )


@teams_ns.route("/teams/<string:team_id>/members/<string:member_id>")
class TeamMember(Resource):
    @team_admin_required
    def put(self, team_id, member_id):
        """Change a member's role. Requires an Admin or the Owner.

        Body: ``role``: ``viewer``, ``editor`` or ``admin`` (``team_member`` /
        ``team_admin`` still work). ``owner`` is 400: only the ownership
        transfer changes the Owner. The owner can't be demoted and the last
        admin can't step down (``change_membership``).
        """
        data = request.get_json(silent=True) or {}
        role = _requested_role(data, None)
        if role is None:
            return {"success": False, "message": "invalid role"}, 400
        actor = _current_user()
        notice = None
        try:
            with db_session() as conn:
                members = TeamMembersRepository(conn)
                before = members.role_for(member_id, team_id)
                if before is None:
                    # A role change is for members; adding someone is the add route's job.
                    return {"success": False, "message": "Not a member"}, 404
                try:
                    members.change_membership(team_id, member_id, role, actor=actor)
                except MembershipChangeRefused as refused:
                    return _refusal(refused)
                if before != role:
                    _audit_role_change(conn, actor, team_id, member_id, before, role)
                    notice = _payer_left_notice(conn, team_id, member_id, before, role, actor)
            _send_payer_left(notice)
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            logger.error("Update member role failed: %s", err, exc_info=True)
            return {"success": False}, 400

    @team_member_required
    def delete(self, team_id, member_id):
        """Remove a member. team_admin removes anyone; a member may remove self
        (leave). Guards the last admin."""
        user = _current_user()
        token = getattr(request, "decoded_token", None)
        is_self = member_id == user
        if not is_self and not has_team_role(token, team_id, ROLE_TEAM_ADMIN):
            return {"success": False, "message": "Forbidden"}, 403
        try:
            with db_session() as conn:
                members = TeamMembersRepository(conn)
                before = members.role_for(member_id, team_id)
                try:
                    members.change_membership(team_id, member_id, None, actor=user)
                except MembershipChangeRefused as refused:
                    return _refusal(refused)
                _audit(
                    conn,
                    user,
                    "team.member_remove",
                    team_id=team_id,
                    target_user=member_id,
                    self_leave=is_self,
                )
                notice = _payer_left_notice(conn, team_id, member_id, before, None, user) if before else None
            _send_payer_left(notice)
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            logger.error("Remove member failed: %s", err, exc_info=True)
            return {"success": False}, 400


@teams_ns.route("/teams/<string:team_id>/grants")
class TeamGrants(Resource):
    @team_member_required
    def get(self, team_id):
        """List resources shared with this team. Requires membership.

        Each row carries the resource's name, owner and people labels (email
        when on file, else null), ``caller`` — the caller's own live access
        fields on that resource (null if none) — and ``origin``
        (``personal_shared``: grants are only ever on members' personal
        items). A Viewer or Editor sees whole-team grants and grants aimed at
        them; an Admin, the Owner, or someone with ``share`` on the resource,
        sees every grant. ``paused_reason`` is ``owner_left`` on a grant whose
        item's owner is no longer in the team (it gives no access until they
        are re-added), else null. The envelope gives the caller's ``role``
        (``owner|admin|editor|viewer``) and ``team_role`` in today's names.
        """
        user = _current_user()
        token = getattr(request, "decoded_token", None)
        resource_type = request.args.get("resource_type")
        try:
            with db_readonly() as conn:
                grants = TeamResourceGrantsRepository(conn).list_for_team(
                    team_id, resource_type
                )
                role = team_role_for(conn, user, team_id)
                sees_all = role in ("owner", "admin") or has_role(token, ROLE_ADMIN)
                rows = _resource_rows(conn, grants)
                access = _caller_access(conn, user, grants, rows)
                visible = []
                for g in grants:
                    key = (g["resource_type"], str(g["resource_id"]))
                    ra = access.get(key)
                    target = g.get("target_user_id")
                    if not (sees_all or not target or target == user or (ra and ra.can("share"))):
                        continue
                    row = rows.get(key) or {}
                    g["resource_name"] = row.get("name")
                    g["owner_id"] = row.get("user_id") or g.get("owner_id")
                    g["caller"] = ra.payload() if ra else None
                    # Every grant is on a member's personal item ("Personal, shared by members").
                    g["origin"] = "personal_shared"
                    visible.append(g)
                present = _members_among(conn, team_id, {g.get("owner_id") for g in visible})
                for g in visible:
                    g["paused_reason"] = _paused_reason(g.get("owner_id"), present)
                labels = _user_labels(
                    conn,
                    {
                        u
                        for g in visible
                        for u in (g.get("owner_id"), g.get("target_user_id"), g.get("granted_by"))
                        if u
                    },
                )
            for g in visible:
                g["owner_label"] = labels.get(g.get("owner_id"))
                g["target_user_label"] = labels.get(g.get("target_user_id"))
                g["granted_by_label"] = labels.get(g.get("granted_by"))
            return make_response(
                jsonify(
                    {
                        "success": True,
                        "grants": visible,
                        "role": role,
                        "team_role": legacy_member_role(role),
                    }
                ),
                200,
            )
        except Exception as err:
            logger.error("List grants failed: %s", err, exc_info=True)
            return {"success": False}, 400

    @team_member_required
    def post(self, team_id):
        """Share a resource with this team, or change an existing grant's level.

        Needs ``share`` on the resource (the owner, or an editor when the owner
        turned on ``editors_can_share``) and membership of the team. The grant
        records the real owner as ``owner_id`` and the caller as ``granted_by``.
        """
        user = _current_user()
        data = request.get_json(silent=True) or {}
        resource_type = data.get("resource_type")
        resource_id = data.get("resource_id")
        access_level = data.get("access_level", "viewer")
        # None → share with the whole team; a sub → share with that one member.
        target_user_id = (data.get("target_user_id") or "").strip() or None
        if not _valid_resource(resource_type, resource_id):
            return {"success": False, "message": "invalid resource"}, 400
        if access_level not in _VALID_ACCESS_LEVELS:
            return {"success": False, "message": "invalid access_level"}, 400
        try:
            with db_session() as conn:
                # ``require`` dispatches by resource_type, so a mismatched
                # type/id can't register a bogus grant (the table has no FK).
                try:
                    ra = require(conn, resource_type, resource_id, user, "share")
                except AccessDenied as denied:
                    # A team's own item has no ``share``: its members reach it by their
                    # team role and it has no per-item people. Said only to someone
                    # who can see it (a 403, never a 404).
                    if denied.status == 403 and is_principal_id(resource_owner(conn, resource_type, resource_id)):
                        return make_response(
                            jsonify(
                                {
                                    "success": False,
                                    "error": "team_item",
                                    "message": "This item belongs to a team and can't be shared item by item",
                                }
                            ),
                            409,
                        )
                    return _denied(denied)
                # A per-member share target must actually be a member of the team.
                if target_user_id and not TeamMembersRepository(conn).is_member(
                    target_user_id, team_id
                ):
                    return {"success": False, "message": "Target is not a team member"}, 400
                grant = TeamResourceGrantsRepository(conn).grant(
                    team_id,
                    resource_type,
                    ra.resource_id,
                    owner_id=ra.owner_id,
                    granted_by=user,
                    access_level=access_level,
                    target_user_id=target_user_id,
                )
                _audit(
                    conn,
                    user,
                    "team.share",
                    team_id=team_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    access_level=access_level,
                    target_user_id=target_user_id,
                )
            # Post-commit, best-effort: tell the recipient(s) it was shared.
            _notify_resource_shared(
                user, team_id, resource_type, resource_id, access_level, target_user_id
            )
            return make_response(jsonify({"success": True, "grant": grant}), 201)
        except Exception as err:
            logger.error("Share resource failed: %s", err, exc_info=True)
            return {"success": False}, 400

    def delete(self, team_id):
        """Unshare a resource from this team.

        Allowed with ``share`` on the resource — no membership needed, so an
        owner who left the team can still pull their resource back — or for a
        team_admin of this team. ``target_user_id`` picks one member's grant
        (absent → the whole-team grant). Identifiers come from query params
        (some proxies strip DELETE bodies), with a JSON-body fallback.
        """
        user = _current_user()
        token = getattr(request, "decoded_token", None)
        if not user:
            return make_response(
                jsonify({"success": False, "message": "Authentication required"}), 401
            )
        data = request.get_json(silent=True) or {}
        resource_type = request.args.get("resource_type") or data.get("resource_type")
        resource_id = request.args.get("resource_id") or data.get("resource_id")
        # Which grant to remove: whole-team (None) or a specific member's.
        target_user_id = (
            request.args.get("target_user_id") or data.get("target_user_id") or ""
        ).strip() or None
        if not _valid_resource(resource_type, resource_id):
            return {"success": False, "message": "invalid resource"}, 400
        try:
            with db_session() as conn:
                try:
                    require(conn, resource_type, resource_id, user, "share")
                except AccessDenied:
                    if not has_team_role(token, team_id, ROLE_TEAM_ADMIN):
                        return {"success": False, "message": "Forbidden"}, 403
                revoked = TeamResourceGrantsRepository(conn).revoke(
                    team_id, resource_type, resource_id, target_user_id=target_user_id
                )
                if revoked:
                    _audit(
                        conn,
                        user,
                        "team.unshare",
                        team_id=team_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        target_user_id=target_user_id,
                    )
            return make_response(jsonify({"success": bool(revoked)}), 200)
        except Exception as err:
            logger.error("Unshare resource failed: %s", err, exc_info=True)
            return {"success": False}, 400


@teams_ns.route("/teams/<string:team_id>/transfer_owner")
class TeamOwnerTransfer(Resource):
    def post(self, team_id):
        """Transfer team ownership. Owner-only (global admin overrides).

        The new owner must already be a member; they are promoted to team_admin.
        """
        user = _current_user()
        if not user:
            return {"success": False}, 401
        data = request.get_json(silent=True) or {}
        new_owner = (data.get("user_id") or "").strip()
        if not new_owner:
            return {"success": False, "message": "user_id required"}, 400
        token = getattr(request, "decoded_token", None)
        try:
            with db_session() as conn:
                teams = TeamsRepository(conn)
                team = teams.get(team_id)
                if not team:
                    return {"success": False, "message": "Not found"}, 404
                if team["owner_id"] != user and not has_role(token, ROLE_ADMIN):
                    return {"success": False, "message": "Only the team owner can transfer"}, 403
                members = TeamMembersRepository(conn)
                if not members.is_member(new_owner, team_id):
                    return {"success": False, "message": "New owner must be a member"}, 400
                members.set_manual_role(team_id, new_owner, ROLE_TEAM_ADMIN, granted_by=user)
                teams.reassign_owner(team_id, new_owner)
                _audit(
                    conn,
                    user,
                    "team.transfer_owner",
                    team_id=team_id,
                    new_owner=new_owner,
                )
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            logger.error("Transfer owner failed: %s", err, exc_info=True)
            return {"success": False}, 400


@teams_ns.route("/resource_shares")
class ResourceShares(Resource):
    def get(self):
        """List the teams a resource is shared with. Needs ``share`` on it.

        Powers the share dialog (current shares + unshare), so only someone who
        may change the sharing can enumerate it: 404 when the resource isn't
        visible, 403 when the caller's role can't share. A team's own item has
        no shares: any member gets where its access comes from instead
        (:func:`_team_item_shares`).
        """
        user = _current_user()
        if not user:
            return {"success": False}, 401
        resource_type = request.args.get("resource_type")
        resource_id = request.args.get("resource_id")
        if not _valid_resource(resource_type, resource_id):
            return {"success": False, "message": "invalid resource"}, 400
        try:
            with db_readonly() as conn:
                ra = resolve(conn, resource_type, resource_id, user)
                if ra is not None and ra.is_team_item:
                    return make_response(jsonify(_team_item_shares(conn, ra, user)), 200)
                try:
                    require(conn, resource_type, resource_id, user, "share")
                except AccessDenied as denied:
                    return _denied(denied)
                shares = TeamResourceGrantsRepository(conn).list_for_resource(
                    resource_type, resource_id
                )
            return make_response(jsonify({"success": True, "shares": shares}), 200)
        except Exception as err:
            logger.error("List resource shares failed: %s", err, exc_info=True)
            return {"success": False}, 400


def _team_item_shares(conn, ra: ResourceAccess, user: str) -> dict:
    """The share dialog of a team's item: the workspace, its size and the agent's outside access.

    Args:
        conn: Open connection.
        ra: The caller's access to the item (a team item).
        user: The caller.

    Returns:
        dict: ``success``, ``shares`` (always empty), ``workspace`` (``{kind, team_id, name}``),
        ``members_count``, and for an agent ``outside_access``, the agent payload's own block
        (``outside_access_state``: ``{api_key, public_link, webhook, paid_by, paused_for,
        can_take_over}``), so the dialog and the agent page never disagree. Every member reads
        what is on; only those who manage it read who pays and why it is paused.
    """
    # Imported here: the agents package pulls in most of the API, which would
    # make importing the teams routes order-dependent.
    from docsgpt.api.user.agents import sharing as agent_sharing

    team = TeamsRepository(conn).get(ra.team_id) or {}
    members_count = conn.execute(
        text("SELECT count(DISTINCT user_id) FROM team_members WHERE team_id = CAST(:t AS uuid)"),
        {"t": ra.team_id},
    ).scalar()
    body = {
        # First, so the named ``workspace`` below replaces the payload's unnamed one.
        **ra.payload(),
        "success": True,
        "shares": [],
        "workspace": {"kind": "team", "team_id": ra.team_id, "name": team.get("name")},
        "members_count": int(members_count or 0),
    }
    if ra.resource_type == "agent":
        agent = AgentsRepository(conn).get_by_id(ra.resource_id) or {}
        body["outside_access"] = agent_sharing.outside_access_state(conn, agent, ra, user)
    return body


def _settings_response(ra: ResourceAccess):
    """The ``resource_settings`` body: switches plus the caller's access."""
    return make_response(
        jsonify(
            {
                "success": True,
                "resource_type": ra.resource_type,
                "resource_id": ra.resource_id,
                "settings": public_settings(ra.resource_type, ra.settings),
                **ra.payload(),
            }
        ),
        200,
    )


@teams_ns.route("/resource_settings")
class ResourceSettings(Resource):
    def get(self):
        """A resource's sharing switches. Anyone with access may read them.

        Query: ``resource_type``, ``resource_id``. Returns ``settings`` as
        ``[{key, value, default}]`` in display order, plus the caller's
        ``access`` and ``allowed_actions``.
        """
        user = _current_user()
        if not user:
            return {"success": False}, 401
        resource_type = request.args.get("resource_type")
        resource_id = request.args.get("resource_id")
        if resource_type not in RESOURCE_TYPES or not resource_id:
            return {"success": False, "message": "invalid resource"}, 400
        try:
            with db_readonly() as conn:
                try:
                    ra = require(conn, resource_type, resource_id, user, "use")
                except AccessDenied as denied:
                    return _denied(denied)
            return _settings_response(ra)
        except Exception as err:
            logger.error("Get resource settings failed: %s", err, exc_info=True)
            return {"success": False}, 400

    def put(self):
        """Change a resource's sharing switches. Needs ``manage_settings`` (owner).

        Body: ``{"resource_type", "resource_id", "settings": {key: bool}}``.
        An unknown key or a non-boolean value is a 400. Returns the GET shape.
        """
        user = _current_user()
        if not user:
            return {"success": False}, 401
        data = request.get_json(silent=True) or {}
        resource_type = data.get("resource_type")
        resource_id = data.get("resource_id")
        changes = data.get("settings")
        if resource_type not in RESOURCE_TYPES or not resource_id or not isinstance(resource_id, str):
            return {"success": False, "message": "invalid resource"}, 400
        if not isinstance(changes, dict):
            return {"success": False, "message": "settings must be an object"}, 400
        try:
            with db_session() as conn:
                try:
                    ra = require(conn, resource_type, resource_id, user, "manage_settings")
                except AccessDenied as denied:
                    return _denied(denied)
                try:
                    merged = set_settings(conn, resource_type, ra.resource_id, changes, user)
                except ValueError as bad:
                    return {"success": False, "message": str(bad)}, 400
                updated = build(resource_type, ra.resource_id, ra.access, ra.owner_id, merged)
            return _settings_response(updated)
        except Exception as err:
            logger.error("Update resource settings failed: %s", err, exc_info=True)
            return {"success": False}, 400


@teams_ns.route("/admin/teams")
class AllTeams(Resource):
    method_decorators = []

    def get(self):
        """Global-admin oversight: every team with member counts, or a picker search.

        With no query args every team is returned. Any of these switches to a
        bounded search (same row shape):
            q: Case-insensitive substring of the team name or slug.
            without_quota: ``1`` keeps only teams with no team ``all``-bucket
                quota policy.
            limit: The most rows to return, clamped to 1-100 (default 20).
        """
        token = getattr(request, "decoded_token", None)
        if not token:
            return {"success": False}, 401
        if not has_role(token, ROLE_ADMIN):
            return {"success": False, "message": "Forbidden"}, 403
        args = request.args
        searching = any(key in args for key in ("q", "without_quota", "limit"))
        try:
            limit = int(args.get("limit", _TEAM_SEARCH_LIMIT))
        except (TypeError, ValueError):
            limit = _TEAM_SEARCH_LIMIT
        limit = min(max(limit, 1), _TEAM_SEARCH_MAX)
        try:
            with db_readonly() as conn:
                repo = TeamsRepository(conn)
                if searching:
                    teams = repo.search(
                        q=args.get("q"),
                        without_quota=args.get("without_quota", "").lower() in ("1", "true"),
                        limit=limit,
                    )
                else:
                    teams = repo.list_all()
            return make_response(jsonify({"success": True, "teams": teams}), 200)
        except Exception as err:
            logger.error("List all teams failed: %s", err, exc_info=True)
            return {"success": False}, 400
