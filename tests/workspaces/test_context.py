"""The request's workspace: header, query fallback, Personal by default, membership checked (never trusted)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces import context
from docsgpt.workspaces.context import (
    WORKSPACE_HEADER,
    Workspace,
    WorkspaceError,
    current_workspace,
    parse_workspace_ref,
    require_workspace_role,
)
from docsgpt.workspaces.principal import principal_id

_app = Flask(__name__)


def _request(sub="bob", header=None, query=None):
    """A request context for ``sub`` with the workspace in the header and/or the query."""
    headers = {WORKSPACE_HEADER: header} if header is not None else {}
    path = f"/api/agents?workspace={query}" if query is not None else "/api/agents"
    ctx = _app.test_request_context(path, headers=headers)
    ctx.push()
    from flask import request

    request.decoded_token = {"sub": sub} if sub else None
    return ctx


@pytest.fixture
def team_id(pg_conn) -> str:
    team = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner_id="alice")
    members = TeamMembersRepository(pg_conn)
    members.add_member(str(team["id"]), "alice", role="team_admin")
    members.add_member(str(team["id"]), "bob", role="team_editor")
    members.add_member(str(team["id"]), "carol", role="team_viewer")
    return str(team["id"])


class TestParse:
    @pytest.mark.parametrize("header, query, expected", [
        (None, None, None),
        ("", None, None),
        ("personal", None, None),
        (" Personal ", None, None),
        ("abc", None, "abc"),
        (None, "xyz", "xyz"),
        (None, "personal", None),
        # The header wins over the query parameter.
        ("abc", "xyz", "abc"),
        ("personal", "xyz", None),
    ])
    def test_header_then_query_then_personal(self, header, query, expected):
        ctx = _request(header=header, query=query)
        try:
            from flask import request

            assert parse_workspace_ref(request) == expected
        finally:
            ctx.pop()


class TestCurrentWorkspace:
    def _resolve(self, pg_conn, **kwargs) -> Workspace:
        ctx = _request(**kwargs)
        try:
            return current_workspace(pg_conn)
        finally:
            ctx.pop()

    def test_missing_header_is_personal(self, pg_conn):
        ws = self._resolve(pg_conn, sub="bob")
        assert ws == Workspace(kind="personal", team_id=None, owner_id="bob", role="owner")
        assert ws.is_personal and not ws.is_team
        assert ws.owner_for_create("bob") == ("bob", "bob")

    def test_a_member_gets_the_team_with_their_role(self, pg_conn, team_id):
        ws = self._resolve(pg_conn, sub="bob", header=team_id)
        assert ws == Workspace(kind="team", team_id=team_id, owner_id=principal_id(team_id), role="editor")
        assert ws.owner_for_create("bob") == (principal_id(team_id), "bob")
        owner = self._resolve(pg_conn, sub="alice", query=team_id.upper())
        assert (owner.team_id, owner.role) == (team_id, "owner")

    @pytest.mark.parametrize("ref", ["{other}", "not-a-uuid", "{team}"])
    def test_a_non_member_gets_404(self, pg_conn, team_id, ref):
        other = str(uuid.uuid4())
        with pytest.raises(WorkspaceError) as refused:
            self._resolve(pg_conn, sub="mallory", header=ref.format(team=team_id, other=other))
        assert (refused.value.status, refused.value.code) == (404, "workspace_not_found")
        with _app.app_context():
            response = refused.value.response()
        assert response.status_code == 404
        assert response.get_json() == {
            "success": False, "error": "workspace_not_found", "message": "Workspace not found",
        }

    def test_an_instance_admin_is_not_a_member(self, pg_conn, team_id):
        ctx = _request(sub="root", header=team_id)
        try:
            from flask import request

            request.decoded_token = {"sub": "root", "role": "admin", "roles": ["admin"]}
            with pytest.raises(WorkspaceError):
                current_workspace(pg_conn)
        finally:
            ctx.pop()

    def test_no_caller_is_401(self, pg_conn):
        with pytest.raises(WorkspaceError) as refused:
            self._resolve(pg_conn, sub=None)
        assert refused.value.status == 401

    def test_a_principal_caller_is_its_own_team_and_ignores_the_header(self, pg_conn, team_id):
        principal = principal_id(team_id)
        ws = self._resolve(pg_conn, sub=principal, header="personal")
        assert ws == Workspace(kind="team", team_id=team_id, owner_id=principal, role=None)

    def test_memoised_per_request(self, pg_conn, team_id):
        ctx = _request(sub="bob", header=team_id)
        try:
            with patch.object(context, "team_role_for", wraps=context.team_role_for) as role_for:
                first = current_workspace(pg_conn)
                second = current_workspace(pg_conn)
            assert first is second
            assert role_for.call_count == 1
        finally:
            ctx.pop()

    def test_opens_its_own_connection_when_none_is_given(self, pg_conn, team_id):
        class _Ctx:
            def __enter__(self):
                return pg_conn

            def __exit__(self, *exc):
                return False

        ctx = _request(sub="carol", header=team_id)
        try:
            with patch.object(context, "db_readonly", return_value=_Ctx()):
                assert current_workspace().role == "viewer"
        finally:
            ctx.pop()


class TestRequireRole:
    def test_personal_passes(self):
        require_workspace_role(Workspace("personal", None, "bob", "owner"), "admin")

    @pytest.mark.parametrize("role, minimum, allowed", [
        ("viewer", "viewer", True),
        ("viewer", "editor", False),
        ("editor", "editor", True),
        ("editor", "admin", False),
        ("admin", "editor", True),
        ("owner", "admin", True),
        (None, "viewer", False),
    ])
    def test_team_roles(self, role, minimum, allowed):
        ws = Workspace("team", "t", "__team__t", role)
        if allowed:
            require_workspace_role(ws, minimum)
            return
        with pytest.raises(WorkspaceError) as refused:
            require_workspace_role(ws, minimum)
        assert (refused.value.status, refused.value.code) == (403, "workspace_role_required")
