"""A team's connections: who may do what with them, who owns a new one, and when the account can't be used.

A team connection is owned by the team's principal and records the person who connected it
(``connected_by``). Members see it, Editors sync it, Admins manage it, and only the person who connected it
(while still an Admin) browses the account. While that person is deactivated, gone or below Admin, nothing
uses the account: no token refresh, no credentials, no MCP tokens.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask, request
from sqlalchemy import text

from docsgpt.connectors import oauth_flows, service
from docsgpt.connectors.team import (
    CONNECTION_ACTIONS,
    OWNER_TEAM,
    ConnectionAccess,
    ConnectionDenied,
    authorize_connection,
    connection_fields,
    creation_owner,
    is_team_connection,
)
from docsgpt.security.encryption import encrypt_json
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER, WorkspaceError
from docsgpt.workspaces.principal import ADMIN_NOTICE_KINDS, principal_id, route_owner_notice

_app = Flask(__name__)

#: Each team role and the actions it gets on a team connection someone else connected.
_MATRIX = {
    "viewer": {"view"},
    "editor": {"view", "sync"},
    "admin": {"view", "sync", "manage"},
    "owner": {"view", "sync", "manage"},
}


@contextmanager
def _same_conn(conn):
    yield conn


def _patch_db(conn):
    return patch.multiple("docsgpt.connectors.service", db_session=lambda: _same_conn(conn),
                          db_readonly=lambda: _same_conn(conn))


@pytest.fixture
def team(pg_conn):
    """Team Ops: alice owns it; adam and ana are Admins, eddie an Editor, vi a Viewer."""
    row = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(row["id"])
    members = TeamMembersRepository(pg_conn)
    members.add_member(tid, "alice", role="team_admin")
    members.add_member(tid, "adam", role="team_admin")
    members.add_member(tid, "ana", role="team_admin")
    members.add_member(tid, "eddie", role="team_editor")
    members.add_member(tid, "vi", role="team_viewer")
    return tid


def _set_role(conn, team_id, user_id, role):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user_id}
    )
    if role:
        TeamMembersRepository(conn).add_member(team_id, user_id, role=role)


def _connection(conn, owner, connected_by=None, *, secrets=None, auth_kind="oauth", provider="google_drive"):
    repo = ConnectorSessionsRepository(conn)
    row = repo.create(
        owner, provider, connector_key=provider, auth_kind=auth_kind,
        account_label=f"{uuid.uuid4().hex[:6]}@example.com", connected_by=connected_by,
        encrypted_credentials=encrypt_json(secrets, owner) if secrets is not None else None,
    )
    return row


def _team_row(conn, team_id, connected_by="adam", **kw):
    return _connection(conn, principal_id(team_id), connected_by, **kw)


# ---------------------------------------------------------------------------
# Who may do what
# ---------------------------------------------------------------------------


class TestAuthorize:
    def test_the_actions_and_their_roles(self):
        assert CONNECTION_ACTIONS == {"view": "viewer", "sync": "editor", "manage": "admin", "pick": "admin"}
        assert OWNER_TEAM == "team"

    @pytest.mark.parametrize("user, role", [("vi", "viewer"), ("eddie", "editor"), ("ana", "admin"),
                                            ("alice", "owner")])
    @pytest.mark.parametrize("action", ["view", "sync", "manage", "pick"])
    def test_each_role_on_a_team_connection_someone_else_connected(self, pg_conn, team, user, role, action):
        row = _team_row(pg_conn, team, "adam")
        if action in _MATRIX[role]:
            access = authorize_connection(pg_conn, str(row["id"]), user, action)
            assert (access.is_team, access.role, access.team_id) == (True, role, team)
            return
        with pytest.raises(ConnectionDenied) as denied:
            authorize_connection(pg_conn, str(row["id"]), user, action)
        expected = {
            "pick": (403, "connection_picker_owner_only"),
            "manage": (403, "connection_admin_required"),
            "sync": (403, "workspace_role_required"),
        }[action]
        assert (denied.value.status, denied.value.code) == expected

    def test_the_admin_who_connected_it_may_do_everything(self, pg_conn, team):
        row = _team_row(pg_conn, team, "adam")

        access = authorize_connection(pg_conn, str(row["id"]), "adam", "pick")

        assert access.allowed_actions() == ["view", "sync", "manage", "pick"]
        assert access.connected_by == "adam" and access.user == "adam"

    @pytest.mark.parametrize("role", ["team_editor", "team_viewer"])
    def test_who_connected_it_loses_the_picker_with_the_admin_role(self, pg_conn, team, role):
        row = _team_row(pg_conn, team, "adam")
        _set_role(pg_conn, team, "adam", role)

        with pytest.raises(ConnectionDenied) as denied:
            authorize_connection(pg_conn, str(row["id"]), "adam", "pick")

        assert denied.value.status == 403
        assert "pick" not in authorize_connection(pg_conn, str(row["id"]), "adam", "view").allowed_actions()

    @pytest.mark.parametrize("action", ["view", "sync", "manage", "pick"])
    def test_an_outsider_finds_nothing(self, pg_conn, team, action):
        row = _team_row(pg_conn, team, "adam")
        _set_role(pg_conn, team, "adam", None)  # who connected it left: they are an outsider now

        for outsider in ("mallory", "adam"):
            with pytest.raises(ConnectionDenied) as denied:
                authorize_connection(pg_conn, str(row["id"]), outsider, action)
            assert (denied.value.status, denied.value.code) == (404, "connection_not_found")

    @pytest.mark.parametrize("action", ["view", "sync", "manage", "pick"])
    def test_a_personal_connection_is_its_owners_alone(self, pg_conn, action):
        row = _connection(pg_conn, "lena")

        access = authorize_connection(pg_conn, str(row["id"]), "lena", action)
        assert (access.is_team, access.role, access.team_id) == (False, "owner", None)
        with pytest.raises(ConnectionDenied) as denied:
            authorize_connection(pg_conn, str(row["id"]), "bob", action)
        assert denied.value.code == "connection_not_found"

    def test_a_principal_caller_and_an_unknown_id_find_nothing(self, pg_conn, team):
        row = _team_row(pg_conn, team, "adam")
        for user, cid in ((principal_id(team), str(row["id"])), ("adam", str(uuid.uuid4())), ("adam", "nope")):
            with pytest.raises(ConnectionDenied) as denied:
                authorize_connection(pg_conn, cid, user, "view")
            assert denied.value.status == 404

    def test_an_unknown_action_is_a_bug(self, pg_conn, team):
        row = _team_row(pg_conn, team, "adam")
        with pytest.raises(ValueError):
            authorize_connection(pg_conn, str(row["id"]), "adam", "browse")

    def test_the_refusal_is_a_json_response(self):
        with _app.app_context():
            response = ConnectionDenied(403, "connection_admin_required", "Admins only").response()
        assert response.status_code == 403
        assert response.get_json() == {
            "success": False, "error": "connection_admin_required", "message": "Admins only",
        }

    def test_is_team_connection(self, pg_conn, team):
        assert is_team_connection(_team_row(pg_conn, team, "adam"))
        assert not is_team_connection(_connection(pg_conn, "lena"))
        assert not is_team_connection(None)

    def test_access_is_a_plain_value(self):
        access = ConnectionAccess({"id": "x"}, "lena", None, "owner", None, "lena")
        assert not access.is_team and access.can("pick")


# ---------------------------------------------------------------------------
# Who owns a new connection
# ---------------------------------------------------------------------------


@contextmanager
def _request(sub, workspace=None):
    headers = {WORKSPACE_HEADER: workspace} if workspace else {}
    with _app.test_request_context("/api/connections", headers=headers):
        request.decoded_token = {"sub": sub}
        yield


class TestCreationOwner:
    @pytest.mark.parametrize("owner_param", [None, "", "personal"])
    def test_personal_unless_the_team_is_asked_for_even_from_a_team(self, pg_conn, team, owner_param):
        with _request("adam", team):
            assert creation_owner(pg_conn, "adam", owner_param) == ("adam", None)

    @pytest.mark.parametrize("user", ["adam", "alice"])
    def test_an_admin_connects_for_the_team_the_header_names(self, pg_conn, team, user):
        with _request(user, team):
            assert creation_owner(pg_conn, user, "team") == (principal_id(team), user)

    @pytest.mark.parametrize("user", ["eddie", "vi"])
    def test_below_admin_is_refused(self, pg_conn, team, user):
        with _request(user, team), pytest.raises(WorkspaceError) as refused:
            creation_owner(pg_conn, user, "team")
        assert (refused.value.status, refused.value.code) == (403, "workspace_role_required")

    def test_an_outsider_is_refused(self, pg_conn, team):
        with _request("mallory", team), pytest.raises(WorkspaceError) as refused:
            creation_owner(pg_conn, "mallory", "team")
        assert refused.value.status == 404

    def test_the_team_needs_a_team_workspace(self, pg_conn):
        with _request("adam"), pytest.raises(WorkspaceError) as refused:
            creation_owner(pg_conn, "adam", "team")
        assert (refused.value.status, refused.value.code) == (400, "team_workspace_required")

    def test_any_other_owner_is_refused(self, pg_conn, team):
        with _request("adam", team), pytest.raises(WorkspaceError) as refused:
            creation_owner(pg_conn, "adam", "someone-else")
        assert (refused.value.status, refused.value.code) == (400, "invalid_owner")


# ---------------------------------------------------------------------------
# What a payload says
# ---------------------------------------------------------------------------


class TestConnectionFields:
    def test_a_viewer_sees_who_connected_it_and_nothing_more(self, pg_conn, team):
        UsersRepository(pg_conn).upsert("adam")
        pg_conn.execute(text("UPDATE users SET email = 'adam@ops.example' WHERE user_id = 'adam'"))
        row = _team_row(pg_conn, team, "adam")

        assert connection_fields(pg_conn, row, "vi") == {
            "owner": "team", "team_id": team, "connected_by": {"user_id": "adam", "label": "adam@ops.example"},
            "paused_for": None, "allowed_actions": ["view"], "can_pick": False,
        }

    def test_who_connected_it_can_pick(self, pg_conn, team):
        fields = connection_fields(pg_conn, _team_row(pg_conn, team, "adam"), "adam")
        assert fields["can_pick"] is True
        assert fields["allowed_actions"] == ["view", "sync", "manage", "pick"]

    def test_a_paused_account_says_why_and_nobody_picks(self, pg_conn, team):
        row = _team_row(pg_conn, team, "adam")
        _set_role(pg_conn, team, "adam", None)

        fields = connection_fields(pg_conn, row, "ana")

        assert fields["paused_for"] == {"reason": "payer_left", "until": None, "left_team": True}
        assert fields["connected_by"] == {"user_id": "adam", "label": "adam"}
        assert fields["can_pick"] is False
        assert "manage" in fields["allowed_actions"]

    def test_a_personal_connection(self, pg_conn):
        fields = connection_fields(pg_conn, _connection(pg_conn, "lena"), "lena")
        assert fields == {
            "owner": "personal", "team_id": None, "connected_by": None, "paused_for": None,
            "allowed_actions": ["view", "sync", "manage", "pick"], "can_pick": True,
        }


# ---------------------------------------------------------------------------
# A paused account is never used
# ---------------------------------------------------------------------------


class _ExpiredAuth:
    def __init__(self):
        self.calls = []

    def is_token_expired(self, token_info):
        return True

    def refresh_access_token(self, refresh_token):
        self.calls.append(refresh_token)
        return {"access_token": "new", "refresh_token": "rt-1"}

    def sanitize_token_info(self, token_info, **extra):
        return dict(token_info)


class TestAccountUsable:
    def _paused(self, pg_conn, team, **kw):
        row = _team_row(pg_conn, team, "adam", **kw)
        _set_role(pg_conn, team, "adam", "team_editor")
        return row

    def test_status_paused(self):
        assert service.STATUS_PAUSED == "paused"

    def test_a_paused_team_account_is_not_refreshed_and_not_flagged(self, pg_conn, team):
        row = self._paused(pg_conn, team, secrets={"token_info": {"access_token": "old", "refresh_token": "rt-0"}})
        fake = _ExpiredAuth()
        with _patch_db(pg_conn), patch(
            "docsgpt.parser.connectors.connector_creator.ConnectorCreator.create_auth", return_value=fake
        ), patch("docsgpt.events.publisher.publish_user_event") as publish:
            with pytest.raises(service.ConnectionUnavailable) as unavailable:
                service.get_valid_token_info(str(row["id"]))

        assert unavailable.value.status == "paused"
        assert unavailable.value.paused_for == {"reason": "payer_left", "until": None, "left_team": False}
        assert fake.calls == []
        assert ConnectorSessionsRepository(pg_conn).get(str(row["id"]))["status"] == "connected"
        publish.assert_not_called()

    def test_a_usable_team_account_refreshes(self, pg_conn, team):
        row = _team_row(pg_conn, team, "adam", secrets={"token_info": {"access_token": "old", "refresh_token": "rt-0"}})
        fake = _ExpiredAuth()
        with _patch_db(pg_conn), patch(
            "docsgpt.parser.connectors.connector_creator.ConnectorCreator.create_auth", return_value=fake
        ):
            assert service.get_valid_token_info(str(row["id"]))["access_token"] == "new"

    def test_pasted_credentials_of_a_paused_account_stay_sealed(self, pg_conn, team):
        row = self._paused(pg_conn, team, secrets={"credentials": {"api_key": "sk-12345678"}}, auth_kind="api_key",
                           provider="linear")
        with _patch_db(pg_conn):
            for read in (service.get_credentials, service.access_credentials):
                with pytest.raises(service.ConnectionUnavailable) as unavailable:
                    read(row)
                assert unavailable.value.status == "paused"

    def test_an_oauth_access_token_of_a_paused_account_stays_sealed(self, pg_conn, team):
        row = self._paused(pg_conn, team, secrets={"token_info": {"access_token": "old", "refresh_token": "rt-0"}})
        with _patch_db(pg_conn), patch("docsgpt.connectors.service.get_valid_token_info") as token:
            with pytest.raises(service.ConnectionUnavailable):
                service.access_credentials(row)
        token.assert_not_called()

    def test_mcp_tokens_of_a_paused_account_are_neither_read_nor_written(self, pg_conn, team):
        base = "https://mcp.example.com"
        principal = principal_id(team)
        row = ConnectorSessionsRepository(pg_conn).create(
            principal, service.mcp_provider(base), connector_key="custom_mcp", auth_kind="mcp_oauth",
            server_url=base, connected_by="adam",
            encrypted_credentials=encrypt_json({"tokens": {"access_token": "t"}}, principal),
        )
        _set_role(pg_conn, team, "adam", None)
        with _patch_db(pg_conn):
            with pytest.raises(service.ConnectionUnavailable):
                service.read_mcp_secrets(principal, base, str(row["id"]))
            # Without its id a team's sign-in is never found, paused or not.
            assert service.read_mcp_secrets(principal, base) == {}
            with pytest.raises(service.ConnectionUnavailable):
                service.update_mcp_secrets(principal, base, {"tokens": {"access_token": "u"}},
                                           connection_id=str(row["id"]))
        assert service.read_secrets(ConnectorSessionsRepository(pg_conn).get(str(row["id"])))["tokens"] == {
            "access_token": "t"
        }

    def test_a_personal_account_is_never_paused_here(self, pg_conn):
        row = _connection(pg_conn, "lena", secrets={"credentials": {"api_key": "sk-12345678"}}, auth_kind="api_key",
                          provider="linear")
        UsersRepository(pg_conn).upsert("lena")
        pg_conn.execute(text("UPDATE users SET active = false WHERE user_id = 'lena'"))
        with _patch_db(pg_conn):
            service.ensure_account_usable(pg_conn, row)
            assert service.get_credentials(row) == {"api_key": "sk-12345678"}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class TestRepository:
    def test_who_connected_is_stored_and_changed(self, pg_conn, team):
        repo = ConnectorSessionsRepository(pg_conn)
        row = _team_row(pg_conn, team, "adam")
        assert row["connected_by"] == "adam"

        assert repo.set_connected_by(str(row["id"]), "ana") is True
        assert repo.get(str(row["id"]))["connected_by"] == "ana"

    def test_a_lazily_made_team_row_needs_a_person(self, pg_conn, team):
        from sqlalchemy.exc import IntegrityError

        repo = ConnectorSessionsRepository(pg_conn)
        principal = principal_id(team)
        with pytest.raises(IntegrityError), pg_conn.begin_nested():
            repo.merge_session_data(principal, "mcp:https://a.example", "https://a.example", {})
        row = repo.merge_session_data(principal, "mcp:https://a.example", "https://a.example", {}, connected_by="ana")
        assert row["connected_by"] == "ana"
        # Merging into it again keeps who connected it.
        again = repo.merge_session_data(principal, "mcp:https://a.example", "https://a.example", {"x": 1},
                                        connected_by="adam")
        assert (str(again["id"]), again["connected_by"]) == (str(row["id"]), "ana")

    def test_connections_each_person_connected_for_a_team(self, pg_conn, team):
        repo = ConnectorSessionsRepository(pg_conn)
        _team_row(pg_conn, team, "adam")
        _team_row(pg_conn, team, "adam")
        _team_row(pg_conn, team, "ana")
        _connection(pg_conn, "adam")

        assert repo.connected_by_counts(principal_id(team), ["adam", "ana", "eddie"]) == {
            "adam": 2, "ana": 1, "eddie": 0,
        }
        assert repo.connected_by_counts(principal_id(team), []) == {}


class TestOAuthPlumbing:
    def test_a_team_sign_in_names_its_owner_and_replacement(self, pg_conn, team):
        row = _team_row(pg_conn, team, "adam")
        state = oauth_flows.start(
            pg_conn, "ana", "google_drive", str(row["id"]), "http://app",
            owner_id=principal_id(team), replace_account=True,
        )

        flow = oauth_flows.take(pg_conn, state, "ana")

        assert (flow["user_id"], flow["owner_id"], flow["replace_account"]) == ("ana", principal_id(team), True)

    def test_a_personal_sign_in_names_no_owner(self, pg_conn):
        row = _connection(pg_conn, "lena")
        state = oauth_flows.start(pg_conn, "lena", "google_drive", str(row["id"]), "http://app")

        flow = oauth_flows.take(pg_conn, state, "lena")

        assert (flow["owner_id"], flow["replace_account"]) == (None, False)

    def test_begin_for_a_team_records_who_connects(self, pg_conn, team):
        principal = principal_id(team)
        pending = service.begin_oauth(pg_conn, principal, "google_drive", connected_by="ana")
        assert (pending["user_id"], pending["connected_by"], pending["status"]) == (principal, "ana", "pending")

    def test_personal_sign_ins_work_as_before(self, pg_conn):
        pending = service.begin_oauth(pg_conn, "lena", "google_drive")
        row = service.complete_oauth(pg_conn, pending, "google_drive", {"access_token": "a"}, "l@example.com",
                                     connected_by=None)
        assert (row["user_id"], row["connected_by"], row["status"]) == ("lena", None, "connected")


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------


class TestReconnectNotice:
    def test_a_team_rows_reconnect_notice_reaches_its_admins(self, pg_conn, team):
        assert "connection.reconnect_needed" in ADMIN_NOTICE_KINDS
        assert route_owner_notice(pg_conn, principal_id(team), None, "connection.reconnect_needed") == [
            "adam", "alice", "ana",
        ]

    def test_flagging_a_team_row_tells_the_admins(self, pg_conn, team):
        row = _team_row(pg_conn, team, "adam")
        delivered = []
        with _patch_db(pg_conn), patch(
            "docsgpt.storage.db.session.db_readonly", lambda: _same_conn(pg_conn)
        ), patch("docsgpt.events.publisher._deliver", side_effect=lambda u, *a: delivered.append(u) or "1-0"):
            service.mark_reconnect_needed(str(row["id"]), "revoked")

        assert sorted(delivered) == ["adam", "alice", "ana"]
