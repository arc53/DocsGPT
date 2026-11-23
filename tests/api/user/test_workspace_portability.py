"""Agent YAML export and import per workspace (docsgpt.api.user.agents.portability).

An import lands in the request's workspace: in a team every row it writes is
owned by the team's principal and names the importer as its creator, and every
reference resolves among the team's own items only. A Personal import never
matches a team's items. Knowledge folders map by their full path in the one
folder tree, so two folders of the same name can go to different targets.
Real SQL on ``pg_conn``.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.api.user.agents.portability import (
    API_VERSION,
    ExportAgent,
    ImportAgent,
    ImportAgentPlan,
    ImportWorkspaceMismatch,
    agent_to_yaml,
    apply_import,
    parse_agent_yaml,
    plan_import,
    serialize_agent,
)
from docsgpt.security.encryption import decrypt_tool_credentials
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FoldersRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER, Workspace
from docsgpt.workspaces.principal import principal_id

pytestmark = pytest.mark.integration

EDITOR, VIEWER, ADMIN, STRANGER = "eddie", "vera", "adam", "sam"
PORT = "docsgpt.api.user.agents.portability"


@pytest.fixture
def app():
    return Flask(__name__)


def _team(conn, owner="alice", name="Ops"):
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in ((ADMIN, "team_admin"), (EDITOR, "team_editor"), (VIEWER, "team_viewer")):
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _team_ws(tid, principal, role="editor"):
    return Workspace(kind="team", team_id=tid, owner_id=principal, role=role)


def _doc(**spec):
    spec.setdefault("name", "Imported")
    metadata = spec.pop("_metadata", {"slug": "imported"})
    return {"apiVersion": API_VERSION, "kind": "Agent", "metadata": metadata, "spec": spec}


def _folder(conn, owner, name, parent=None):
    return str(FoldersRepository(conn).create(owner, name, parent_id=parent, created_by=EDITOR)["id"])


def _created_by(conn, table, row_id):
    return conn.execute(text(f"SELECT created_by FROM {table} WHERE id = CAST(:id AS uuid)"), {"id": row_id}).scalar()


def _fake_tool(monkeypatch, requirements=None):
    fake = Mock()
    fake.get_config_requirements.return_value = requirements or {
        "api_key": {"secret": True, "required": True, "label": "API Key"}
    }
    fake.get_actions_metadata.return_value = []
    monkeypatch.setattr(f"{PORT}._tool_instance", lambda tool_type: fake)
    return fake


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _session():
        # A savepoint, so a refused import leaves nothing behind (like the real transaction).
        with conn.begin_nested():
            yield conn

    @contextmanager
    def _readonly():
        yield conn

    with patch(f"{PORT}.db_session", _session), patch(f"{PORT}.db_readonly", _readonly), patch(
        "docsgpt.workspaces.context.db_readonly", _readonly
    ):
        yield


def _post(app, conn, resource_cls, user, body, *, team=None):
    headers = {WORKSPACE_HEADER: team} if team else {}
    with _patch_db(conn), app.test_request_context("/api/import_agent", method="POST", json=body, headers=headers):
        from flask import request

        request.decoded_token = {"sub": user}
        return resource_cls().post()


def _export(app, conn, user, agent_id):
    with _patch_db(conn), app.test_request_context(f"/api/export_agent?id={agent_id}", method="GET"):
        from flask import request

        request.decoded_token = {"sub": user}
        return ExportAgent().get()


def _workflow_agent(conn, owner, agent_cfg):
    wf = WorkflowsRepository(conn).create(owner, "Pipeline", created_by=EDITOR)
    wf_id = str(wf["id"])
    nodes = WorkflowNodesRepository(conn).bulk_create(
        wf_id, 1,
        [
            {"node_id": "start-1", "node_type": "start", "title": "Start"},
            {"node_id": "agent-1", "node_type": "agent", "title": "Answer",
             "config": {"agent_type": "classic", "system_prompt": "s", **agent_cfg}},
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
    return AgentsRepository(conn).create(owner, "Flow", "draft", agent_type="workflow", workflow_id=wf_id,
                                         created_by=EDITOR)


def _node_config(conn, workflow_id, owner):
    wf = WorkflowsRepository(conn).get(str(workflow_id), owner)
    nodes = WorkflowNodesRepository(conn).find_by_version(str(wf["id"]), int(wf["current_graph_version"]))
    return next(n for n in nodes if n["node_id"] == "agent-1")["config"]


# ---------------------------------------------------------------------------
# A team import writes the team's rows
# ---------------------------------------------------------------------------
class TestTeamImport:
    def test_creates_principal_owned_rows_with_the_importer_as_creator(self, app, pg_conn, monkeypatch):
        tid, principal = _team(pg_conn)
        _fake_tool(monkeypatch)
        doc = _doc(
            prompt={"name": "House style", "content": "Be brief."},
            tools=[{"type": "read_webpage", "name": "Search", "config": {}, "requires_secrets": ["api_key"]}],
        )
        body = {"yaml": agent_to_yaml(doc), "resolution": {"tools": {"tool-0": {"secrets": {"api_key": "SECRET"}}}}}
        resp = _post(app, pg_conn, ImportAgent, EDITOR, body, team=tid)
        assert resp.status_code == 200, resp.json
        assert resp.json["action"] == "created" and resp.json["status"] == "draft"
        assert resp.json["workspace"] == {"kind": "team", "team_id": tid, "role": "editor"}

        agent = AgentsRepository(pg_conn).get(resp.json["agent_id"], principal)
        assert agent is not None and agent["status"] == "draft" and not agent.get("key")
        assert _created_by(pg_conn, "agents", agent["id"]) == EDITOR
        assert AgentsRepository(pg_conn).get(resp.json["agent_id"], EDITOR) is None

        prompt = PromptsRepository(pg_conn).get(str(agent["prompt_id"]), principal)
        assert prompt is not None and _created_by(pg_conn, "prompts", prompt["id"]) == EDITOR

        tool = UserToolsRepository(pg_conn).get(str(agent["tools"][0]), principal)
        assert tool is not None and _created_by(pg_conn, "user_tools", tool["id"]) == EDITOR
        # A team tool is in each member's chats by their own preference, the importer's switched on.
        assert tool["status"] is False
        assert UserToolPreferencesRepository(pg_conn).in_chat_many(EDITOR, [str(tool["id"])]) == {
            str(tool["id"]): True
        }
        # Secrets are sealed to the team, so every member's run opens them as the team.
        blob = tool["config"]["encrypted_credentials"]
        assert decrypt_tool_credentials(blob, principal) == {"api_key": "SECRET"}
        assert decrypt_tool_credentials(blob, EDITOR) == {}

    def test_a_workflow_lands_under_the_principal(self, pg_conn):
        tid, principal = _team(pg_conn)
        source = _workflow_agent(pg_conn, EDITOR, {})
        doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, source, EDITOR)))
        doc["metadata"] = {}
        result = apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        agent = AgentsRepository(pg_conn).get(result["agent_id"], principal)
        workflow = WorkflowsRepository(pg_conn).get(str(agent["workflow_id"]), principal)
        assert workflow is not None
        assert _created_by(pg_conn, "workflows", workflow["id"]) == EDITOR

    def test_matches_the_teams_own_items(self, pg_conn):
        tid, principal = _team(pg_conn)
        src = SourcesRepository(pg_conn).create("KB", user_id=principal, type="file", created_by=EDITOR)
        top = _folder(pg_conn, principal, "Carriers")
        eu = _folder(pg_conn, principal, "EU", parent=top)
        prompt = PromptsRepository(pg_conn).create(principal, "House", "Be brief.", created_by=EDITOR)
        doc = _doc(
            sources=[{"name": "KB", "type": "file"},
                     {"name": "EU", "type": "folder", "key": "folder-0", "path": ["Carriers", "EU"]}],
            prompt={"name": "House", "content": "Be brief."},
        )
        ws = _team_ws(tid, principal)
        plan = plan_import(pg_conn, EDITOR, doc, workspace=ws)
        assert [(s["type"], s["status"], s["target_id"]) for s in plan["sources"]] == [
            ("file", "matched", str(src["id"])), ("folder", "matched", eu),
        ]
        assert plan["prompt"]["status"] == "reuse"
        result = apply_import(pg_conn, EDITOR, doc, workspace=ws)
        agent = AgentsRepository(pg_conn).get(result["agent_id"], principal)
        assert [str(s) for s in agent["extra_source_ids"]] == [str(src["id"])]
        assert [str(f) for f in agent["knowledge_folder_ids"]] == [eu]
        assert str(agent["prompt_id"]) == str(prompt["id"])

    def test_updates_the_team_agent_the_file_names(self, pg_conn):
        tid, principal = _team(pg_conn)
        team_agent = AgentsRepository(pg_conn).create(principal, "Team Bot", "published", slug="team-bot",
                                                      created_by=ADMIN, key="k-team")
        doc = _doc(name="Team Bot v2", _metadata={"id": str(team_agent["id"]), "slug": "team-bot"})
        result = apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        assert result["action"] == "updated" and result["agent_id"] == str(team_agent["id"])
        row = AgentsRepository(pg_conn).get(str(team_agent["id"]), principal)
        # An update keeps the agent's status and published access.
        assert row["name"] == "Team Bot v2" and row["status"] == "published" and row["key"] == "k-team"


# ---------------------------------------------------------------------------
# Fail closed: who may import, and what a team import may bind
# ---------------------------------------------------------------------------
class TestImportRefusals:
    @pytest.mark.parametrize("resource", [ImportAgent, ImportAgentPlan])
    def test_a_viewer_importing_into_a_team_gets_403(self, app, pg_conn, resource):
        tid, principal = _team(pg_conn)
        resp = _post(app, pg_conn, resource, VIEWER, {"yaml": agent_to_yaml(_doc())}, team=tid)
        assert resp.status_code == 403
        assert resp.json["error"] == "workspace_role_required"
        assert AgentsRepository(pg_conn).list_for_user(principal) == []

    @pytest.mark.parametrize("resource", [ImportAgent, ImportAgentPlan])
    def test_a_team_the_caller_isnt_in_gets_404(self, app, pg_conn, resource):
        tid, principal = _team(pg_conn)
        resp = _post(app, pg_conn, resource, STRANGER, {"yaml": agent_to_yaml(_doc())}, team=tid)
        assert resp.status_code == 404
        assert resp.json["error"] == "workspace_not_found"
        assert AgentsRepository(pg_conn).list_for_user(principal) == []
        assert AgentsRepository(pg_conn).list_for_user(STRANGER) == []

    def test_a_team_import_never_binds_the_importers_personal_items(self, pg_conn, monkeypatch):
        tid, principal = _team(pg_conn)
        _fake_tool(monkeypatch)
        mine_src = SourcesRepository(pg_conn).create("KB", user_id=EDITOR, type="file")
        mine_folder = _folder(pg_conn, EDITOR, "Carriers")
        mine_prompt = PromptsRepository(pg_conn).create(EDITOR, "House", "Be brief.")
        mine_tool = UserToolsRepository(pg_conn).create(
            EDITOR, "read_webpage", config={}, custom_name="Search", display_name="Read", actions=[],
        )
        mine_model = UserCustomModelsRepository(pg_conn).create(
            EDITOR, "llama-3", "My Llama", "https://models.example.com/v1", "sk-plain",
        )
        doc = _doc(
            sources=[{"name": "KB", "type": "file"},
                     {"name": "Carriers", "type": "folder", "key": "folder-0", "path": ["Carriers"]}],
            prompt={"name": "House", "content": "Be brief."},
            tools=[{"type": "read_webpage", "name": "Search", "config": {}}],
            model={"default": "My Llama", "available": [
                {"type": "custom", "display_name": "My Llama", "upstream_model_id": "llama-3",
                 "base_url": "https://models.example.com/v1"},
                str(mine_model["id"]),
            ]},
        )
        ws = _team_ws(tid, principal)
        plan = plan_import(pg_conn, EDITOR, doc, workspace=ws)
        assert [s["status"] for s in plan["sources"]] == ["missing", "missing"]
        assert plan["tools"][0]["status"] != "reuse"
        assert plan["prompt"]["status"] == "create"
        assert [m["status"] for m in plan["models"]] == ["unavailable", "unavailable"]
        # The team has no such model and an Editor may not add one.
        assert plan["models"][0]["reason"] == "custom_model_admin_required"
        assert plan["models"][0]["requires_secrets"] == []

        resolution = {
            "sources": {"KB": str(mine_src["id"])},
            "folders": {"Carriers": mine_folder, "folder-0": mine_folder},
            "tools": {"tool-0": {"decision": "reuse", "tool_id": str(mine_tool["id"])}},
            "models": {"My Llama": {"api_key": "sk-new"}},
        }
        result = apply_import(pg_conn, EDITOR, doc, resolution, workspace=ws)
        agent = AgentsRepository(pg_conn).get(result["agent_id"], principal)
        assert not agent.get("extra_source_ids")
        assert not agent.get("knowledge_folder_ids")
        assert str(mine_tool["id"]) not in [str(t) for t in agent.get("tools") or []]
        assert str(agent["prompt_id"]) != str(mine_prompt["id"])
        assert PromptsRepository(pg_conn).get(str(agent["prompt_id"]), principal) is not None
        assert not agent.get("models") and not agent.get("default_model_id")
        # No custom model was made for the team or for the importer.
        assert UserCustomModelsRepository(pg_conn).list_for_user(principal) == []
        assert [str(m["id"]) for m in UserCustomModelsRepository(pg_conn).list_for_user(EDITOR)] == [
            str(mine_model["id"])
        ]
        assert any("custom model" in w.lower() for w in result["warnings"])

    def test_a_team_workflow_node_never_keeps_the_importers_raw_ids(self, pg_conn):
        tid, principal = _team(pg_conn)
        mine_src = SourcesRepository(pg_conn).create("KB", user_id=EDITOR, type="file")
        mine_tool = UserToolsRepository(pg_conn).create(
            EDITOR, "read_webpage", config={}, display_name="Read", actions=[],
        )
        mine_folder = _folder(pg_conn, EDITOR, "Carriers")
        mine_model = UserCustomModelsRepository(pg_conn).create(
            EDITOR, "llama-3", "My Llama", "https://models.example.com/v1", "sk-plain",
        )
        source = _workflow_agent(pg_conn, EDITOR, {})
        doc = parse_agent_yaml(agent_to_yaml(serialize_agent(pg_conn, source, EDITOR)))
        doc["metadata"] = {}
        node = next(n for n in doc["spec"]["workflow"]["nodes"] if n["id"] == "agent-1")
        node["config"].update({
            "tools": [str(mine_tool["id"])], "sources": [str(mine_src["id"])],
            "folders": [mine_folder], "model_id": str(mine_model["id"]),
        })
        # Even if the model registry would take the id, a team node never keeps a custom model.
        monkeypatch_validate = patch(f"{PORT}.validate_model_id", lambda model_id, user_id=None: True)
        with monkeypatch_validate:
            result = apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        agent = AgentsRepository(pg_conn).get(result["agent_id"], principal)
        cfg = _node_config(pg_conn, agent["workflow_id"], principal)
        assert cfg["tools"] == [] and cfg["sources"] == [] and cfg["folders"] == []
        assert not cfg.get("model_id")

    def test_the_backstop_refuses_a_personal_ref_in_a_team_import(self, app, pg_conn, monkeypatch):
        tid, principal = _team(pg_conn)
        mine_src = SourcesRepository(pg_conn).create("KB", user_id=EDITOR, type="file")
        # A resolver that let a personal item through is caught before anything is written.
        monkeypatch.setattr(
            f"{PORT}._apply_sources",
            lambda conn, owner, spec, resolution, warnings: ([str(mine_src["id"])], {"KB": str(mine_src["id"])}),
        )
        doc = _doc(prompt={"name": "House", "content": "Be brief."})
        resp = _post(app, pg_conn, ImportAgent, EDITOR, {"yaml": agent_to_yaml(doc)}, team=tid)
        assert resp.status_code == 400
        assert resp.json["error"] == "workspace_mismatch"
        assert [r["id"] for r in resp.json["resources"]] == [str(mine_src["id"])]
        # The prompt made before the check goes with the rolled-back transaction.
        assert AgentsRepository(pg_conn).list_for_user(principal) == []
        assert PromptsRepository(pg_conn).list_for_user(principal) == []

        with pytest.raises(ImportWorkspaceMismatch) as err:
            apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        assert err.value.refs == [("source", str(mine_src["id"]))]

    def test_the_backstop_refuses_a_team_ref_in_a_personal_import(self, pg_conn, monkeypatch):
        _, principal = _team(pg_conn)
        team_src = SourcesRepository(pg_conn).create("KB", user_id=principal, type="file", created_by=EDITOR)
        monkeypatch.setattr(
            f"{PORT}._apply_sources",
            lambda conn, owner, spec, resolution, warnings: ([str(team_src["id"])], {"KB": str(team_src["id"])}),
        )
        with pytest.raises(ImportWorkspaceMismatch):
            apply_import(pg_conn, EDITOR, _doc())

    def test_a_personal_only_tool_isnt_created_in_a_team(self, pg_conn, monkeypatch):
        tid, principal = _team(pg_conn)
        _fake_tool(monkeypatch, requirements={})
        doc = _doc(tools=[{"type": "remote_device", "name": "", "config": {}}])
        ws = _team_ws(tid, principal)
        plan = plan_import(pg_conn, EDITOR, doc, workspace=ws)
        assert plan["tools"][0]["status"] == "unavailable"
        assert plan["tools"][0]["reason"] == "remote_device_personal_only"
        result = apply_import(pg_conn, EDITOR, doc, workspace=ws)
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []
        assert AgentsRepository(pg_conn).get(result["agent_id"], principal)["tools"] == []


# ---------------------------------------------------------------------------
# A Personal import never matches a team's items
# ---------------------------------------------------------------------------
class TestPersonalImport:
    def test_never_matches_team_items(self, pg_conn, monkeypatch):
        _, principal = _team(pg_conn)
        _fake_tool(monkeypatch, requirements={})
        team_src = SourcesRepository(pg_conn).create("KB", user_id=principal, type="file", created_by=EDITOR)
        team_folder = _folder(pg_conn, principal, "Carriers")
        team_prompt = PromptsRepository(pg_conn).create(principal, "House", "Be brief.", created_by=EDITOR)
        team_tool = UserToolsRepository(pg_conn).create(
            principal, "read_webpage", config={}, custom_name="Search", display_name="Read", actions=[],
            created_by=EDITOR,
        )
        team_agent = AgentsRepository(pg_conn).create(principal, "Team Bot", "draft", slug="team-bot",
                                                      created_by=EDITOR)
        doc = _doc(
            name="Mine",
            _metadata={"id": str(team_agent["id"]), "slug": "team-bot"},
            sources=[{"name": "KB", "type": "file"},
                     {"name": "Carriers", "type": "folder", "key": "folder-0", "path": ["Carriers"]}],
            prompt={"name": "House", "content": "Be brief."},
            tools=[{"type": "read_webpage", "name": "Search", "config": {}}],
        )
        plan = plan_import(pg_conn, EDITOR, doc)
        assert plan["target"]["action"] == "create"
        assert [s["status"] for s in plan["sources"]] == ["missing", "missing"]
        assert plan["tools"][0]["status"] == "create"
        assert plan["prompt"]["status"] == "create"
        assert plan["workspace"] == {"kind": "personal", "team_id": None, "role": "owner"}

        resolution = {
            "sources": {"KB": str(team_src["id"])},
            "folders": {"Carriers": team_folder},
            "tools": {"tool-0": {"decision": "reuse", "tool_id": str(team_tool["id"])}},
        }
        result = apply_import(pg_conn, EDITOR, doc, resolution)
        assert result["action"] == "created" and result["agent_id"] != str(team_agent["id"])
        agent = AgentsRepository(pg_conn).get(result["agent_id"], EDITOR)
        assert not agent.get("extra_source_ids") and not agent.get("knowledge_folder_ids")
        assert str(team_tool["id"]) not in [str(t) for t in agent.get("tools") or []]
        assert str(agent["prompt_id"]) != str(team_prompt["id"])
        assert AgentsRepository(pg_conn).get(str(team_agent["id"]), principal)["name"] == "Team Bot"


# ---------------------------------------------------------------------------
# Folders map by full path, not by name
# ---------------------------------------------------------------------------
def _two_archives_doc():
    return _doc(sources=[
        {"name": "Archive", "type": "folder", "key": "folder-0", "path": ["Clients", "Archive"]},
        {"name": "Archive", "type": "folder", "key": "folder-1", "path": ["Vendors", "Archive"]},
    ])


class TestFolderPaths:
    def test_the_plan_names_each_folder_entrys_key_and_path(self, pg_conn):
        clients = _folder(pg_conn, EDITOR, "Clients")
        archive = _folder(pg_conn, EDITOR, "Archive", parent=clients)
        plan = plan_import(pg_conn, EDITOR, _two_archives_doc())
        folders = [s for s in plan["sources"] if s["type"] == "folder"]
        # The fields today's dialog reads stay; the new ones sit beside them.
        assert folders == [
            {"name": "Archive", "type": "folder", "status": "matched", "target_id": archive,
             "key": "folder-0", "path": ["Clients", "Archive"], "path_key": "Clients/Archive",
             "target_path": ["Clients", "Archive"]},
            # No folder on that path: the name still matches, and the plan says where.
            {"name": "Archive", "type": "folder", "status": "matched", "target_id": archive,
             "key": "folder-1", "path": ["Vendors", "Archive"], "path_key": "Vendors/Archive",
             "target_path": ["Clients", "Archive"]},
        ]

    @pytest.mark.parametrize("keys", [("Clients/Archive", "Vendors/Archive"), ("folder-0", "folder-1")])
    def test_same_named_folders_map_to_different_targets(self, pg_conn, keys):
        a = _folder(pg_conn, EDITOR, "Old clients")
        b = _folder(pg_conn, EDITOR, "Old vendors")
        result = apply_import(pg_conn, EDITOR, _two_archives_doc(), {"folders": {keys[0]: a, keys[1]: b}})
        agent = AgentsRepository(pg_conn).get(result["agent_id"], EDITOR)
        assert [str(f) for f in agent["knowledge_folder_ids"]] == [a, b]

    def test_a_name_key_still_maps_when_it_names_one_folder(self, pg_conn):
        target = _folder(pg_conn, EDITOR, "Shippers")
        doc = _doc(sources=[{"name": "Carriers", "type": "folder", "key": "folder-0", "path": ["Carriers"]}])
        result = apply_import(pg_conn, EDITOR, doc, {"folders": {"Carriers": target}})
        assert [str(f) for f in AgentsRepository(pg_conn).get(result["agent_id"], EDITOR)["knowledge_folder_ids"]] == [
            target
        ]

    def test_a_name_key_naming_two_folders_is_ignored(self, pg_conn):
        target = _folder(pg_conn, EDITOR, "Shippers")
        result = apply_import(pg_conn, EDITOR, _two_archives_doc(), {"folders": {"Archive": target}})
        assert not AgentsRepository(pg_conn).get(result["agent_id"], EDITOR).get("knowledge_folder_ids")
        assert any("more than one folder" in w for w in result["warnings"])

    def test_a_team_import_matches_by_path_in_the_teams_tree(self, pg_conn):
        tid, principal = _team(pg_conn)
        clients = _folder(pg_conn, principal, "Clients")
        _folder(pg_conn, principal, "Archive")
        archive = _folder(pg_conn, principal, "Archive", parent=clients)
        # The importer's own tree has the same path; the team's is the one used.
        mine = _folder(pg_conn, EDITOR, "Clients")
        _folder(pg_conn, EDITOR, "Archive", parent=mine)
        doc = _doc(sources=[_two_archives_doc()["spec"]["sources"][0]])
        result = apply_import(pg_conn, EDITOR, doc, workspace=_team_ws(tid, principal))
        agent = AgentsRepository(pg_conn).get(result["agent_id"], principal)
        assert [str(f) for f in agent["knowledge_folder_ids"]] == [archive]


# ---------------------------------------------------------------------------
# Export of a team agent
# ---------------------------------------------------------------------------
class TestTeamExport:
    def test_an_editor_exports_with_the_teams_folder_paths(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        top = _folder(pg_conn, principal, "Carriers")
        eu = _folder(pg_conn, principal, "EU", parent=top)
        agent = AgentsRepository(pg_conn).create(principal, "Team Bot", "draft", knowledge_folder_ids=[eu],
                                                 created_by=ADMIN)
        resp = _export(app, pg_conn, EDITOR, str(agent["id"]))
        assert resp.status_code == 200
        doc = parse_agent_yaml(resp.get_data(as_text=True))
        assert doc["spec"]["sources"] == [
            {"name": "EU", "type": "folder", "key": "folder-0", "path": ["Carriers", "EU"], "ref": eu}
        ]

    def test_a_viewer_cant_export(self, app, pg_conn):
        _, principal = _team(pg_conn)
        agent = AgentsRepository(pg_conn).create(principal, "Team Bot", "draft", created_by=ADMIN)
        assert _export(app, pg_conn, VIEWER, str(agent["id"])).status_code == 403
        assert _export(app, pg_conn, STRANGER, str(agent["id"])).status_code == 404

    def test_a_members_own_folder_on_a_team_agent_goes_by_name_only(self, app, pg_conn):
        _, principal = _team(pg_conn)
        top = _folder(pg_conn, ADMIN, "Private clients")
        theirs = _folder(pg_conn, ADMIN, "EU", parent=top)
        agent = AgentsRepository(pg_conn).create(principal, "Team Bot", "draft", knowledge_folder_ids=[theirs],
                                                 created_by=ADMIN)
        resp = _export(app, pg_conn, EDITOR, str(agent["id"]))
        assert "Private clients" not in resp.get_data(as_text=True)
        assert parse_agent_yaml(resp.get_data(as_text=True))["spec"]["sources"] == [
            {"name": "EU", "type": "folder", "key": "folder-0"}
        ]


# ---------------------------------------------------------------------------
# An imported api_tool's header and query values are sealed like a created one's
# ---------------------------------------------------------------------------
def _api_tool_doc(value="sk-live"):
    action = {
        "name": "get_users", "description": "Get users", "url": "https://api.example.com/users", "method": "GET",
        "active": True,
        "headers": {"type": "object", "properties": {
            "X-Key": {"type": "string", "description": "k", "value": value, "filled_by_llm": False},
        }},
        "query_params": {"type": "object", "properties": {}},
        "body": {"type": "object", "properties": {}},
    }
    return _doc(tools=[{"type": "api_tool", "name": "API", "config": {"actions": {"get_users": action}}}])


class TestImportedApiToolSecrets:
    def _import(self, conn, workspace=None):
        with patch(f"{PORT}.validate_url"):
            result = apply_import(conn, EDITOR, _api_tool_doc(), workspace=workspace)
        owner = workspace.owner_id if workspace else EDITOR
        agent = AgentsRepository(conn).get(result["agent_id"], owner)
        return UserToolsRepository(conn).get(str(agent["tools"][0]), owner)

    def _assert_sealed_and_runs(self, tool, owner):
        import json

        from docsgpt.agents.tool_executor import api_tool_action_with_secrets

        assert "sk-live" not in json.dumps(tool["config"])
        assert decrypt_tool_credentials(tool["config"]["encrypted_action_secrets"], owner) == {
            "get_users": {"headers": {"X-Key": "sk-live"}}
        }
        action = api_tool_action_with_secrets(tool, "get_users")
        assert action["headers"]["properties"]["X-Key"]["value"] == "sk-live"

    def test_a_personal_import_seals_the_value_and_the_run_opens_it(self, pg_conn):
        self._assert_sealed_and_runs(self._import(pg_conn), EDITOR)

    def test_a_team_import_seals_the_value_to_the_team(self, pg_conn):
        tid, principal = _team(pg_conn)
        tool = self._import(pg_conn, _team_ws(tid, principal))
        assert tool["user_id"] == principal
        self._assert_sealed_and_runs(tool, principal)
        assert decrypt_tool_credentials(tool["config"]["encrypted_action_secrets"], EDITOR) == {}
