"""An agent or workflow names only custom models its own owner owns.

A custom model resolves in its owner's account, so a team's item runs on the team's models and a person's on
their own. A save that names a person's model on a team item answers 400 ``custom_model_personal_only``; one
that names a team's model on a personal item, or on another team's item, answers 400
``custom_model_team_only``. Both carry ``message`` and the offending ``models``. An editor of someone's personal
workflow who sets their own model on it keeps the validation error they got before. A template adopted into a
workspace drops the custom models that workspace can't run.
"""

from __future__ import annotations

import uuid

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.workspaces.principal import principal_id
from tests.api.user.test_workspace_followups import (
    EDITOR,
    OWNER,
    _adopt,
    _call,
    _create,
    _custom_model,
    _graph,
    _json,
    _node_model,
    _status,
    _team,
    _template,
    _update,
)

PERSONAL_ONLY = "custom_model_personal_only"
TEAM_ONLY = "custom_model_team_only"


@pytest.fixture(autouse=True)
def _registry():
    from docsgpt.core.model_registry import ModelRegistry

    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


def _team_model(conn, team_id: str, name: str = "Team Llama") -> str:
    return str(UserCustomModelsRepository(conn).create(
        principal_id(team_id), "llama-3", name, "https://m.example/v1", "sk-team", created_by=OWNER,
    )["id"])


def _other_team(conn) -> str:
    return str(TeamsRepository(conn).create("Dev", f"dev-{uuid.uuid4().hex[:6]}", "dora")["id"])


def _refused(resp, code: str, models: list[str]) -> dict:
    assert _status(resp) == 400, _json(resp)
    body = _json(resp)
    # An agent save answers the code in ``error``; a workflow save in ``code`` (``error`` holds the message).
    assert (body.get("code") or body.get("error")) == code
    assert body["message"]
    assert body["models"] == models
    return body


def _workflow_post(conn, user, team, model_id):
    from docsgpt.api.user.workflows.routes import WorkflowList

    body = {"name": "WF", "description": "d", **_graph(model_id)}
    return _call(conn, WorkflowList, "post", "/api/workflows", user, json=body, team=team)


def _workflow_put(conn, user, workflow_id, model_id):
    from docsgpt.api.user.workflows.routes import WorkflowDetail

    body = {"name": "WF", "description": "d", **_graph(model_id)}
    return _call(conn, WorkflowDetail, "put", f"/api/workflows/{workflow_id}", user, json=body, args=(workflow_id,))


def _saved_node_model(conn, workflow: dict):
    from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository

    nodes = WorkflowNodesRepository(conn).find_by_version(str(workflow["id"]), workflow["current_graph_version"])
    cfg = next(n for n in nodes if n["node_type"] == "agent")["config"]
    return (cfg.get("config") or cfg).get("model_id")


class TestTeamAgent:
    def test_saves_with_the_teams_own_model(self, pg_conn):
        tid, principal = _team(pg_conn)
        model = _team_model(pg_conn, tid)
        resp = _create(pg_conn, EDITOR, tid, default_model_id=model, models=["gpt-4o", model])
        assert _status(resp) == 201, _json(resp)
        row = AgentsRepository(pg_conn).get_by_id(_json(resp)["id"])
        assert row["user_id"] == principal
        assert row["default_model_id"] == model and row["models"] == ["gpt-4o", model]

    def test_an_update_keeps_the_teams_own_model(self, pg_conn):
        tid, principal = _team(pg_conn)
        model = _team_model(pg_conn, tid)
        agent_id = str(AgentsRepository(pg_conn).create(principal, "Bot", "draft", agent_type="classic")["id"])
        resp = _update(pg_conn, EDITOR, agent_id, default_model_id=model)
        assert _status(resp) == 200, _json(resp)
        assert AgentsRepository(pg_conn).get_by_id(agent_id)["default_model_id"] == model

    def test_a_persons_model_is_refused_as_personal_only(self, pg_conn):
        tid, principal = _team(pg_conn)
        mine = _custom_model(pg_conn, EDITOR)
        body = _refused(_create(pg_conn, EDITOR, tid, default_model_id=mine), PERSONAL_ONLY, [mine])
        assert "team" in body["message"]
        assert AgentsRepository(pg_conn).list_for_user(principal) == []

    def test_another_teams_model_is_refused_as_team_only(self, pg_conn):
        tid, principal = _team(pg_conn)
        theirs = _team_model(pg_conn, _other_team(pg_conn), name="Dev Llama")
        _refused(_create(pg_conn, EDITOR, tid, models=["gpt-4o", theirs]), TEAM_ONLY, [theirs])
        assert AgentsRepository(pg_conn).list_for_user(principal) == []

    def test_another_teams_model_on_an_inline_graph_is_refused(self, pg_conn):
        tid, principal = _team(pg_conn)
        theirs = _team_model(pg_conn, _other_team(pg_conn))
        resp = _create(pg_conn, EDITOR, tid, agent_type="workflow", workflow_graph=_graph(theirs))
        _refused(resp, TEAM_ONLY, [theirs])
        assert WorkflowsRepository(pg_conn).list_for_user(principal) == []

    def test_an_update_naming_another_teams_model_is_refused(self, pg_conn):
        _, principal = _team(pg_conn)
        theirs = _team_model(pg_conn, _other_team(pg_conn))
        agent_id = str(AgentsRepository(pg_conn).create(principal, "Bot", "draft", agent_type="classic")["id"])
        _refused(_update(pg_conn, EDITOR, agent_id, default_model_id=theirs), TEAM_ONLY, [theirs])
        assert not AgentsRepository(pg_conn).get_by_id(agent_id).get("default_model_id")


class TestPersonalAgent:
    def test_a_teams_model_is_refused_as_team_only(self, pg_conn):
        tid, _ = _team(pg_conn)
        model = _team_model(pg_conn, tid)
        body = _refused(_create(pg_conn, EDITOR, None, default_model_id=model), TEAM_ONLY, [model])
        assert "team" in body["message"]
        assert AgentsRepository(pg_conn).list_for_user(EDITOR) == []

    def test_an_update_naming_a_teams_model_is_refused(self, pg_conn):
        tid, _ = _team(pg_conn)
        model = _team_model(pg_conn, tid)
        agent_id = str(AgentsRepository(pg_conn).create(EDITOR, "Mine", "draft", agent_type="classic")["id"])
        _refused(_update(pg_conn, EDITOR, agent_id, models=[model]), TEAM_ONLY, [model])
        assert not AgentsRepository(pg_conn).get_by_id(agent_id).get("models")

    def test_its_owners_own_model_still_saves(self, pg_conn):
        mine = _custom_model(pg_conn, EDITOR)
        resp = _create(pg_conn, EDITOR, None, default_model_id=mine, models=[mine])
        assert _status(resp) == 201, _json(resp)


class TestWorkflows:
    def test_a_team_editor_saves_a_team_workflow_on_the_teams_model(self, pg_conn):
        tid, principal = _team(pg_conn)
        model = _team_model(pg_conn, tid)
        resp = _workflow_post(pg_conn, EDITOR, tid, model)
        assert _status(resp) == 200 and _json(resp)["success"], _json(resp)
        [row] = WorkflowsRepository(pg_conn).list_for_user(principal)
        assert _saved_node_model(pg_conn, row) == model

    def test_a_team_editors_own_model_on_a_team_workflow_is_refused(self, pg_conn):
        tid, principal = _team(pg_conn)
        mine = _custom_model(pg_conn, EDITOR)
        _refused(_workflow_post(pg_conn, EDITOR, tid, mine), PERSONAL_ONLY, [mine])
        assert WorkflowsRepository(pg_conn).list_for_user(principal) == []

    def test_another_teams_model_on_a_team_workflow_save_is_refused(self, pg_conn):
        _, principal = _team(pg_conn)
        theirs = _team_model(pg_conn, _other_team(pg_conn))
        wf = str(WorkflowsRepository(pg_conn).create(principal, "wf")["id"])
        _refused(_workflow_put(pg_conn, EDITOR, wf, theirs), TEAM_ONLY, [theirs])

    def test_a_team_editor_updates_a_team_workflow_on_the_teams_model(self, pg_conn):
        tid, principal = _team(pg_conn)
        model = _team_model(pg_conn, tid)
        wf = str(WorkflowsRepository(pg_conn).create(principal, "wf")["id"])
        resp = _workflow_put(pg_conn, EDITOR, wf, model)
        assert _status(resp) == 200, _json(resp)

    def test_a_teams_model_on_a_personal_workflow_is_refused(self, pg_conn):
        tid, _ = _team(pg_conn)
        model = _team_model(pg_conn, tid)
        _refused(_workflow_post(pg_conn, EDITOR, None, model), TEAM_ONLY, [model])
        assert WorkflowsRepository(pg_conn).list_for_user(EDITOR) == []

    def test_a_personal_workflow_save_naming_a_teams_model_is_refused(self, pg_conn):
        tid, _ = _team(pg_conn)
        model = _team_model(pg_conn, tid)
        wf = str(WorkflowsRepository(pg_conn).create(EDITOR, "wf")["id"])
        _refused(_workflow_put(pg_conn, EDITOR, wf, model), TEAM_ONLY, [model])


class TestEditorOfSomeonesPersonalWorkflow:
    """An editor's own model on the owner's personal workflow keeps the validation error it had."""

    def test_their_own_model_gets_the_validation_error(self, pg_conn):
        from tests.api.user.test_resource_sponsors import EDITOR as SP_EDITOR
        from tests.api.user.test_resource_sponsors import OWNER as SP_OWNER
        from tests.api.user.test_resource_sponsors import TestWorkflows as SponsorWorkflows
        from tests.api.user.test_resource_sponsors import _agent as shared_agent

        wf = str(WorkflowsRepository(pg_conn).create(SP_OWNER, "wf")["id"])
        shared_agent(pg_conn, agent_type="workflow", workflow_id=wf)
        mine = _custom_model(pg_conn, SP_EDITOR)
        resp = SponsorWorkflows()._put(Flask(__name__), pg_conn, wf, SP_EDITOR, SponsorWorkflows._model_body(mine))

        assert _status(resp) == 400, _json(resp)
        body = _json(resp)
        assert body.get("code") is None
        assert any("which the workflow's owner doesn't have" in e for e in body["errors"])


class TestAdoptingATemplate:
    def test_a_team_keeps_its_own_model_and_drops_another_teams(self, pg_conn):
        tid, _ = _team(pg_conn)
        ours = _team_model(pg_conn, tid)
        theirs = _team_model(pg_conn, _other_team(pg_conn))
        row = _adopt(pg_conn, EDITOR, _template(pg_conn, default_model_id=ours, models=[ours, theirs]), tid)
        assert row["default_model_id"] == ours
        assert row["models"] == [ours]

    def test_a_personal_adoption_drops_a_teams_model(self, pg_conn):
        tid, _ = _team(pg_conn)
        model = _team_model(pg_conn, tid)
        row = _adopt(pg_conn, EDITOR, _template(pg_conn, default_model_id=model, models=["gpt-4o", model]))
        assert not row.get("default_model_id")
        assert row["models"] == ["gpt-4o"]

    def test_a_team_keeps_its_own_model_on_a_graph_node(self, pg_conn):
        tid, _ = _team(pg_conn)
        ours = _team_model(pg_conn, tid)
        row = _adopt(pg_conn, EDITOR, _template(pg_conn, node_model_id=ours), tid)
        assert _node_model(pg_conn, row["workflow_id"]) == ours
