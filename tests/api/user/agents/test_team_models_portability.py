"""Agent import and export with a team's custom models.

Into a team, a model id is usable only when the team owns that model, and a custom model the file describes
reuses the team's model with the same endpoint (base URL and upstream id, whatever its name). Without one, a
team Admin may add it with a key (a team model they are recorded as adding, audited like any add); an Editor
or a token can't, and the plan says why. Into Personal nothing changes, except a team's model id is refused.
An export by someone who may not see a team model's endpoint leaves the endpoint out.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
import yaml
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
from docsgpt.api.user.agents.portability import (
    ExportAgent,
    ImportAgent,
    ImportAgentPlan,
    agent_to_yaml,
    apply_import,
    plan_import,
)
from docsgpt.security.encryption import decrypt_tool_credentials
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from tests.api.user.test_workspace_portability import (
    ADMIN,
    EDITOR,
    PORT,
    _doc,
    _node_config,
    _patch_db,
    _team,
    _team_ws,
    _workflow_agent,
)

BASE = "https://models.example.com/v1"
SPEC = {"type": "custom", "display_name": "Llama", "upstream_model_id": "llama-3", "base_url": BASE}

pytestmark = pytest.mark.integration


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture(autouse=True)
def _public_dns():
    """Every base URL resolves to a public address, so the SSRF guard passes without the network."""
    public = [(None, None, None, None, ("104.18.0.1", 0))]
    with patch("docsgpt.security.safe_url.socket.getaddrinfo", return_value=public):
        yield


@pytest.fixture
def any_model_id():
    """The registry takes every id, so only the ownership rule decides."""
    with patch(f"{PORT}.validate_model_id", lambda model_id, user_id=None: True):
        yield


def _model(conn, owner, name="Team Llama", *, base_url=BASE, upstream="llama-3", created_by=None) -> str:
    if created_by is None and owner.startswith("__team__"):
        created_by = ADMIN
    return str(UserCustomModelsRepository(conn).create(
        owner, upstream, name, base_url, "sk-test", created_by=created_by,
    )["id"])


def _models_doc(*available, default="Llama"):
    return _doc(model={"default": default, "available": list(available)})


def _agent(conn, agent_id, owner) -> dict:
    return AgentsRepository(conn).get(agent_id, owner)


def _added(conn) -> list[dict]:
    return [r[0] for r in conn.execute(
        text("SELECT metadata FROM auth_events WHERE event = 'team.model_added' ORDER BY created_at")
    ).fetchall()]


@contextmanager
def _token(user):
    """A request context whose caller is ``user`` holding a personal access token."""
    app = Flask(__name__)
    with app.test_request_context("/api/import_agent", method="POST"):
        from flask import request

        request.decoded_token = {"sub": user, "auth_method": "pat", "pat_id": "t1", "scopes": ["agents:write"],
                                 "resource_filter": {}}
        yield


class TestTeamPlan:
    def test_a_described_model_reuses_the_teams_match_whatever_its_name(self, pg_conn):
        tid, principal = _team(pg_conn)
        theirs = _model(pg_conn, principal, base_url="HTTPS://Models.Example.COM/v1/")
        plan = plan_import(pg_conn, EDITOR, _models_doc(SPEC), workspace=_team_ws(tid, principal))
        assert plan["models"] == [{"display_name": "Llama", "status": "reuse", "requires_secrets": []}]

        result = apply_import(pg_conn, EDITOR, _models_doc(SPEC), workspace=_team_ws(tid, principal))
        agent = _agent(pg_conn, result["agent_id"], principal)
        assert agent["models"] == [theirs] and agent["default_model_id"] == theirs
        assert len(UserCustomModelsRepository(pg_conn).list_for_user(principal)) == 1

    @pytest.mark.parametrize("role", ("admin", "owner"))
    def test_without_a_match_an_admin_may_add_it(self, pg_conn, role):
        tid, principal = _team(pg_conn)
        plan = plan_import(pg_conn, ADMIN, _models_doc(SPEC), workspace=_team_ws(tid, principal, role))
        assert plan["models"] == [{"display_name": "Llama", "status": "create", "requires_secrets": ["api_key"]}]

    @pytest.mark.parametrize("role", ("editor", "viewer"))
    def test_without_a_match_an_editor_cant(self, pg_conn, role):
        tid, principal = _team(pg_conn)
        # The person's own match doesn't count: the team must have it.
        _model(pg_conn, EDITOR, "Llama")
        plan = plan_import(pg_conn, EDITOR, _models_doc(SPEC), workspace=_team_ws(tid, principal, role))
        assert plan["models"] == [{
            "display_name": "Llama", "status": "unavailable", "requires_secrets": [],
            "reason": "custom_model_admin_required",
        }]
        assert any("Admin" in w for w in plan["warnings"])

    def test_a_token_cant_add_one(self, pg_conn):
        tid, principal = _team(pg_conn)
        with _token(ADMIN):
            plan = plan_import(pg_conn, ADMIN, _models_doc(SPEC), workspace=_team_ws(tid, principal, "admin"))
        assert plan["models"][0]["status"] == "unavailable"
        assert plan["models"][0]["reason"] == "not_available_to_tokens"

    def test_a_model_id_is_usable_only_when_the_team_owns_it(self, pg_conn, any_model_id):
        tid, principal = _team(pg_conn)
        other_tid, other_principal = _team(pg_conn, owner="olga", name="Other")
        theirs = _model(pg_conn, principal)
        mine = _model(pg_conn, EDITOR, "Mine")
        foreign = _model(pg_conn, other_principal, "Foreign", created_by="olga")
        doc = _models_doc(theirs, mine, foreign, default=theirs)
        plan = plan_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        assert [m["status"] for m in plan["models"]] == ["matched", "unavailable", "unavailable"]

        result = apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        agent = _agent(pg_conn, result["agent_id"], principal)
        assert agent["models"] == [theirs] and agent["default_model_id"] == theirs


class TestTeamApply:
    def test_an_admin_adds_the_teams_model_with_a_key(self, pg_conn):
        tid, principal = _team(pg_conn)
        resolution = {"models": {"Llama": {"api_key": "sk-new"}}}
        with Flask(__name__).test_request_context("/api/import_agent", method="POST"):
            result = apply_import(pg_conn, ADMIN, _models_doc(SPEC), resolution,
                                  workspace=_team_ws(tid, principal, "admin"))

        [row] = UserCustomModelsRepository(pg_conn).list_for_user(principal)
        assert row["created_by"] == ADMIN
        assert decrypt_tool_credentials(row["api_key_encrypted"], principal)["api_key"] == "sk-new"
        assert UserCustomModelsRepository(pg_conn).list_for_user(ADMIN) == []
        agent = _agent(pg_conn, result["agent_id"], principal)
        assert agent["models"] == [str(row["id"])] and agent["default_model_id"] == str(row["id"])
        [meta] = _added(pg_conn)
        assert meta == {"team_id": tid, "model_id": str(row["id"]), "display_name": "Llama",
                        "upstream_model_id": "llama-3", "copied": False}

    def test_an_editor_never_adds_one_even_with_a_key(self, pg_conn):
        tid, principal = _team(pg_conn)
        resolution = {"models": {"Llama": {"api_key": "sk-new"}}}
        result = apply_import(pg_conn, EDITOR, _models_doc(SPEC), resolution, workspace=_team_ws(tid, principal))

        assert UserCustomModelsRepository(pg_conn).list_for_user(principal) == []
        assert UserCustomModelsRepository(pg_conn).list_for_user(EDITOR) == []
        agent = _agent(pg_conn, result["agent_id"], principal)
        assert not agent.get("models") and not agent.get("default_model_id")
        assert any("Admin" in w for w in result["warnings"])
        assert _added(pg_conn) == []

    def test_a_token_never_adds_one(self, pg_conn):
        tid, principal = _team(pg_conn)
        resolution = {"models": {"Llama": {"api_key": "sk-new"}}}
        with _token(ADMIN):
            apply_import(pg_conn, ADMIN, _models_doc(SPEC), resolution, workspace=_team_ws(tid, principal, "admin"))
        assert UserCustomModelsRepository(pg_conn).list_for_user(principal) == []

    def test_a_workflow_node_keeps_the_teams_model_and_drops_a_persons(self, pg_conn, any_model_id):
        tid, principal = _team(pg_conn)
        theirs = _model(pg_conn, principal)
        mine = _model(pg_conn, EDITOR, "Mine")
        source = _workflow_agent(pg_conn, principal, {"model_id": theirs})
        from docsgpt.api.user.agents.portability import parse_agent_yaml, serialize_agent

        doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, source, principal)))
        doc["metadata"] = {}
        result = apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        agent = _agent(pg_conn, result["agent_id"], principal)
        assert _node_config(pg_conn, agent["workflow_id"], principal)["model_id"] == theirs

        node = next(n for n in doc["spec"]["workflow"]["nodes"] if n["id"] == "agent-1")
        node["config"]["model_id"] = mine
        doc["spec"]["model"] = {"default": "", "available": []}
        result = apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        agent = _agent(pg_conn, result["agent_id"], principal)
        assert not _node_config(pg_conn, agent["workflow_id"], principal).get("model_id")


class TestEditorsExportBack:
    """An Editor's export leaves a team model's endpoint out but keeps its ``ref``: brought back into the same
    team, the ref names the team's own model, so the agent and its workflow nodes keep it."""

    def test_an_agent_keeps_the_teams_model(self, pg_conn):
        tid, principal = _team(pg_conn)
        theirs = _model(pg_conn, principal)
        source = AgentsRepository(pg_conn).create(principal, "Helper", "draft", models=[theirs],
                                                  default_model_id=theirs, created_by=EDITOR)
        from docsgpt.api.user.agents.portability import parse_agent_yaml, serialize_agent

        doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, source, principal, model_endpoints=False)))
        doc["metadata"] = {}
        assert "base_url" not in doc["spec"]["model"]["available"][0]

        plan = plan_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        assert plan["models"] == [{"display_name": "Team Llama", "status": "reuse", "requires_secrets": []}]
        result = apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        agent = _agent(pg_conn, result["agent_id"], principal)
        assert agent["models"] == [theirs] and agent["default_model_id"] == theirs

    def test_a_workflow_node_keeps_the_teams_model(self, pg_conn, any_model_id):
        tid, principal = _team(pg_conn)
        theirs = _model(pg_conn, principal)
        source = _workflow_agent(pg_conn, principal, {"model_id": theirs})
        from docsgpt.api.user.agents.portability import parse_agent_yaml, serialize_agent

        doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, source, principal, model_endpoints=False)))
        doc["metadata"] = {}
        result = apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        agent = _agent(pg_conn, result["agent_id"], principal)
        assert _node_config(pg_conn, agent["workflow_id"], principal)["model_id"] == theirs

    def test_a_ref_resolves_only_among_the_workspaces_own_models(self, pg_conn):
        tid, principal = _team(pg_conn)
        _other_tid, other_principal = _team(pg_conn, owner="olga", name="Other")
        foreign = _model(pg_conn, other_principal, "Foreign", created_by="olga")
        entry = {k: v for k, v in SPEC.items() if k != "base_url"} | {"ref": foreign}

        plan = plan_import(pg_conn, EDITOR, _models_doc(entry), workspace=_team_ws(tid, principal))
        assert plan["models"][0]["status"] == "unavailable"
        result = apply_import(pg_conn, EDITOR, _models_doc(entry), workspace=_team_ws(tid, principal))
        agent = _agent(pg_conn, result["agent_id"], principal)
        assert not agent.get("models") and not agent.get("default_model_id")


class TestPersonal:
    def test_a_teams_model_id_is_refused(self, pg_conn, any_model_id):
        tid, principal = _team(pg_conn)
        theirs = _model(pg_conn, principal)
        doc = _models_doc(theirs, default=theirs)
        plan = plan_import(pg_conn, EDITOR, doc)
        assert plan["models"] == [{"id": theirs, "status": "unavailable"}]

        result = apply_import(pg_conn, EDITOR, doc)
        agent = _agent(pg_conn, result["agent_id"], EDITOR)
        assert not agent.get("models") and not agent.get("default_model_id")

    def test_a_described_model_still_matches_by_name_too(self, pg_conn):
        _model(pg_conn, EDITOR, "Other name")
        plan = plan_import(pg_conn, EDITOR, _models_doc(SPEC))
        assert plan["models"] == [{"display_name": "Llama", "status": "create", "requires_secrets": ["api_key"]}]


class TestRoutes:
    def _post(self, app, conn, resource, user, body, team, token=False):
        headers = {WORKSPACE_HEADER: team}
        with _patch_db(conn), app.test_request_context("/api/import_agent", method="POST", json=body,
                                                       headers=headers):
            from flask import request

            request.decoded_token = {"sub": user}
            if token:
                request.decoded_token.update(auth_method="pat", pat_id="t1", scopes=["agents:write"],
                                             resource_filter={})
            return resource().post()

    def test_the_plan_route_says_an_editor_needs_an_admin(self, app, pg_conn):
        tid, _ = _team(pg_conn)
        resp = self._post(app, pg_conn, ImportAgentPlan, EDITOR, {"yaml": agent_to_yaml(_models_doc(SPEC))}, tid)
        assert resp.status_code == 200
        assert resp.get_json()["plan"]["models"][0]["reason"] == "custom_model_admin_required"

    def test_an_admins_import_adds_the_model_and_refreshes_the_teams_models(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        body = {"yaml": agent_to_yaml(_models_doc(SPEC)), "resolution": {"models": {"Llama": {"api_key": "k"}}}}
        with patch(f"{PORT}.ModelRegistry.invalidate_user") as invalidate:
            resp = self._post(app, pg_conn, ImportAgent, ADMIN, body, tid)
        assert resp.status_code == 200, resp.get_json()
        assert len(UserCustomModelsRepository(pg_conn).list_for_user(principal)) == 1
        invalidate.assert_called_once_with(principal)

    def test_a_token_import_adds_no_team_model(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        body = {"yaml": agent_to_yaml(_models_doc(SPEC)), "resolution": {"models": {"Llama": {"api_key": "k"}}}}
        resp = self._post(app, pg_conn, ImportAgent, ADMIN, body, tid, token=True)
        assert resp.status_code == 200, resp.get_json()
        assert UserCustomModelsRepository(pg_conn).list_for_user(principal) == []


class TestExport:
    def _export(self, app, conn, user, agent_id):
        with _patch_db(conn), app.test_request_context(f"/api/export_agent?id={agent_id}", method="GET"):
            from flask import request

            request.decoded_token = {"sub": user}
            return ExportAgent().get()

    def _custom_entry(self, resp) -> dict:
        assert resp.status_code == 200, resp.get_data(as_text=True)
        spec = yaml.safe_load(resp.get_data(as_text=True))["spec"]
        return next(m for m in spec["model"]["available"] if isinstance(m, dict))

    def test_an_editor_exports_a_team_model_without_its_endpoint(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        theirs = _model(pg_conn, principal)
        ag = AgentsRepository(pg_conn).create(principal, "Helper", "draft", models=[theirs],
                                              default_model_id=theirs, created_by=EDITOR)
        entry = self._custom_entry(self._export(app, pg_conn, EDITOR, str(ag["id"])))
        assert "base_url" not in entry and entry["upstream_model_id"] == "llama-3"
        assert self._custom_entry(self._export(app, pg_conn, ADMIN, str(ag["id"])))["base_url"] == BASE

    def test_an_editor_exports_a_team_workflow_node_model_without_its_endpoint(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        theirs = _model(pg_conn, principal)
        ag = _workflow_agent(pg_conn, principal, {"model_id": theirs})
        assert "base_url" not in self._custom_entry(self._export(app, pg_conn, EDITOR, str(ag["id"])))
