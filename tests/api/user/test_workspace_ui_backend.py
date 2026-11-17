"""Backend additions the workspace UI reads.

- The paginated sources list splits by origin (``own`` / ``shared``) and counts each.
- ``/api/available_tools`` and ``/api/models`` leave out, in a team, what a team can't hold.
- A team item's share dialog names who pays for the agent's outside access.
- A refused membership change carries a stable error code.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn, *modules):
    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        for module in modules:
            for name in ("db_session", "db_readonly"):
                stack.enter_context(patch(f"{module}.{name}", _yield))
        yield


def _people(conn, *users):
    repo = UsersRepository(conn)
    for user in users:
        repo.upsert(user, email=f"{user}@x.io")


def _team(conn, owner="alice", members=(("adam", "team_admin"), ("eddie", "team_editor"), ("vera", "team_viewer"))):
    _people(conn, owner, *(u for u, _ in members))
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:8]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid


def _get(app, conn, resource_cls, path, modules, user="alice", team_id=None):
    headers = {WORKSPACE_HEADER: team_id} if team_id else {}
    with _patch_db(conn, *modules), app.test_request_context(path, headers=headers):
        from flask import request

        request.decoded_token = {"sub": user}
        return resource_cls().get()


# ---------------------------------------------------------------------------
# Sources: ?origin=own|shared|all
# ---------------------------------------------------------------------------

_SOURCES = ("docsgpt.api.user.sources.routes",)


class TestSourcesOrigin:
    @pytest.fixture
    def library(self, pg_conn):
        """Alice owns two sources; Bob shares one with her through a team."""
        _people(pg_conn, "alice", "bob")
        repo = SourcesRepository(pg_conn)
        mine = str(repo.create("mine", user_id="alice", type="local")["id"])
        mine_2 = str(repo.create("mine-2", user_id="alice", type="local")["id"])
        theirs = str(repo.create("theirs", user_id="bob", type="local")["id"])
        team = TeamsRepository(pg_conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", "bob")
        TeamMembersRepository(pg_conn).add_member(str(team["id"]), "alice")
        TeamResourceGrantsRepository(pg_conn).grant(
            str(team["id"]), "source", theirs, "bob", "bob", access_level="viewer"
        )
        return {"mine": mine, "mine-2": mine_2, "theirs": theirs}

    def _page(self, app, pg_conn, query="", team_id=None, user="alice"):
        from docsgpt.api.user.sources.routes import PaginatedSources

        return _get(
            app, pg_conn, PaginatedSources, f"/api/sources/paginated?rows=50{query}", _SOURCES,
            user=user, team_id=team_id,
        )

    def test_all_is_the_default_and_counts_both_origins(self, app, pg_conn, library):
        resp = self._page(app, pg_conn)
        assert resp.status_code == 200
        body = resp.json
        assert {row["id"] for row in body["paginated"]} == set(library.values())
        assert body["origin_counts"] == {"own": 2, "shared": 1}
        assert body["kind_counts"]["all"] == 3

    def test_own_lists_only_the_callers_sources(self, app, pg_conn, library):
        resp = self._page(app, pg_conn, "&origin=own")
        assert resp.status_code == 200
        body = resp.json
        assert {row["id"] for row in body["paginated"]} == {library["mine"], library["mine-2"]}
        assert body["total"] == 2
        assert body["kind_counts"]["all"] == 2
        assert body["kind_counts"]["shared"] == 0
        assert body["usage_counts"]["all"] == 2
        # The other origin's count stays, so the UI can show both sections' sizes.
        assert body["origin_counts"] == {"own": 2, "shared": 1}

    def test_shared_lists_only_what_others_share(self, app, pg_conn, library):
        resp = self._page(app, pg_conn, "&origin=shared")
        assert resp.status_code == 200
        body = resp.json
        assert [row["id"] for row in body["paginated"]] == [library["theirs"]]
        assert body["total"] == 1
        assert body["kind_counts"]["all"] == 1
        assert body["kind_counts"]["files"] == 1
        assert body["usage_counts"]["all"] == 1
        assert body["origin_counts"] == {"own": 2, "shared": 1}

    def test_origin_counts_follow_the_other_filters(self, app, pg_conn, library):
        resp = self._page(app, pg_conn, "&origin=shared&search=mine")
        body = resp.json
        assert body["paginated"] == []
        assert body["origin_counts"] == {"own": 2, "shared": 0}

    def test_in_a_team_shared_is_always_empty(self, app, pg_conn, library):
        tid = _team(pg_conn)
        team_source = str(SourcesRepository(pg_conn).create("team doc", user_id=principal_id(tid), type="local")["id"])
        # Bob's source shared with one of Alice's teams never enters a team list.
        TeamResourceGrantsRepository(pg_conn).grant(tid, "source", library["theirs"], "bob", "bob")

        shared = self._page(app, pg_conn, "&origin=shared", team_id=tid).json
        assert shared["paginated"] == []
        assert shared["total"] == 0
        assert shared["origin_counts"] == {"own": 1, "shared": 0}

        own = self._page(app, pg_conn, "&origin=own", team_id=tid).json
        assert [row["id"] for row in own["paginated"]] == [team_source]
        assert own["workspace"]["team_id"] == tid

    def test_an_unknown_origin_is_400(self, app, pg_conn, library):
        resp = self._page(app, pg_conn, "&origin=team")
        assert resp.status_code == 400
        assert resp.json["code"] == "invalid_filter"


# ---------------------------------------------------------------------------
# Tools: /api/available_tools
# ---------------------------------------------------------------------------

_TOOLS = ("docsgpt.api.user.tools.routes", "docsgpt.connectors.service")


class TestAvailableToolsInATeam:
    def _names(self, resp):
        return {tool["name"] for tool in resp.json["data"]}

    def _list(self, app, pg_conn, user="alice", team_id=None):
        from docsgpt.api.user.tools.routes import AvailableTools

        return _get(app, pg_conn, AvailableTools, "/api/available_tools", _TOOLS, user=user, team_id=team_id)

    def test_personal_lists_service_and_device_tools(self, app, pg_conn):
        resp = self._list(app, pg_conn)
        assert resp.status_code == 200
        body = resp.json
        groups = {tool["group"] for tool in body["data"]}
        assert "service" in groups
        assert "remote_device" in self._names(resp)
        assert body["workspace"] == {"kind": "personal", "team_id": None, "role": "owner"}

    @pytest.mark.parametrize("user", ["alice", "vera"])
    def test_a_team_leaves_out_what_it_cannot_hold(self, app, pg_conn, user):
        tid = _team(pg_conn)
        personal = self._list(app, pg_conn, user=user)
        resp = self._list(app, pg_conn, user=user, team_id=tid)
        assert resp.status_code == 200
        body = resp.json
        assert "remote_device" not in self._names(resp)
        # A service's tool stays, on each person's own account while the team has no connection for it.
        services = [tool for tool in body["data"] if tool["group"] == "service"]
        assert services and all(tool["member_only"] is True for tool in services)
        # Everything else a team can add stays, MCP included.
        kept = {t["name"] for t in personal.json["data"] if t["name"] != "remote_device"}
        assert self._names(resp) == kept
        assert "mcp_tool" in kept
        assert body["workspace"]["kind"] == "team" and body["workspace"]["team_id"] == tid

    def test_the_list_follows_the_create_time_rule(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import team_tool_refusal

        tid = _team(pg_conn)
        personal = self._names(self._list(app, pg_conn))
        team = self._names(self._list(app, pg_conn, team_id=tid))
        assert {name for name in personal if team_tool_refusal(name, member=True) is not None} == personal - team

    def test_a_non_member_is_404(self, app, pg_conn):
        tid = _team(pg_conn)
        _people(pg_conn, "olga")
        resp = self._list(app, pg_conn, user="olga", team_id=tid)
        assert resp.status_code == 404
        assert resp.json["error"] == "workspace_not_found"


# ---------------------------------------------------------------------------
# Models: /api/models
# ---------------------------------------------------------------------------

_MODELS = ("docsgpt.api.user.models.routes",)


class TestModelsInATeam:
    @pytest.fixture(autouse=True)
    def _byom(self):
        from docsgpt.core.model_registry import ModelRegistry
        from docsgpt.core.model_settings import AvailableModel, ModelProvider

        ModelRegistry.reset()
        mine = AvailableModel(
            id="byom-1", provider=ModelProvider.OPENAI_COMPATIBLE, display_name="My model", source="user",
            base_url="https://models.example.com/v1",
        )
        with patch.object(ModelRegistry, "_user_models_for", return_value={"byom-1": mine}):
            yield
        ModelRegistry.reset()

    def _list(self, app, pg_conn, user="alice", team_id=None):
        from docsgpt.api.user.models.routes import ModelsListResource

        return _get(app, pg_conn, ModelsListResource, "/api/models", _MODELS, user=user, team_id=team_id)

    def test_personal_lists_the_callers_own_models(self, app, pg_conn):
        resp = self._list(app, pg_conn)
        assert resp.status_code == 200
        assert "byom-1" in {m["id"] for m in resp.json["models"]}

    def test_a_team_leaves_out_personal_models(self, app, pg_conn):
        tid = _team(pg_conn)
        personal = self._list(app, pg_conn)
        resp = self._list(app, pg_conn, team_id=tid)
        assert resp.status_code == 200
        body = resp.json
        assert all(m["source"] != "user" for m in body["models"])
        assert {m["id"] for m in body["models"]} == {m["id"] for m in personal.json["models"]} - {"byom-1"}
        assert body["count"] == len(body["models"])

    def test_a_non_member_is_404(self, app, pg_conn):
        tid = _team(pg_conn)
        resp = self._list(app, pg_conn, user="olga", team_id=tid)
        assert resp.status_code == 404
        assert resp.json["error"] == "workspace_not_found"


# ---------------------------------------------------------------------------
# Teams: share dialog payer, refusal codes
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with ExitStack() as stack:
        for target in (
            "docsgpt.api.user.teams.routes.db_readonly",
            "docsgpt.api.user.teams.routes.db_session",
            "docsgpt.api.user.team_authz.db_readonly",
        ):
            stack.enter_context(patch(target, _yield))
        stack.enter_context(patch("docsgpt.api.user.teams.routes.publish_user_event"))
        yield pg_conn


@contextmanager
def _as(sub):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


def _body(resp):
    return json.loads(resp.data)


class TestTeamItemPayer:
    def _shares(self, client, aid, user="vera"):
        with _as(user):
            return client.get(f"/api/resource_shares?resource_type=agent&resource_id={aid}")

    def test_paid_by_names_the_payer(self, client, db):
        tid = _team(db)
        aid = str(AgentsRepository(db).create(
            principal_id(tid), "Team agent", "published", key=f"k-{uuid.uuid4().hex}", access_payer_id="adam",
        )["id"])
        resp = self._shares(client, aid, "alice")
        assert resp.status_code == 200
        outside = _body(resp)["outside_access"]
        assert outside["api_key"] is True
        assert outside["paid_by"] == {"user_id": "adam", "label": "adam@x.io"}
        # Below Admin the dialog says what is on, not who pays.
        assert _body(self._shares(client, aid, "vera"))["outside_access"]["paid_by"] is None

    def test_paid_by_is_none_without_outside_access(self, client, db):
        tid = _team(db)
        aid = str(AgentsRepository(db).create(
            principal_id(tid), "Team agent", "published", access_payer_id="adam",
        )["id"])
        resp = self._shares(client, aid)
        assert _body(resp)["outside_access"]["paid_by"] is None


class TestMemberRefusalCodes:
    def test_last_admin(self, client, db):
        # carol owns the team but holds no admin row (an old team); bob is the only admin.
        _people(db, "carol", "bob")
        tid = str(TeamsRepository(db).create("Old", f"old-{uuid.uuid4().hex[:6]}", "carol")["id"])
        TeamMembersRepository(db).add_member(tid, "bob", role="team_admin")
        with _as("bob"):
            resp = client.put(f"/api/teams/{tid}/members/bob", json={"role": "viewer"})
        assert resp.status_code == 409
        assert _body(resp) == {
            "success": False, "error": "last_admin", "message": "Cannot demote the last team admin",
        }

    def test_owner_must_transfer(self, client, db):
        tid = _team(db)
        with _as("alice"):
            resp = client.delete(f"/api/teams/{tid}/members/alice")
        assert resp.status_code == 400
        assert _body(resp) == {
            "success": False,
            "error": "owner_must_transfer",
            "message": "Transfer team ownership to another member before you leave the team",
        }

    def test_owner_protected(self, client, db):
        tid = _team(db)
        with _as("adam"):
            resp = client.put(f"/api/teams/{tid}/members/alice", json={"role": "editor"})
        assert resp.status_code == 403
        assert _body(resp) == {
            "success": False, "error": "owner_protected", "message": "The team owner can't be demoted",
        }
