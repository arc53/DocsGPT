"""Knowledge folders in agent YAML export/import (docsgpt.api.user.agents.portability).

A folder travels by name (and its path) as a ``spec.sources`` entry with
``type: folder``. Import matches the importer's own source folders, by path
first, then by name; an unmatched one is dropped with a warning, which the
plan shows too. Real SQL on ``pg_conn``.
"""

from __future__ import annotations

import pytest

from docsgpt.api.user.agents.portability import (
    agent_to_yaml,
    apply_import,
    parse_agent_yaml,
    plan_import,
    serialize_agent,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

pytestmark = pytest.mark.integration

OWNER, IMPORTER = "fp-owner", "fp-importer"


def _folder(conn, user, name, parent=None):
    return str(FoldersRepository(conn).create(user, name, resource_type="source", parent_id=parent)["id"])


def _classic(conn, **extra):
    return AgentsRepository(conn).create(OWNER, "Folder Bot", "published", agent_type="classic", **extra)


def _round_trip(conn, agent, user=OWNER, importer=OWNER):
    return parse_agent_yaml(agent_to_yaml(serialize_agent(conn, agent, user)))


def _folders(conn, agent_id, user):
    return [str(f) for f in AgentsRepository(conn).get(agent_id, user).get("knowledge_folder_ids") or []]


def _workflow_agent(conn, folders):
    wf = WorkflowsRepository(conn).create(OWNER, "Pipeline")
    wf_id = str(wf["id"])
    nodes = WorkflowNodesRepository(conn).bulk_create(
        wf_id, 1,
        [
            {"node_id": "start-1", "node_type": "start", "title": "Start"},
            {"node_id": "agent-1", "node_type": "agent", "title": "Answer",
             "config": {"agent_type": "classic", "system_prompt": "s", "folders": folders}},
            {"node_id": "end-1", "node_type": "end", "title": "End"},
        ],
    )
    by_str = {n["node_id"]: n["id"] for n in nodes}
    WorkflowEdgesRepository(conn).bulk_create(
        wf_id, 1,
        [
            {"edge_id": "e1", "from_node_id": by_str["start-1"], "to_node_id": by_str["agent-1"]},
            {"edge_id": "e2", "from_node_id": by_str["agent-1"], "to_node_id": by_str["end-1"]},
        ],
    )
    agent = AgentsRepository(conn).create(OWNER, "Flow", "published", agent_type="workflow", workflow_id=wf_id)
    return agent, wf


def _node_folders(conn, workflow_id, user):
    wf = WorkflowsRepository(conn).get(str(workflow_id), user)
    nodes = WorkflowNodesRepository(conn).find_by_version(str(wf["id"]), int(wf["current_graph_version"]))
    return next(n for n in nodes if n["node_id"] == "agent-1")["config"].get("folders")


class TestClassic:
    def test_export_names_each_folder(self, pg_conn):
        top = _folder(pg_conn, OWNER, "Carriers")
        eu = _folder(pg_conn, OWNER, "EU", parent=top)
        src = SourcesRepository(pg_conn).create("KB", user_id=OWNER, type="file")
        agent = _classic(pg_conn, extra_source_ids=[str(src["id"])], knowledge_folder_ids=[eu])
        sources = serialize_agent(pg_conn, agent, OWNER)["spec"]["sources"]
        assert sources == [
            {"name": "KB", "type": "file", "ref": str(src["id"])},
            {"name": "EU", "type": "folder", "path": ["Carriers", "EU"], "ref": eu},
        ]

    def test_round_trip_keeps_the_folders(self, pg_conn):
        folder = _folder(pg_conn, OWNER, "Carriers")
        agent = _classic(pg_conn, knowledge_folder_ids=[folder])
        result = apply_import(pg_conn, OWNER, _round_trip(pg_conn, agent))
        assert result["action"] == "updated"
        assert _folders(pg_conn, str(agent["id"]), OWNER) == [folder]
        assert not result["warnings"]

    def test_another_user_matches_their_own_folders_by_path_then_name(self, pg_conn):
        top = _folder(pg_conn, OWNER, "Carriers")
        eu = _folder(pg_conn, OWNER, "EU", parent=top)
        rail = _folder(pg_conn, OWNER, "Rail")
        agent = _classic(pg_conn, knowledge_folder_ids=[eu, rail])
        doc = _round_trip(pg_conn, agent)
        # The importer has an "EU" at the top and one under "carriers": the path wins.
        _folder(pg_conn, IMPORTER, "EU")
        their_top = _folder(pg_conn, IMPORTER, "carriers")
        their_eu = _folder(pg_conn, IMPORTER, "eu", parent=their_top)
        their_rail = _folder(pg_conn, IMPORTER, "Archive")
        their_rail = _folder(pg_conn, IMPORTER, "Rail", parent=their_rail)
        plan = plan_import(pg_conn, IMPORTER, doc)
        folders = [s for s in plan["sources"] if s["type"] == "folder"]
        assert [(f["name"], f["status"], f["target_id"]) for f in folders] == [
            ("EU", "matched", their_eu), ("Rail", "matched", their_rail),
        ]
        result = apply_import(pg_conn, IMPORTER, doc)
        assert _folders(pg_conn, result["agent_id"], IMPORTER) == [their_eu, their_rail]

    def test_unmatched_folders_drop_with_a_warning(self, pg_conn):
        folder = _folder(pg_conn, OWNER, "Carriers")
        agent = _classic(pg_conn, knowledge_folder_ids=[folder])
        doc = _round_trip(pg_conn, agent)
        # An agent folder of the same name is not a knowledge folder.
        FoldersRepository(pg_conn).create(IMPORTER, "Carriers", resource_type="agent")
        plan = plan_import(pg_conn, IMPORTER, doc)
        assert [s for s in plan["sources"] if s["type"] == "folder"] == [
            {"name": "Carriers", "type": "folder", "status": "missing", "target_id": None}
        ]
        assert plan["warnings"] == ["Folder 'Carriers' not found; left unattached"]
        result = apply_import(pg_conn, IMPORTER, doc)
        assert _folders(pg_conn, result["agent_id"], IMPORTER) == []
        assert "Folder 'Carriers' not found; left unattached" in result["warnings"]
        assert not any("Source 'Carriers'" in w for w in result["warnings"])

    def test_a_folder_entry_is_never_a_source(self, pg_conn):
        folder = _folder(pg_conn, OWNER, "KB")
        SourcesRepository(pg_conn).create("KB", user_id=OWNER, type="file")
        agent = _classic(pg_conn, knowledge_folder_ids=[folder])
        result = apply_import(pg_conn, OWNER, _round_trip(pg_conn, agent))
        row = AgentsRepository(pg_conn).get(result["agent_id"], OWNER)
        assert not row.get("extra_source_ids")
        assert _folders(pg_conn, result["agent_id"], OWNER) == [folder]


class TestWorkflow:
    def test_node_folders_travel_by_name(self, pg_conn):
        folder = _folder(pg_conn, OWNER, "Carriers")
        agent, wf = _workflow_agent(pg_conn, [folder])
        export = serialize_agent(pg_conn, agent, OWNER)
        node = next(n for n in export["spec"]["workflow"]["nodes"] if n["id"] == "agent-1")
        assert node["config"]["folders"] == ["Carriers"]
        assert {"name": "Carriers", "type": "folder", "path": ["Carriers"], "ref": folder} in export["spec"]["sources"]
        doc = parse_agent_yaml(agent_to_yaml(export))
        apply_import(pg_conn, OWNER, doc)
        assert _node_folders(pg_conn, wf["id"], OWNER) == [folder]
        # The agent row of a workflow agent keeps none.
        assert _folders(pg_conn, str(agent["id"]), OWNER) == []

    def test_an_importer_without_the_folder_gets_none(self, pg_conn):
        folder = _folder(pg_conn, OWNER, "Carriers")
        agent, _ = _workflow_agent(pg_conn, [folder])
        doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, agent, OWNER)))
        result = apply_import(pg_conn, IMPORTER, doc)
        created = AgentsRepository(pg_conn).get(result["agent_id"], IMPORTER)
        assert _node_folders(pg_conn, created["workflow_id"], IMPORTER) == []
        assert "Folder 'Carriers' not found; left unattached" in result["warnings"]

    def test_raw_ids_must_be_the_importers_folders(self, pg_conn):
        foreign = _folder(pg_conn, OWNER, "Theirs")
        mine = _folder(pg_conn, IMPORTER, "Mine")
        agent, _ = _workflow_agent(pg_conn, [])
        doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, agent, OWNER)))
        node = next(n for n in doc["spec"]["workflow"]["nodes"] if n["id"] == "agent-1")
        node["config"]["folders"] = [foreign, mine]
        result = apply_import(pg_conn, IMPORTER, doc)
        created = AgentsRepository(pg_conn).get(result["agent_id"], IMPORTER)
        assert _node_folders(pg_conn, created["workflow_id"], IMPORTER) == [mine]
