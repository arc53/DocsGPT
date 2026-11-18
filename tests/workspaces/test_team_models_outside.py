"""A team agent on the team's custom model may go outside the team, under the team's outside policy.

A team's model is the team's stored secret, like a team tool's stored credentials: an Admin may give the agent
an API key, a public link or a webhook, and share it with another team, and the model is never held against it
as someone else's resource. The share dialog names the team's models the agent runs on (``team_models``), so it
can warn that the receiving team's members run the agent on the owning team's model. Real repositories on
``pg_conn``.
"""

from __future__ import annotations

import uuid

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.workspaces.principal import principal_id
from tests.api.user.agents.test_workspace_agents import (
    ADMIN,
    _agent,
    _call,
    _json,
    _row,
    _source,
    _status,
    _team,
)


@pytest.fixture
def app():
    return Flask(__name__)


def _model(conn, owner: str, name: str) -> str:
    return str(UserCustomModelsRepository(conn).create(
        owner, "llama-3", name, "https://m.example/v1", "sk", created_by=ADMIN if owner.startswith("__team__") else None,
    )["id"])


@pytest.fixture
def w(pg_conn):
    """Ops (alice owner, adam admin, eddie editor, vera viewer) with a team model and an agent on it; Dev, a team
    adam is in too, with a model of its own."""
    tid, principal = _team(pg_conn)
    model = _model(pg_conn, principal, "Ops Llama")
    dev = str(TeamsRepository(pg_conn).create("Dev", f"dev-{uuid.uuid4().hex[:6]}", "dora")["id"])
    TeamMembersRepository(pg_conn).add_member(dev, "dora", role="team_admin")
    TeamMembersRepository(pg_conn).add_member(dev, ADMIN, role="team_viewer")
    agent = _agent(pg_conn, principal, status="published", default_model_id=model, models=[model],
                   created_by=ADMIN)
    return {"ops": tid, "principal": principal, "model": model, "dev": dev, "agent": agent,
            "dev_model": _model(pg_conn, principal_id(dev), "Dev Llama")}


class TestPublishing:
    def test_a_public_link(self, app, pg_conn, w):
        from docsgpt.api.user.agents.sharing import ShareAgent

        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", ADMIN, json={"id": w["agent"], "shared": True})
        assert _status(resp) == 200, _json(resp)
        assert _row(pg_conn, w["agent"])["shared"]

    def test_a_webhook(self, app, pg_conn, w):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        resp = _call(app, pg_conn, AgentWebhook, "get", "/api/agent_webhook", ADMIN, query={"id": w["agent"]})
        assert _status(resp) == 200, _json(resp)
        assert _row(pg_conn, w["agent"])["incoming_webhook_token"]

    def test_an_api_key_when_created_published(self, app, pg_conn, w):
        from tests.api.user.agents.test_workspace_agents import _PUBLISHED, _create

        resp = _create(app, pg_conn, ADMIN, w["ops"], default_model_id=w["model"], **_PUBLISHED)
        assert _status(resp) == 201, _json(resp)
        row = _row(pg_conn, _json(resp)["id"])
        assert row["key"] and row["default_model_id"] == w["model"]

    def test_the_model_is_not_a_borrowed_resource(self, pg_conn, w):
        from docsgpt.api.user.agents.graph_checks import agent_borrowed_refs

        assert agent_borrowed_refs(pg_conn, _row(pg_conn, w["agent"])) == []


class TestShareWithAnotherTeam:
    def test_the_agent_can_be_shared(self, app, pg_conn, w):
        from docsgpt.api.user.teams import outside

        with app.app_context():
            refusal, share = outside.share_team_item(pg_conn, ADMIN, w["dev"], "agent", w["agent"], "viewer", None)
        assert refusal is None
        assert share["created"]
        assert TeamItemSharesRepository(pg_conn).get(w["dev"], "agent", w["agent"]) is not None


def _dialog(pg_conn, item_type: str, item_id: str) -> dict:
    from docsgpt.api.user.resource_access import resolve
    from docsgpt.api.user.teams.routes import _team_item_shares

    return _team_item_shares(pg_conn, resolve(pg_conn, item_type, item_id, ADMIN), ADMIN)


class TestShareDialog:
    def test_names_the_teams_models_the_agent_runs_on(self, pg_conn, w):
        body = _dialog(pg_conn, "agent", w["agent"])
        assert body["warning_kind"] == "agent"
        assert body["team_models"] == [{"id": w["model"], "name": "Ops Llama"}]

    def test_names_a_model_on_a_workflow_node_once_and_never_anyone_elses(self, pg_conn, w):
        from docsgpt.api.user.workflows.routes import _write_graph

        from tests.api.user.test_resource_sponsors import _wf_body

        second = _model(pg_conn, w["principal"], "Another Ops model")
        mine = _model(pg_conn, ADMIN, "Adam's own")
        wid = str(WorkflowsRepository(pg_conn).create(w["principal"], "wf", created_by=ADMIN)["id"])
        graph = _wf_body()
        graph["nodes"][1]["data"]["config"]["model_id"] = second
        _write_graph(pg_conn, wid, 1, graph["nodes"], graph["edges"])
        agent = _agent(pg_conn, w["principal"], agent_type="workflow", workflow_id=wid,
                       default_model_id=w["model"], models=["docsgpt-local", w["model"], w["dev_model"], mine])

        body = _dialog(pg_conn, "agent", agent)

        assert body["team_models"] == [
            {"id": second, "name": "Another Ops model"},
            {"id": w["model"], "name": "Ops Llama"},
        ]

    def test_an_agent_on_instance_models_names_none(self, pg_conn, w):
        agent = _agent(pg_conn, w["principal"], default_model_id="docsgpt-local")
        assert _dialog(pg_conn, "agent", agent)["team_models"] == []

    def test_a_source_names_none(self, pg_conn, w):
        assert _dialog(pg_conn, "source", _source(pg_conn, w["principal"]))["team_models"] == []
