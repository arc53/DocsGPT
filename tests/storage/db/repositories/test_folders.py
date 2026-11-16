"""Tests for FoldersRepository and FolderItemsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository


def _repo(conn) -> FoldersRepository:
    return FoldersRepository(conn)


class TestCreate:
    def test_creates_folder(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "My Folder")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "My Folder"
        assert doc["id"] is not None

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "f")
        assert doc["_id"] == doc["id"]


class TestNesting:
    def test_create_with_parent(self, pg_conn):
        repo = _repo(pg_conn)
        parent = repo.create("u", "Parent")
        child = repo.create("u", "Child", parent_id=parent["id"])
        assert str(child["parent_id"]) == str(parent["id"])

    def test_list_children(self, pg_conn):
        repo = _repo(pg_conn)
        parent = repo.create("u", "Parent")
        repo.create("u", "Child A", parent_id=parent["id"])
        repo.create("u", "Child B", parent_id=parent["id"])
        repo.create("u", "Top-level — not a child")
        children = repo.list_children(parent["id"], "u")
        assert {c["name"] for c in children} == {"Child A", "Child B"}

    def test_update_reparents(self, pg_conn):
        repo = _repo(pg_conn)
        a = repo.create("u", "A")
        b = repo.create("u", "B")
        c = repo.create("u", "C", parent_id=a["id"])
        repo.update(c["id"], "u", {"parent_id": b["id"]})
        assert str(repo.get(c["id"], "u")["parent_id"]) == str(b["id"])

    def test_update_clears_parent(self, pg_conn):
        repo = _repo(pg_conn)
        parent = repo.create("u", "P")
        child = repo.create("u", "C", parent_id=parent["id"])
        repo.update(child["id"], "u", {"parent_id": None})
        assert repo.get(child["id"], "u")["parent_id"] is None

    def test_delete_parent_unparents_children(self, pg_conn):
        """A top-level folder's children become top-level folders."""
        repo = _repo(pg_conn)
        parent = repo.create("u", "P")
        child = repo.create("u", "C", parent_id=parent["id"])
        assert repo.delete_into_parent(parent) == {"moved_items": 0, "moved_folders": 1, "renamed": []}
        survivor = repo.get(child["id"], "u")
        assert survivor is not None
        assert survivor["parent_id"] is None

    def test_get_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "F", legacy_mongo_id="abc123")
        found = repo.get_by_legacy_id("abc123", "u")
        assert found is not None
        assert found["name"] == "F"


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "f")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "f")
        assert repo.get(created["id"], "user-other") is None


class TestListForUser:
    def test_lists_only_own_folders(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "f1")
        repo.create("alice", "f2")
        repo.create("bob", "f3")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)


class TestUpdate:
    def test_updates_name(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        updated = repo.update(created["id"], "user-1", {"name": "new"})
        assert updated is True
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "new"

    def test_update_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old")
        updated = repo.update(created["id"], "user-other", {"name": "new"})
        assert updated is False
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "old"

    def test_update_disallowed_field_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "f")
        updated = repo.update(created["id"], "user-1", {"id": "00000000-0000-0000-0000-000000000000"})
        assert updated is False


class TestDelete:
    def test_moves_children_and_items_to_the_parent(self, pg_conn):
        repo = _repo(pg_conn)
        items = FolderItemsRepository(pg_conn)
        top = repo.create("u", "Top")
        mid = repo.create("u", "Mid", parent_id=top["id"])
        leaf = repo.create("u", "Leaf", parent_id=mid["id"])
        agent = AgentsRepository(pg_conn).create("u", "a", "draft")
        items.file("u", "agent", agent["id"], mid["id"])
        assert repo.delete_into_parent(mid) == {"moved_items": 1, "moved_folders": 1, "renamed": []}
        assert repo.get(mid["id"], "u") is None
        assert repo.get(leaf["id"], "u")["parent_id"] == top["id"]
        assert items.filing("u", "agent", agent["id"]) == top["id"]

    def test_top_level_delete_unfiles_items(self, pg_conn):
        repo = _repo(pg_conn)
        items = FolderItemsRepository(pg_conn)
        folder = repo.create("u", "F")
        agent = AgentsRepository(pg_conn).create("u", "a", "draft")
        items.file("u", "agent", agent["id"], folder["id"])
        assert repo.delete_into_parent(folder) == {"moved_items": 1, "moved_folders": 0, "renamed": []}
        assert items.filing("u", "agent", agent["id"]) is None


class TestTree:
    def test_ancestors_and_subtree_levels(self, pg_conn):
        repo = _repo(pg_conn)
        a = repo.create("u", "A")
        b = repo.create("u", "B", parent_id=a["id"])
        c = repo.create("u", "C", parent_id=b["id"])
        assert repo.ancestors(c["id"], "u") == [c["id"], b["id"], a["id"]]
        assert repo.subtree_levels(a["id"], "u") == {a["id"]: 1, b["id"]: 2, c["id"]: 3}
        assert repo.ancestors(c["id"], "other") == []

    def test_a_corrupt_cycle_terminates(self, pg_conn):
        repo = _repo(pg_conn)
        a = repo.create("u", "A")
        b = repo.create("u", "B", parent_id=a["id"])
        pg_conn.execute(
            text("UPDATE folders SET parent_id = CAST(:b AS uuid) WHERE id = CAST(:a AS uuid)"),
            {"a": a["id"], "b": b["id"]},
        )
        assert set(repo.ancestors(a["id"], "u")) == {a["id"], b["id"]}
        assert set(repo.subtree_levels(a["id"], "u")) == {a["id"], b["id"]}

    def test_sibling_named_ignores_case_and_type_but_not_parent(self, pg_conn):
        repo = _repo(pg_conn)
        parent = repo.create("u", "P")
        child = repo.create("u", "Carriers", parent_id=parent["id"])
        top = repo.create("u", "Carriers", resource_type="source")
        assert repo.sibling_named("u", "agent", parent["id"], "carriers")["id"] == child["id"]
        assert repo.sibling_named("u", "agent", parent["id"], "carriers", exclude_id=child["id"]) is None
        # One tree: the type no longer separates folders.
        assert repo.sibling_named("u", "agent", None, "carriers")["id"] == top["id"]
        assert repo.sibling_named("u", "source", None, "CARRIERS")["id"] == top["id"]

    def test_one_tree_whatever_the_type(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "agents")
        source = repo.create("u", "knowledge", resource_type="source")
        assert sorted(f["name"] for f in repo.list_for_user("u", "source")) == ["agents", "knowledge"]
        assert sorted(f["name"] for f in repo.list_for_user("u")) == ["agents", "knowledge"]
        assert repo.get(source["id"], "u", "agent")["id"] == source["id"]
        assert "resource_type" not in source

    def test_names_are_unique_across_kinds(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "Shared")
        with pytest.raises(IntegrityError), pg_conn.begin_nested():
            repo.create("u", "shared", resource_type="source")


class TestDeleteKeepsNamesUnique:
    def test_a_child_whose_name_is_taken_above_gets_a_suffix(self, pg_conn):
        repo = _repo(pg_conn)
        items = FolderItemsRepository(pg_conn)
        top = repo.create("u", "Docs")
        project = repo.create("u", "Project")
        clash = repo.create("u", "docs", parent_id=project["id"])
        taken = repo.create("u", "Docs (2)", parent_id=project["id"])
        agent = AgentsRepository(pg_conn).create("u", "x", "draft")
        items.file("u", "agent", agent["id"], project["id"])
        moved = repo.delete_into_parent(project)
        assert moved == {
            "moved_items": 1,
            "moved_folders": 2,
            "renamed": [{"id": clash["id"], "from": "docs", "to": "docs (3)"}],
        }
        names = {f["id"]: f["name"] for f in repo.list_for_user("u")}
        assert names == {top["id"]: "Docs", clash["id"]: "docs (3)", taken["id"]: "Docs (2)"}

    def test_a_child_named_like_the_deleted_folder_keeps_its_name(self, pg_conn):
        repo = _repo(pg_conn)
        outer = repo.create("u", "Docs")
        inner = repo.create("u", "Docs", parent_id=outer["id"])
        moved = repo.delete_into_parent(outer)
        assert moved["renamed"] == []
        assert repo.get(inner["id"], "u")["name"] == "Docs"


class TestFolderItems:
    def test_file_moves_and_unfiles(self, pg_conn):
        repo = _repo(pg_conn)
        items = FolderItemsRepository(pg_conn)
        a = repo.create("u", "A")
        b = repo.create("u", "B")
        agent = AgentsRepository(pg_conn).create("u", "x", "draft")
        items.file("u", "agent", agent["id"], a["id"])
        items.file("u", "agent", agent["id"], b["id"])
        assert items.filings("u", "agent") == {agent["id"]: b["id"]}
        assert items.resource_ids_in("u", [a["id"], b["id"]]) == [agent["id"]]
        items.file("u", "agent", agent["id"], None)
        assert items.filings("u", "agent") == {}

    def test_filings_are_per_user(self, pg_conn):
        repo = _repo(pg_conn)
        items = FolderItemsRepository(pg_conn)
        mine = repo.create("u", "Mine")
        theirs = repo.create("v", "Theirs")
        agent = AgentsRepository(pg_conn).create("u", "x", "draft")
        items.file("u", "agent", agent["id"], mine["id"])
        items.file("v", "agent", agent["id"], theirs["id"])
        assert items.filing("u", "agent", agent["id"]) == mine["id"]
        assert items.filing("v", "agent", agent["id"]) == theirs["id"]
        assert items.filings("u", "agent", ["not-a-uuid"]) == {}

    @pytest.mark.parametrize("kind", ["agent", "source", "tool", "prompt"])
    def test_an_item_that_is_gone_is_not_filed(self, pg_conn, kind):
        """Filing locks the item first: one deleted meanwhile leaves no row behind (there is no FK to it)."""
        import uuid

        folder = _repo(pg_conn).create("u", "F")
        items = FolderItemsRepository(pg_conn)
        gone = str(uuid.uuid4())
        items.file("u", kind, gone, folder["id"])
        assert items.filing("u", kind, gone) is None
        assert items.file_if_unfiled("u", kind, gone, folder["id"]) is False
        assert items.filing("u", kind, gone) is None

    def test_file_if_unfiled_never_moves_a_filing(self, pg_conn):
        repo = _repo(pg_conn)
        items = FolderItemsRepository(pg_conn)
        a = repo.create("u", "A")
        b = repo.create("u", "B")
        agent = AgentsRepository(pg_conn).create("u", "x", "draft")
        assert items.file_if_unfiled("u", "agent", agent["id"], a["id"]) is True
        assert items.file_if_unfiled("u", "agent", agent["id"], b["id"]) is False
        assert items.filing("u", "agent", agent["id"]) == a["id"]


class TestTenantIsolation:
    def test_user_a_cannot_see_user_b_folders(self, pg_conn):
        repo = _repo(pg_conn)
        folder_a = repo.create("alice", "private")
        assert repo.get(folder_a["id"], "bob") is None

    def test_list_returns_only_own_folders(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "a1")
        repo.create("bob", "b1")
        alice_folders = repo.list_for_user("alice")
        bob_folders = repo.list_for_user("bob")
        assert len(alice_folders) == 1
        assert len(bob_folders) == 1
        assert alice_folders[0]["name"] == "a1"
        assert bob_folders[0]["name"] == "b1"
