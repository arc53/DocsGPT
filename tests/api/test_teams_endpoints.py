"""Endpoint authorization tests for the teams API.

These drive the real app.py chokepoint + team_authz plane (only handle_auth /
resolve_roles and the leaf repos are mocked), so they catch regressions in the
authorization wiring: who can read/manage a team, that team_id comes from the
URL path (never the body), and that sharing requires resource ownership. Data
correctness lives in tests/storage/db/repositories/test_teams.py.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def client():
    from application.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@contextmanager
def _cm(value):
    yield value


def _auth(sub="u1", roles=("user",), team_role=None):
    """Patch the chokepoint auth + the team_authz membership resolution.

    ``team_role`` is what TeamMembersRepository.role_for returns inside
    team_authz (None = not a member).
    """
    members = Mock()
    members.role_for.return_value = team_role
    return [
        patch("application.app.handle_auth", return_value={"sub": sub}),
        patch("application.app.resolve_roles", return_value=list(roles)),
        patch("application.api.user.team_authz.db_readonly", lambda: _cm(Mock())),
        patch("application.api.user.team_authz.TeamMembersRepository", return_value=members),
    ]


def _apply(patches):
    for p in patches:
        p.start()


def _stop(patches):
    for p in reversed(patches):
        p.stop()


@pytest.mark.unit
class TestTeamCreation:
    def test_unauthenticated_401(self, client):
        with patch("application.app.handle_auth", return_value=None):
            resp = client.post("/api/teams", json={"name": "Acme"})
        assert resp.status_code == 401

    def test_self_serve_create_returns_201(self, client):
        teams_repo = Mock()
        teams_repo.slug_exists.return_value = False
        teams_repo.create.return_value = {"id": "t1", "name": "Acme", "slug": "acme"}
        members_repo = Mock()
        patches = _auth(sub="alice") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch("application.api.user.teams.routes.TeamsRepository", return_value=teams_repo),
            patch(
                "application.api.user.teams.routes.TeamMembersRepository",
                return_value=members_repo,
            ),
        ]
        _apply(patches)
        try:
            resp = client.post("/api/teams", json={"name": "Acme"})
        finally:
            _stop(patches)
        assert resp.status_code == 201
        # Creator is added as team_admin in the same flow.
        args, kwargs = members_repo.add_member.call_args
        assert kwargs.get("role") == "team_admin" or "team_admin" in args

    def test_missing_name_400(self, client):
        patches = _auth(sub="alice")
        _apply(patches)
        try:
            resp = client.post("/api/teams", json={})
        finally:
            _stop(patches)
        assert resp.status_code == 400


@pytest.mark.unit
class TestTeamAccessControl:
    def test_detail_requires_membership(self, client):
        patches = _auth(sub="stranger", team_role=None)
        _apply(patches)
        try:
            resp = client.get("/api/teams/team-1")
        finally:
            _stop(patches)
        assert resp.status_code == 403

    def test_member_can_read_detail(self, client):
        teams_repo = Mock()
        teams_repo.get.return_value = {"id": "team-1", "name": "Acme", "owner_id": "alice"}
        members_repo = Mock()
        members_repo.list_members.return_value = []
        members_repo.role_for.return_value = "team_member"
        patches = _auth(sub="bob", team_role="team_member") + [
            patch("application.api.user.teams.routes.db_readonly", lambda: _cm(Mock())),
            patch("application.api.user.teams.routes.TeamsRepository", return_value=teams_repo),
            patch(
                "application.api.user.teams.routes.TeamMembersRepository",
                return_value=members_repo,
            ),
        ]
        _apply(patches)
        try:
            resp = client.get("/api/teams/team-1")
        finally:
            _stop(patches)
        assert resp.status_code == 200

    def test_team_id_taken_from_path_not_body(self, client):
        # Caller is NOT a member of team-1; a forged team_id in the body must be
        # ignored — the decorator reads team_id from the URL path only.
        patches = _auth(sub="stranger", team_role=None)
        _apply(patches)
        try:
            resp = client.get("/api/teams/team-1", json={"team_id": "team-i-own"})
        finally:
            _stop(patches)
        assert resp.status_code == 403

    def test_add_member_requires_team_admin(self, client):
        patches = _auth(sub="bob", team_role="team_member")
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/members", json={"user_id": "x", "role": "team_member"}
            )
        finally:
            _stop(patches)
        assert resp.status_code == 403

    def test_team_admin_can_add_member(self, client):
        members_repo = Mock()
        patches = _auth(sub="alice", team_role="team_admin") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch(
                "application.api.user.teams.routes.TeamMembersRepository",
                return_value=members_repo,
            ),
        ]
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/members", json={"user_id": "carol", "role": "team_member"}
            )
        finally:
            _stop(patches)
        assert resp.status_code == 200
        members_repo.set_manual_role.assert_called_once()

    def test_add_member_by_email_resolves_to_sub(self, client):
        members_repo = Mock()
        users_repo = Mock()
        users_repo.find_by_email.return_value = {"user_id": "resolved-sub"}
        patches = _auth(sub="alice", team_role="team_admin") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch(
                "application.api.user.teams.routes.TeamMembersRepository",
                return_value=members_repo,
            ),
            patch(
                "application.api.user.teams.routes.UsersRepository",
                return_value=users_repo,
            ),
        ]
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/members",
                json={"email": "bob@example.com", "role": "team_member"},
            )
        finally:
            _stop(patches)
        assert resp.status_code == 200
        args, kwargs = members_repo.set_manual_role.call_args
        assert "resolved-sub" in args  # resolved sub used, not the email

    def test_add_member_email_not_found(self, client):
        users_repo = Mock()
        users_repo.find_by_email.return_value = None
        patches = _auth(sub="alice", team_role="team_admin") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch(
                "application.api.user.teams.routes.UsersRepository",
                return_value=users_repo,
            ),
        ]
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/members",
                json={"email": "ghost@example.com", "role": "team_member"},
            )
        finally:
            _stop(patches)
        assert resp.status_code == 404

    def test_delete_team_non_owner_forbidden(self, client):
        teams_repo = Mock()
        teams_repo.get.return_value = {"id": "team-1", "owner_id": "alice"}
        patches = _auth(sub="bob", roles=("user",), team_role="team_admin") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch("application.api.user.teams.routes.TeamsRepository", return_value=teams_repo),
        ]
        _apply(patches)
        try:
            resp = client.delete("/api/teams/team-1")
        finally:
            _stop(patches)
        # team_admin is not the owner — only the owner (or a global admin) deletes.
        assert resp.status_code == 403
        teams_repo.delete.assert_not_called()


@pytest.mark.unit
class TestSharingAuthz:
    def test_share_requires_ownership(self, client):
        patches = _auth(sub="bob", team_role="team_member") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch("application.api.user.teams.routes.owns_resource", return_value=False),
        ]
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/grants",
                json={
                    "resource_type": "agent",
                    "resource_id": "11111111-1111-1111-1111-111111111111",
                },
            )
        finally:
            _stop(patches)
        assert resp.status_code == 403

    def test_owner_can_share(self, client):
        grants_repo = Mock()
        grants_repo.grant.return_value = {"id": "g1", "access_level": "viewer"}
        patches = _auth(sub="alice", team_role="team_member") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch("application.api.user.teams.routes.owns_resource", return_value=True),
            patch(
                "application.api.user.teams.routes.TeamResourceGrantsRepository",
                return_value=grants_repo,
            ),
        ]
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/grants",
                json={
                    "resource_type": "agent",
                    "resource_id": "22222222-2222-2222-2222-222222222222",
                    "access_level": "editor",
                },
            )
        finally:
            _stop(patches)
        assert resp.status_code == 201
        _, kwargs = grants_repo.grant.call_args
        assert kwargs.get("access_level") == "editor"

    def test_invalid_resource_type_rejected(self, client):
        patches = _auth(sub="alice", team_role="team_member") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
        ]
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/grants",
                json={"resource_type": "secret_thing", "resource_id": "a1"},
            )
        finally:
            _stop(patches)
        assert resp.status_code == 400

    def test_share_with_member_validates_membership(self, client):
        # target_user_id must be a member of the team.
        members_repo = Mock()
        members_repo.is_member.return_value = False
        patches = _auth(sub="alice", team_role="team_member") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch("application.api.user.teams.routes.owns_resource", return_value=True),
            patch(
                "application.api.user.teams.routes.TeamMembersRepository",
                return_value=members_repo,
            ),
        ]
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/grants",
                json={
                    "resource_type": "agent",
                    "resource_id": "22222222-2222-2222-2222-222222222222",
                    "target_user_id": "stranger",
                },
            )
        finally:
            _stop(patches)
        assert resp.status_code == 400

    def test_share_with_valid_member(self, client):
        members_repo = Mock()
        members_repo.is_member.return_value = True
        grants_repo = Mock()
        grants_repo.grant.return_value = {"id": "g1", "target_user_id": "bob"}
        patches = _auth(sub="alice", team_role="team_member") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch("application.api.user.teams.routes.owns_resource", return_value=True),
            patch(
                "application.api.user.teams.routes.TeamMembersRepository",
                return_value=members_repo,
            ),
            patch(
                "application.api.user.teams.routes.TeamResourceGrantsRepository",
                return_value=grants_repo,
            ),
        ]
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/grants",
                json={
                    "resource_type": "agent",
                    "resource_id": "22222222-2222-2222-2222-222222222222",
                    "target_user_id": "bob",
                },
            )
        finally:
            _stop(patches)
        assert resp.status_code == 201
        _, kwargs = grants_repo.grant.call_args
        assert kwargs.get("target_user_id") == "bob"

    def test_non_uuid_resource_id_rejected(self, client):
        # Team grants are UUID-only (post-cutover); a legacy/non-UUID id must be
        # rejected cleanly, not cast-and-poison the txn into a generic error.
        patches = _auth(sub="alice", team_role="team_member") + [
            patch("application.api.user.teams.routes.db_session", lambda: _cm(Mock())),
            patch("application.api.user.teams.routes.owns_resource", return_value=True),
        ]
        _apply(patches)
        try:
            resp = client.post(
                "/api/teams/team-1/grants",
                json={"resource_type": "agent", "resource_id": "legacy-mongo-id"},
            )
        finally:
            _stop(patches)
        assert resp.status_code == 400


@pytest.mark.unit
class TestAdminOversight:
    def test_non_admin_forbidden(self, client):
        patches = _auth(sub="bob", roles=("user",))
        _apply(patches)
        try:
            resp = client.get("/api/admin/teams")
        finally:
            _stop(patches)
        assert resp.status_code == 403

    def test_global_admin_lists_all(self, client):
        teams_repo = Mock()
        teams_repo.list_all.return_value = [{"id": "t1", "member_count": 3}]
        patches = _auth(sub="root", roles=("admin", "user")) + [
            patch("application.api.user.teams.routes.db_readonly", lambda: _cm(Mock())),
            patch("application.api.user.teams.routes.TeamsRepository", return_value=teams_repo),
        ]
        _apply(patches)
        try:
            resp = client.get("/api/admin/teams")
        finally:
            _stop(patches)
        assert resp.status_code == 200
        assert json.loads(resp.data)["teams"][0]["member_count"] == 3
