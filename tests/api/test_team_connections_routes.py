"""The connection routes on a team's connections, and connecting an account for a team.

A team connection is owned by the team's principal and records who connected it. Every member lists it,
Admins manage it, and only the Admin who connected it browses the account. A sign-in for the team is
finished by the person who started it, re-checked as an Admin, and the flow (never the request's
workspace) names the team. Another Admin reconnects it with their own account in place.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.connectors import oauth_flows, service
from docsgpt.security.encryption import decrypt_json, encrypt_json
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id
from tests.connectors.conftest import _oauth_connectors_configured  # noqa: F401  (autouse)


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def team(pg_conn):
    """Team Ops: alice owns it; adam and ana are Admins, eddie an Editor, vi a Viewer."""
    row = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(row["id"])
    members = TeamMembersRepository(pg_conn)
    for user, role in (("alice", "team_admin"), ("adam", "team_admin"), ("ana", "team_admin"),
                       ("eddie", "team_editor"), ("vi", "team_viewer")):
        members.add_member(tid, user, role=role)
    return tid


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.api.connector.connections", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.api.connector.routes", db_session=_yield, db_readonly=_yield), \
            patch("docsgpt.workspaces.context.db_readonly", _yield):
        yield


def _call(app, resource, method, path, user, *, body=None, team=None, args=(), query=""):
    headers = {WORKSPACE_HEADER: team} if team else {}
    with app.test_request_context(f"{path}{query}", method=method.upper(), json=body, headers=headers):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return getattr(resource(), method)(*args)


def _row(conn, owner, connected_by=None, *, provider="google_drive", auth_kind="oauth", label=None, secrets=None):
    return ConnectorSessionsRepository(conn).create(
        owner, provider, connector_key=provider, auth_kind=auth_kind, status="connected",
        account_label=label or f"{uuid.uuid4().hex[:6]}@example.com", connected_by=connected_by,
        encrypted_credentials=encrypt_json(
            secrets if secrets is not None else {"token_info": {"access_token": "at", "refresh_token": "rt"}},
            owner,
        ),
    )


def _team_row(conn, team, connected_by="adam", **kw):
    return _row(conn, principal_id(team), connected_by, **kw)


def _set_role(conn, team_id, user_id, role):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user_id}
    )
    if role:
        TeamMembersRepository(conn).add_member(team_id, user_id, role=role)


#: A provider's auth whose sign-in starts at a fixed URL.
_AUTH = MagicMock(get_authorization_url=MagicMock(return_value="https://accounts.example/auth"))


def _audit_events(conn, event):
    return conn.execute(
        text("SELECT user_id, metadata FROM auth_events WHERE event = :e ORDER BY created_at"), {"e": event},
    ).fetchall()


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


class TestLists:
    def test_a_viewer_lists_the_teams_connections_read_only(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionsList

        row = _team_row(pg_conn, team, "adam")
        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "get", "/api/connections", "vi", team=team, query="?owner=team")

        assert resp.status_code == 200
        [listed] = resp.get_json()["connections"]
        assert listed["id"] == str(row["id"])
        assert listed["owner"] == "team" and listed["team_id"] == team
        assert listed["connected_by"]["user_id"] == "adam"
        assert listed["allowed_actions"] == ["view"] and listed["can_pick"] is False
        assert listed["status"] == "connected"

    def test_without_owner_team_a_team_header_lists_the_callers_own(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionsList

        _team_row(pg_conn, team, "adam")
        own = _row(pg_conn, "vi")
        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "get", "/api/connections", "vi", team=team)

        assert [c["id"] for c in resp.get_json()["connections"]] == [str(own["id"])]
        assert resp.get_json()["connections"][0]["owner"] == "personal"

    def test_an_outsider_cant_list_a_team(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionsList

        _team_row(pg_conn, team, "adam")
        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "get", "/api/connections", "mallory", team=team, query="?owner=team")

        assert resp.status_code == 404

    def test_a_paused_account_lists_as_paused(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionsList

        _team_row(pg_conn, team, "adam")
        _set_role(pg_conn, team, "adam", None)
        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "get", "/api/connections", "ana", team=team, query="?owner=team")

        [listed] = resp.get_json()["connections"]
        assert listed["status"] == "paused"
        assert listed["paused_for"]["reason"] == "payer_left"

    def test_the_catalog_summarises_the_teams_connections(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectorCatalog

        _team_row(pg_conn, team, "adam")
        _row(pg_conn, "vi", provider="google_drive")
        _team_row(pg_conn, team, "adam", provider="share_point")
        _set_role(pg_conn, team, "adam", "team_editor")
        with _db(pg_conn):
            resp = _call(app, ConnectorCatalog, "get", "/api/connectors/catalog", "vi", team=team,
                         query="?owner=team")

        cards = {c["key"]: c for c in resp.get_json()["connectors"]}
        assert cards["google_drive"]["connection_count"] == 1
        assert cards["google_drive"]["status"] == "paused"
        assert cards["google_drive"]["state"] == "paused"

    def test_paused_ranks_above_error_and_below_reconnect(self):
        assert service.worst_status(["connected", "paused", "error"]) == "paused"
        assert service.worst_status(["paused", "reconnect_needed"]) == "reconnect_needed"


# ---------------------------------------------------------------------------
# Who may do what by id
# ---------------------------------------------------------------------------


def _manage_calls(cid, tool_id="00000000-0000-0000-0000-000000000000"):
    from docsgpt.api.connector import connections as c

    return [
        (c.ConnectionDetail, "patch", f"/api/connections/{cid}", {"name": "x"}, [cid]),
        (c.ConnectionDetail, "delete", f"/api/connections/{cid}", {}, [cid]),
        (c.ConnectionDisconnect, "post", f"/api/connections/{cid}/disconnect", {}, [cid]),
        (c.ConnectionSetup, "post", f"/api/connections/{cid}/setup", {"create_tools": True}, [cid]),
        (c.ConnectionReconnect, "post", f"/api/connections/{cid}/reconnect", {}, [cid]),
        (c.ConnectionToolPermissions, "put", f"/api/connections/{cid}/tools/{tool_id}/permissions",
         {"permissions": {"a": "ask"}}, [cid, tool_id]),
        (c.ConnectionToolParameters, "put", f"/api/connections/{cid}/tools/{tool_id}/parameters",
         {"action": "a", "parameters": {"p": None}}, [cid, tool_id]),
        (c.ConnectionRefreshTools, "post", f"/api/connections/{cid}/refresh-tools", {}, [cid]),
        (c.ConnectionWrites, "put", f"/api/connections/{cid}/writes", {"allow": False}, [cid]),
    ]


class TestById:
    @pytest.mark.parametrize("user", ["vi", "eddie"])
    def test_below_admin_every_manage_route_is_refused(self, app, pg_conn, team, user):
        row = _team_row(pg_conn, team, "adam")
        cid = str(row["id"])
        with _db(pg_conn):
            for resource, method, path, body, args in _manage_calls(cid):
                resp = _call(app, resource, method, path, user, body=body, args=args)
                assert resp.status_code == 403, (resource.__name__, method)
                assert resp.get_json()["error"] == "connection_admin_required"
        after = ConnectorSessionsRepository(pg_conn).get(cid)
        assert after is not None and after["status"] == "connected" and after["account_name"] is None

    def test_a_viewer_reads_the_detail(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionDetail

        row = _team_row(pg_conn, team, "adam")
        with _db(pg_conn):
            resp = _call(app, ConnectionDetail, "get", f"/api/connections/{row['id']}", "vi", args=[str(row["id"])])

        assert resp.status_code == 200
        detail = resp.get_json()["connection"]
        assert detail["owner"] == "team" and detail["allowed_actions"] == ["view"]

    def test_an_outsider_finds_nothing(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionDetail

        row = _team_row(pg_conn, team, "adam")
        cid = str(row["id"])
        with _db(pg_conn):
            detail = _call(app, ConnectionDetail, "get", f"/api/connections/{cid}", "mallory", args=[cid])
            for resource, method, path, body, args in _manage_calls(cid):
                resp = _call(app, resource, method, path, "mallory", body=body, args=args)
                assert resp.status_code == 404, (resource.__name__, method)
        assert detail.status_code == 404

    def test_an_admin_renames_it(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionDetail

        row = _team_row(pg_conn, team, "adam")
        with _db(pg_conn):
            resp = _call(app, ConnectionDetail, "patch", f"/api/connections/{row['id']}", "ana",
                         body={"name": "Team drive"}, args=[str(row["id"])])

        assert resp.status_code == 200
        assert resp.get_json()["connection"]["account_name"] == "Team drive"
        assert resp.get_json()["connection"]["owner"] == "team"

    def test_disconnect_and_remove_are_audited(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionDetail, ConnectionDisconnect

        first = _team_row(pg_conn, team, "adam")
        second = _team_row(pg_conn, team, "adam", provider="share_point")
        with _db(pg_conn), patch.object(service, "revoke_at_provider", return_value=True):
            off = _call(app, ConnectionDisconnect, "post", "/x", "ana", args=[str(first["id"])])
            gone = _call(app, ConnectionDetail, "delete", "/x", "ana", body={"sources": "keep"},
                         args=[str(second["id"])])

        assert off.status_code == 200 and gone.status_code == 200
        [(actor, meta)] = _audit_events(pg_conn, "team.connection_disconnected")
        assert actor == "ana" and meta["connection_id"] == str(first["id"]) and meta["team_id"] == team
        [(actor, meta)] = _audit_events(pg_conn, "team.connection_removed")
        assert meta["connection_id"] == str(second["id"]) and meta["sources"] == "keep"
        assert ConnectorSessionsRepository(pg_conn).get(str(second["id"])) is None

    def test_a_personal_connection_writes_no_team_audit(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDisconnect

        row = _row(pg_conn, "lena")
        with _db(pg_conn), patch.object(service, "revoke_at_provider", return_value=True):
            resp = _call(app, ConnectionDisconnect, "post", "/x", "lena", args=[str(row["id"])])

        assert resp.status_code == 200
        assert _audit_events(pg_conn, "team.connection_disconnected") == []


# ---------------------------------------------------------------------------
# Browsing the account: only the Admin who connected it
# ---------------------------------------------------------------------------


class TestPicker:
    @pytest.mark.parametrize("user, code", [("ana", "connection_picker_owner_only"),
                                            ("alice", "connection_picker_owner_only"),
                                            ("eddie", "connection_picker_owner_only")])
    def test_picker_token_is_only_for_who_connected_it(self, app, pg_conn, team, user, code):
        from docsgpt.api.connector.connections import ConnectionPickerToken

        row = _team_row(pg_conn, team, "adam")
        cid = str(row["id"])
        with _db(pg_conn), patch.object(service, "picker_token", return_value={"access_token": "live"}) as token:
            refused = _call(app, ConnectionPickerToken, "post", "/x", user, args=[cid])
            allowed = _call(app, ConnectionPickerToken, "post", "/x", "adam", args=[cid])

        assert refused.status_code == 403 and refused.get_json()["error"] == code
        assert "live" not in refused.get_data(as_text=True)
        assert allowed.status_code == 200 and allowed.get_json()["access_token"] == "live"
        token.assert_called_once()

    def test_a_paused_account_hands_out_no_token(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionPickerToken

        row = _team_row(pg_conn, team, "adam")
        UsersRepository(pg_conn).upsert("adam")
        pg_conn.execute(text("UPDATE users SET active = false WHERE user_id = 'adam'"))
        with _db(pg_conn):
            resp = _call(app, ConnectionPickerToken, "post", "/x", "adam", args=[str(row["id"])])

        assert resp.status_code == 409
        assert resp.get_json()["error"] == "connection_paused"
        assert resp.get_json()["paused_for"]["reason"] == "owner_inactive"
        assert "access_token" not in resp.get_json()

    def test_a_left_payer_is_paused_for_the_picker(self, app, pg_conn, team):
        """Demoted below Admin: the picker is refused before anything is read."""
        from docsgpt.api.connector.connections import ConnectionPickerToken

        row = _team_row(pg_conn, team, "adam")
        _set_role(pg_conn, team, "adam", "team_editor")
        with _db(pg_conn), patch.object(service, "picker_token") as token:
            resp = _call(app, ConnectionPickerToken, "post", "/x", "adam", args=[str(row["id"])])

        assert resp.status_code == 403
        token.assert_not_called()

    def test_files_and_validate_session_are_only_for_who_connected_it(self, app, pg_conn, team):
        from docsgpt.api.connector.routes import ConnectorFiles, ConnectorValidateSession

        row = _team_row(pg_conn, team, "adam")
        body = {"provider": "google_drive", "connection_id": str(row["id"])}
        loader = MagicMock()
        loader.load_data.return_value = []
        loader.next_page_token = None
        with _db(pg_conn), patch(
            "docsgpt.api.connector.routes.ConnectorCreator.create_connector", return_value=loader,
        ), patch.object(service, "picker_token", return_value={"access_token": "live"}):
            files_refused = _call(app, ConnectorFiles, "post", "/api/connectors/files", "ana", body=body)
            token_refused = _call(app, ConnectorValidateSession, "post", "/x", "ana", body=body)
            files_ok = _call(app, ConnectorFiles, "post", "/api/connectors/files", "adam", body=body)
            token_ok = _call(app, ConnectorValidateSession, "post", "/x", "adam", body=body)

        assert files_refused.status_code == 403
        assert files_refused.get_json()["error"] == "connection_picker_owner_only"
        assert token_refused.status_code == 403 and "live" not in token_refused.get_data(as_text=True)
        assert files_ok.status_code == 200 and token_ok.status_code == 200

    def test_files_of_a_team_row_stay_hidden_from_outsiders(self, app, pg_conn, team):
        from docsgpt.api.connector.routes import ConnectorFiles

        row = _team_row(pg_conn, team, "adam")
        with _db(pg_conn), patch("docsgpt.api.connector.routes.ConnectorCreator.create_connector") as create:
            resp = _call(app, ConnectorFiles, "post", "/x", "mallory",
                         body={"provider": "google_drive", "connection_id": str(row["id"])})

        assert resp.status_code == 401
        create.assert_not_called()

    def test_repositories_are_only_for_who_connected_it(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionRepositories

        row = _team_row(pg_conn, team, "adam", provider="github", auth_kind="api_key",
                        secrets={"credentials": {"access_token": "ghp_x"}})
        cid = str(row["id"])
        with _db(pg_conn), patch("docsgpt.connectors.github.list_repositories", return_value=[{"name": "r"}]):
            refused = _call(app, ConnectionRepositories, "get", "/x", "ana", args=[cid])
            allowed = _call(app, ConnectionRepositories, "get", "/x", "adam", args=[cid])

        assert refused.status_code == 403 and refused.get_json()["error"] == "connection_picker_owner_only"
        assert allowed.status_code == 200 and allowed.get_json()["repositories"] == [{"name": "r"}]

    def test_linear_is_only_for_who_connected_it(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import LinearWorkspace

        principal = principal_id(team)
        cid = str(pg_conn.execute(
            text("INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, "
                 "account_label, server_url, connected_by) VALUES (:u, 'mcp:https://mcp.linear.app', "
                 "'mcp:linear', 'mcp_oauth', 'connected', 'acme', 'https://mcp.linear.app', 'adam') RETURNING id"),
            {"u": principal},
        ).scalar())
        with _db(pg_conn), patch("docsgpt.connectors.mcp.run_connection_session", return_value={"teams": []}):
            refused = _call(app, LinearWorkspace, "get", "/x", "ana", args=[cid])
            allowed = _call(app, LinearWorkspace, "get", "/x", "adam", args=[cid])

        assert refused.status_code == 403 and refused.get_json()["error"] == "connection_picker_owner_only"
        assert allowed.status_code == 200

    def test_setup_sync_is_only_for_who_connected_it(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionSetup

        row = _team_row(pg_conn, team, "adam")
        cid = str(row["id"])
        body = {"create_tools": False, "sync": {"items": {"folder_ids": ["f1"]}, "frequency": "weekly"}}
        task = MagicMock(id="task-1")
        with _db(pg_conn), patch("docsgpt.api.user.tasks.ingest_connector_task.apply_async",
                                 return_value=task) as apply:
            refused = _call(app, ConnectionSetup, "post", "/x", "ana", body=body, args=[cid])
            assert apply.call_count == 0
            allowed = _call(app, ConnectionSetup, "post", "/x", "adam", body=body, args=[cid])

        assert refused.status_code == 403 and refused.get_json()["error"] == "connection_picker_owner_only"
        assert allowed.status_code == 200
        kwargs = apply.call_args.kwargs["kwargs"]
        assert kwargs["user"] == principal_id(team)
        assert kwargs["actor_id"] == "adam"
        assert kwargs["connection_id"] == cid

    def test_setup_sync_of_a_paused_account_is_refused(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionSetup

        row = _team_row(pg_conn, team, "adam")
        # The person who connected it is out of the team: the account is paused for everyone.
        _set_role(pg_conn, team, "adam", None)
        with _db(pg_conn), patch("docsgpt.api.user.tasks.ingest_connector_task.apply_async") as apply:
            resp = _call(app, ConnectionSetup, "post", "/x", "ana", body={"create_tools": True}, args=[str(row["id"])])

        assert resp.status_code == 409
        assert resp.get_json()["error"] == "connection_paused"
        assert resp.get_json()["paused_for"]["reason"] == "payer_left"
        apply.assert_not_called()

    def test_setup_tools_are_the_teams_and_name_who_added_them(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionSetup

        row = _team_row(pg_conn, team, "adam", provider="telegram", auth_kind="api_key",
                        secrets={"credentials": {"token": "123:abcdefgh"}})
        with _db(pg_conn):
            resp = _call(app, ConnectionSetup, "post", "/x", "ana", body={"create_tools": True}, args=[str(row["id"])])

        assert resp.status_code == 200
        tool = pg_conn.execute(
            text("SELECT user_id, created_by FROM user_tools WHERE connection_id = CAST(:c AS uuid)"),
            {"c": str(row["id"])},
        ).one()
        assert (tool.user_id, tool.created_by) == (principal_id(team), "ana")


# ---------------------------------------------------------------------------
# Creating: personal unless owner=team
# ---------------------------------------------------------------------------


class TestCreate:
    def test_a_team_header_alone_makes_a_personal_api_key_connection(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "post", "/api/connections", "adam", team=team,
                         body={"connector_key": "telegram", "credentials": {"token": "123:abcdefgh"}})

        assert resp.status_code == 201
        created = ConnectorSessionsRepository(pg_conn).get(resp.get_json()["connection"]["id"])
        assert (created["user_id"], created["connected_by"]) == ("adam", None)

    def test_an_admin_connects_an_api_key_for_the_team(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "post", "/api/connections", "adam", team=team,
                         body={"connector_key": "telegram", "credentials": {"token": "123:abcdefgh"},
                               "owner": "team"})

        assert resp.status_code == 201
        payload = resp.get_json()["connection"]
        created = ConnectorSessionsRepository(pg_conn).get(payload["id"])
        assert (created["user_id"], created["connected_by"]) == (principal_id(team), "adam")
        assert payload["owner"] == "team" and payload["can_pick"] is True
        [(actor, meta)] = _audit_events(pg_conn, "team.connection_added")
        assert actor == "adam" and meta["connection_id"] == payload["id"] and meta["connector_key"] == "telegram"

    @pytest.mark.parametrize("user", ["eddie", "vi"])
    def test_below_admin_cant_connect_for_the_team(self, app, pg_conn, team, user):
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "post", "/api/connections", user, team=team,
                         body={"connector_key": "telegram", "credentials": {"token": "123:abcdefgh"},
                               "owner": "team"})

        assert resp.status_code == 403 and resp.get_json()["error"] == "workspace_role_required"
        assert pg_conn.execute(
            text("SELECT count(*) FROM connector_sessions WHERE user_id = :p"), {"p": principal_id(team)},
        ).scalar() == 0

    def test_oauth_start_without_owner_team_is_personal(self, app, pg_conn, team):
        from docsgpt.api.connector.routes import ConnectorAuth

        with _db(pg_conn), patch.object(service, "ensure_can_store_credentials"), \
                patch("docsgpt.api.connector.routes.ConnectorCreator.create_auth", return_value=_AUTH):
            resp = _call(app, ConnectorAuth, "get", "/api/connectors/auth", "adam", team=team,
                         query="?provider=google_drive")

        assert resp.status_code == 200
        flow = oauth_flows.peek(pg_conn, resp.get_json()["state"])
        assert flow["owner_id"] is None
        pending = ConnectorSessionsRepository(pg_conn).get(str(flow["connection_id"]))
        assert (pending["user_id"], pending["connected_by"]) == ("adam", None)

    def test_oauth_start_for_the_team(self, app, pg_conn, team):
        from docsgpt.api.connector.routes import ConnectorAuth

        with _db(pg_conn), patch.object(service, "ensure_can_store_credentials"), \
                patch("docsgpt.api.connector.routes.ConnectorCreator.create_auth", return_value=_AUTH):
            resp = _call(app, ConnectorAuth, "get", "/api/connectors/auth", "ana", team=team,
                         query="?provider=google_drive&owner=team")
            refused = _call(app, ConnectorAuth, "get", "/api/connectors/auth", "eddie", team=team,
                            query="?provider=google_drive&owner=team")

        assert resp.status_code == 200
        flow = oauth_flows.peek(pg_conn, resp.get_json()["state"])
        assert (flow["user_id"], flow["owner_id"], flow["replace_account"]) == ("ana", principal_id(team), False)
        assert refused.status_code == 403 and refused.get_json()["error"] == "workspace_role_required"


# ---------------------------------------------------------------------------
# Finishing a team sign-in
# ---------------------------------------------------------------------------


@contextmanager
def _signing_in(pg_conn, account="drive@example.com", token_info=None):
    with _db(pg_conn), patch.object(service, "ensure_can_store_credentials"), \
            patch("docsgpt.api.connector.routes.ConnectorCreator.create_auth", return_value=_AUTH), \
            patch("docsgpt.api.connector.routes._exchange_code",
                  return_value=(token_info or {"access_token": "new-at", "refresh_token": "new-rt"}, account)) as ex:
        yield ex


def _start(app, user, team, query):
    from docsgpt.api.connector.routes import ConnectorAuth

    resp = _call(app, ConnectorAuth, "get", "/api/connectors/auth", user, team=team, query=query)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["state"]


def _complete(app, user, state, team=None):
    from docsgpt.api.connector.routes import ConnectorAuthComplete

    return _call(app, ConnectorAuthComplete, "post", "/api/connectors/auth/complete", user, team=team,
                 body={"code": "c", "state": state})


class TestComplete:
    def test_a_team_sign_in_lands_on_the_teams_row(self, app, pg_conn, team):
        with _signing_in(pg_conn):
            state = _start(app, "ana", team, "?provider=google_drive&owner=team")
            # The finishing page sends no team, or another one: the flow decides.
            resp = _complete(app, "ana", state, team=None)

        assert resp.status_code == 200
        row = ConnectorSessionsRepository(pg_conn).get(resp.get_json()["connection_id"])
        assert (row["user_id"], row["connected_by"], row["status"]) == (principal_id(team), "ana", "connected")
        assert row["account_label"] == "drive@example.com"
        [(actor, meta)] = _audit_events(pg_conn, "team.connection_added")
        assert actor == "ana" and meta["account_label"] == "drive@example.com"

    def test_demoted_before_finishing_stores_nothing(self, app, pg_conn, team):
        with _signing_in(pg_conn) as exchange:
            state = _start(app, "ana", team, "?provider=google_drive&owner=team")
            _set_role(pg_conn, team, "ana", "team_editor")
            resp = _complete(app, "ana", state)
            again = _complete(app, "ana", state)

        assert resp.status_code == 403 and resp.get_json()["error"] == "connection_admin_required"
        exchange.assert_not_called()
        assert pg_conn.execute(
            text("SELECT count(*) FROM connector_sessions WHERE user_id = :p AND encrypted_credentials IS NOT NULL"),
            {"p": principal_id(team)},
        ).scalar() == 0
        assert again.status_code == 400  # the flow is used up

    def test_removed_before_finishing_stores_nothing(self, app, pg_conn, team):
        with _signing_in(pg_conn):
            state = _start(app, "ana", team, "?provider=google_drive&owner=team")
            _set_role(pg_conn, team, "ana", None)
            resp = _complete(app, "ana", state)

        assert resp.status_code == 403
        assert pg_conn.execute(
            text("SELECT count(*) FROM connector_sessions WHERE user_id = :p AND encrypted_credentials IS NOT NULL"),
            {"p": principal_id(team)},
        ).scalar() == 0

    def test_a_personal_flow_finished_from_a_team_stays_personal(self, app, pg_conn, team):
        with _signing_in(pg_conn):
            state = _start(app, "ana", None, "?provider=google_drive")
            resp = _complete(app, "ana", state, team=team)

        row = ConnectorSessionsRepository(pg_conn).get(resp.get_json()["connection_id"])
        assert (row["user_id"], row["connected_by"]) == ("ana", None)

    def test_another_admin_signing_in_to_the_same_account_takes_it_over(self, app, pg_conn, team):
        existing = _team_row(pg_conn, team, "adam", label="drive@example.com")
        with _signing_in(pg_conn, account="drive@example.com"):
            state = _start(app, "ana", team, "?provider=google_drive&owner=team")
            resp = _complete(app, "ana", state)

        assert resp.get_json()["connection_id"] == str(existing["id"])
        row = ConnectorSessionsRepository(pg_conn).get(str(existing["id"]))
        assert row["connected_by"] == "ana"
        [(_, meta)] = _audit_events(pg_conn, "team.connection_reconnected")
        assert meta["replaced"] is False and meta["previous_connected_by"] == "adam"


# ---------------------------------------------------------------------------
# Reconnecting with another Admin's account
# ---------------------------------------------------------------------------


class TestReplace:
    def _source(self, conn, team, cid):
        return str(conn.execute(
            text("INSERT INTO sources (user_id, name, connection_id) VALUES (:u, 'Docs', CAST(:c AS uuid)) "
                 "RETURNING id"),
            {"u": principal_id(team), "c": cid},
        ).scalar())

    def test_another_admin_reconnects_with_their_account_in_place(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionReconnect

        old = _team_row(pg_conn, team, "adam", label="adam@example.com",
                        secrets={"token_info": {"access_token": "old-at", "refresh_token": "old-rt"}})
        cid = str(old["id"])
        source_id = self._source(pg_conn, team, cid)
        revoked = []
        with _signing_in(pg_conn, account="ana@example.com"), patch.object(
            service, "revoke_at_provider", side_effect=lambda row, secrets: revoked.append(secrets) or True,
        ):
            started = _call(app, ConnectionReconnect, "post", "/x", "ana", args=[cid])
            assert started.status_code == 200
            assert started.get_json()["replace"] is True
            flow = oauth_flows.peek(pg_conn, started.get_json()["state"])
            assert (flow["owner_id"], flow["replace_account"]) == (principal_id(team), True)
            resp = _complete(app, "ana", started.get_json()["state"])

        assert resp.status_code == 200 and resp.get_json()["connection_id"] == cid
        row = ConnectorSessionsRepository(pg_conn).get(cid)
        assert (row["connected_by"], row["account_label"], row["status"]) == ("ana", "ana@example.com", "connected")
        assert row["last_error"] is None
        assert decrypt_json(row["encrypted_credentials"], principal_id(team))["token_info"]["access_token"] == "new-at"
        assert revoked == [{"token_info": {"access_token": "old-at", "refresh_token": "old-rt"}}]
        assert str(pg_conn.execute(
            text("SELECT connection_id FROM sources WHERE id = CAST(:s AS uuid)"), {"s": source_id},
        ).scalar()) == cid
        [(actor, meta)] = _audit_events(pg_conn, "team.connection_reconnected")
        assert actor == "ana"
        assert meta == {"team_id": team, "connection_id": cid, "replaced": True, "previous_connected_by": "adam"}

    def test_the_same_admin_reconnects_the_same_row(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionReconnect

        old = _team_row(pg_conn, team, "adam", label="adam@example.com")
        with _signing_in(pg_conn, account="adam@example.com"):
            started = _call(app, ConnectionReconnect, "post", "/x", "adam", args=[str(old["id"])])
            flow = oauth_flows.peek(pg_conn, started.get_json()["state"])
            resp = _complete(app, "adam", started.get_json()["state"])

        assert started.get_json()["replace"] is False and flow["replace_account"] is False
        assert resp.get_json()["connection_id"] == str(old["id"])
        assert ConnectorSessionsRepository(pg_conn).get(str(old["id"]))["connected_by"] == "adam"

    def test_an_account_the_team_already_has_is_refused(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionReconnect

        old = _team_row(pg_conn, team, "adam", label="adam@example.com")
        other = _team_row(pg_conn, team, "adam", label="ana@example.com")
        with _signing_in(pg_conn, account="ana@example.com"), patch.object(service, "revoke_at_provider") as revoke:
            started = _call(app, ConnectionReconnect, "post", "/x", "ana", args=[str(old["id"])])
            resp = _complete(app, "ana", started.get_json()["state"])

        assert resp.status_code == 409
        assert resp.get_json()["error"] == "account_already_connected"
        assert resp.get_json()["connection_id"] == str(other["id"])
        row = ConnectorSessionsRepository(pg_conn).get(str(old["id"]))
        assert (row["connected_by"], row["account_label"]) == ("adam", "adam@example.com")
        revoke.assert_not_called()

    def test_api_key_reconnect_by_another_admin_names_them(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionReconnect

        old = _team_row(pg_conn, team, "adam", provider="telegram", auth_kind="api_key",
                        secrets={"credentials": {"token": "123:old"}})
        with _db(pg_conn):
            resp = _call(app, ConnectionReconnect, "post", "/x", "ana", body={"credentials": {"token": "123:new"}},
                         args=[str(old["id"])])

        assert resp.status_code == 200
        row = ConnectorSessionsRepository(pg_conn).get(str(old["id"]))
        assert row["connected_by"] == "ana"
        assert decrypt_json(row["encrypted_credentials"], principal_id(team))["credentials"]["token"] == "123:new"
        [(_, meta)] = _audit_events(pg_conn, "team.connection_reconnected")
        assert meta["previous_connected_by"] == "adam" and meta["replaced"] is True

    def test_api_key_replace_keeps_nothing_of_the_old_account(self, app, pg_conn, team):
        """Another Admin's key replaces the account: every field is theirs, none of the old ones stay."""
        from docsgpt.api.connector.connections import ConnectionReconnect

        old = _team_row(pg_conn, team, "adam", provider="telegram", auth_kind="api_key", label="…dold",
                        secrets={"credentials": {"token": "123:adam-old", "chat_id": "-100"}})
        cid = str(old["id"])
        with _db(pg_conn):
            partial = _call(app, ConnectionReconnect, "post", "/x", "ana",
                            body={"credentials": {"chat_id": "-200"}}, args=[cid])
            unchanged = ConnectorSessionsRepository(pg_conn).get(cid)
            resp = _call(app, ConnectionReconnect, "post", "/x", "ana",
                         body={"credentials": {"token": "123:ana-new-key"}}, args=[cid])

        assert partial.status_code == 400
        assert unchanged["connected_by"] == "adam"
        assert decrypt_json(unchanged["encrypted_credentials"], principal_id(team))["credentials"]["token"] == (
            "123:adam-old"
        )
        assert resp.status_code == 200
        row = ConnectorSessionsRepository(pg_conn).get(cid)
        assert decrypt_json(row["encrypted_credentials"], principal_id(team))["credentials"] == {
            "token": "123:ana-new-key",
        }
        assert (row["connected_by"], row["account_label"]) == ("ana", "…-key")

    def test_api_key_replace_with_a_key_the_team_has_is_refused(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionReconnect

        old = _team_row(pg_conn, team, "adam", provider="telegram", auth_kind="api_key", label="…dold",
                        secrets={"credentials": {"token": "123:adam-old"}})
        other = _team_row(pg_conn, team, "ana", provider="telegram", auth_kind="api_key", label="…-key",
                          secrets={"credentials": {"token": "123:ana-new-key"}})
        with _db(pg_conn):
            resp = _call(app, ConnectionReconnect, "post", "/x", "ana",
                         body={"credentials": {"token": "123:ana-new-key"}}, args=[str(old["id"])])

        assert resp.status_code == 409
        assert resp.get_json()["error"] == "account_already_connected"
        assert resp.get_json()["connection_id"] == str(other["id"])
        assert ConnectorSessionsRepository(pg_conn).get(str(old["id"]))["connected_by"] == "adam"

    def test_api_key_replace_takes_a_free_label(self, app, pg_conn, team):
        """Another key with the same hint keeps its label; the replaced account gets a numbered one."""
        from docsgpt.api.connector.connections import ConnectionReconnect

        old = _team_row(pg_conn, team, "adam", provider="telegram", auth_kind="api_key", label="…dold",
                        secrets={"credentials": {"token": "123:adam-old"}})
        _team_row(pg_conn, team, "ana", provider="telegram", auth_kind="api_key", label="…-key",
                  secrets={"credentials": {"token": "999:other-key"}})
        with _db(pg_conn):
            resp = _call(app, ConnectionReconnect, "post", "/x", "ana",
                         body={"credentials": {"token": "123:ana-new-key"}}, args=[str(old["id"])])

        assert resp.status_code == 200
        assert ConnectorSessionsRepository(pg_conn).get(str(old["id"]))["account_label"] == "…-key (2)"

    def test_github_key_replace_names_the_new_account(self, app, pg_conn, team):
        from docsgpt.api.connector.connections import ConnectionReconnect

        old = _team_row(pg_conn, team, "adam", provider="github", auth_kind="api_key", label="adam-gh",
                        secrets={"credentials": {"access_token": "ghp_adam_old"}})
        with _db(pg_conn), patch("docsgpt.connectors.github.token_account", return_value="ana-gh") as whose:
            resp = _call(app, ConnectionReconnect, "post", "/x", "ana",
                         body={"credentials": {"access_token": "ghp_ana_new"}}, args=[str(old["id"])])

        assert resp.status_code == 200
        whose.assert_called_once_with("ghp_ana_new")
        row = ConnectorSessionsRepository(pg_conn).get(str(old["id"]))
        assert (row["connected_by"], row["account_label"]) == ("ana", "ana-gh")

    def test_the_same_admin_updates_part_of_their_key(self, app, pg_conn, team):
        """Whoever connected the account may change one field; the others stay."""
        from docsgpt.api.connector.connections import ConnectionReconnect

        old = _team_row(pg_conn, team, "adam", provider="telegram", auth_kind="api_key", label="…dold",
                        secrets={"credentials": {"token": "123:adam-old", "chat_id": "-100"}})
        with _db(pg_conn):
            resp = _call(app, ConnectionReconnect, "post", "/x", "adam",
                         body={"credentials": {"chat_id": "-200"}}, args=[str(old["id"])])

        assert resp.status_code == 200
        row = ConnectorSessionsRepository(pg_conn).get(str(old["id"]))
        assert decrypt_json(row["encrypted_credentials"], principal_id(team))["credentials"] == {
            "token": "123:adam-old", "chat_id": "-200",
        }
        assert (row["connected_by"], row["account_label"]) == ("adam", "…dold")


class TestCompleteOAuthReplace:
    def test_rewrites_in_place_after_revoking_the_old_grant(self, pg_conn, team):
        old = _team_row(pg_conn, team, "adam", label="adam@example.com",
                        secrets={"token_info": {"refresh_token": "old-rt"}})
        seen = []

        def revoke(row, secrets):
            # Still the old account when its grant is revoked.
            seen.append((ConnectorSessionsRepository(pg_conn).get(str(old["id"]))["account_label"], secrets))
            return True

        with patch.object(service, "revoke_at_provider", side_effect=revoke):
            row = service.complete_oauth(pg_conn, old, "google_drive", {"access_token": "n"}, "ana@example.com",
                                         connected_by="ana", replace=True)

        assert seen == [("adam@example.com", {"token_info": {"refresh_token": "old-rt"}})]
        assert str(row["id"]) == str(old["id"])
        assert (row["connected_by"], row["account_label"], row["user_email"]) == ("ana", "ana@example.com",
                                                                                 "ana@example.com")

    def test_the_same_account_keeps_its_grant(self, pg_conn, team):
        """Revoking would also end the grant just made for the same account."""
        old = _team_row(pg_conn, team, "adam", label="drive@example.com")
        with patch.object(service, "revoke_at_provider") as revoke:
            row = service.complete_oauth(pg_conn, old, "google_drive", {"access_token": "n"}, "drive@example.com",
                                         connected_by="ana", replace=True)

        revoke.assert_not_called()
        assert row["connected_by"] == "ana"

    def test_a_personal_row_is_never_replaced(self, pg_conn):
        old = _row(pg_conn, "lena")
        with pytest.raises(ValueError):
            service.complete_oauth(pg_conn, old, "google_drive", {"access_token": "n"}, "x@example.com",
                                   connected_by="lena", replace=True)

    def test_account_already_connected(self, pg_conn, team):
        old = _team_row(pg_conn, team, "adam", label="adam@example.com")
        other = _team_row(pg_conn, team, "adam", label="ana@example.com")
        with pytest.raises(service.AccountAlreadyConnected) as taken:
            service.complete_oauth(pg_conn, old, "google_drive", {"access_token": "n"}, "ana@example.com",
                                   connected_by="ana", replace=True)
        assert taken.value.connection_id == str(other["id"])
