"""Team management API: CRUD, membership, and resource-sharing grants.

Authorization model (two planes, see ``team_authz.py``):
- Any authenticated user may create a team (self-serve); the creator becomes a
  ``team_admin`` in the same transaction.
- Team detail / member list / grant list require team membership.
- Member management and team edit require ``team_admin``.
- Team deletion and owner transfer are owner-only (a global ``admin`` overrides).
- Sharing a resource requires the caller to OWN it (dispatched by resource_type)
  and be a member of the target team. Sharing is additive visibility — the
  resource's owner is never changed.

``team_id`` always comes from the URL path (never the body) — enforced by
``require_team_role`` and by reading ``team_id`` as a route kwarg here.
"""

from __future__ import annotations

import logging
import re
import uuid

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from application.api.user.authz import ROLE_ADMIN, has_role
from application.api.user.team_authz import (
    has_team_role,
    team_admin_required,
    team_member_required,
)
from application.api.user.team_sharing import is_valid_resource_type, owns_resource
from application.events.publisher import publish_user_event
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.auth_events import AuthEventsRepository
from application.storage.db.repositories.prompts import PromptsRepository
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.team_members import (
    ROLE_TEAM_ADMIN,
    ROLE_TEAM_MEMBER,
    TeamMembersRepository,
)
from application.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from application.storage.db.repositories.teams import TeamsRepository
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

teams_ns = Namespace("teams", description="Team management and resource sharing", path="/api")

_VALID_TEAM_ROLES = (ROLE_TEAM_ADMIN, ROLE_TEAM_MEMBER)
_VALID_ACCESS_LEVELS = ("viewer", "editor")


def _current_user() -> str | None:
    token = getattr(request, "decoded_token", None)
    return token.get("sub") if isinstance(token, dict) else None


def _audit(conn, actor: str | None, event: str, **metadata) -> None:
    """Append a team management event to the audit trail (best-effort).

    Runs inside the action's transaction so the audit row commits atomically
    with the change. Never raises into the request path — an audit failure must
    not fail the operation.
    """
    try:
        # SAVEPOINT: a failed audit insert poisons the surrounding txn, so
        # nest it — on failure only the audit rolls back, not the action.
        with conn.begin_nested():
            AuthEventsRepository(conn).insert(
                user_id=actor or "unknown",
                event=event,
                ip=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
                metadata={k: v for k, v in metadata.items() if v is not None},
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
    """Toast the new member that they were added to a team."""
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
                "role": role,
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
            team["member_role"] = ROLE_TEAM_ADMIN
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
                team["members"] = members.list_members(team_id)
                team["member_role"] = members.role_for(user, team_id)
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
                TeamsRepository(conn).delete(team_id)
                _audit(conn, user, "team.delete", team_id=team_id)
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            logger.error("Delete team failed: %s", err, exc_info=True)
            return {"success": False}, 400


@teams_ns.route("/teams/<string:team_id>/members")
class TeamMembers(Resource):
    @team_member_required
    def get(self, team_id):
        """List members. Requires membership."""
        try:
            with db_readonly() as conn:
                members = TeamMembersRepository(conn).list_members(team_id)
            return make_response(jsonify({"success": True, "members": members}), 200)
        except Exception as err:
            logger.error("List members failed: %s", err, exc_info=True)
            return {"success": False}, 400

    @team_admin_required
    def post(self, team_id):
        """Add a member by email (preferred) or raw user_id. Requires team_admin."""
        data = request.get_json(silent=True) or {}
        new_user = (data.get("user_id") or "").strip()
        email = (data.get("email") or "").strip()
        role = data.get("role", ROLE_TEAM_MEMBER)
        if role not in _VALID_TEAM_ROLES:
            return {"success": False, "message": "invalid role"}, 400
        if not new_user and not email:
            return {"success": False, "message": "email or user_id required"}, 400
        try:
            with db_session() as conn:
                # Resolve an email to its sub (the user must have logged in at
                # least once for their email to be on file).
                if not new_user and email:
                    user_row = UsersRepository(conn).find_by_email(email)
                    if not user_row:
                        return {
                            "success": False,
                            "message": "No user found with that email (they must sign in once first)",
                        }, 404
                    new_user = user_row["user_id"]
                TeamMembersRepository(conn).set_manual_role(
                    team_id, new_user, role, granted_by=_current_user()
                )
                _audit(
                    conn,
                    _current_user(),
                    "team.member_add",
                    team_id=team_id,
                    target_user=new_user,
                    role=role,
                )
            # Post-commit, best-effort: tell the new member they were added.
            _notify_member_added(team_id, new_user, role, _current_user())
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            logger.error("Add member failed: %s", err, exc_info=True)
            return {"success": False}, 400


@teams_ns.route("/teams/<string:team_id>/members/<string:member_id>")
class TeamMember(Resource):
    @team_admin_required
    def put(self, team_id, member_id):
        """Change a member's role. Requires team_admin. Guards the last admin."""
        data = request.get_json(silent=True) or {}
        role = data.get("role")
        if role not in _VALID_TEAM_ROLES:
            return {"success": False, "message": "invalid role"}, 400
        try:
            with db_session() as conn:
                members = TeamMembersRepository(conn)
                if role == ROLE_TEAM_MEMBER and self._would_orphan_admins(
                    members, team_id, member_id
                ):
                    return {
                        "success": False,
                        "message": "Cannot demote the last team admin",
                    }, 409
                members.set_manual_role(team_id, member_id, role, granted_by=_current_user())
                _audit(
                    conn,
                    _current_user(),
                    "team.member_role",
                    team_id=team_id,
                    target_user=member_id,
                    role=role,
                )
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
                if self._would_orphan_admins(members, team_id, member_id):
                    return {
                        "success": False,
                        "message": "Cannot remove the last team admin",
                    }, 409
                members.remove_member(team_id, member_id)
                _audit(
                    conn,
                    user,
                    "team.member_remove",
                    team_id=team_id,
                    target_user=member_id,
                    self_leave=is_self,
                )
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            logger.error("Remove member failed: %s", err, exc_info=True)
            return {"success": False}, 400

    @staticmethod
    def _would_orphan_admins(
        members: TeamMembersRepository, team_id: str, member_id: str
    ) -> bool:
        """True if removing/demoting ``member_id`` leaves the team with no admin.

        Locks the admin rows (FOR UPDATE) so concurrent demote/remove calls
        serialize — preventing two simultaneous removals of distinct admins from
        both passing the guard and orphaning the team.
        """
        admins = members.lock_admins(team_id)
        if member_id not in admins:
            return False
        return len(admins) <= 1


@teams_ns.route("/teams/<string:team_id>/grants")
class TeamGrants(Resource):
    @team_member_required
    def get(self, team_id):
        """List resources shared with this team. Requires membership."""
        resource_type = request.args.get("resource_type")
        try:
            with db_readonly() as conn:
                grants = TeamResourceGrantsRepository(conn).list_for_team(
                    team_id, resource_type
                )
            return make_response(jsonify({"success": True, "grants": grants}), 200)
        except Exception as err:
            logger.error("List grants failed: %s", err, exc_info=True)
            return {"success": False}, 400

    @team_member_required
    def post(self, team_id):
        """Share a resource the caller OWNS with this team (additive visibility)."""
        user = _current_user()
        data = request.get_json(silent=True) or {}
        resource_type = data.get("resource_type")
        resource_id = data.get("resource_id")
        access_level = data.get("access_level", "viewer")
        # None → share with the whole team; a sub → share with that one member.
        target_user_id = (data.get("target_user_id") or "").strip() or None
        if (
            not is_valid_resource_type(resource_type)
            or not resource_id
            or not looks_like_uuid(resource_id)
        ):
            return {"success": False, "message": "invalid resource"}, 400
        if access_level not in _VALID_ACCESS_LEVELS:
            return {"success": False, "message": "invalid access_level"}, 400
        try:
            with db_session() as conn:
                # Ownership is the security boundary: dispatch by resource_type so
                # a mismatched type/id can't register a bogus grant.
                if not owns_resource(conn, resource_type, resource_id, user):
                    return {"success": False, "message": "Not the resource owner"}, 403
                # A per-member share target must actually be a member of the team.
                if target_user_id and not TeamMembersRepository(conn).is_member(
                    target_user_id, team_id
                ):
                    return {"success": False, "message": "Target is not a team member"}, 400
                grant = TeamResourceGrantsRepository(conn).grant(
                    team_id,
                    resource_type,
                    resource_id,
                    owner_id=user,
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

    @team_member_required
    def delete(self, team_id):
        """Unshare a resource. Allowed for the resource owner or a team_admin.

        Identifiers come from query params (some proxies strip DELETE bodies),
        with a JSON-body fallback for older clients.
        """
        user = _current_user()
        token = getattr(request, "decoded_token", None)
        data = request.get_json(silent=True) or {}
        resource_type = request.args.get("resource_type") or data.get("resource_type")
        resource_id = request.args.get("resource_id") or data.get("resource_id")
        # Which grant to remove: whole-team (None) or a specific member's.
        target_user_id = (
            request.args.get("target_user_id") or data.get("target_user_id") or ""
        ).strip() or None
        if (
            not is_valid_resource_type(resource_type)
            or not resource_id
            or not looks_like_uuid(resource_id)
        ):
            return {"success": False, "message": "invalid resource"}, 400
        try:
            with db_session() as conn:
                is_owner = owns_resource(conn, resource_type, resource_id, user)
                if not is_owner and not has_team_role(token, team_id, ROLE_TEAM_ADMIN):
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
        """List the teams a resource the caller OWNS is shared with.

        Powers the share dialog (show current shares + unshare). Owner-only so a
        non-owner can't enumerate a resource's sharing graph.
        """
        user = _current_user()
        if not user:
            return {"success": False}, 401
        resource_type = request.args.get("resource_type")
        resource_id = request.args.get("resource_id")
        if (
            not is_valid_resource_type(resource_type)
            or not resource_id
            or not looks_like_uuid(resource_id)
        ):
            return {"success": False, "message": "invalid resource"}, 400
        try:
            with db_readonly() as conn:
                if not owns_resource(conn, resource_type, resource_id, user):
                    return {"success": False, "message": "Not the resource owner"}, 403
                shares = TeamResourceGrantsRepository(conn).list_for_resource(
                    resource_type, resource_id
                )
            return make_response(jsonify({"success": True, "shares": shares}), 200)
        except Exception as err:
            logger.error("List resource shares failed: %s", err, exc_info=True)
            return {"success": False}, 400


@teams_ns.route("/admin/teams")
class AllTeams(Resource):
    method_decorators = []

    def get(self):
        """Global-admin oversight: every team with member counts."""
        token = getattr(request, "decoded_token", None)
        if not token:
            return {"success": False}, 401
        if not has_role(token, ROLE_ADMIN):
            return {"success": False, "message": "Forbidden"}, 403
        try:
            with db_readonly() as conn:
                teams = TeamsRepository(conn).list_all()
            return make_response(jsonify({"success": True, "teams": teams}), 200)
        except Exception as err:
            logger.error("List all teams failed: %s", err, exc_info=True)
            return {"success": False}, 400
