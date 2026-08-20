"""Workflow-agent YAML export/import (application.api.user.agents.portability).

Real SQL against the ephemeral ``pg_conn`` fixture, like
``test_agent_portability.py``. Covers the graph block: reference rewriting
(tools → ``tool-N`` keys, sources → names, custom models → display names),
secret redaction inside node configs, graph validation at apply, and
idempotent re-import as a new graph version of the same workflow.
"""

from __future__ import annotations

import pytest

from application.agents.default_tools import default_tool_id
from application.api.user.agents.portability import (
    AgentImportError,
    agent_to_yaml,
    apply_import,
    parse_agent_yaml,
    plan_import,
    serialize_agent,
)
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.user_custom_models import (
    UserCustomModelsRepository,
)
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
from application.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from application.storage.db.repositories.workflows import WorkflowsRepository


pytestmark = pytest.mark.integration


def _graph(conn, workflow_row):
    version = int(workflow_row.get("current_graph_version") or 1)
    nodes = WorkflowNodesRepository(conn).find_by_version(str(workflow_row["id"]), version)
    edges = WorkflowEdgesRepository(conn).find_by_version(str(workflow_row["id"]), version)
    return nodes, edges


def _seed_workflow_agent(conn, user, *, tool_id=None, source_id=None, model_id=None):
    """Workflow agent with a start → agent → end graph referencing real resources."""
    agent_cfg = {
        "agent_type": "classic",
        "system_prompt": "Answer briefly.",
        "tools": [t for t in [tool_id, default_tool_id("read_document")] if t],
        "sources": [s for s in [source_id] if s],
        "model_id": model_id,
    }
    wf = WorkflowsRepository(conn).create(user, "Pipeline", description="wd")
    wf_id = str(wf["id"])
    nodes = WorkflowNodesRepository(conn).bulk_create(
        wf_id,
        1,
        [
            {"node_id": "start-1", "node_type": "start", "title": "Start"},
            {"node_id": "agent-1", "node_type": "agent", "title": "Answer", "config": agent_cfg},
            {"node_id": "end-1", "node_type": "end", "title": "End"},
        ],
    )
    by_str = {n["node_id"]: n["id"] for n in nodes}
    WorkflowEdgesRepository(conn).bulk_create(
        wf_id,
        1,
        [
            {"edge_id": "e1", "from_node_id": by_str["start-1"], "to_node_id": by_str["agent-1"]},
            {"edge_id": "e2", "from_node_id": by_str["agent-1"], "to_node_id": by_str["end-1"]},
        ],
    )
    agent = AgentsRepository(conn).create(
        user,
        "Flow Bot",
        "published",
        description="wf agent",
        agent_type="workflow",
        workflow_id=wf_id,
    )
    return agent, wf


def _seed_tool(conn, user):
    return UserToolsRepository(conn).create(
        user,
        "brave",
        config={"encrypted_credentials": "SECRETBLOB", "region": "US"},
        custom_name="My Brave",
        display_name="Brave Search",
        description="search",
        config_requirements={"token": {"secret": True, "required": True}, "region": {}},
        actions=[],
    )


def test_export_rewrites_node_refs_and_redacts_secrets(pg_conn):
    user = "u_wf_export"
    tool = _seed_tool(pg_conn, user)
    src = SourcesRepository(pg_conn).create("KB", user_id=user, type="file")
    model = UserCustomModelsRepository(pg_conn).create(
        user, "llama-3", "My Llama", "https://models.example.com/v1", "sk-plain"
    )
    agent, wf = _seed_workflow_agent(
        pg_conn,
        user,
        tool_id=str(tool["id"]),
        source_id=str(src["id"]),
        model_id=str(model["id"]),
    )

    export = serialize_agent(pg_conn, agent, user)
    text = agent_to_yaml(export)
    spec = export["spec"]

    assert "SECRETBLOB" not in text and "sk-plain" not in text
    # Raw ids never appear inside the graph block (the sections may carry
    # ``ref`` hints, same as classic export).
    workflow_text = agent_to_yaml(spec["workflow"])
    assert str(tool["id"]) not in workflow_text
    assert str(src["id"]) not in workflow_text
    assert str(model["id"]) not in workflow_text

    assert spec["workflow"]["name"] == "Pipeline"
    assert [n["id"] for n in spec["workflow"]["nodes"]] == ["agent-1", "end-1", "start-1"]
    agent_node = next(n for n in spec["workflow"]["nodes"] if n["id"] == "agent-1")
    assert agent_node["config"]["tools"] == ["tool-0", "tool-1"]
    assert agent_node["config"]["sources"] == ["KB"]
    assert agent_node["config"]["model_id"] == "My Llama"

    # The collected sections use the classic serializers' portable identities.
    assert spec["tools"][0]["type"] == "brave"
    assert spec["tools"][0]["requires_secrets"] == ["token"]
    assert spec["tools"][1] == {"type": "read_document", "builtin": True}
    assert spec["sources"][0]["name"] == "KB"
    assert spec["model"]["available"][0]["display_name"] == "My Llama"
    assert spec["prompt"] == "default"

    edges = spec["workflow"]["edges"]
    assert {(e["source"], e["target"]) for e in edges} == {
        ("start-1", "agent-1"),
        ("agent-1", "end-1"),
    }


def test_export_without_workflow_emits_null_block(pg_conn):
    user = "u_wf_export2"
    agent = AgentsRepository(pg_conn).create(
        user, "Draft Flow", "draft", agent_type="workflow"
    )
    export = serialize_agent(pg_conn, agent, user)
    assert export["spec"]["workflow"] is None
    assert export["spec"]["tools"] == []
    assert export["spec"]["sources"] == []


def test_round_trip_same_user_reuses_everything(pg_conn):
    user = "u_wf_round"
    tool = _seed_tool(pg_conn, user)
    src = SourcesRepository(pg_conn).create("KB", user_id=user, type="file")
    model = UserCustomModelsRepository(pg_conn).create(
        user, "llama-3", "My Llama", "https://models.example.com/v1", "sk-plain"
    )
    agent, wf = _seed_workflow_agent(
        pg_conn,
        user,
        tool_id=str(tool["id"]),
        source_id=str(src["id"]),
        model_id=str(model["id"]),
    )

    doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, agent, user)))
    result = apply_import(pg_conn, user, doc)

    assert result["action"] == "updated"
    assert result["agent_id"] == str(agent["id"])
    updated = AgentsRepository(pg_conn).get(str(agent["id"]), user)
    # Same workflow row, bumped to a new graph version.
    assert str(updated["workflow_id"]) == str(wf["id"])
    wf_row = WorkflowsRepository(pg_conn).get(str(wf["id"]), user)
    assert int(wf_row["current_graph_version"]) == 2
    nodes, edges = _graph(pg_conn, wf_row)
    assert len(nodes) == 3 and len(edges) == 2
    agent_node = next(n for n in nodes if n["node_id"] == "agent-1")
    # References resolved back to the same owned resources — no duplicates.
    assert set(agent_node["config"]["tools"]) == {
        str(tool["id"]), default_tool_id("read_document"),
    }
    assert agent_node["config"]["sources"] == [str(src["id"])]
    assert agent_node["config"]["model_id"] == str(model["id"])
    assert len(UserToolsRepository(pg_conn).list_for_user(user)) == 1
    # Old graph versions are pruned.
    assert WorkflowNodesRepository(pg_conn).find_by_version(str(wf["id"]), 1) == []


def test_import_into_fresh_user_creates_workflow(pg_conn):
    owner = "u_wf_owner"
    tool = _seed_tool(pg_conn, owner)
    src = SourcesRepository(pg_conn).create("KB", user_id=owner, type="file")
    agent, _ = _seed_workflow_agent(
        pg_conn, owner, tool_id=str(tool["id"]), source_id=str(src["id"])
    )
    doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, agent, owner)))

    importer = "u_wf_importer"
    result = apply_import(
        pg_conn,
        importer,
        doc,
        {"tools": {"tool-0": {"decision": "create", "secrets": {"token": "tok"}}}},
    )

    assert result["action"] == "created"
    created = AgentsRepository(pg_conn).get(result["agent_id"], importer)
    assert created["status"] == "draft"
    assert created["workflow_id"] is not None
    wf_row = WorkflowsRepository(pg_conn).get(str(created["workflow_id"]), importer)
    assert wf_row is not None and wf_row["name"] == "Pipeline"
    nodes, edges = _graph(pg_conn, wf_row)
    assert len(nodes) == 3 and len(edges) == 2
    agent_node = next(n for n in nodes if n["node_id"] == "agent-1")
    # The tool was created for the importer; the missing source was dropped.
    my_tool = UserToolsRepository(pg_conn).list_for_user(importer)[0]
    assert set(agent_node["config"]["tools"]) == {
        str(my_tool["id"]), default_tool_id("read_document"),
    }
    assert agent_node["config"]["sources"] == []
    assert any("Source 'KB' not found" in w for w in result["warnings"])
    assert any("not resolved" in w for w in result["warnings"])


def test_plan_reports_workflow_block(pg_conn):
    user = "u_wf_plan"
    agent, wf = _seed_workflow_agent(pg_conn, user)
    doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, agent, user)))

    plan = plan_import(pg_conn, user, doc)
    assert plan["workflow"] == {"nodes": 3, "edges": 2, "action": "update"}

    other_plan = plan_import(pg_conn, "someone_else", doc)
    assert other_plan["workflow"]["action"] == "create"


def test_import_rejects_invalid_graph(pg_conn):
    user = "u_wf_invalid"
    doc = {
        "apiVersion": "docsgpt.arc53.com/v1",
        "kind": "Agent",
        "metadata": {"slug": "broken-flow"},
        "spec": {
            "name": "Broken Flow",
            "agent_type": "workflow",
            "workflow": {
                "name": "Broken",
                # No start/end nodes — the API's validation gate must reject it.
                "nodes": [{"id": "a", "type": "agent", "config": {}}],
                "edges": [],
            },
        },
    }
    with pytest.raises(AgentImportError, match="Workflow validation failed"):
        apply_import(pg_conn, user, doc)
    # Nothing half-imported.
    assert AgentsRepository(pg_conn).list_for_user(user) == []
    assert WorkflowsRepository(pg_conn).list_for_user(user) == []


def test_import_drops_foreign_raw_ids_from_node_config(pg_conn):
    """A hand-edited file carrying someone else's raw ids must not link them."""
    victim = "u_wf_victim"
    victim_tool = _seed_tool(pg_conn, victim)
    victim_src = SourcesRepository(pg_conn).create("Secret KB", user_id=victim, type="file")

    doc = {
        "apiVersion": "docsgpt.arc53.com/v1",
        "kind": "Agent",
        "metadata": {"slug": "sneaky-flow"},
        "spec": {
            "name": "Sneaky Flow",
            "agent_type": "workflow",
            "workflow": {
                "name": "Sneaky",
                "nodes": [
                    {"id": "s", "type": "start"},
                    {
                        "id": "a",
                        "type": "agent",
                        "config": {
                            "tools": [str(victim_tool["id"])],
                            "sources": [str(victim_src["id"])],
                        },
                    },
                    {"id": "e", "type": "end"},
                ],
                "edges": [
                    {"id": "e1", "source": "s", "target": "a"},
                    {"id": "e2", "source": "a", "target": "e"},
                ],
            },
        },
    }
    result = apply_import(pg_conn, "u_wf_attacker", doc)
    created = AgentsRepository(pg_conn).get(result["agent_id"], "u_wf_attacker")
    wf_row = WorkflowsRepository(pg_conn).get(str(created["workflow_id"]), "u_wf_attacker")
    nodes, _ = _graph(pg_conn, wf_row)
    agent_node = next(n for n in nodes if n["node_id"] == "a")
    assert agent_node["config"]["tools"] == []
    assert agent_node["config"]["sources"] == []
    assert len(result["warnings"]) == 2


def test_import_route_rejects_invalid_graph_as_client_error(pg_conn):
    """Apply-time graph rejection is a 400 carrying the validation detail.

    Regression: an ``AgentImportError`` raised while applying (the file parses,
    but the graph fails the workflow API's validation gate) used to fall into
    the route's generic handler and surface as a 500 with no explanation.
    """
    from contextlib import contextmanager
    from unittest.mock import patch

    from flask import Flask, request

    from application.api.user.agents.portability import ImportAgent

    @contextmanager
    def _conn():
        yield pg_conn

    yaml_text = (
        "kind: Agent\napiVersion: docsgpt.arc53.com/v1\n"
        "spec:\n"
        "  name: Broken Flow\n"
        "  agent_type: workflow\n"
        "  workflow:\n"
        "    name: Broken\n"
        "    nodes:\n"
        "      - id: a\n"
        "        type: agent\n"
        "    edges: []\n"
    )
    app = Flask(__name__)
    with patch(
        "application.api.user.agents.portability.db_session", _conn
    ), app.test_request_context(
        "/api/import_agent", method="POST", json={"yaml": yaml_text}
    ):
        request.decoded_token = {"sub": "u_wf_route"}
        response = ImportAgent().post()
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert "Workflow validation failed" in body["message"]
    assert AgentsRepository(pg_conn).list_for_user("u_wf_route") == []


def test_import_without_workflow_keeps_published_agents_graph(pg_conn):
    user = "u_wf_keep"
    agent, wf = _seed_workflow_agent(pg_conn, user)
    doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, agent, user)))
    del doc["spec"]["workflow"]

    result = apply_import(pg_conn, user, doc)
    assert result["action"] == "updated"
    updated = AgentsRepository(pg_conn).get(str(agent["id"]), user)
    assert str(updated["workflow_id"]) == str(wf["id"])


def test_import_with_null_workflow_keeps_published_but_clears_draft(pg_conn):
    user = "u_wf_null"
    agent, wf = _seed_workflow_agent(pg_conn, user)
    doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, agent, user)))
    doc["spec"]["workflow"] = None

    # Published agent: explicit null must not break it — kept with a warning.
    result = apply_import(pg_conn, user, doc)
    updated = AgentsRepository(pg_conn).get(str(agent["id"]), user)
    assert str(updated["workflow_id"]) == str(wf["id"])
    assert any("kept its existing" in w for w in result["warnings"])

    # Draft agent: explicit null clears the link.
    AgentsRepository(pg_conn).update(str(agent["id"]), user, {"status": "draft"})
    apply_import(pg_conn, user, doc)
    updated = AgentsRepository(pg_conn).get(str(agent["id"]), user)
    assert updated["workflow_id"] is None
