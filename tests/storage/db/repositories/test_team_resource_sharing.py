"""Integration tests for prompts/sources/tools team-sharing repo methods."""

from __future__ import annotations

import uuid

from application.storage.db.repositories.prompts import PromptsRepository
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.user_tools import UserToolsRepository


class TestPromptsSharing:
    def test_get_by_id_and_list_by_ids(self, pg_conn):
        repo = PromptsRepository(pg_conn)
        p1 = repo.create("alice", "P1", "c1")
        p2 = repo.create("alice", "P2", "c2")
        # get_for_rendering is the ownerless fetch used by the team fallback.
        assert repo.get_for_rendering(str(p1["id"]))["name"] == "P1"
        ids = {str(p1["id"]), str(p2["id"])}
        assert {str(p["id"]) for p in repo.list_by_ids(list(ids))} == ids

    def test_update_by_id_optimistic_lock(self, pg_conn):
        repo = PromptsRepository(pg_conn)
        p = repo.create("alice", "P", "c")
        pid = str(p["id"])
        ts = repo.get_for_rendering(pid)["updated_at"]
        assert repo.update_by_id(pid, "P2", "c2", expected_updated_at=ts) is True
        assert repo.get_for_rendering(pid)["content"] == "c2"
        # Stale version → None (route answers 409).
        assert repo.update_by_id(pid, "P3", "c3", expected_updated_at="2000-01-01T00:00:00+00:00") is None
        # No version → unconditional.
        assert repo.update_by_id(pid, "P4", "c4") is True


class TestSourcesSharing:
    def test_get_by_id_owner_agnostic(self, pg_conn):
        repo = SourcesRepository(pg_conn)
        src = repo.create("KB", user_id="alice")
        sid = str(src["id"])
        assert repo.get_by_id(sid)["id"] == sid
        # get_any is owner-scoped.
        assert repo.get_any(sid, "bob") is None
        assert {str(s["id"]) for s in repo.list_by_ids([sid])} == {sid}


class TestToolsSharing:
    def test_get_by_id_owner_agnostic(self, pg_conn):
        repo = UserToolsRepository(pg_conn)
        tool = repo.create("alice", "api_tool", config={"x": 1}, actions=[])
        tid = str(tool["id"])
        assert repo.get_by_id(tid)["id"] == tid
        assert repo.get_any(tid, "bob") is None
        assert {str(t["id"]) for t in repo.list_by_ids([tid])} == {tid}
