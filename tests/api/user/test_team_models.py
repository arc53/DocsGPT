"""A team's custom models: an Admin adds one for the team, every member sees and uses it.

The team's principal owns the row and seals its key, and the row records the person who added it. Viewers
and Editors read it without its base URL, Admins and the Owner manage it, and anyone outside the team is told
it doesn't exist. A model is the team's only when the request says so (``owner=team``); routes about one
model go by the row's owner and ignore the workspace header. Tokens may read a team's models but never
change one.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
from docsgpt.security.encryption import decrypt_credentials
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

ROLES = {"alice": "owner", "ana": "admin", "eddie": "editor", "vi": "viewer", "mallory": None}
MANAGERS = ("alice", "ana")


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture(autouse=True)
def _registry():
    from docsgpt.core.model_registry import ModelRegistry

    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


@pytest.fixture(autouse=True)
def _public_dns():
    """Every base URL resolves to a public address, so the SSRF guard passes without the network."""
    public = [(None, None, None, None, ("104.18.0.1", 0))]
    with patch("docsgpt.security.safe_url.socket.getaddrinfo", return_value=public):
        yield


@pytest.fixture
def team(pg_conn):
    """Team Ops: alice owns it; ana is an Admin, eddie an Editor, vi a Viewer. mallory is outside."""
    users = UsersRepository(pg_conn)
    for user in ROLES:
        users.upsert(user, email=f"{user}@x.io")
    row = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(row["id"])
    members = TeamMembersRepository(pg_conn)
    for user, role in (("ana", "team_admin"), ("eddie", "team_editor"), ("vi", "team_viewer")):
        members.add_member(tid, user, role=role)
    return tid


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.api.user.models.routes", db_session=_yield, db_readonly=_yield), \
            patch("docsgpt.workspaces.context.db_readonly", _yield), \
            patch("docsgpt.storage.db.session.db_readonly", _yield):
        yield


def _pat(user: str, scopes=("models:read", "models:write")) -> dict:
    return {"sub": user, "auth_method": "pat", "pat_id": "t1", "scopes": list(scopes), "resource_filter": {}}


def _call(app, resource, method, user, *, path="/api/user/models", body=None, team=None, args=(), token=None):
    headers = {WORKSPACE_HEADER: team} if team else {}
    with app.test_request_context(path, method=method.upper(), json=body, headers=headers):
        from flask import request

        request.decoded_token = token if token is not None else ({"sub": user} if user else None)
        return getattr(resource(), method)(*args)


def _model(conn, owner: str, *, created_by=None, name="Team Llama", key="sk-team", enabled=True) -> dict:
    return UserCustomModelsRepository(conn).create(
        user_id=owner, upstream_model_id="llama-3", display_name=name, base_url="https://llm.example.com/v1",
        api_key_plaintext=key, enabled=enabled, created_by=created_by,
    )


def _team_model(conn, team: str, **kw) -> dict:
    kw.setdefault("created_by", "ana")
    return _model(conn, principal_id(team), **kw)


def _row(conn, model_id) -> dict | None:
    return UserCustomModelsRepository(conn).get_by_id(str(model_id))


def _audit(conn, event):
    return [
        r[0] for r in conn.execute(
            text("SELECT metadata FROM auth_events WHERE event = :e ORDER BY created_at"), {"e": event},
        ).fetchall()
    ]


_NEW = {
    "upstream_model_id": "llama-3", "display_name": "Team Llama", "base_url": "https://llm.example.com/v1",
    "api_key": "sk-new",
}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.parametrize("user", MANAGERS)
    def test_an_admin_adds_a_model_for_the_team(self, app, pg_conn, team, user):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource

        with _db(pg_conn), patch("docsgpt.api.user.models.routes.ModelRegistry.invalidate_user") as invalidate:
            resp = _call(app, UserModelsCollectionResource, "post", user, body={**_NEW, "owner": "team"}, team=team)

        assert resp.status_code == 201, resp.get_json()
        body = resp.get_json()
        row = _row(pg_conn, body["id"])
        principal = principal_id(team)
        assert row["user_id"] == principal and row["created_by"] == user
        # The key is sealed for the team, not for the person who pasted it.
        assert decrypt_credentials(row["api_key_encrypted"], principal)["api_key"] == "sk-new"
        assert not decrypt_credentials(row["api_key_encrypted"], user)
        assert body["owner"] == "team" and body["team_id"] == team and body["source"] == "team"
        assert body["created_by"] == {"user_id": user, "label": f"{user}@x.io"}
        assert "manage" in body["allowed_actions"] and body["base_url"] == _NEW["base_url"]
        assert "api_key" not in body
        invalidate.assert_called_once_with(principal)

    def test_adding_one_is_audited(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource

        with _db(pg_conn):
            resp = _call(app, UserModelsCollectionResource, "post", "ana", body={**_NEW, "owner": "team"}, team=team)

        [meta] = _audit(pg_conn, "team.model_added")
        assert meta == {
            "team_id": team, "model_id": resp.get_json()["id"], "display_name": "Team Llama",
            "upstream_model_id": "llama-3", "copied": False,
        }

    @pytest.mark.parametrize("user,status,code", [
        ("eddie", 403, "workspace_role_required"),
        ("vi", 403, "workspace_role_required"),
        ("mallory", 404, "workspace_not_found"),
    ])
    def test_below_admin_nothing_is_added(self, app, pg_conn, team, user, status, code):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource

        with _db(pg_conn):
            resp = _call(app, UserModelsCollectionResource, "post", user, body={**_NEW, "owner": "team"}, team=team)

        assert resp.status_code == status and resp.get_json()["error"] == code
        assert UserCustomModelsRepository(pg_conn).list_for_user(principal_id(team)) == []
        assert UserCustomModelsRepository(pg_conn).list_for_user(user) == []

    def test_owner_team_needs_a_team_workspace(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource

        with _db(pg_conn):
            resp = _call(app, UserModelsCollectionResource, "post", "ana", body={**_NEW, "owner": "team"})
            bad = _call(app, UserModelsCollectionResource, "post", "ana", body={**_NEW, "owner": "them"}, team=team)

        assert resp.status_code == 400 and resp.get_json()["error"] == "team_workspace_required"
        assert bad.status_code == 400 and bad.get_json()["error"] == "invalid_owner"
        assert UserCustomModelsRepository(pg_conn).list_for_user("ana") == []

    def test_the_header_alone_never_makes_a_team_model(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource

        with _db(pg_conn), patch("docsgpt.api.user.models.routes.ModelRegistry.invalidate_user") as invalidate:
            resp = _call(app, UserModelsCollectionResource, "post", "ana", body=_NEW, team=team)

        assert resp.status_code == 201
        body = resp.get_json()
        row = _row(pg_conn, body["id"])
        assert row["user_id"] == "ana" and row["created_by"] == "ana"
        assert body["owner"] == "personal" and body["source"] == "user" and body["created_by"] is None
        invalidate.assert_called_once_with("ana")
        assert _audit(pg_conn, "team.model_added") == []


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestList:
    def test_a_viewer_lists_the_teams_models_without_the_endpoint(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource

        model = _team_model(pg_conn, team)
        _model(pg_conn, "vi", name="Mine")
        with _db(pg_conn):
            resp = _call(app, UserModelsCollectionResource, "get", "vi", path="/api/user/models?owner=team", team=team)

        assert resp.status_code == 200
        [listed] = resp.get_json()["models"]
        assert listed["id"] == str(model["id"]) and listed["owner"] == "team" and listed["source"] == "team"
        assert listed["allowed_actions"] == ["view", "use"]
        assert listed["created_by"] == {"user_id": "ana", "label": "ana@x.io"}
        assert "base_url" not in listed

    def test_an_admin_sees_the_endpoint(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource

        _team_model(pg_conn, team)
        with _db(pg_conn):
            resp = _call(app, UserModelsCollectionResource, "get", "ana", path="/api/user/models?owner=team", team=team)

        [listed] = resp.get_json()["models"]
        assert listed["base_url"] == "https://llm.example.com/v1"
        assert listed["allowed_actions"] == ["view", "use", "manage"]

    def test_without_owner_team_a_team_header_lists_the_callers_own(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource

        _team_model(pg_conn, team)
        own = _model(pg_conn, "vi", name="Mine")
        with _db(pg_conn):
            resp = _call(app, UserModelsCollectionResource, "get", "vi", team=team)

        assert [m["id"] for m in resp.get_json()["models"]] == [str(own["id"])]
        assert resp.get_json()["models"][0]["owner"] == "personal"

    def test_an_outsider_cant_list_a_team(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource

        _team_model(pg_conn, team)
        with _db(pg_conn):
            outsider = _call(
                app, UserModelsCollectionResource, "get", "mallory", path="/api/user/models?owner=team", team=team,
            )
            no_team = _call(app, UserModelsCollectionResource, "get", "ana", path="/api/user/models?owner=team")

        assert outsider.status_code == 404 and outsider.get_json()["error"] == "workspace_not_found"
        assert no_team.status_code == 400 and no_team.get_json()["error"] == "team_workspace_required"


# ---------------------------------------------------------------------------
# One model: get, patch, delete, test
# ---------------------------------------------------------------------------


def _expected(user: str, minimum: str) -> int:
    role = ROLES[user]
    if role is None:
        return 404
    rank = ("viewer", "editor", "admin", "owner")
    return 200 if rank.index(role) >= rank.index(minimum) else 403


class TestOneModel:
    @pytest.mark.parametrize("user", list(ROLES))
    def test_get(self, app, pg_conn, team, user):
        from docsgpt.api.user.models.routes import UserModelResource

        model = _team_model(pg_conn, team)
        mid = str(model["id"])
        with _db(pg_conn):
            resp = _call(app, UserModelResource, "get", user, path=f"/api/user/models/{mid}", args=[mid])

        assert resp.status_code == _expected(user, "viewer")
        if resp.status_code == 404:
            assert resp.get_json()["error"] == "model_not_found"
        else:
            assert resp.get_json()["owner"] == "team"
            assert ("base_url" in resp.get_json()) is (user in MANAGERS)

    @pytest.mark.parametrize("user", list(ROLES))
    def test_patch(self, app, pg_conn, team, user):
        from docsgpt.api.user.models.routes import UserModelResource

        model = _team_model(pg_conn, team)
        mid = str(model["id"])
        with _db(pg_conn):
            resp = _call(app, UserModelResource, "patch", user, path=f"/api/user/models/{mid}",
                         body={"display_name": "Renamed"}, args=[mid])

        status = _expected(user, "admin")
        assert resp.status_code == status
        if status == 403:
            assert resp.get_json()["error"] == "model_admin_required"
        if status == 404:
            assert resp.get_json()["error"] == "model_not_found"
        assert _row(pg_conn, mid)["display_name"] == ("Renamed" if status == 200 else "Team Llama")

    @pytest.mark.parametrize("user", list(ROLES))
    def test_delete(self, app, pg_conn, team, user):
        from docsgpt.api.user.models.routes import UserModelResource

        model = _team_model(pg_conn, team)
        mid = str(model["id"])
        with _db(pg_conn):
            resp = _call(app, UserModelResource, "delete", user, path=f"/api/user/models/{mid}", args=[mid])

        status = _expected(user, "admin")
        assert resp.status_code == status
        assert (_row(pg_conn, mid) is None) is (status == 200)

    @pytest.mark.parametrize("user", list(ROLES))
    def test_test_by_id(self, app, pg_conn, team, user):
        from docsgpt.api.user.models.routes import UserModelTestResource

        model = _team_model(pg_conn, team)
        mid = str(model["id"])
        with _db(pg_conn), patch(
            "docsgpt.api.user.models.routes._run_connection_test", return_value=({"ok": True}, 200),
        ) as run:
            resp = _call(app, UserModelTestResource, "post", user, path=f"/api/user/models/{mid}/test", body={},
                         args=[mid])

        status = _expected(user, "admin")
        assert resp.status_code == status
        if status == 200:
            # The stored key is opened with the team's principal.
            assert run.call_args.args[1] == "sk-team"
        else:
            run.assert_not_called()

    @pytest.mark.parametrize("header", [None, "personal", "other-team"])
    def test_id_routes_ignore_the_header(self, app, pg_conn, team, header):
        from docsgpt.api.user.models.routes import UserModelResource

        other = str(TeamsRepository(pg_conn).create("Dev", f"dev-{uuid.uuid4().hex[:6]}", "ana")["id"])
        model = _team_model(pg_conn, team)
        mid = str(model["id"])
        sent = other if header == "other-team" else header
        with _db(pg_conn):
            got = _call(app, UserModelResource, "get", "ana", path=f"/api/user/models/{mid}", team=sent, args=[mid])
            patched = _call(app, UserModelResource, "patch", "ana", path=f"/api/user/models/{mid}", team=sent,
                            body={"enabled": False}, args=[mid])

        assert got.status_code == 200 and got.get_json()["team_id"] == team
        assert patched.status_code == 200 and _row(pg_conn, mid)["enabled"] is False

    def test_someone_elses_personal_model_is_not_found_from_the_team(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource

        theirs = _model(pg_conn, "eddie", name="Eddie's")
        mid = str(theirs["id"])
        with _db(pg_conn):
            resp = _call(app, UserModelResource, "get", "ana", path=f"/api/user/models/{mid}", team=team, args=[mid])
            deleted = _call(app, UserModelResource, "delete", "alice", path=f"/api/user/models/{mid}", team=team,
                            args=[mid])

        assert resp.status_code == 404 and resp.get_json()["error"] == "model_not_found"
        assert deleted.status_code == 404 and _row(pg_conn, mid) is not None

    def test_a_personal_model_still_works_for_its_owner(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource

        mine = _model(pg_conn, "eddie", name="Eddie's")
        mid = str(mine["id"])
        with _db(pg_conn):
            resp = _call(app, UserModelResource, "patch", "eddie", path=f"/api/user/models/{mid}", team=team,
                         body={"display_name": "Still mine"}, args=[mid])

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["owner"] == "personal" and body["base_url"] and body["allowed_actions"] == ["view", "use", "manage"]

    def test_replacing_the_key_reseals_it_for_the_team_and_is_audited(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource

        model = _team_model(pg_conn, team)
        mid = str(model["id"])
        principal = principal_id(team)
        with _db(pg_conn), patch("docsgpt.api.user.models.routes.ModelRegistry.invalidate_user") as invalidate:
            resp = _call(app, UserModelResource, "patch", "alice", path=f"/api/user/models/{mid}",
                         body={"api_key": "sk-rotated", "display_name": "Renamed", "enabled": False}, args=[mid])

        assert resp.status_code == 200
        row = _row(pg_conn, mid)
        assert decrypt_credentials(row["api_key_encrypted"], principal)["api_key"] == "sk-rotated"
        # The person who added it stays on record.
        assert row["created_by"] == "ana"
        invalidate.assert_called_once_with(principal)
        [meta] = _audit(pg_conn, "team.model_updated")
        assert meta["team_id"] == team and meta["model_id"] == mid and meta["key_replaced"] is True
        assert sorted(meta["fields"]) == ["display_name", "enabled"]

    def test_deleting_one_names_its_usage_and_is_audited(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource

        model = _team_model(pg_conn, team)
        mid = str(model["id"])
        principal = principal_id(team)
        agent = AgentsRepository(pg_conn).create(principal, "Helper", "draft", default_model_id=mid)
        with _db(pg_conn), patch("docsgpt.api.user.models.routes.ModelRegistry.invalidate_user") as invalidate:
            resp = _call(app, UserModelResource, "delete", "ana", path=f"/api/user/models/{mid}", args=[mid])

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["usage"]["agents"] == [{"id": str(agent["id"]), "name": "Helper"}]
        assert body["usage"]["workflows"] == []
        invalidate.assert_called_once_with(principal)
        [meta] = _audit(pg_conn, "team.model_removed")
        assert meta == {"team_id": team, "model_id": mid, "display_name": "Team Llama", "agents": 1, "workflows": 0}

    def test_personal_writes_are_not_audited_on_a_team(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource

        mine = _model(pg_conn, "ana")
        mid = str(mine["id"])
        with _db(pg_conn):
            _call(app, UserModelResource, "patch", "ana", path=f"/api/user/models/{mid}", body={"enabled": False},
                  team=team, args=[mid])
            resp = _call(app, UserModelResource, "delete", "ana", path=f"/api/user/models/{mid}", team=team,
                         args=[mid])

        assert resp.get_json() == {"success": True}
        assert _audit(pg_conn, "team.model_updated") == [] and _audit(pg_conn, "team.model_removed") == []


class TestStoredKeyStaysWithItsHost:
    """The stored key is sent only to the host it was saved for: pointing a model at another origin needs the key."""

    @staticmethod
    def _saved(conn, team, owner):
        return _team_model(conn, team) if owner == "team" else _model(conn, "ana", name="Ana's")

    @pytest.mark.parametrize("owner", ["team", "personal"])
    def test_a_test_against_a_new_host_without_a_key_is_refused(self, app, pg_conn, team, owner):
        from docsgpt.api.user.models.routes import UserModelTestResource

        mid = str(self._saved(pg_conn, team, owner)["id"])
        with _db(pg_conn), patch(
            "docsgpt.api.user.models.routes._run_connection_test", return_value=({"ok": True}, 200),
        ) as run:
            resp = _call(app, UserModelTestResource, "post", "ana", path=f"/api/user/models/{mid}/test",
                         body={"base_url": "https://attacker.example.net/v1"}, args=[mid])

        assert resp.status_code == 400
        assert resp.get_json()["code"] == "api_key_required_for_new_host"
        run.assert_not_called()

    @pytest.mark.parametrize("url", ["http://llm.example.com/v1", "https://llm.example.com:8443/v1"])
    def test_another_scheme_or_port_is_another_host(self, app, pg_conn, team, url):
        from docsgpt.api.user.models.routes import UserModelTestResource

        mid = str(_team_model(pg_conn, team)["id"])
        with _db(pg_conn), patch(
            "docsgpt.api.user.models.routes._run_connection_test", return_value=({"ok": True}, 200),
        ) as run:
            resp = _call(app, UserModelTestResource, "post", "ana", path=f"/api/user/models/{mid}/test",
                         body={"base_url": url}, args=[mid])

        assert resp.status_code == 400
        run.assert_not_called()

    def test_a_test_against_a_new_host_with_a_key_sends_that_key(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelTestResource

        mid = str(_team_model(pg_conn, team)["id"])
        with _db(pg_conn), patch(
            "docsgpt.api.user.models.routes._run_connection_test", return_value=({"ok": True}, 200),
        ) as run:
            resp = _call(app, UserModelTestResource, "post", "ana", path=f"/api/user/models/{mid}/test",
                         body={"base_url": "https://other.example.net/v1", "api_key": "sk-other"}, args=[mid])

        assert resp.status_code == 200
        assert run.call_args.args[:2] == ("https://other.example.net/v1", "sk-other")

    @pytest.mark.parametrize("url", ["https://llm.example.com/v2", "https://LLM.Example.com:443/v1/"])
    def test_the_same_host_keeps_the_stored_key(self, app, pg_conn, team, url):
        from docsgpt.api.user.models.routes import UserModelTestResource

        mid = str(_team_model(pg_conn, team)["id"])
        with _db(pg_conn), patch(
            "docsgpt.api.user.models.routes._run_connection_test", return_value=({"ok": True}, 200),
        ) as run:
            resp = _call(app, UserModelTestResource, "post", "ana", path=f"/api/user/models/{mid}/test",
                         body={"base_url": url}, args=[mid])

        assert resp.status_code == 200
        assert run.call_args.args[1] == "sk-team"

    @pytest.mark.parametrize("owner", ["team", "personal"])
    def test_moving_a_model_to_a_new_host_without_a_key_is_refused(self, app, pg_conn, team, owner):
        from docsgpt.api.user.models.routes import UserModelResource

        mid = str(self._saved(pg_conn, team, owner)["id"])
        with _db(pg_conn), patch("docsgpt.api.user.models.routes.ModelRegistry.invalidate_user"):
            resp = _call(app, UserModelResource, "patch", "ana", path=f"/api/user/models/{mid}",
                         body={"base_url": "https://attacker.example.net/v1", "api_key": ""}, args=[mid])

        assert resp.status_code == 400
        assert resp.get_json()["error"] == "api_key_required_for_new_host"
        assert _row(pg_conn, mid)["base_url"] == "https://llm.example.com/v1"
        assert _audit(pg_conn, "team.model_updated") == []

    def test_moving_a_model_to_a_new_host_with_a_key_replaces_both(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource

        mid = str(_team_model(pg_conn, team)["id"])
        with _db(pg_conn), patch("docsgpt.api.user.models.routes.ModelRegistry.invalidate_user"):
            resp = _call(app, UserModelResource, "patch", "ana", path=f"/api/user/models/{mid}",
                         body={"base_url": "https://other.example.net/v1", "api_key": "sk-other"}, args=[mid])

        assert resp.status_code == 200
        row = _row(pg_conn, mid)
        assert row["base_url"] == "https://other.example.net/v1"
        assert decrypt_credentials(row["api_key_encrypted"], principal_id(team))["api_key"] == "sk-other"

    def test_a_new_path_on_the_same_host_keeps_the_key(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource

        mid = str(_team_model(pg_conn, team)["id"])
        with _db(pg_conn), patch("docsgpt.api.user.models.routes.ModelRegistry.invalidate_user"):
            resp = _call(app, UserModelResource, "patch", "ana", path=f"/api/user/models/{mid}",
                         body={"base_url": "https://llm.example.com/v2"}, args=[mid])

        assert resp.status_code == 200
        row = _row(pg_conn, mid)
        assert row["base_url"] == "https://llm.example.com/v2"
        assert decrypt_credentials(row["api_key_encrypted"], principal_id(team))["api_key"] == "sk-team"


class TestPayloadTest:
    @pytest.mark.parametrize("user,status", [("ana", 200), ("alice", 200), ("eddie", 403), ("vi", 403),
                                             ("mallory", 404)])
    def test_owner_team_needs_an_admin(self, app, pg_conn, team, user, status):
        from docsgpt.api.user.models.routes import UserModelTestPayloadResource

        with _db(pg_conn), patch(
            "docsgpt.api.user.models.routes._run_connection_test", return_value=({"ok": True}, 200),
        ) as run:
            resp = _call(app, UserModelTestPayloadResource, "post", user, path="/api/user/models/test",
                         body={**_NEW, "owner": "team"}, team=team)

        assert resp.status_code == status
        assert run.called is (status == 200)

    def test_without_owner_it_is_the_callers_own_test(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelTestPayloadResource

        with _db(pg_conn), patch(
            "docsgpt.api.user.models.routes._run_connection_test", return_value=({"ok": True}, 200),
        ):
            resp = _call(app, UserModelTestPayloadResource, "post", "vi", path="/api/user/models/test", body=_NEW,
                         team=team)

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/models in a team
# ---------------------------------------------------------------------------


class TestModelsList:
    def _list(self, app, pg_conn, user, team=None):
        from docsgpt.api.user.models.routes import ModelsListResource

        with _db(pg_conn):
            return _call(app, ModelsListResource, "get", user, path="/api/models", team=team)

    def test_a_team_lists_its_enabled_models_without_the_endpoint(self, app, pg_conn, team):
        model = _team_model(pg_conn, team)
        off = _team_model(pg_conn, team, name="Off", enabled=False)
        mine = _model(pg_conn, "vi", name="Mine")

        resp = self._list(app, pg_conn, "vi", team)

        assert resp.status_code == 200
        entries = {m["id"]: m for m in resp.get_json()["models"]}
        listed = entries[str(model["id"])]
        assert listed["source"] == "team" and "base_url" not in listed
        assert str(off["id"]) not in entries
        # A person's own models are never offered in a team.
        assert str(mine["id"]) not in entries
        assert all(m["source"] != "user" for m in entries.values())
        assert resp.get_json()["count"] == len(entries)

    def test_an_admin_gets_no_endpoint_here_either(self, app, pg_conn, team):
        model = _team_model(pg_conn, team)
        resp = self._list(app, pg_conn, "ana", team)
        listed = {m["id"]: m for m in resp.get_json()["models"]}[str(model["id"])]
        assert "base_url" not in listed

    def test_personal_never_lists_a_teams_models(self, app, pg_conn, team):
        model = _team_model(pg_conn, team)
        mine = _model(pg_conn, "vi", name="Mine")

        resp = self._list(app, pg_conn, "vi")

        ids = {m["id"] for m in resp.get_json()["models"]}
        assert str(mine["id"]) in ids and str(model["id"]) not in ids

    def test_an_outsider_is_404(self, app, pg_conn, team):
        _team_model(pg_conn, team)
        resp = self._list(app, pg_conn, "mallory", team)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


class TestTokens:
    def test_a_token_reads_the_teams_models(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource, UserModelsCollectionResource

        model = _team_model(pg_conn, team)
        mid = str(model["id"])
        with _db(pg_conn):
            listed = _call(app, UserModelsCollectionResource, "get", "vi", path="/api/user/models?owner=team",
                           team=team, token=_pat("vi", ["models:read"]))
            got = _call(app, UserModelResource, "get", "vi", path=f"/api/user/models/{mid}", args=[mid],
                        token=_pat("vi", ["models:read"]))

        assert [m["id"] for m in listed.get_json()["models"]] == [mid]
        assert got.status_code == 200

    def test_a_token_cant_add_a_team_model(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelsCollectionResource, UserModelTestPayloadResource

        with _db(pg_conn), patch(
            "docsgpt.api.user.models.routes._run_connection_test", return_value=({"ok": True}, 200),
        ) as run:
            created = _call(app, UserModelsCollectionResource, "post", "ana", body={**_NEW, "owner": "team"},
                            team=team, token=_pat("ana"))
            tested = _call(app, UserModelTestPayloadResource, "post", "ana", path="/api/user/models/test",
                           body={**_NEW, "owner": "team"}, team=team, token=_pat("ana"))

        assert created.status_code == 403 and created.get_json()["error"] == "not_available_to_tokens"
        assert tested.status_code == 403 and tested.get_json()["error"] == "not_available_to_tokens"
        run.assert_not_called()
        assert UserCustomModelsRepository(pg_conn).list_for_user(principal_id(team)) == []

    def test_a_token_cant_change_a_team_model(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource, UserModelTestResource

        model = _team_model(pg_conn, team)
        mid = str(model["id"])
        with _db(pg_conn), patch(
            "docsgpt.api.user.models.routes._run_connection_test", return_value=({"ok": True}, 200),
        ) as run:
            patched = _call(app, UserModelResource, "patch", "ana", path=f"/api/user/models/{mid}",
                            body={"display_name": "X"}, args=[mid], token=_pat("ana"))
            tested = _call(app, UserModelTestResource, "post", "ana", path=f"/api/user/models/{mid}/test", body={},
                           args=[mid], token=_pat("ana"))
            deleted = _call(app, UserModelResource, "delete", "ana", path=f"/api/user/models/{mid}", args=[mid],
                            token=_pat("ana"))

        for resp in (patched, tested, deleted):
            assert resp.status_code == 403 and resp.get_json()["error"] == "not_available_to_tokens"
        run.assert_not_called()
        row = _row(pg_conn, mid)
        assert row is not None and row["display_name"] == "Team Llama"

    def test_a_token_of_an_outsider_still_gets_404(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource

        mid = str(_team_model(pg_conn, team)["id"])
        with _db(pg_conn):
            resp = _call(app, UserModelResource, "delete", "mallory", path=f"/api/user/models/{mid}", args=[mid],
                         token=_pat("mallory"))
        assert resp.status_code == 404

    def test_a_token_still_manages_its_persons_own_models(self, app, pg_conn, team):
        from docsgpt.api.user.models.routes import UserModelResource, UserModelsCollectionResource

        with _db(pg_conn):
            created = _call(app, UserModelsCollectionResource, "post", "ana", body=_NEW, team=team, token=_pat("ana"))
            mid = created.get_json()["id"]
            patched = _call(app, UserModelResource, "patch", "ana", path=f"/api/user/models/{mid}",
                            body={"display_name": "X"}, args=[mid], token=_pat("ana"))

        assert created.status_code == 201 and patched.status_code == 200

    def test_the_agent_tool_lists_a_teams_models_with_the_workspace(self):
        from docsgpt.api.pat.agent_tool import CATALOG

        [entry] = [a for a in CATALOG if a.name == "list_custom_models"]
        assert {"workspace", "owner"} <= set(entry.query)


# ---------------------------------------------------------------------------
# Registry, workflow node picker, save helper, team delete, repository
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_a_principals_layer_is_the_teams(self, pg_conn, team):
        from docsgpt.core.model_registry import ModelRegistry

        model = _team_model(pg_conn, team)
        mine = _model(pg_conn, "vi", name="Mine")
        with _db(pg_conn):
            registry = ModelRegistry.get_instance()
            team_entry = registry.get_model(str(model["id"]), user_id=principal_id(team))
            mine_entry = registry.get_model(str(mine["id"]), user_id="vi")

        # The key opens with the principal, so the model resolves for the team's runs.
        assert team_entry is not None and team_entry.source == "team" and team_entry.api_key == "sk-team"
        assert mine_entry.source == "user"

    def test_a_team_workflows_node_picker_lists_the_teams_models(self, pg_conn, team):
        from docsgpt.api.user.workflows.routes import _owner_models

        model = _team_model(pg_conn, team)
        with _db(pg_conn):
            listed = _owner_models(principal_id(team))
        assert [m["id"] for m in listed] == [str(model["id"])]
        assert listed[0]["source"] == "team"


class TestEndpointKey:
    """Two models are the same model when they point at the same endpoint: scheme and host ignore case, the path
    doesn't (a provider may put a tenant or deployment name in it)."""

    def test_scheme_and_host_ignore_case_and_a_trailing_slash(self):
        from docsgpt.workspaces.team_models import endpoint_key

        assert endpoint_key("HTTPS://LLM.Example.com/v1/", "llama-3") == endpoint_key(
            "https://llm.example.com/v1", "llama-3"
        )

    def test_the_path_keeps_its_case(self):
        from docsgpt.workspaces.team_models import endpoint_key, matching_model

        assert endpoint_key("https://llm.example.com/tenant/ALICE/v1", "m") != endpoint_key(
            "https://llm.example.com/tenant/alice/v1", "m"
        )
        rows = [{"id": "1", "base_url": "https://llm.example.com/tenant/alice/v1", "upstream_model_id": "m"}]
        assert matching_model(rows, "https://llm.example.com/tenant/ALICE/v1", "m") is None
        assert matching_model(rows, "https://LLM.example.com/tenant/alice/v1/", "m")["id"] == "1"


class TestUnownedCustomModels:
    def test_names_custom_models_the_owner_doesnt_own(self, pg_conn, team):
        from docsgpt.workspaces.team_models import unowned_custom_models

        principal = principal_id(team)
        team_model = str(_team_model(pg_conn, team)["id"])
        mine = str(_model(pg_conn, "vi")["id"])
        other_team = str(TeamsRepository(pg_conn).create("Dev", f"dev-{uuid.uuid4().hex[:6]}", "ana")["id"])
        theirs = str(_model(pg_conn, principal_id(other_team))["id"])
        ids = [team_model, mine.upper(), theirs, "gpt-4o", "", None, 7]

        assert unowned_custom_models(pg_conn, principal, ids) == [mine.upper(), theirs]
        assert unowned_custom_models(pg_conn, "vi", ids) == [team_model, theirs]
        assert unowned_custom_models(pg_conn, "vi", []) == []


class TestTeamDelete:
    def test_a_team_with_a_model_names_custom_models(self, pg_conn, team):
        _team_model(pg_conn, team)
        assert TeamsRepository(pg_conn).principal_holdings(team) == {"custom_model": 1}


class TestRepository:
    def test_get_by_id_ignores_the_owner_and_bad_ids(self, pg_conn, team):
        model = _team_model(pg_conn, team)
        repo = UserCustomModelsRepository(pg_conn)
        assert repo.get_by_id(str(model["id"]))["user_id"] == principal_id(team)
        assert repo.get_by_id("not-a-uuid") is None
        assert repo.get_by_id(str(uuid.uuid4())) is None

    def test_usage_lists_the_owners_agents_and_workflows(self, pg_conn, team):
        principal = principal_id(team)
        mid = str(_team_model(pg_conn, team)["id"])
        agents = AgentsRepository(pg_conn)
        by_default = agents.create(principal, "Default", "draft", default_model_id=mid)
        listed = agents.create(principal, "Listed", "draft", models=[mid.upper()])
        agents.create(principal, "Other", "draft", default_model_id="gpt-4o")
        # Someone else's agent naming it is not the team's usage.
        agents.create("vi", "Foreign", "draft", default_model_id=mid)
        workflow = pg_conn.execute(
            text("INSERT INTO workflows (user_id, name) VALUES (:u, 'Flow') RETURNING id::text"), {"u": principal},
        ).scalar()
        pg_conn.execute(
            text(
                "INSERT INTO workflow_nodes (workflow_id, graph_version, node_id, node_type, config) "
                "VALUES (CAST(:w AS uuid), 1, 'n1', 'agent', CAST(:c AS jsonb)), "
                "(CAST(:w AS uuid), 0, 'n2', 'agent', CAST(:old AS jsonb))"
            ),
            {"w": workflow, "c": f'{{"config": {{"model_id": "{mid}"}}}}', "old": f'{{"model_id": "{mid}"}}'},
        )

        usage = UserCustomModelsRepository(pg_conn).usage(principal, mid)

        assert sorted(a["id"] for a in usage["agents"]) == sorted([str(by_default["id"]), str(listed["id"])])
        assert usage["workflows"] == [{"id": workflow, "name": "Flow"}]
