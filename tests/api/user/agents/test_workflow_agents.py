"""Workflow-agent behavior of the agents routes, against real Postgres.

Rebuilds the workflow-related coverage of the retired Mongo-era
``tests/api/user/test_agents_routes.py`` on the ``pg_conn`` fixture:
adopting a workflow template (the graph must be deep-copied, never
shared by id), deleting a workflow agent (only the owner's graph may
go), and creating/updating agents with a workflow reference.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.agents.routes.db_session", _yield
    ), patch(
        "application.api.user.agents.routes.db_readonly", _yield
    ):
        yield


def _seed_workflow(pg_conn, user, *, name="WF"):
    """Create a start → agent → end workflow; returns (workflow, nodes, edges)."""
    from application.storage.db.repositories.workflow_edges import (
        WorkflowEdgesRepository,
    )
    from application.storage.db.repositories.workflow_nodes import (
        WorkflowNodesRepository,
    )
    from application.storage.db.repositories.workflows import WorkflowsRepository

    wf = WorkflowsRepository(pg_conn).create(user, name, description="d")
    wf_id = str(wf["id"])
    nodes = WorkflowNodesRepository(pg_conn).bulk_create(
        wf_id,
        1,
        [
            {"node_id": "start-1", "node_type": "start", "title": "Start"},
            {
                "node_id": "agent-1",
                "node_type": "agent",
                "title": "Agent",
                "config": {"system_prompt": "hi", "tools": [], "sources": []},
            },
            {"node_id": "end-1", "node_type": "end", "title": "End"},
        ],
    )
    by_str = {n["node_id"]: n["id"] for n in nodes}
    edges = WorkflowEdgesRepository(pg_conn).bulk_create(
        wf_id,
        1,
        [
            {
                "edge_id": "e1",
                "from_node_id": by_str["start-1"],
                "to_node_id": by_str["agent-1"],
            },
            {
                "edge_id": "e2",
                "from_node_id": by_str["agent-1"],
                "to_node_id": by_str["end-1"],
            },
        ],
    )
    return wf, nodes, edges


def _graph(pg_conn, workflow_id, version=1):
    from application.storage.db.repositories.workflow_edges import (
        WorkflowEdgesRepository,
    )
    from application.storage.db.repositories.workflow_nodes import (
        WorkflowNodesRepository,
    )

    nodes = WorkflowNodesRepository(pg_conn).find_by_version(str(workflow_id), version)
    edges = WorkflowEdgesRepository(pg_conn).find_by_version(str(workflow_id), version)
    return nodes, edges


class TestCloneToUser:
    def test_clones_graph_for_new_owner(self, pg_conn):
        from application.storage.db.repositories.workflows import WorkflowsRepository

        wf, _, _ = _seed_workflow(pg_conn, "owner-a", name="Source WF")
        clone = WorkflowsRepository(pg_conn).clone_to_user(
            str(wf["id"]), "owner-b", from_owner="owner-a"
        )
        assert clone is not None
        assert str(clone["id"]) != str(wf["id"])
        assert clone["user_id"] == "owner-b"
        assert clone["name"] == "Source WF"

        nodes, edges = _graph(pg_conn, clone["id"])
        assert {n["node_id"] for n in nodes} == {"start-1", "agent-1", "end-1"}
        agent_node = next(n for n in nodes if n["node_id"] == "agent-1")
        assert agent_node["config"] == {
            "system_prompt": "hi", "tools": [], "sources": [],
        }
        # Edges are re-keyed onto the clone's node rows, not the source's.
        clone_node_uuids = {n["id"] for n in nodes}
        assert len(edges) == 2
        for e in edges:
            assert e["from_node_id"] in clone_node_uuids
            assert e["to_node_id"] in clone_node_uuids
        # The source graph is untouched.
        src_nodes, src_edges = _graph(pg_conn, wf["id"])
        assert len(src_nodes) == 3 and len(src_edges) == 2

    def test_wrong_owner_returns_none(self, pg_conn):
        from application.storage.db.repositories.workflows import WorkflowsRepository

        wf, _, _ = _seed_workflow(pg_conn, "owner-a")
        assert (
            WorkflowsRepository(pg_conn).clone_to_user(
                str(wf["id"]), "thief", from_owner="not-the-owner"
            )
            is None
        )

    def test_missing_workflow_returns_none(self, pg_conn):
        from application.storage.db.repositories.workflows import WorkflowsRepository

        assert (
            WorkflowsRepository(pg_conn).clone_to_user(
                "00000000-0000-0000-0000-000000000000", "u"
            )
            is None
        )


class TestAdoptWorkflowAgent:
    def test_adopt_clones_the_graph(self, app, pg_conn):
        from application.api.user.agents.routes import AdoptAgent
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.workflows import WorkflowsRepository

        wf, _, _ = _seed_workflow(pg_conn, "__system__", name="Template WF")
        repo = AgentsRepository(pg_conn)
        template = repo.create(
            "__system__",
            "WF Template",
            "template",
            agent_type="workflow",
            workflow_id=str(wf["id"]),
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/adopt_agent?id={template['id']}", method="POST"
        ):
            from flask import request

            request.decoded_token = {"sub": "u-wf-adopter"}
            response = AdoptAgent().post()
        assert response.status_code == 200

        adopted = next(
            a for a in repo.list_for_user("u-wf-adopter") if a["name"] == "WF Template"
        )
        assert adopted["workflow_id"] is not None
        assert str(adopted["workflow_id"]) != str(wf["id"])
        cloned = WorkflowsRepository(pg_conn).get(
            str(adopted["workflow_id"]), "u-wf-adopter"
        )
        assert cloned is not None
        nodes, edges = _graph(pg_conn, cloned["id"])
        assert {n["node_id"] for n in nodes} == {"start-1", "agent-1", "end-1"}
        assert len(edges) == 2

    def test_adopt_survives_unresolvable_workflow(self, app, pg_conn):
        """A template pointing at a graph its owner doesn't own adopts without one."""
        from application.api.user.agents.routes import AdoptAgent
        from application.storage.db.repositories.agents import AgentsRepository

        wf, _, _ = _seed_workflow(pg_conn, "someone-else")
        repo = AgentsRepository(pg_conn)
        template = repo.create(
            "__system__",
            "Broken WF Template",
            "template",
            agent_type="workflow",
            workflow_id=str(wf["id"]),
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/adopt_agent?id={template['id']}", method="POST"
        ):
            from flask import request

            request.decoded_token = {"sub": "u-wf-adopter2"}
            response = AdoptAgent().post()
        assert response.status_code == 200
        adopted = next(
            a
            for a in repo.list_for_user("u-wf-adopter2")
            if a["name"] == "Broken WF Template"
        )
        assert adopted["workflow_id"] is None
        # The unowned graph was not cloned or mutated.
        nodes, edges = _graph(pg_conn, wf["id"])
        assert len(nodes) == 3 and len(edges) == 2


class TestDeleteWorkflowAgent:
    def test_delete_removes_owned_workflow(self, app, pg_conn):
        from application.api.user.agents.routes import DeleteAgent
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.workflows import WorkflowsRepository

        user = "u-wf-del"
        wf, _, _ = _seed_workflow(pg_conn, user)
        repo = AgentsRepository(pg_conn)
        agent = repo.create(
            user, "WF Agent", "draft", agent_type="workflow", workflow_id=str(wf["id"])
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/delete_agent?id={agent['id']}", method="DELETE"
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = DeleteAgent().delete()
        assert response.status_code == 200
        assert repo.get_any(str(agent["id"]), user) is None
        assert WorkflowsRepository(pg_conn).get_by_id(str(wf["id"])) is None
        nodes, edges = _graph(pg_conn, wf["id"])
        assert nodes == [] and edges == []

    def test_delete_leaves_unowned_workflow_intact(self, app, pg_conn):
        """Regression: deleting an agent whose ``workflow_id`` points at another
        user's workflow (the pre-clone adopted shape) must not touch that graph.
        The old explicit node/edge cleanup was not owner-scoped and gutted it."""
        from application.api.user.agents.routes import DeleteAgent
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.workflows import WorkflowsRepository

        wf, _, _ = _seed_workflow(pg_conn, "__system__", name="Shared Template WF")
        repo = AgentsRepository(pg_conn)
        agent = repo.create(
            "u-wf-del2",
            "Adopted WF Agent",
            "draft",
            agent_type="workflow",
            workflow_id=str(wf["id"]),
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/delete_agent?id={agent['id']}", method="DELETE"
        ):
            from flask import request

            request.decoded_token = {"sub": "u-wf-del2"}
            response = DeleteAgent().delete()
        assert response.status_code == 200
        assert repo.get_any(str(agent["id"]), "u-wf-del2") is None
        # The system's workflow and its whole graph survive.
        assert WorkflowsRepository(pg_conn).get_by_id(str(wf["id"])) is not None
        nodes, edges = _graph(pg_conn, wf["id"])
        assert len(nodes) == 3 and len(edges) == 2


class TestCreateWorkflowAgent:
    def test_create_published_with_owned_workflow(self, app, pg_conn):
        from application.api.user.agents.routes import CreateAgent
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-wf-create"
        wf, _, _ = _seed_workflow(pg_conn, user)

        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_agent",
            method="POST",
            json={
                "name": "My WF Agent",
                "description": "d",
                "agent_type": "workflow",
                "status": "published",
                "workflow": str(wf["id"]),
            },
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = CreateAgent().post()
        assert response.status_code == 201
        agent = next(
            a
            for a in AgentsRepository(pg_conn).list_for_user(user)
            if a["name"] == "My WF Agent"
        )
        assert str(agent["workflow_id"]) == str(wf["id"])
        assert agent["status"] == "published"

    def test_create_published_with_unowned_workflow_returns_404(self, app, pg_conn):
        from application.api.user.agents.routes import CreateAgent

        wf, _, _ = _seed_workflow(pg_conn, "someone-else")

        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_agent",
            method="POST",
            json={
                "name": "Stolen WF Agent",
                "description": "d",
                "agent_type": "workflow",
                "status": "published",
                "workflow": str(wf["id"]),
            },
        ):
            from flask import request

            request.decoded_token = {"sub": "u-wf-thief"}
            response = CreateAgent().post()
        assert response.status_code == 404


class TestUpdateWorkflowAgent:
    def test_update_sets_and_clears_workflow(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-wf-update"
        wf, _, _ = _seed_workflow(pg_conn, user)
        repo = AgentsRepository(pg_conn)
        agent = repo.create(user, "WF Agent", "draft", agent_type="workflow")
        agent_id = str(agent["id"])

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent_id}",
            method="PUT",
            json={"workflow": str(wf["id"])},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(agent_id)
        assert response.status_code == 200
        assert str(repo.get(agent_id, user)["workflow_id"]) == str(wf["id"])

        # Clearing is allowed while the agent stays a draft.
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent_id}",
            method="PUT",
            json={"workflow": None},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(agent_id)
        assert response.status_code == 200
        assert repo.get(agent_id, user)["workflow_id"] is None

    def test_publish_without_workflow_is_rejected(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-wf-update2"
        agent = AgentsRepository(pg_conn).create(
            user, "WF Agent", "draft", agent_type="workflow"
        )
        agent_id = str(agent["id"])

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent_id}",
            method="PUT",
            json={"status": "published"},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(agent_id)
        assert response.status_code == 400
