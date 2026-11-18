"""Folders per workspace: one tree per owner (a person, or a team's principal), holding all four kinds.

In a team the tree is the team's, the same for every member: listing needs any role, editing and filing
need Editor. A team's item is never filed in a personal folder and a personal item never in a team's.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id


@pytest.fixture
def app():
    return Flask(__name__)


def _team(conn, owner="alice", name="Ops", members=(("adam", "team_admin"), ("eddie", "team_editor"),
                                                    ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    targets = [
        "docsgpt.api.user.folders.routes.db_session",
        "docsgpt.api.user.folders.routes.db_readonly",
        "docsgpt.api.user.agents.folders.db_session",
        "docsgpt.api.user.agents.folders.db_readonly",
        "docsgpt.api.user.tools.routes.db_session",
        "docsgpt.api.user.tools.routes.db_readonly",
        "docsgpt.api.user.prompts.routes.db_session",
        "docsgpt.api.user.prompts.routes.db_readonly",
        "docsgpt.workspaces.context.db_readonly",
    ]
    patches = [patch(t, _yield) for t in targets]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


def _call(app, conn, resource_cls, user, *, team=None, method="post", json=None, path="/api/x", args=()):
    headers = {WORKSPACE_HEADER: team} if team else {}
    kwargs = {"method": method.upper(), "headers": headers}
    if json is not None:
        kwargs["json"] = json
    with _patch_db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user}
        response = getattr(resource_cls(), method)(*args)
    return response.status_code, response.get_json()


def _list(app, conn, user, team=None, type_=None):
    from docsgpt.api.user.folders.routes import Folders

    path = "/api/folders" + (f"?type={type_}" if type_ else "")
    return _call(app, conn, Folders, user, team=team, method="get", path=path)


def _create(app, conn, user, name, *, team=None, parent=None, type_=None):
    from docsgpt.api.user.folders.routes import Folders

    body = {"name": name}
    if type_:
        body["type"] = type_
    if parent:
        body["parent_id"] = parent
    return _call(app, conn, Folders, user, team=team, json=body, path="/api/folders")


def _put(app, conn, user, folder_id, body, team=None):
    from docsgpt.api.user.folders.routes import FolderResource

    return _call(app, conn, FolderResource, user, team=team, method="put", json=body,
                 path=f"/api/folders/{folder_id}", args=(folder_id,))


def _delete(app, conn, user, folder_id, team=None):
    from docsgpt.api.user.folders.routes import FolderResource

    return _call(app, conn, FolderResource, user, team=team, method="delete",
                 path=f"/api/folders/{folder_id}", args=(folder_id,))


def _file(app, conn, user, type_, folder_id, ids, team=None):
    from docsgpt.api.user.folders.routes import FolderItems

    return _call(app, conn, FolderItems, user, team=team, json={"type": type_, "folder_id": folder_id, "ids": ids},
                 path="/api/folders/items")


def _source(conn, owner, name="s", created_by=None):
    row = SourcesRepository(conn).create(name, user_id=owner)
    if created_by:
        conn.execute(text("UPDATE sources SET created_by = :c WHERE id = CAST(:i AS uuid)"),
                     {"c": created_by, "i": str(row["id"])})
    return str(row["id"])


def _tool(conn, owner, name="read_webpage", created_by=None):
    return str(UserToolsRepository(conn).create(
        owner, name, config={}, display_name=name, description="",
        actions=[{"name": "act", "active": True}], status=False, created_by=created_by,
    )["id"])


def _prompt(conn, owner, name="P", created_by=None):
    return str(PromptsRepository(conn).create(owner, name, "Be brief.", created_by=created_by)["id"])


def _folder(conn, owner, name, parent=None, created_by=None):
    row = FoldersRepository(conn).create(owner, name, parent_id=parent)
    if created_by:
        conn.execute(text("UPDATE folders SET created_by = :c WHERE id = CAST(:i AS uuid)"),
                     {"c": created_by, "i": str(row["id"])})
    return str(row["id"])


# ---------------------------------------------------------------------------
# One tree, names unique across kinds, compat
# ---------------------------------------------------------------------------
class TestOneTree:
    def test_names_are_unique_across_kinds(self, app, pg_conn):
        assert _create(app, pg_conn, "eve", "Project", type_="agent")[0] == 201
        for kind in ("source", "tool", "prompt", None):
            status, body = _create(app, pg_conn, "eve", "project", type_=kind)
            assert (status, body["error"]) == (409, "folder_name_taken"), kind

    def test_type_is_ignored_on_create_and_optional_on_list(self, app, pg_conn):
        status, body = _create(app, pg_conn, "eve", "Anything", type_="tool")
        assert status == 201
        status, body = _create(app, pg_conn, "eve", "Untyped")
        assert status == 201
        status, body = _list(app, pg_conn, "eve")
        assert status == 200
        assert sorted(f["name"] for f in body["folders"]) == ["Anything", "Untyped"]
        status, body = _list(app, pg_conn, "eve", type_="nonsense")
        assert (status, body["error"]) == (400, "invalid_type")

    def test_compat_type_agent_still_lists(self, app, pg_conn):
        _create(app, pg_conn, "eve", "Agents")
        status, body = _list(app, pg_conn, "eve", type_="agent")
        assert status == 200
        assert [f["name"] for f in body["folders"]] == ["Agents"]
        assert body["folders"][0]["type"] == "agent"

    def test_counts_every_kind_and_item_count_follows_type(self, app, pg_conn):
        status, folder = _create(app, pg_conn, "eve", "Mixed")
        fid = folder["id"]
        items = FolderItemsRepository(pg_conn)
        items.file("eve", "agent", str(AgentsRepository(pg_conn).create("eve", "a", "draft")["id"]), fid)
        items.file("eve", "source", _source(pg_conn, "eve"), fid)
        items.file("eve", "tool", _tool(pg_conn, "eve"), fid)
        items.file("eve", "prompt", _prompt(pg_conn, "eve"), fid)
        items.file("eve", "prompt", _prompt(pg_conn, "eve", "P2"), fid)
        _status, body = _list(app, pg_conn, "eve")
        row = body["folders"][0]
        assert row["counts"] == {"agent": 1, "source": 1, "tool": 1, "prompt": 2}
        assert row["item_count"] == 5
        _status, body = _list(app, pg_conn, "eve", type_="prompt")
        assert body["folders"][0]["item_count"] == 2
        # Any folder holding sources says who reads it live.
        assert "used_by" in body["folders"][0]

    def test_personal_folder_names_its_creator(self, app, pg_conn):
        _create(app, pg_conn, "eve", "Mine")
        _status, body = _list(app, pg_conn, "eve")
        assert body["folders"][0]["created_by"] == {"user_id": "eve", "label": "eve"}


class TestDeleteReparent:
    def test_a_clash_where_children_land_is_renamed(self, app, pg_conn):
        _s, top = _create(app, pg_conn, "eve", "Top")
        _s, mid = _create(app, pg_conn, "eve", "Mid", parent=top["id"])
        _s, child = _create(app, pg_conn, "eve", "Notes", parent=mid["id"])
        _create(app, pg_conn, "eve", "notes", parent=top["id"])
        status, body = _delete(app, pg_conn, "eve", mid["id"])
        assert status == 200
        assert body["success"] is True
        assert body["moved_folders"] == 1
        assert body["renamed"] == [{"id": child["id"], "from": "Notes", "to": "Notes (2)"}]
        assert FoldersRepository(pg_conn).get(child["id"], "eve")["parent_id"] == top["id"]


# ---------------------------------------------------------------------------
# Team trees
# ---------------------------------------------------------------------------
class TestTeamTree:
    def test_the_same_tree_for_every_member_owned_by_the_principal(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        status, created = _create(app, pg_conn, "eddie", "Shared", team=tid)
        assert status == 201, created
        row = FoldersRepository(pg_conn).get(created["id"], principal)
        assert row is not None and row["created_by"] == "eddie"
        UsersRepository(pg_conn).upsert("eddie", email="eddie@example.com")
        for member in ("vera", "adam", "alice"):
            status, body = _list(app, pg_conn, member, team=tid)
            assert status == 200
            assert [f["name"] for f in body["folders"]] == ["Shared"]
            assert body["folders"][0]["created_by"] == {"user_id": "eddie", "label": "eddie@example.com"}
        # Nobody's Personal list shows it, and the team list shows nobody's personal folders.
        _create(app, pg_conn, "eddie", "Private")
        assert [f["name"] for f in _list(app, pg_conn, "eddie")[1]["folders"]] == ["Private"]
        assert [f["name"] for f in _list(app, pg_conn, "eddie", team=tid)[1]["folders"]] == ["Shared"]

    def test_a_viewer_lists_but_cannot_change_anything(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        fid = _folder(pg_conn, principal, "Team", created_by="eddie")
        source = _source(pg_conn, principal)
        status, body = _create(app, pg_conn, "vera", "New", team=tid)
        assert (status, body["error"]) == (403, "workspace_role_required")
        status, body = _put(app, pg_conn, "vera", fid, {"name": "Renamed"})
        assert (status, body["error"]) == (403, "workspace_role_required")
        status, body = _put(app, pg_conn, "vera", fid, {"parent_id": None})
        assert (status, body["error"]) == (403, "workspace_role_required")
        status, body = _delete(app, pg_conn, "vera", fid)
        assert (status, body["error"]) == (403, "workspace_role_required")
        status, body = _file(app, pg_conn, "vera", "source", fid, [source], team=tid)
        assert (status, body["error"]) == (403, "workspace_role_required")
        status, body = _file(app, pg_conn, "vera", "source", None, [source], team=tid)
        assert (status, body["error"]) == (403, "workspace_role_required")
        assert FoldersRepository(pg_conn).get(fid, principal)["name"] == "Team"
        assert FolderItemsRepository(pg_conn).filings(principal, "source") == {}

    def test_an_editor_renames_moves_and_deletes_by_the_folders_own_tree(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        top = _folder(pg_conn, principal, "Top")
        mid = _folder(pg_conn, principal, "Mid", parent=top)
        child = _folder(pg_conn, principal, "Notes", parent=mid)
        _folder(pg_conn, principal, "notes", parent=top)
        source = _source(pg_conn, principal)
        FolderItemsRepository(pg_conn).file(principal, "source", source, mid)
        # No header: a folder-by-id route goes by the folder's own owner.
        status, body = _put(app, pg_conn, "eddie", mid, {"name": "Middle"})
        assert (status, body["name"]) == (200, "Middle")
        status, body = _delete(app, pg_conn, "eddie", mid)
        assert status == 200
        assert body == {"success": True, "moved_items": 1, "moved_folders": 1,
                        "renamed": [{"id": child, "from": "Notes", "to": "Notes (2)"}]}
        assert FolderItemsRepository(pg_conn).filing(principal, "source", source) == top

    def test_a_non_member_gets_404(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        fid = _folder(pg_conn, principal, "Team")
        status, body = _list(app, pg_conn, "mallory", team=tid)
        assert (status, body["error"]) == (404, "workspace_not_found")
        status, body = _create(app, pg_conn, "mallory", "x", team=tid)
        assert (status, body["error"]) == (404, "workspace_not_found")
        for status, body in (
            _put(app, pg_conn, "mallory", fid, {"name": "mine"}),
            _delete(app, pg_conn, "mallory", fid),
        ):
            assert (status, body["error"]) == (404, "folder_not_found")
        status, body = _file(app, pg_conn, "mallory", "source", fid, [_source(pg_conn, "mallory")])
        assert (status, body["error"]) == (404, "folder_not_found")
        assert FoldersRepository(pg_conn).get(fid, principal)["name"] == "Team"

    def test_another_teams_folder_is_not_a_parent(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        _other, other_principal = _team(pg_conn, name="Other", members=(("eddie", "team_editor"),))
        theirs = _folder(pg_conn, other_principal, "Theirs")
        status, body = _create(app, pg_conn, "eddie", "x", team=tid, parent=theirs)
        assert (status, body["error"]) == (404, "folder_not_found")
        mine = _folder(pg_conn, principal, "Mine")
        status, body = _put(app, pg_conn, "eddie", mine, {"parent_id": theirs})
        assert (status, body["error"]) == (404, "folder_not_found")


# ---------------------------------------------------------------------------
# Filing rules
# ---------------------------------------------------------------------------
class TestFilingRules:
    def test_a_team_item_is_never_filed_in_a_personal_folder(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        personal = _folder(pg_conn, "eddie", "Mine")
        for kind, item in (
            ("source", _source(pg_conn, principal)),
            ("tool", _tool(pg_conn, principal)),
            ("prompt", _prompt(pg_conn, principal)),
            ("agent", str(AgentsRepository(pg_conn).create(principal, "a", "draft")["id"])),
        ):
            status, body = _file(app, pg_conn, "eddie", kind, personal, [item])
            assert (status, body["error"]) == (409, "team_item_not_fileable"), kind
            assert body["ids"] == [item]
        assert FolderItemsRepository(pg_conn).resource_ids_in("eddie", [personal]) == []

    def test_a_personal_item_is_never_filed_in_a_team_folder(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        team_folder = _folder(pg_conn, principal, "Team")
        mine = _source(pg_conn, "eddie")
        team_source = _source(pg_conn, principal)
        status, body = _file(app, pg_conn, "eddie", "source", team_folder, [team_source, mine], team=tid)
        assert (status, body["error"]) == (409, "item_not_in_team")
        assert body["ids"] == [mine]
        # Nothing was written: the whole request is refused.
        assert FolderItemsRepository(pg_conn).filings(principal, "source") == {}

    def test_another_teams_item_is_not_filed_in_this_teams_folder(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        _other, other_principal = _team(pg_conn, name="Other", members=(("eddie", "team_editor"),))
        team_folder = _folder(pg_conn, principal, "Team")
        theirs = _prompt(pg_conn, other_principal)
        status, body = _file(app, pg_conn, "eddie", "prompt", team_folder, [theirs], team=tid)
        assert (status, body["error"]) == (409, "item_not_in_team")

    def test_editor_files_team_items_under_the_principal(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        team_folder = _folder(pg_conn, principal, "Team")
        tool, prompt = _tool(pg_conn, principal), _prompt(pg_conn, principal)
        assert _file(app, pg_conn, "eddie", "tool", team_folder, [tool], team=tid)[0] == 200
        assert _file(app, pg_conn, "adam", "prompt", team_folder, [prompt], team=tid)[0] == 200
        assert FolderItemsRepository(pg_conn).filings(principal, "tool") == {tool: team_folder}
        assert FolderItemsRepository(pg_conn).filings(principal, "prompt") == {prompt: team_folder}
        assert FolderItemsRepository(pg_conn).filings("eddie", "tool") == {}
        _s, body = _list(app, pg_conn, "vera", team=tid)
        assert body["folders"][0]["counts"] == {"agent": 0, "source": 0, "tool": 1, "prompt": 1}
        # Unfiling in the team takes the team's filing away.
        assert _file(app, pg_conn, "eddie", "tool", None, [tool], team=tid)[0] == 200
        assert FolderItemsRepository(pg_conn).filings(principal, "tool") == {}

    def test_personal_folder_holds_own_and_grant_shared_tools_and_prompts(self, app, pg_conn):
        team = TeamsRepository(pg_conn).create("T", f"t-{uuid.uuid4().hex[:6]}", "owen")
        TeamMembersRepository(pg_conn).add_member(str(team["id"]), "eve")
        shared_tool, shared_prompt = _tool(pg_conn, "owen"), _prompt(pg_conn, "owen")
        grants = TeamResourceGrantsRepository(pg_conn)
        for kind, rid in (("tool", shared_tool), ("prompt", shared_prompt)):
            grants.grant(str(team["id"]), kind, rid, "owen", "owen", access_level="viewer", target_user_id="eve")
        folder = _folder(pg_conn, "eve", "Mine")
        own_tool = _tool(pg_conn, "eve")
        status, body = _file(app, pg_conn, "eve", "tool", folder, [own_tool, shared_tool])
        assert (status, body["moved"]) == (200, [own_tool, shared_tool])
        status, body = _file(app, pg_conn, "eve", "prompt", folder, [shared_prompt])
        assert (status, body["moved"]) == (200, [shared_prompt])
        _s, body = _list(app, pg_conn, "eve")
        assert body["folders"][0]["counts"]["tool"] == 2

    def test_a_builtin_tool_has_no_row_and_is_skipped(self, app, pg_conn):
        from docsgpt.agents.default_tools import default_tool_id

        folder = _folder(pg_conn, "eve", "Mine")
        builtin = default_tool_id("memory")
        status, body = _file(app, pg_conn, "eve", "tool", folder, [builtin])
        assert (status, body["skipped"]) == (200, [builtin])

    def test_the_delete_triggers_clean_tool_and_prompt_filings(self, app, pg_conn):
        folder = _folder(pg_conn, "eve", "Mine")
        tool, prompt = _tool(pg_conn, "eve"), _prompt(pg_conn, "eve")
        items = FolderItemsRepository(pg_conn)
        items.file("eve", "tool", tool, folder)
        items.file("eve", "prompt", prompt, folder)
        UserToolsRepository(pg_conn).delete(tool, "eve")
        PromptsRepository(pg_conn).delete(prompt, "eve")
        assert items.filings("eve", "tool") == {}
        assert items.filings("eve", "prompt") == {}


# ---------------------------------------------------------------------------
# Live team folders
# ---------------------------------------------------------------------------
class TestLiveTeamFolder:
    def test_feeds_a_team_agent_with_sources_any_editor_filed(self, app, pg_conn):
        from docsgpt.api.user.folder_knowledge import folder_details, folder_source_ids

        tid, principal = _team(pg_conn)
        status, folder = _create(app, pg_conn, "eddie", "Live", team=tid)
        fid = folder["id"]
        by_eddie = _source(pg_conn, principal, "by-eddie", created_by="eddie")
        by_adam = _source(pg_conn, principal, "by-adam", created_by="adam")
        assert _file(app, pg_conn, "eddie", "source", fid, [by_eddie], team=tid)[0] == 200
        assert _file(app, pg_conn, "adam", "source", fid, [by_adam], team=tid)[0] == 200
        agent = AgentsRepository(pg_conn).create(principal, "Team agent", "draft", created_by="eddie")
        pg_conn.execute(
            text("UPDATE agents SET knowledge_folder_ids = ARRAY[CAST(:f AS uuid)] WHERE id = CAST(:a AS uuid)"),
            {"f": fid, "a": agent["id"]},
        )
        agent = AgentsRepository(pg_conn).get_by_id(str(agent["id"]))
        assert sorted(folder_source_ids(pg_conn, [fid], "agent", agent)) == sorted([by_eddie, by_adam])
        # The team's own folder is not named as someone else's on the agent.
        details = folder_details(pg_conn, [fid], "vera", "agent", agent)
        assert details[0]["source_count"] == 2
        assert "owner_id" not in details[0] and "stopped" not in details[0]

    def test_a_team_chat_reads_the_teams_folder(self, app, pg_conn):
        from docsgpt.api.user.folder_knowledge import caller_folder_source_ids

        tid, principal = _team(pg_conn)
        fid = _folder(pg_conn, principal, "Live")
        source = _source(pg_conn, principal)
        FolderItemsRepository(pg_conn).file(principal, "source", source, fid)
        assert caller_folder_source_ids(pg_conn, [fid], principal) == [source]
        assert caller_folder_source_ids(pg_conn, [fid], "eddie") == []

    def test_a_stray_personal_source_in_a_team_tree_feeds_nothing(self, app, pg_conn):
        from docsgpt.api.user.folder_knowledge import folder_source_ids

        tid, principal = _team(pg_conn)
        fid = _folder(pg_conn, principal, "Live")
        personal = _source(pg_conn, "eddie")
        # Written past the rules on purpose.
        FolderItemsRepository(pg_conn).file(principal, "source", personal, fid)
        agent = AgentsRepository(pg_conn).create(principal, "Team agent", "draft")
        assert folder_source_ids(pg_conn, [fid], "agent", agent) == []


# ---------------------------------------------------------------------------
# Tools and prompts carry their filing
# ---------------------------------------------------------------------------
def _tool_rows(status_body):
    _status, body = status_body
    return {t["id"]: t for t in body["tools"] if not t.get("default") and not t.get("builtin")}


class TestToolAndPromptFiling:
    def test_tool_folder_id_round_trip(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool, GetTools, UpdateTool

        top = _folder(pg_conn, "eve", "Top")
        sub = _folder(pg_conn, "eve", "Sub", parent=top)
        body = {"name": "read_webpage", "displayName": "w", "description": "", "config": {}, "status": True,
                "folder_id": sub}
        status, created = _call(app, pg_conn, CreateTool, "eve", json=body)
        assert status == 200, created
        tid = created["id"]
        row = _tool_rows(_call(app, pg_conn, GetTools, "eve", method="get"))[tid]
        assert row["folder_id"] == sub
        assert row["folder_path"] == [{"id": top, "name": "Top"}, {"id": sub, "name": "Sub"}]
        assert _call(app, pg_conn, UpdateTool, "eve", json={"id": tid, "folder_id": top})[0] == 200
        assert _tool_rows(_call(app, pg_conn, GetTools, "eve", method="get"))[tid]["folder_id"] == top
        assert _call(app, pg_conn, UpdateTool, "eve", json={"id": tid, "folder_id": None})[0] == 200
        row = _tool_rows(_call(app, pg_conn, GetTools, "eve", method="get"))[tid]
        assert (row["folder_id"], row["folder_path"]) == (None, [])

    def test_tool_create_refuses_a_folder_outside_the_workspace(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        tid, principal = _team(pg_conn)
        personal = _folder(pg_conn, "eddie", "Mine")
        body = {"name": "read_webpage", "displayName": "w", "description": "", "config": {}, "status": True,
                "folder_id": personal}
        status, resp = _call(app, pg_conn, CreateTool, "eddie", team=tid, json=body)
        assert (status, resp["error"]) == (404, "folder_not_found")
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_team_tool_files_in_the_team_tree(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool, GetTools

        tid, principal = _team(pg_conn)
        team_folder = _folder(pg_conn, principal, "Team")
        body = {"name": "read_webpage", "displayName": "w", "description": "", "config": {}, "status": False,
                "folder_id": team_folder}
        status, created = _call(app, pg_conn, CreateTool, "eddie", team=tid, json=body)
        assert status == 200, created
        assert FolderItemsRepository(pg_conn).filings(principal, "tool") == {created["id"]: team_folder}
        row = _tool_rows(_call(app, pg_conn, GetTools, "vera", team=tid, method="get"))[created["id"]]
        assert row["folder_path"] == [{"id": team_folder, "name": "Team"}]

    def test_a_team_viewer_cannot_refile_a_team_tool(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool

        tid, principal = _team(pg_conn)
        team_folder = _folder(pg_conn, principal, "Team")
        tool = _tool(pg_conn, principal)
        status, _body = _call(app, pg_conn, UpdateTool, "vera", json={"id": tool, "folder_id": team_folder})
        assert status == 403
        assert FolderItemsRepository(pg_conn).filings(principal, "tool") == {}

    def test_prompt_folder_id_round_trip(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import CreatePrompt, GetPrompts, GetSinglePrompt, UpdatePrompt

        folder = _folder(pg_conn, "eve", "Prompts")
        status, created = _call(app, pg_conn, CreatePrompt, "eve",
                                json={"name": "P", "content": "c", "folder_id": folder})
        assert status == 200, created
        pid = created["id"]
        _s, rows = _call(app, pg_conn, GetPrompts, "eve", method="get")
        row = next(p for p in rows if p["id"] == pid)
        assert (row["folder_id"], row["folder_path"]) == (folder, [{"id": folder, "name": "Prompts"}])
        assert next(p for p in rows if p["id"] == "default").get("folder_id") is None
        _s, single = _call(app, pg_conn, GetSinglePrompt, "eve", method="get", path=f"/api/x?id={pid}")
        assert single["folder_id"] == folder
        status, _b = _call(app, pg_conn, UpdatePrompt, "eve",
                           json={"id": pid, "name": "P", "content": "c2", "folder_id": None})
        assert status == 200
        assert FolderItemsRepository(pg_conn).filings("eve", "prompt") == {}

    def test_team_prompt_files_in_the_team_tree(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import CreatePrompt, GetPrompts

        tid, principal = _team(pg_conn)
        team_folder = _folder(pg_conn, principal, "Team")
        status, created = _call(app, pg_conn, CreatePrompt, "eddie", team=tid,
                                json={"name": "P", "content": "c", "folder_id": team_folder})
        assert status == 200, created
        assert FolderItemsRepository(pg_conn).filings(principal, "prompt") == {created["id"]: team_folder}
        _s, rows = _call(app, pg_conn, GetPrompts, "vera", team=tid, method="get")
        assert next(p for p in rows if p["id"] == created["id"])["folder_id"] == team_folder


# ---------------------------------------------------------------------------
# /api/agents/folders aliases
# ---------------------------------------------------------------------------
class TestAgentFolderAliases:
    def test_the_aliases_follow_the_workspace(self, app, pg_conn):
        from docsgpt.api.user.agents.folders import AgentFolder, AgentFolders

        tid, principal = _team(pg_conn)
        fid = _folder(pg_conn, principal, "Team")
        agent = str(AgentsRepository(pg_conn).create(principal, "Team agent", "draft")["id"])
        FolderItemsRepository(pg_conn).file(principal, "agent", agent, fid)
        status, body = _call(app, pg_conn, AgentFolders, "vera", team=tid, method="get")
        assert (status, [f["name"] for f in body["folders"]]) == (200, ["Team"])
        status, body = _call(app, pg_conn, AgentFolder, "vera", method="get", args=(fid,))
        assert status == 200
        assert [a["id"] for a in body["agents"]] == [agent]
        status, body = _call(app, pg_conn, AgentFolders, "vera", team=tid, json={"name": "x"})
        assert (status, body["error"]) == (403, "workspace_role_required")
        status, body = _call(app, pg_conn, AgentFolders, "eddie", team=tid, json={"name": "x"})
        assert status == 201
        assert FoldersRepository(pg_conn).get(body["id"], principal) is not None
        status, _b = _call(app, pg_conn, AgentFolder, "vera", method="delete", args=(fid,))
        assert status == 403
        status, _b = _call(app, pg_conn, AgentFolder, "mallory", method="get", args=(fid,))
        assert status == 404

    def test_move_agent_into_a_personal_folder_refuses_a_team_agent(self, app, pg_conn):
        from docsgpt.api.user.agents.folders import MoveAgentToFolder

        tid, principal = _team(pg_conn)
        agent = str(AgentsRepository(pg_conn).create(principal, "Team agent", "draft")["id"])
        personal = _folder(pg_conn, "eddie", "Mine")
        status, body = _call(app, pg_conn, MoveAgentToFolder, "eddie",
                             json={"agent_id": agent, "folder_id": personal})
        assert (status, body["error"]) == (409, "team_item_not_fileable")


# ---------------------------------------------------------------------------
# Personal access tokens
# ---------------------------------------------------------------------------
AGENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TOOL_A = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TOOL_B = "dddddddd-dddd-dddd-dddd-dddddddddddd"
FOLDER = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


@pytest.fixture(scope="module")
def flask_app():
    from docsgpt.app import app as real_app

    real_app.config["TESTING"] = True
    return real_app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _claims(scopes, resource_filter=None):
    from docsgpt.api.pat.tokens import expand_scopes

    return {"sub": "alice", "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
            "scopes": sorted(expand_scopes(scopes)), "resource_filter": resource_filter or {}}


def _pat(client, method, path, claims, **kwargs):
    with patch("docsgpt.app.handle_auth", return_value=claims), patch(
        "docsgpt.api.user.folders.routes.db_session", side_effect=RuntimeError("no database here")
    ), patch("docsgpt.api.user.folders.routes.db_readonly", side_effect=RuntimeError("no database here")), patch(
        "docsgpt.api.user.agents.folders.db_session", side_effect=RuntimeError("no database here")
    ):
        return client.open(path, method=method, **kwargs)


def _denied(response):
    if response.status_code != 403:
        return None
    return (json.loads(response.data) or {}).get("error")


@pytest.mark.unit
class TestPatFolderRule:
    def test_type_query_cannot_lift_an_agent_restriction_on_a_folder_id_route(self, client):
        claims = _claims(["agents:write", "sources:write"], {"agents": [AGENT_A]})
        for query in ("", "?type=source", "?type=tool", "?type=prompt"):
            assert _denied(_pat(client, "PUT", f"/api/folders/{FOLDER}{query}", claims, json={"name": "y"})) \
                == "resource_not_allowed", query
            assert _denied(_pat(client, "DELETE", f"/api/folders/{FOLDER}{query}", claims)) \
                == "resource_not_allowed", query

    @pytest.mark.parametrize("family", ["agents", "sources", "tools", "prompts"])
    def test_a_token_restricted_on_any_kind_cannot_change_folders(self, client, family):
        claims = _claims([f"{family}:write"], {family: [TOOL_A]})
        assert _denied(_pat(client, "POST", "/api/folders", claims, json={"name": "x"})) == "resource_not_allowed"
        assert _denied(_pat(client, "PUT", f"/api/folders/{FOLDER}", claims, json={"name": "x"})) \
            == "resource_not_allowed"
        assert _denied(_pat(client, "DELETE", f"/api/folders/{FOLDER}", claims)) == "resource_not_allowed"

    def test_the_agent_folder_aliases_follow_the_same_rule(self, client):
        claims = _claims(["agents:write"], {"tools": [TOOL_A]})
        assert _denied(_pat(client, "POST", "/api/agents/folders/", claims, json={"name": "x"})) \
            == "resource_not_allowed"
        assert _denied(_pat(client, "PUT", f"/api/agents/folders/{FOLDER}", claims, json={"name": "x"})) \
            == "resource_not_allowed"

    def test_any_write_scope_creates_a_folder(self, client):
        for scope in ("agents:write", "sources:write", "tools:write", "prompts:write"):
            response = _pat(client, "POST", "/api/folders", _claims([scope]), json={"name": "x"})
            assert _denied(response) is None, scope
        response = _pat(client, "POST", "/api/folders", _claims(["agents:read"]), json={"name": "x"})
        assert _denied(response) == "insufficient_scope"

    def test_filing_reads_the_family_from_the_body(self, client):
        claims = _claims(["tools:write"], {"tools": [TOOL_A]})
        ok = _pat(client, "POST", "/api/folders/items", claims,
                  json={"type": "tool", "folder_id": None, "ids": [TOOL_A]})
        bad = _pat(client, "POST", "/api/folders/items", claims,
                   json={"type": "tool", "folder_id": None, "ids": [TOOL_A, TOOL_B]})
        sneaky = _pat(client, "POST", "/api/folders/items?type=agent", claims,
                      json={"type": "tool", "folder_id": None, "ids": [TOOL_B]})
        assert _denied(ok) is None
        assert _denied(bad) == "resource_not_allowed"
        assert _denied(sneaky) == "resource_not_allowed"
        # Filing a kind needs that kind's write scope.
        wrong = _pat(client, "POST", "/api/folders/items", _claims(["agents:write"]),
                     json={"type": "prompt", "folder_id": None, "ids": [TOOL_A]})
        assert _denied(wrong) == "insufficient_scope"

    def test_agent_tool_offers_no_folder_edits_to_a_restricted_token(self):
        from docsgpt.api.pat.agent_tool import build_actions

        free = build_actions("https://x", "tok", ["tools:write", "tools:read"], {})
        assert {"create_folder", "update_folder", "file_in_folder", "list_folders"} <= set(free)
        restricted = build_actions("https://x", "tok", ["tools:write", "tools:read"], {"tools": [TOOL_A]})
        assert "create_folder" not in restricted and "update_folder" not in restricted
        assert "file_in_folder" in restricted
        assert "tool" in restricted["file_in_folder"]["body"]["properties"]["type"]["description"]
