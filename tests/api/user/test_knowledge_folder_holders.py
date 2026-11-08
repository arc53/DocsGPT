"""Agents and workflow agent nodes that read a whole knowledge folder live.

An agent stores its folders in ``agents.knowledge_folder_ids`` (request field
``folders``); a workflow agent node in ``config.folders``. Only a folder's
owner may attach it; one already attached stays when someone else saves the
holder. Folders never enter the sponsor plan: they read as their owner's.
Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

from tests.api.user.test_resource_sponsors import (
    EDITOR,
    OWNER,
    VIEWER,
    _agent,
    _row,
    _status,
    _wf_body,
)
from tests.api.user.test_resource_sponsors import _call as _sponsor_call


@pytest.fixture
def app():
    from flask import Flask

    return Flask(__name__)


@contextmanager
def _folder_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.folder_knowledge.db_readonly", _yield):
        yield


def _call(app, conn, resource_cls, method, path, user, *, json=None, args=()):
    with _folder_db(conn):
        return _sponsor_call(app, conn, resource_cls, method, path, user, json=json, args=args)


def _folder(conn, owner=OWNER, name="Carriers", type_="source", parent=None):
    return str(FoldersRepository(conn).create(owner, name, resource_type=type_, parent_id=parent)["id"])


def _filed_source(conn, folder_id, owner=OWNER, name="doc"):
    sid = str(SourcesRepository(conn).create(name, user_id=owner)["id"])
    FolderItemsRepository(conn).file(owner, "source", sid, folder_id)
    return sid


def _create(app, conn, body, user=OWNER):
    from docsgpt.api.user.agents.routes import CreateAgent

    base = {"name": "Bot", "description": "d", "agent_type": "classic", "status": "draft"}
    return _call(app, conn, CreateAgent, "post", "/api/create_agent", user, json={**base, **body})


def _put(app, conn, agent_id, user, body):
    from docsgpt.api.user.agents.routes import UpdateAgent

    return _call(app, conn, UpdateAgent, "put", f"/api/update_agent/{agent_id}", user,
                 json=body, args=(agent_id,))


def _get(app, conn, agent_id, user=OWNER):
    from docsgpt.api.user.agents.routes import GetAgent

    resp = _call(app, conn, GetAgent, "get", f"/api/get_agent?id={agent_id}", user)
    return resp.get_json()


def _folders(row) -> list[str]:
    return [str(f) for f in row.get("knowledge_folder_ids") or []]


class TestAgentCreate:
    def test_attaches_the_callers_folder(self, app, pg_conn):
        folder = _folder(pg_conn)
        _filed_source(pg_conn, folder)
        resp = _create(app, pg_conn, {"folders": [folder.upper()]})
        assert _status(resp) == 201, resp.get_json()
        agent_id = resp.get_json()["id"]
        row = _row(pg_conn, agent_id)
        assert _folders(row) == [folder]
        # A folder-only agent gets the classic retriever like any agent without sources.
        assert row["retriever"] == "classic"
        out = _get(app, pg_conn, agent_id)
        assert out["folders"] == [folder]
        assert out["folder_details"] == [{"id": folder, "name": "Carriers", "source_count": 1}]

    def test_folders_must_be_a_list(self, app, pg_conn):
        folder = _folder(pg_conn)
        resp = _create(app, pg_conn, {"folders": folder})
        assert _status(resp) == 400
        assert resp.get_json()["message"] == "Folders must be a list"
        resp = _create(app, pg_conn, {"folders": ["not-a-folder"]})
        assert _status(resp) == 400

    def test_a_form_post_sends_folders_as_json(self, app, pg_conn):
        import json

        from flask import request

        from docsgpt.api.user.agents.routes import CreateAgent

        folder = _folder(pg_conn)
        form = {"name": "Bot", "description": "d", "agent_type": "classic", "status": "draft",
                "folders": json.dumps([folder])}
        with _folder_db(pg_conn):
            from tests.api.user.test_resource_sponsors import _patch_db

            with _patch_db(pg_conn), app.test_request_context("/api/create_agent", method="POST", data=form):
                request.decoded_token = {"sub": OWNER}
                resp = CreateAgent().post()
        assert _status(resp) == 201, resp.get_json()
        assert _folders(_row(pg_conn, resp.get_json()["id"])) == [folder]

    @pytest.mark.parametrize("kind", ["theirs", "agent_folder", "missing"])
    def test_refuses_a_folder_that_is_not_the_callers_source_folder(self, app, pg_conn, kind):
        folder = {
            "theirs": lambda: _folder(pg_conn, owner=EDITOR),
            "agent_folder": lambda: _folder(pg_conn, type_="agent"),
            "missing": lambda: str(uuid.uuid4()),
        }[kind]()
        resp = _create(app, pg_conn, {"folders": [folder]})
        assert _status(resp) == 403
        assert resp.get_json()["error"] == "folder_not_accessible"

    def test_workflow_agents_keep_no_folders(self, app, pg_conn):
        folder = _folder(pg_conn)
        resp = _create(app, pg_conn, {"agent_type": "workflow", "folders": [folder]})
        assert _status(resp) == 201, resp.get_json()
        assert _folders(_row(pg_conn, resp.get_json()["id"])) == []


class TestAgentUpdate:
    def test_editor_attaches_their_own_folder_without_a_sponsor(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        mine = _folder(pg_conn, owner=EDITOR, name="Editor's")
        resp = _put(app, pg_conn, agent_id, EDITOR, {"folders": [mine]})
        assert _status(resp) == 200, resp.get_json()
        row = _row(pg_conn, agent_id)
        assert _folders(row) == [mine]
        assert not row.get("resource_sponsors")

    def test_editor_cannot_attach_the_owners_folder(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        owners = _folder(pg_conn)
        resp = _put(app, pg_conn, agent_id, EDITOR, {"folders": [owners]})
        assert _status(resp) == 403
        assert resp.get_json()["error"] == "folder_not_accessible"
        assert _folders(_row(pg_conn, agent_id)) == []

    def test_folders_already_attached_stay_and_may_be_removed(self, app, pg_conn):
        owners = _folder(pg_conn)
        agent_id, _ = _agent(pg_conn, knowledge_folder_ids=[owners])
        mine = _folder(pg_conn, owner=EDITOR, name="Mine")
        resp = _put(app, pg_conn, agent_id, EDITOR, {"folders": [owners, mine]})
        assert _status(resp) == 200, resp.get_json()
        assert _folders(_row(pg_conn, agent_id)) == [owners, mine]
        resp = _put(app, pg_conn, agent_id, EDITOR, {"folders": []})
        assert _status(resp) == 200, resp.get_json()
        assert _folders(_row(pg_conn, agent_id)) == []

    def test_folders_must_be_a_list(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        resp = _put(app, pg_conn, agent_id, OWNER, {"folders": "abc"})
        assert _status(resp) == 400
        assert resp.get_json()["message"] == "Folders must be a list"

    def test_a_save_without_folders_keeps_them(self, app, pg_conn):
        folder = _folder(pg_conn)
        agent_id, _ = _agent(pg_conn, knowledge_folder_ids=[folder])
        assert _status(_put(app, pg_conn, agent_id, OWNER, {"name": "Renamed"})) == 200
        assert _folders(_row(pg_conn, agent_id)) == [folder]

    def test_viewer_reads_folder_details_with_the_owner_named(self, app, pg_conn):
        from sqlalchemy import text

        pg_conn.execute(
            text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT (user_id) DO UPDATE SET email = :e"),
            {"u": OWNER, "e": "owner@example.com"},
        )
        folder = _folder(pg_conn)
        _filed_source(pg_conn, folder)
        agent_id, _ = _agent(pg_conn, knowledge_folder_ids=[folder])
        out = _get(app, pg_conn, agent_id, VIEWER)
        assert out["folders"] == [folder]
        assert out["folder_details"] == [
            {"id": folder, "name": "Carriers", "source_count": 1, "owner_name": "owner@example.com"}
        ]

    def test_listing_carries_folder_ids(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import GetAgents

        folder = _folder(pg_conn)
        agent_id, _ = _agent(pg_conn, knowledge_folder_ids=[folder])
        rows = _call(app, pg_conn, GetAgents, "get", "/api/get_agents", OWNER).get_json()
        assert next(r for r in rows if r["id"] == agent_id)["folders"] == [folder]

    def test_deleting_the_folder_detaches_it(self, app, pg_conn):
        from docsgpt.api.user.folders.service import delete_folder

        folder = _folder(pg_conn)
        agent_id, _ = _agent(pg_conn, knowledge_folder_ids=[folder])
        delete_folder(pg_conn, FoldersRepository(pg_conn).get(folder, OWNER))
        assert _folders(_row(pg_conn, agent_id)) == []


def _node_body(folders=None, source=None, nested=True):
    body = _wf_body(source=source)
    if folders is not None:
        cfg = body["nodes"][1]["data"]
        if nested:
            cfg["config"]["folders"] = folders
        else:
            body["nodes"][1]["data"] = {**cfg["config"], "folders": folders}
    return body


class TestWorkflowNodes:
    def _setup(self, pg_conn):
        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        _agent(pg_conn, agent_type="workflow", workflow_id=str(wf["id"]))
        return str(wf["id"])

    def _put_wf(self, app, pg_conn, wid, user, body):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        return _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", user, json=body, args=(wid,))

    def _get_wf(self, app, pg_conn, wid, user=OWNER):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        return _call(app, pg_conn, WorkflowDetail, "get", f"/api/workflows/{wid}", user, args=(wid,)).get_json()

    @pytest.mark.parametrize("nested", [True, False])
    def test_owner_attaches_own_folder_and_reads_its_name(self, app, pg_conn, nested):
        wid = self._setup(pg_conn)
        folder = _folder(pg_conn)
        _filed_source(pg_conn, folder)
        resp = self._put_wf(app, pg_conn, wid, OWNER, _node_body([folder], nested=nested))
        assert _status(resp) == 200, resp.get_json()
        data = self._get_wf(app, pg_conn, wid)["data"]
        assert data["ref_details"]["folders"] == [{"id": folder, "name": "Carriers", "source_count": 1}]

    def test_editor_cannot_attach_the_owners_folder_but_keeps_it(self, app, pg_conn):
        wid = self._setup(pg_conn)
        owners = _folder(pg_conn)
        assert _status(self._put_wf(app, pg_conn, wid, EDITOR, _node_body([owners]))) == 403
        assert _status(self._put_wf(app, pg_conn, wid, OWNER, _node_body([owners]))) == 200
        mine = _folder(pg_conn, owner=EDITOR, name="Mine")
        resp = self._put_wf(app, pg_conn, wid, EDITOR, _node_body([owners, mine]))
        assert _status(resp) == 200, resp.get_json()
        assert not (WorkflowsRepository(pg_conn).get_by_id(wid).get("resource_sponsors") or {})

    def test_folders_must_be_a_list_of_ids(self, app, pg_conn):
        from docsgpt.api.user.workflows.routes import workflow_graph_shape_errors

        body = _node_body("abc")
        errors = workflow_graph_shape_errors(body["nodes"], body["edges"])
        assert any("folders" in e for e in errors)
        assert not workflow_graph_shape_errors(_node_body([str(uuid.uuid4())])["nodes"], body["edges"])

    def test_node_config_reads_folders(self):
        from docsgpt.agents.workflows.schemas import AgentNodeConfig

        fid = str(uuid.uuid4())
        assert AgentNodeConfig(folders=[fid]).folders == [fid]
        assert AgentNodeConfig().folders == []

    def test_adopt_drops_template_folders(self, pg_conn):
        from docsgpt.api.user.agents.routes import _strip_foreign_node_refs

        mine = _folder(pg_conn, owner=EDITOR)
        foreign = _folder(pg_conn)
        transform = _strip_foreign_node_refs(pg_conn, EDITOR)
        nested = transform("agent", {"config": {"folders": [foreign, mine]}, "folders": [foreign]})
        assert nested == {"config": {"folders": [mine]}}
        assert transform("agent", {"folders": [foreign]}) == {"folders": []}


class TestUsage:
    def test_agents_and_workflow_nodes_use_a_folder(self, app, pg_conn):
        from docsgpt.api.user.folders.routes import Folders
        from docsgpt.api.user.resource_usage import used_by_many

        folder = _folder(pg_conn)
        other = _folder(pg_conn, name="Unused")
        classic, _ = _agent(pg_conn, knowledge_folder_ids=[folder])
        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        workflow_agent, _ = _agent(pg_conn, agent_type="workflow", workflow_id=str(wf["id"]))
        put = TestWorkflowNodes()._put_wf(app, pg_conn, str(wf["id"]), OWNER, _node_body([folder.upper()]))
        assert _status(put) == 200, put.get_json()
        usage = used_by_many(pg_conn, OWNER, "folder", [folder, other], deletable_ids=[folder, other])
        assert {a["id"] for a in usage[folder]["agents"]} == {classic, workflow_agent}
        assert usage[other] == {"agents": [], "others": 0}

        @contextmanager
        def _yield():
            yield pg_conn

        with patch("docsgpt.api.user.folders.routes.db_readonly", _yield):
            listed = _call(app, pg_conn, Folders, "get", "/api/folders?type=source", OWNER).get_json()["folders"]
        by_id = {f["id"]: f for f in listed}
        assert {a["agent_type"] for a in by_id[folder]["used_by"]["agents"]} == {"classic", "workflow"}

    def test_a_teammates_workflow_counts_as_others(self, pg_conn):
        from docsgpt.api.user.resource_usage import used_by_many

        folder = _folder(pg_conn, owner=EDITOR)
        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        AgentsRepository(pg_conn).create(OWNER, "Private", "published", agent_type="workflow",
                                         workflow_id=str(wf["id"]), key=f"k-{uuid.uuid4().hex}")
        from docsgpt.api.user.workflows.routes import _write_graph

        body = _node_body([folder])
        _write_graph(pg_conn, str(wf["id"]), 1, body["nodes"], body["edges"])
        usage = used_by_many(pg_conn, EDITOR, "folder", [folder], deletable_ids=[folder])
        assert usage[folder] == {"agents": [], "others": 1}
