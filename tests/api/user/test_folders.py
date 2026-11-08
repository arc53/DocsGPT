"""``/api/folders``: personal folders for agents and sources, on real repositories (``pg_conn``)."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository

USER, OTHER = "f-user", "f-other"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.folders.routes.db_session", _yield), patch(
        "docsgpt.api.user.folders.routes.db_readonly", _yield
    ):
        yield


def _call(app, conn, method, path, user=USER, *, json=None, args=()):
    from docsgpt.api.user.folders.routes import FolderItems, FolderResource, Folders

    resource = FolderItems if path.startswith("/api/folders/items") else (
        FolderResource if args else Folders
    )
    kwargs = {"method": method.upper()}
    if json is not None:
        kwargs["json"] = json
    with _patch_db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        response = getattr(resource(), method.lower())(*args)
    return response.status_code, response.get_json()


def _create(app, conn, name, *, type_="source", parent=None, user=USER):
    body = {"type": type_, "name": name}
    if parent:
        body["parent_id"] = parent
    return _call(app, conn, "post", "/api/folders", user, json=body)


def _source(conn, owner=USER, name="s"):
    return str(SourcesRepository(conn).create(name, user_id=owner)["id"])


def _share(conn, resource_type, resource_id, owner, member, level="viewer"):
    team = TeamsRepository(conn).create("T", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), resource_type, resource_id, owner, owner, access_level=level, target_user_id=member
    )


class TestCreate:
    def test_needs_a_session(self, app, pg_conn):
        status, _ = _call(app, pg_conn, "get", "/api/folders?type=source", None)
        assert status == 401

    def test_type_is_required(self, app, pg_conn):
        status, body = _call(app, pg_conn, "get", "/api/folders")
        assert (status, body["error"]) == (400, "invalid_type")
        status, body = _call(app, pg_conn, "post", "/api/folders", json={"type": "tool", "name": "x"})
        assert (status, body["error"]) == (400, "invalid_type")

    def test_creates_a_trimmed_folder(self, app, pg_conn):
        status, body = _create(app, pg_conn, "  Carriers  ")
        assert status == 201
        assert body["name"] == "Carriers"
        assert body["type"] == "source"
        assert body["parent_id"] is None
        assert (body["item_count"], body["folder_count"]) == (0, 0)
        assert body["used_by"] == {"agents": [], "others": 0}

    @pytest.mark.parametrize("name", ["", "   ", "x" * 81, "bad\x07name", 7, None])
    def test_rejects_bad_names(self, app, pg_conn, name):
        status, body = _call(app, pg_conn, "post", "/api/folders", json={"type": "source", "name": name})
        assert (status, body["error"]) == (400, "invalid_folder_name")

    def test_sibling_names_are_unique_ignoring_case(self, app, pg_conn):
        _, parent = _create(app, pg_conn, "Carriers")
        assert _create(app, pg_conn, "carriers")[1]["error"] == "folder_name_taken"
        assert _create(app, pg_conn, "CARRIERS")[0] == 409
        # Another parent, another type or another user is fine.
        assert _create(app, pg_conn, "Carriers", parent=parent["id"])[0] == 201
        assert _create(app, pg_conn, "Carriers", type_="agent")[0] == 201
        assert _create(app, pg_conn, "Carriers", user=OTHER)[0] == 201

    def test_three_levels_deep_at_most(self, app, pg_conn):
        _, one = _create(app, pg_conn, "1")
        _, two = _create(app, pg_conn, "2", parent=one["id"])
        status, three = _create(app, pg_conn, "3", parent=two["id"])
        assert status == 201
        status, body = _create(app, pg_conn, "4", parent=three["id"])
        assert (status, body["error"]) == (400, "folder_too_deep")

    def test_parent_must_be_the_callers_folder_of_the_type(self, app, pg_conn):
        _, agent_folder = _create(app, pg_conn, "Agents", type_="agent")
        _, theirs = _create(app, pg_conn, "Theirs", user=OTHER)
        for parent in (agent_folder["id"], theirs["id"], "not-a-folder"):
            status, body = _create(app, pg_conn, "x", parent=parent)
            assert (status, body["error"]) == (404, "folder_not_found")


class TestUpdate:
    def _put(self, app, conn, folder_id, body, user=USER):
        return _call(app, conn, "put", f"/api/folders/{folder_id}", user, json=body, args=(folder_id,))

    def test_renames_and_moves(self, app, pg_conn):
        _, a = _create(app, pg_conn, "A")
        _, b = _create(app, pg_conn, "B")
        status, body = self._put(app, pg_conn, b["id"], {"name": "Bee", "parent_id": a["id"]})
        assert status == 200
        assert (body["name"], body["parent_id"]) == ("Bee", a["id"])
        status, body = self._put(app, pg_conn, b["id"], {"parent_id": None})
        assert (status, body["parent_id"]) == (200, None)

    def test_rename_collides_with_a_sibling(self, app, pg_conn):
        _create(app, pg_conn, "A")
        _, b = _create(app, pg_conn, "B")
        status, body = self._put(app, pg_conn, b["id"], {"name": "a"})
        assert (status, body["error"]) == (409, "folder_name_taken")
        # Renaming to its own name in another case is fine.
        assert self._put(app, pg_conn, b["id"], {"name": "b"})[0] == 200

    def test_a_move_lands_among_new_siblings_by_name(self, app, pg_conn):
        _, a = _create(app, pg_conn, "A")
        _create(app, pg_conn, "Dup", parent=a["id"])
        _, dup = _create(app, pg_conn, "Dup")
        status, body = self._put(app, pg_conn, dup["id"], {"parent_id": a["id"]})
        assert (status, body["error"]) == (409, "folder_name_taken")

    def test_no_cycles(self, app, pg_conn):
        _, a = _create(app, pg_conn, "A")
        _, b = _create(app, pg_conn, "B", parent=a["id"])
        for target in (a["id"], b["id"]):
            status, body = self._put(app, pg_conn, a["id"], {"parent_id": target})
            assert (status, body["error"]) == (400, "folder_cycle")

    def test_a_move_keeps_the_whole_subtree_within_three_levels(self, app, pg_conn):
        _, a = _create(app, pg_conn, "A")
        _, a2 = _create(app, pg_conn, "A2", parent=a["id"])
        _, b = _create(app, pg_conn, "B")
        _create(app, pg_conn, "B2", parent=b["id"])
        status, body = self._put(app, pg_conn, b["id"], {"parent_id": a2["id"]})
        assert (status, body["error"]) == (400, "folder_too_deep")
        assert self._put(app, pg_conn, b["id"], {"parent_id": a["id"]})[0] == 200

    def test_existing_deeper_folders_keep_working(self, app, pg_conn):
        repo = FoldersRepository(pg_conn)
        parent = None
        for level in range(5):
            parent = repo.create(USER, f"L{level}", parent_id=parent["id"] if parent else None)
        status, body = self._put(app, pg_conn, parent["id"], {"name": "renamed"})
        assert (status, body["name"]) == (200, "renamed")
        # A full-form save re-sending the current parent isn't a move.
        status, _ = self._put(app, pg_conn, parent["id"], {"name": "again", "parent_id": parent["parent_id"]})
        assert status == 200

    def test_another_users_folder_is_not_found(self, app, pg_conn):
        _, theirs = _create(app, pg_conn, "Theirs", user=OTHER)
        status, body = self._put(app, pg_conn, theirs["id"], {"name": "mine"})
        assert (status, body["error"]) == (404, "folder_not_found")


class TestDelete:
    def _delete(self, app, conn, folder_id, user=USER):
        return _call(app, conn, "delete", f"/api/folders/{folder_id}", user, args=(folder_id,))

    def test_contents_move_to_the_parent(self, app, pg_conn):
        _, top = _create(app, pg_conn, "Top")
        _, mid = _create(app, pg_conn, "Mid", parent=top["id"])
        _, leaf = _create(app, pg_conn, "Leaf", parent=mid["id"])
        source = _source(pg_conn)
        FolderItemsRepository(pg_conn).file(USER, "source", source, mid["id"])
        status, body = self._delete(app, pg_conn, mid["id"])
        assert status == 200
        assert body == {"success": True, "moved_items": 1, "moved_folders": 1}
        assert FoldersRepository(pg_conn).get(leaf["id"], USER)["parent_id"] == top["id"]
        assert FolderItemsRepository(pg_conn).filing(USER, "source", source) == top["id"]

    def test_agents_reading_it_live_lose_it(self, app, pg_conn):
        _, folder = _create(app, pg_conn, "Live")
        agent = AgentsRepository(pg_conn).create(USER, "a", "draft")
        pg_conn.execute(
            text("UPDATE agents SET knowledge_folder_ids = ARRAY[CAST(:f AS uuid)] WHERE id = CAST(:a AS uuid)"),
            {"f": folder["id"], "a": agent["id"]},
        )
        assert self._delete(app, pg_conn, folder["id"])[0] == 200
        assert AgentsRepository(pg_conn).get_by_id(agent["id"])["knowledge_folder_ids"] == []

    def test_another_users_folder_is_not_found(self, app, pg_conn):
        _, theirs = _create(app, pg_conn, "Theirs", user=OTHER)
        assert self._delete(app, pg_conn, theirs["id"])[0] == 404
        assert FoldersRepository(pg_conn).get(theirs["id"], OTHER) is not None


class TestFileItems:
    def _file(self, app, conn, body, user=USER):
        return _call(app, conn, "post", "/api/folders/items", user, json=body)

    def test_files_what_the_caller_can_see(self, app, pg_conn):
        _, folder = _create(app, pg_conn, "K")
        own = _source(pg_conn)
        shared = _source(pg_conn, owner=OTHER, name="shared")
        hidden = _source(pg_conn, owner=OTHER, name="hidden")
        _share(pg_conn, "source", shared, OTHER, USER)
        stamp = SourcesRepository(pg_conn).get_by_id(shared)["updated_at"]
        status, body = self._file(app, pg_conn, {"type": "source", "folder_id": folder["id"],
                                                 "ids": [own, shared, hidden]})
        assert status == 200
        assert (body["moved"], body["skipped"]) == ([own, shared], [hidden])
        assert FolderItemsRepository(pg_conn).filings(USER, "source") == {own: folder["id"], shared: folder["id"]}
        # Filing never touches the item, and the owner's filing is their own.
        assert SourcesRepository(pg_conn).get_by_id(shared)["updated_at"] == stamp
        assert FolderItemsRepository(pg_conn).filings(OTHER, "source") == {}

    def test_null_unfiles(self, app, pg_conn):
        _, folder = _create(app, pg_conn, "K")
        own = _source(pg_conn)
        self._file(app, pg_conn, {"type": "source", "folder_id": folder["id"], "ids": [own]})
        status, body = self._file(app, pg_conn, {"type": "source", "folder_id": None, "ids": [own]})
        assert (status, body["moved"]) == (200, [own])
        assert FolderItemsRepository(pg_conn).filings(USER, "source") == {}

    def test_only_into_the_callers_folder_of_the_items_type(self, app, pg_conn):
        _, agent_folder = _create(app, pg_conn, "Agents", type_="agent")
        _, theirs = _create(app, pg_conn, "Theirs", user=OTHER)
        own = _source(pg_conn)
        for folder_id in (agent_folder["id"], theirs["id"]):
            status, body = self._file(app, pg_conn, {"type": "source", "folder_id": folder_id, "ids": [own]})
            assert (status, body["error"]) == (404, "folder_not_found")

    @pytest.mark.parametrize("ids", [None, [], "x", [str(i) for i in range(501)]])
    def test_ids_must_be_a_short_list(self, app, pg_conn, ids):
        status, body = self._file(app, pg_conn, {"type": "source", "folder_id": None, "ids": ids})
        assert (status, body["error"]) == (400, "invalid_ids")

    def test_files_agents_too(self, app, pg_conn):
        _, folder = _create(app, pg_conn, "Agents", type_="agent")
        agent = str(AgentsRepository(pg_conn).create(OTHER, "a", "draft")["id"])
        _share(pg_conn, "agent", agent, OTHER, USER)
        status, body = self._file(app, pg_conn, {"type": "agent", "folder_id": folder["id"], "ids": [agent]})
        assert (status, body["moved"]) == (200, [agent])


class TestList:
    def test_counts_direct_children_the_caller_can_see(self, app, pg_conn):
        _, top = _create(app, pg_conn, "Top")
        _, child = _create(app, pg_conn, "Child", parent=top["id"])
        own = _source(pg_conn)
        shared = _source(pg_conn, owner=OTHER, name="shared")
        _share(pg_conn, "source", shared, OTHER, USER)
        items = FolderItemsRepository(pg_conn)
        items.file(USER, "source", own, top["id"])
        items.file(USER, "source", shared, child["id"])
        # A filing of a source no longer shared stays hidden.
        gone = _source(pg_conn, owner=OTHER, name="gone")
        items.file(USER, "source", gone, top["id"])
        status, body = _call(app, pg_conn, "get", "/api/folders?type=source")
        assert status == 200
        by_name = {f["name"]: f for f in body["folders"]}
        assert (by_name["Top"]["item_count"], by_name["Top"]["folder_count"]) == (1, 1)
        assert (by_name["Child"]["item_count"], by_name["Child"]["folder_count"]) == (1, 0)
        assert by_name["Child"]["parent_id"] == top["id"]

    def test_lists_one_type_of_the_callers_folders(self, app, pg_conn):
        _create(app, pg_conn, "K")
        _create(app, pg_conn, "A", type_="agent")
        _create(app, pg_conn, "Theirs", user=OTHER)
        _, body = _call(app, pg_conn, "get", "/api/folders?type=agent")
        assert [f["name"] for f in body["folders"]] == ["A"]
        assert "used_by" not in body["folders"][0]

    def test_source_folders_name_the_agents_reading_them(self, app, pg_conn):
        _, folder = _create(app, pg_conn, "Live")
        agent = AgentsRepository(pg_conn).create(USER, "Reader", "published")
        pg_conn.execute(
            text("UPDATE agents SET knowledge_folder_ids = ARRAY[CAST(:f AS uuid)] WHERE id = CAST(:a AS uuid)"),
            {"f": folder["id"], "a": agent["id"]},
        )
        hidden = AgentsRepository(pg_conn).create(OTHER, "Theirs", "published")
        pg_conn.execute(
            text("UPDATE agents SET knowledge_folder_ids = ARRAY[CAST(:f AS uuid)] WHERE id = CAST(:a AS uuid)"),
            {"f": folder["id"], "a": hidden["id"]},
        )
        _, body = _call(app, pg_conn, "get", "/api/folders?type=source")
        used_by = body["folders"][0]["used_by"]
        assert [a["name"] for a in used_by["agents"]] == ["Reader"]
        assert used_by["others"] == 1
