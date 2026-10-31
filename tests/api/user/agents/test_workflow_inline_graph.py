"""A workflow agent saved in one request: the agent row and its graph, drafts included.

POST /api/create_agent and PUT /api/update_agent/<id> take ``workflow_graph``
(``{nodes, edges, retry_defaults?}``, an object in JSON or a JSON string in a
multipart form) for ``agent_type=workflow``. A draft gets shape-only checks;
publishing runs the full graph validation. The node ref gate and the sponsor
plan are the ones PUT /api/workflows/<id> uses. Real repositories on ``pg_conn``.
"""

from __future__ import annotations

import copy
import io
import json
import uuid
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.api.user.resource_access import (
    CODE_CONFIRMATION_REQUIRED,
    CODE_UNEXPECTED_CONFIRMATION,
    sponsor_key,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

from tests.api.user.test_resource_sponsors import (
    EDITOR,
    OWNER,
    _agent,
    _editor_resources,
    _patch_db,
    _row,
    _status,
    _wf_body,
)


@pytest.fixture
def app():
    return Flask(__name__)


def _graph(tool=None, source=None, tools=None):
    body = _wf_body(tool, source, tools=tools)
    return {"nodes": body["nodes"], "edges": body["edges"]}


def _invalid_graph():
    """Well-formed but not runnable: an agent node with no start or end."""
    return {
        "nodes": [{"id": "a1", "type": "agent", "position": {"x": 0, "y": 0}, "data": {"config": {}}}],
        "edges": [],
    }


def _send(app, conn, method, path, user, *, json_body=None, form=None, args=()):
    from docsgpt.api.user.agents.routes import CreateAgent, UpdateAgent

    resource = CreateAgent if method == "post" else UpdateAgent
    kwargs = {"method": method.upper()}
    if json_body is not None:
        kwargs["json"] = json_body
    if form is not None:
        kwargs["data"] = form
        kwargs["content_type"] = "multipart/form-data"
    with _patch_db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource(), method)(*args)


def _create(app, conn, body, user=OWNER):
    return _send(app, conn, "post", "/api/create_agent", user, json_body=body)


def _update(app, conn, agent_id, body, user=OWNER):
    return _send(app, conn, "put", f"/api/update_agent/{agent_id}", user, json_body=body, args=(agent_id,))


def _json(resp):
    return resp.get_json() if hasattr(resp, "get_json") else resp[0]


def _workflow_count(conn, user=OWNER):
    return len(WorkflowsRepository(conn).list_for_user(user))


def _stored_graph(conn, workflow_id):
    wf = WorkflowsRepository(conn).get_by_id(workflow_id)
    nodes = WorkflowNodesRepository(conn).find_by_version(workflow_id, wf["current_graph_version"])
    return wf, sorted(n["node_id"] for n in nodes)


class TestCreate:
    def test_draft_saves_a_graph_that_is_not_runnable_yet(self, app, pg_conn):
        resp = _create(app, pg_conn, {
            "name": "Flow", "agent_type": "workflow", "status": "draft", "workflow_graph": _invalid_graph(),
        })
        assert _status(resp) == 201, _json(resp)
        body = _json(resp)
        agent = AgentsRepository(pg_conn).get_by_id(body["id"])
        assert agent["status"] == "draft" and agent["agent_type"] == "workflow"
        assert body["workflow_id"] == str(agent["workflow_id"])
        assert body["key"] == ""
        wf, node_ids = _stored_graph(pg_conn, body["workflow_id"])
        assert node_ids == ["a1"]
        assert wf["name"] == "Flow" and wf["user_id"] == OWNER

    def test_publish_runs_the_full_validation_and_writes_nothing_on_failure(self, app, pg_conn):
        resp = _create(app, pg_conn, {
            "name": "Flow", "agent_type": "workflow", "status": "published", "workflow_graph": _invalid_graph(),
        })
        assert _status(resp) == 400
        body = _json(resp)
        assert body["success"] is False and body["message"] == "Workflow validation failed"
        assert body["errors"]
        assert _workflow_count(pg_conn) == 0
        assert AgentsRepository(pg_conn).list_for_user(OWNER) == []

    @pytest.mark.parametrize(
        "graph",
        [
            {"nodes": "x", "edges": []},
            {"nodes": [{"type": "agent"}], "edges": []},
            {"nodes": [{"id": "a", "type": "teleport"}], "edges": []},
            {"nodes": [{"id": "a", "type": "start"}, {"id": "a", "type": "end"}], "edges": []},
            {"nodes": [{"id": "a", "type": "start"}], "edges": [{"id": "e1", "source": "a"}]},
            "not json",
            ["a list"],
        ],
    )
    def test_a_draft_still_needs_a_well_formed_graph(self, app, pg_conn, graph):
        resp = _create(app, pg_conn, {
            "name": "Flow", "agent_type": "workflow", "status": "draft", "workflow_graph": graph,
        })
        assert _status(resp) == 400
        assert _workflow_count(pg_conn) == 0

    def test_published_multipart_with_image(self, app, pg_conn):
        form = {
            "name": "Flow",
            "description": "Routes tickets",
            "agent_type": "workflow",
            "status": "published",
            "workflow_graph": json.dumps({**_graph(), "retry_defaults": None}),
            "image": (io.BytesIO(b"png"), "logo.png"),
        }
        with patch("docsgpt.api.user.agents.routes.handle_image_upload", return_value=("https://cdn.example.com/logo.png", None)):
            resp = _send(app, pg_conn, "post", "/api/create_agent", OWNER, form=form)
        assert _status(resp) == 201, _json(resp)
        body = _json(resp)
        agent = AgentsRepository(pg_conn).get_by_id(body["id"])
        assert agent["status"] == "published" and agent["key"]
        assert agent["image"] == body["image"] == "https://cdn.example.com/logo.png"
        wf, node_ids = _stored_graph(pg_conn, body["workflow_id"])
        assert node_ids == ["a1", "end1", "start1"]
        assert (wf["name"], wf["description"]) == ("Flow", "Routes tickets")

    def test_inline_graph_and_workflow_id_together_is_400(self, app, pg_conn):
        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        resp = _create(app, pg_conn, {
            "name": "Flow", "agent_type": "workflow", "status": "draft",
            "workflow": str(wf["id"]), "workflow_graph": _graph(),
        })
        assert _status(resp) == 400

    def test_inline_graph_on_a_classic_agent_is_400(self, app, pg_conn):
        resp = _create(app, pg_conn, {"name": "A", "status": "draft", "workflow_graph": _graph()})
        assert _status(resp) == 400
        assert _workflow_count(pg_conn) == 0

    def test_node_ref_gate(self, app, pg_conn):
        foreign = str(UserToolsRepository(pg_conn).create("someone-else", "api_tool")["id"])
        resp = _create(app, pg_conn, {
            "name": "Flow", "agent_type": "workflow", "status": "draft", "workflow_graph": _graph(foreign),
        })
        assert _status(resp) == 403
        assert _json(resp)["message"] == "Tool not accessible"
        assert _workflow_count(pg_conn) == 0
        assert AgentsRepository(pg_conn).list_for_user(OWNER) == []


def _workflow_agent(app, pg_conn, *, status="published", graph=None):
    """The owner's workflow agent, shared with EDITOR as editor, saved through the inline path."""
    resp = _create(app, pg_conn, {
        "name": "Flow", "agent_type": "workflow", "status": status, "workflow_graph": graph or _graph(),
    })
    assert _status(resp) == 201, _json(resp)
    agent_id = _json(resp)["id"]
    from tests.api.user.test_resource_sponsors import _share_agent

    _share_agent(pg_conn, agent_id)
    return agent_id, _json(resp)["workflow_id"]


class TestUpdate:
    def test_graph_and_agent_fields_in_one_save(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        graph = _graph()
        graph["nodes"][1]["id"] = "a2"
        graph["edges"] = [
            {"id": "e1", "source": "start1", "target": "a2"},
            {"id": "e2", "source": "a2", "target": "end1"},
        ]
        resp = _update(app, pg_conn, agent_id, {"name": "Renamed", "workflow_graph": graph})
        assert _status(resp) == 200, _json(resp)
        assert _json(resp)["workflow_id"] == wid
        wf, node_ids = _stored_graph(pg_conn, wid)
        assert node_ids == ["a2", "end1", "start1"]
        assert wf["current_graph_version"] == 2 and wf["name"] == "Renamed"
        # Only the current version is kept.
        assert WorkflowNodesRepository(pg_conn).find_by_version(wid, 1) == []
        assert _row(pg_conn, agent_id)["name"] == "Renamed"

    def test_save_as_draft_then_publish_validates_the_stored_graph(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn, status="draft")
        resp = _update(app, pg_conn, agent_id, {"status": "draft", "workflow_graph": _invalid_graph()})
        assert _status(resp) == 200, _json(resp)
        assert _row(pg_conn, agent_id)["status"] == "draft"

        refused = _update(app, pg_conn, agent_id, {"status": "published"})
        assert _status(refused) == 400
        assert _json(refused)["message"] == "Workflow validation failed"
        assert _row(pg_conn, agent_id)["status"] == "draft"

        published = _update(app, pg_conn, agent_id, {"status": "published", "workflow_graph": _graph()})
        assert _status(published) == 200, _json(published)
        assert _row(pg_conn, agent_id)["status"] == "published"

    def test_a_published_save_with_an_invalid_graph_changes_nothing(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        resp = _update(app, pg_conn, agent_id, {"name": "New", "workflow_graph": _invalid_graph()})
        assert _status(resp) == 400
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1
        assert _row(pg_conn, agent_id)["name"] == "Flow"

    def test_a_draft_agent_without_a_workflow_gets_one(self, app, pg_conn):
        resp = _create(app, pg_conn, {"name": "Empty", "agent_type": "workflow", "status": "draft"})
        agent_id = _json(resp)["id"]
        assert _row(pg_conn, agent_id)["workflow_id"] is None
        saved = _update(app, pg_conn, agent_id, {"workflow_graph": _graph()})
        assert _status(saved) == 200, _json(saved)
        wid = str(_row(pg_conn, agent_id)["workflow_id"])
        assert _json(saved)["workflow_id"] == wid
        assert _stored_graph(pg_conn, wid)[1] == ["a1", "end1", "start1"]

    def test_editor_sponsor_confirmation_round_trip(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        asked = _update(app, pg_conn, agent_id, {"workflow_graph": _graph(tool)}, user=EDITOR)
        assert _status(asked) == 409
        assert _json(asked)["code"] == CODE_CONFIRMATION_REQUIRED
        assert [r["id"] for r in _json(asked)["resources"]] == [tool]
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1

        key = sponsor_key("tool", tool)
        saved = _update(
            app, pg_conn, agent_id, {"workflow_graph": _graph(tool), "confirm_sponsor": [key]}, user=EDITOR,
        )
        assert _status(saved) == 200, _json(saved)
        assert WorkflowsRepository(pg_conn).get_by_id(wid)["resource_sponsors"] == {key: EDITOR}

        stray = _update(
            app, pg_conn, agent_id,
            {"workflow_graph": _graph(tool), "confirm_sponsor": [sponsor_key("tool", str(uuid.uuid4()))]},
            user=EDITOR,
        )
        assert _status(stray) == 400
        assert _json(stray)["code"] == CODE_UNEXPECTED_CONFIRMATION

    def test_editor_cannot_add_the_owners_private_tool(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        private = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        resp = _update(app, pg_conn, agent_id, {"workflow_graph": _graph(private)}, user=EDITOR)
        assert _status(resp) == 403
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1

    def test_a_stale_editor_write_leaves_the_graph_alone(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        resp = _update(
            app, pg_conn, agent_id,
            {"name": "X", "workflow_graph": copy.deepcopy(_graph()), "expected_updated_at": "2001-01-01T00:00:00Z"},
            user=EDITOR,
        )
        assert _status(resp) == 409
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1

    def test_a_workflow_agents_description_can_be_cleared(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        _update(app, pg_conn, agent_id, {"description": "Answers renewals"})
        resp = _update(app, pg_conn, agent_id, {"description": "", "workflow_graph": _graph()})
        assert _status(resp) == 200, _json(resp)
        assert _row(pg_conn, agent_id)["description"] == ""
        assert WorkflowsRepository(pg_conn).get_by_id(wid)["description"] == ""

    def test_a_classic_agents_description_still_cannot_be_cleared(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        resp = _update(app, pg_conn, agent_id, {"description": "  "})
        assert _status(resp) == 400
        assert "cannot be empty" in _json(resp)["message"]

    def test_inline_graph_with_workflow_field_is_400(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        resp = _update(app, pg_conn, agent_id, {"workflow": wid, "workflow_graph": _graph()})
        assert _status(resp) == 400

    def test_inline_graph_on_a_classic_agent_is_400(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        resp = _update(app, pg_conn, agent_id, {"workflow_graph": _graph()})
        assert _status(resp) == 400


class TestTokens:
    """A personal access token needs workflows:write to write a graph, and no content restriction."""

    def _pat(self, scopes, resource_filter=None):
        from docsgpt.api.pat.tokens import expand_scopes

        return {
            "sub": OWNER, "auth_method": "pat", "pat_id": "t", "pat_name": "ci",
            "scopes": sorted(expand_scopes(scopes)), "resource_filter": resource_filter or {},
        }

    def test_agents_write_alone_cannot_write_a_graph(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import CreateAgent

        body = {"name": "Flow", "agent_type": "workflow", "status": "draft", "workflow_graph": _graph()}
        with _patch_db(pg_conn), app.test_request_context("/api/create_agent", method="POST", json=body):
            from flask import request

            request.decoded_token = self._pat(["agents:write"])
            denied = CreateAgent().post()
            request.decoded_token = self._pat(["agents:write", "workflows:write"])
            allowed = CreateAgent().post()
        assert _status(denied) == 403 and _json(denied)["error"] == "insufficient_scope"
        assert _status(allowed) == 201

    def test_a_content_restricted_token_cannot_send_an_inline_graph(self, app):
        from docsgpt.api.pat import rules

        class _Req:
            is_json = True

            def get_json(self, silent=True):
                return {"workflow_graph": {"nodes": [], "edges": []}}

        for family in ("sources", "tools", "prompts", "workflows"):
            reason = rules._agent_body_check(_Req(), {family: [str(uuid.uuid4())]}, OWNER)
            assert reason, family
        assert rules._agent_body_check(_Req(), {"agents": [str(uuid.uuid4())]}, OWNER) is None


class TestPublishedAgentsRunValidatedGraphs:
    """A published workflow agent never ends up on a graph that only passed the draft checks."""

    def _draft_workflow(self, app, pg_conn):
        """A draft agent's workflow, holding an unfinished graph, then detached and free to attach."""
        agent_id, wid = _workflow_agent(app, pg_conn, status="draft", graph=_invalid_graph())
        assert _status(_update(app, pg_conn, agent_id, {"agent_type": "classic", "workflow": ""})) == 200
        return wid

    def test_create_published_with_an_unvalidated_workflow_is_400(self, app, pg_conn):
        wid = self._draft_workflow(app, pg_conn)
        resp = _create(app, pg_conn, {"name": "Pub", "agent_type": "workflow", "status": "published", "workflow": wid})
        assert _status(resp) == 400
        assert _json(resp)["message"] == "Workflow validation failed" and _json(resp)["errors"]
        assert [a["name"] for a in AgentsRepository(pg_conn).list_for_user(OWNER)] == ["Flow"]
        # A draft may still take it.
        draft = _create(app, pg_conn, {"name": "Draft", "agent_type": "workflow", "status": "draft", "workflow": wid})
        assert _status(draft) == 201, _json(draft)

    def test_a_published_agent_switching_to_an_unvalidated_workflow_is_400(self, app, pg_conn):
        wid = self._draft_workflow(app, pg_conn)
        agent_id, old_wid = _workflow_agent(app, pg_conn)
        resp = _update(app, pg_conn, agent_id, {"workflow": wid})
        assert _status(resp) == 400
        assert _json(resp)["errors"]
        assert str(_row(pg_conn, agent_id)["workflow_id"]) == old_wid

    def test_a_published_agent_saved_back_to_draft_still_needs_a_valid_graph(self, app, pg_conn):
        """Its key keeps working whatever its status, so the graph it runs must be a finished one."""
        agent_id, wid = _workflow_agent(app, pg_conn)
        resp = _update(app, pg_conn, agent_id, {"status": "draft", "workflow_graph": _invalid_graph()})
        assert _status(resp) == 400
        assert _json(resp)["message"] == "Workflow validation failed" and _json(resp)["errors"]
        assert _row(pg_conn, agent_id)["status"] == "published"
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1
        valid = _update(app, pg_conn, agent_id, {"status": "draft", "workflow_graph": _graph()})
        assert _status(valid) == 200, _json(valid)
        assert _row(pg_conn, agent_id)["status"] == "draft"

    def test_a_keyed_draft_keeps_needing_a_valid_graph_on_later_saves(self, app, pg_conn):
        """Back to draft once, the key still runs it: every later draft save validates in full."""
        agent_id, wid = _workflow_agent(app, pg_conn)
        assert _status(_update(app, pg_conn, agent_id, {"status": "draft"})) == 200
        assert _row(pg_conn, agent_id)["status"] == "draft" and _row(pg_conn, agent_id)["key"]
        version = _stored_graph(pg_conn, wid)[0]["current_graph_version"]
        resp = _update(app, pg_conn, agent_id, {"workflow_graph": _invalid_graph()})
        assert _status(resp) == 400
        assert _json(resp)["errors"]
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == version

    def test_a_keyed_draft_switching_to_an_unvalidated_workflow_is_400(self, app, pg_conn):
        wid = self._draft_workflow(app, pg_conn)
        agent_id, old_wid = _workflow_agent(app, pg_conn)
        assert _status(_update(app, pg_conn, agent_id, {"status": "draft"})) == 200
        resp = _update(app, pg_conn, agent_id, {"workflow": wid})
        assert _status(resp) == 400
        assert str(_row(pg_conn, agent_id)["workflow_id"]) == old_wid

    @pytest.mark.parametrize("trigger", ["webhook", "schedule"])
    def test_a_never_published_draft_that_runs_headless_needs_a_valid_graph(self, app, pg_conn, trigger):
        """A webhook token or a schedule runs a draft without its key, so its graph must be finished too."""
        agent_id, wid = _workflow_agent(app, pg_conn, status="draft")
        if trigger == "webhook":
            AgentsRepository(pg_conn).update(agent_id, OWNER, {"incoming_webhook_token": uuid.uuid4().hex})
        else:
            from docsgpt.storage.db.repositories.schedules import SchedulesRepository

            SchedulesRepository(pg_conn).create(OWNER, agent_id, "recurring", "Run", cron="0 9 * * *")
        resp = _update(app, pg_conn, agent_id, {"workflow_graph": _invalid_graph()})
        assert _status(resp) == 400
        assert _json(resp)["errors"]

    def test_a_draft_nothing_runs_still_saves_an_unfinished_graph(self, app, pg_conn):
        agent_id, _ = _workflow_agent(app, pg_conn, status="draft")
        resp = _update(app, pg_conn, agent_id, {"workflow_graph": _invalid_graph()})
        assert _status(resp) == 200, _json(resp)

    def test_a_published_agent_switching_to_an_unvalidated_workflow_as_a_draft_is_400(self, app, pg_conn):
        wid = self._draft_workflow(app, pg_conn)
        agent_id, old_wid = _workflow_agent(app, pg_conn)
        resp = _update(app, pg_conn, agent_id, {"status": "draft", "workflow": wid})
        assert _status(resp) == 400
        assert _json(resp)["errors"]
        assert str(_row(pg_conn, agent_id)["workflow_id"]) == old_wid
        assert _row(pg_conn, agent_id)["status"] == "published"

    def test_a_published_classic_agent_turning_into_a_draft_workflow_needs_a_valid_graph(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        resp = _update(
            app, pg_conn, agent_id,
            {"agent_type": "workflow", "status": "draft", "workflow_graph": _invalid_graph()},
        )
        assert _status(resp) == 400
        assert _row(pg_conn, agent_id)["agent_type"] != "workflow"

    def test_a_valid_stored_workflow_still_attaches(self, app, pg_conn):
        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        from docsgpt.api.user.workflows.routes import _write_graph

        _write_graph(pg_conn, str(wf["id"]), 1, _graph()["nodes"], _graph()["edges"])
        resp = _create(
            app, pg_conn, {"name": "Pub", "agent_type": "workflow", "status": "published", "workflow": str(wf["id"])},
        )
        assert _status(resp) == 201, _json(resp)


class TestGraphOnlySaves:
    def test_a_stale_graph_only_editor_save_is_refused(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        resp = _update(
            app, pg_conn, agent_id,
            {"workflow_graph": _graph(), "expected_updated_at": "2001-01-01T00:00:00Z"}, user=EDITOR,
        )
        assert _status(resp) == 409
        assert _json(resp)["code"] == "stale_write"
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1

    def test_a_graph_only_save_bumps_the_agents_updated_at(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        before = _row(pg_conn, agent_id)["updated_at"]
        from sqlalchemy import text

        # now() is the transaction's start time; move the stored stamp back so a bump shows.
        pg_conn.execute(
            text("UPDATE agents SET updated_at = updated_at - interval '1 hour' WHERE id = CAST(:id AS uuid)"),
            {"id": agent_id},
        )
        stamp = _row(pg_conn, agent_id)["updated_at"]
        resp = _update(
            app, pg_conn, agent_id, {"workflow_graph": _graph(), "expected_updated_at": str(stamp)}, user=EDITOR,
        )
        assert _status(resp) == 200, _json(resp)
        assert _row(pg_conn, agent_id)["updated_at"] == before
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 2

    def test_the_update_answers_with_the_new_updated_at_for_the_next_save(self, app, pg_conn):
        agent_id, _ = _workflow_agent(app, pg_conn)
        stamp = _row(pg_conn, agent_id)["updated_at"]
        first = _update(
            app, pg_conn, agent_id,
            {"name": "One", "workflow_graph": _graph(), "expected_updated_at": str(stamp)}, user=EDITOR,
        )
        assert _status(first) == 200, _json(first)
        fresh = _json(first)["updated_at"]
        assert fresh and fresh == _row(pg_conn, agent_id)["updated_at"]
        # The answer's stamp is the one the next save sends.
        second = _update(app, pg_conn, agent_id, {"name": "Two", "expected_updated_at": fresh}, user=EDITOR)
        assert _status(second) == 200, _json(second)
        assert _json(second)["updated_at"] == _row(pg_conn, agent_id)["updated_at"]

    def test_a_stale_editor_save_that_creates_the_workflow_is_refused(self, app, pg_conn):
        from tests.api.user.test_resource_sponsors import _share_agent

        agent_id = _json(_create(app, pg_conn, {"name": "Empty", "agent_type": "workflow", "status": "draft"}))["id"]
        _share_agent(pg_conn, agent_id)
        resp = _update(
            app, pg_conn, agent_id,
            {"workflow_graph": _graph(), "expected_updated_at": "2001-01-01T00:00:00Z"}, user=EDITOR,
        )
        assert _status(resp) == 409
        assert _row(pg_conn, agent_id)["workflow_id"] is None
        assert _workflow_count(pg_conn) == 0


class TestEmptyToolIds:
    @pytest.mark.parametrize("tools", [[""], [None], ["  "]])
    def test_create_and_update_refuse_an_empty_tool_id(self, app, pg_conn, tools):
        created = _create(app, pg_conn, {"name": "A", "status": "draft", "tools": tools})
        assert _status(created) == 403
        agent_id, _ = _agent(pg_conn)
        updated = _update(app, pg_conn, agent_id, {"tools": tools})
        assert _status(updated) == 403


def _age(conn, agent_id):
    """Move the agent's ``updated_at`` an hour back, past its trigger, and return it.

    ``now()`` is fixed inside the test's transaction, so a bump only shows
    against an older stamp.
    """
    from sqlalchemy import text

    conn.execute(text("ALTER TABLE agents DISABLE TRIGGER agents_set_updated_at"))
    conn.execute(
        text("UPDATE agents SET updated_at = updated_at - interval '1 hour' WHERE id = CAST(:id AS uuid)"),
        {"id": agent_id},
    )
    conn.execute(text("ALTER TABLE agents ENABLE TRIGGER agents_set_updated_at"))
    return _row(conn, agent_id)["updated_at"]


class TestStaleWriteToken:
    """``expected_updated_at`` refuses a save only after someone else edited the agent or its graph."""

    def test_the_owner_chatting_does_not_make_an_editors_copy_stale(self, app, pg_conn):
        agent_id, _ = _workflow_agent(app, pg_conn)
        stamp = _age(pg_conn, agent_id)
        # What the stream processor writes on each of the owner's chats.
        AgentsRepository(pg_conn).update(agent_id, OWNER, {"last_used_at": "2026-10-31T12:00:00+00:00"})
        resp = _update(app, pg_conn, agent_id, {"name": "Edited", "expected_updated_at": stamp}, user=EDITOR)
        assert _status(resp) == 200, _json(resp)

    def test_regenerating_the_key_does_not_make_an_editors_copy_stale(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import RegenerateAgentKey
        from tests.api.user.test_resource_sponsors import _call

        agent_id, _ = _workflow_agent(app, pg_conn)
        stamp = _age(pg_conn, agent_id)
        regenerated = _call(
            app, pg_conn, RegenerateAgentKey, "post", f"/api/agent/{agent_id}/regenerate_key", OWNER,
            args=(agent_id,),
        )
        assert _status(regenerated) == 200, _json(regenerated)
        resp = _update(app, pg_conn, agent_id, {"name": "Edited", "expected_updated_at": stamp}, user=EDITOR)
        assert _status(resp) == 200, _json(resp)

    def test_a_stale_owner_save_is_refused(self, app, pg_conn):
        agent_id, wid = _workflow_agent(app, pg_conn)
        resp = _update(
            app, pg_conn, agent_id,
            {"name": "X", "workflow_graph": _graph(), "expected_updated_at": "2001-01-01T00:00:00Z"},
        )
        assert _status(resp) == 409
        assert _json(resp)["code"] == "stale_write"
        assert _row(pg_conn, agent_id)["name"] == "Flow"
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1

    def test_an_owner_save_with_the_current_stamp_or_none_goes_through(self, app, pg_conn):
        agent_id, _ = _workflow_agent(app, pg_conn)
        stamp = _row(pg_conn, agent_id)["updated_at"]
        assert _status(_update(app, pg_conn, agent_id, {"name": "One", "expected_updated_at": stamp})) == 200
        assert _status(_update(app, pg_conn, agent_id, {"name": "Two"})) == 200
        assert _row(pg_conn, agent_id)["name"] == "Two"

    def test_a_graph_saved_on_the_workflow_makes_the_agents_copy_stale(self, app, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowDetail
        from tests.api.user.test_resource_sponsors import _call

        agent_id, wid = _workflow_agent(app, pg_conn)
        stamp = _age(pg_conn, agent_id)
        saved = _call(
            app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", OWNER,
            json={"name": "Flow", **_graph()}, args=(wid,),
        )
        assert _status(saved) == 200, _json(saved)
        assert _row(pg_conn, agent_id)["updated_at"] > stamp
        resp = _update(
            app, pg_conn, agent_id, {"workflow_graph": _graph(), "expected_updated_at": stamp}, user=EDITOR,
        )
        assert _status(resp) == 409
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 2


def _malformed(kind):
    """A graph the store can't write, made from the valid one."""
    graph = _graph()
    agent_node, first_edge = graph["nodes"][1], graph["edges"][0]
    if kind == "duplicate edge id":
        graph["edges"][1]["id"] = first_edge["id"]
    elif kind == "object title":
        agent_node["title"] = {"text": "A"}
    elif kind == "number title":
        agent_node["title"] = 5
    elif kind == "list description":
        agent_node["description"] = ["d"]
    elif kind == "object source handle":
        first_edge["sourceHandle"] = {"id": "out"}
    elif kind == "number target handle":
        first_edge["targetHandle"] = 1
    elif kind == "list type":
        agent_node["type"] = []
    elif kind == "object type":
        agent_node["type"] = {}
    elif kind == "text config":
        agent_node["data"] = {"config": "x"}
    return graph


_MALFORMED = [
    "duplicate edge id", "object title", "number title", "list description",
    "object source handle", "number target handle", "list type", "object type", "text config",
]


class TestMalformedGraphs:
    """A graph the store can't write is a 400 with its errors on every save path, never a database error."""

    @pytest.mark.parametrize("status", ["draft", "published"])
    @pytest.mark.parametrize("kind", _MALFORMED)
    def test_create(self, app, pg_conn, kind, status):
        resp = _create(app, pg_conn, {
            "name": "Flow", "description": "d", "agent_type": "workflow", "status": status,
            "workflow_graph": _malformed(kind),
        })
        assert _status(resp) == 400, _json(resp)
        assert _json(resp)["errors"]
        assert _workflow_count(pg_conn) == 0

    @pytest.mark.parametrize("kind", _MALFORMED)
    def test_update(self, app, pg_conn, kind):
        agent_id, wid = _workflow_agent(app, pg_conn, status="draft")
        resp = _update(app, pg_conn, agent_id, {"workflow_graph": _malformed(kind)})
        assert _status(resp) == 400, _json(resp)
        assert _json(resp)["errors"]
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1

    @pytest.mark.parametrize("kind", _MALFORMED)
    def test_workflow_put(self, app, pg_conn, kind):
        from docsgpt.api.user.workflows.routes import WorkflowDetail
        from tests.api.user.test_resource_sponsors import _call

        _, wid = _workflow_agent(app, pg_conn)
        resp = _call(
            app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", OWNER,
            json={"name": "Flow", **_malformed(kind)}, args=(wid,),
        )
        assert _status(resp) == 400, _json(resp)
        assert _json(resp)["errors"]
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1

    def test_a_string_or_missing_title_description_and_handles_still_save(self, app, pg_conn):
        graph = _graph()
        graph["nodes"][1].update({"title": "Agent", "description": "Answers"})
        graph["nodes"][0].update({"title": None, "description": None})
        graph["edges"][0].update({"sourceHandle": "out", "targetHandle": None})
        resp = _create(app, pg_conn, {
            "name": "Flow", "agent_type": "workflow", "status": "published", "workflow_graph": graph,
        })
        assert _status(resp) == 201, _json(resp)
