"""Tests for PromptsRepository against a real Postgres instance."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.storage.db.repositories.prompts import PromptsRepository


def _repo(conn) -> PromptsRepository:
    return PromptsRepository(conn)


def _age(conn, row: dict, days: int) -> None:
    """Make ``row`` ``days`` older: rows created in one transaction share ``created_at``."""
    conn.execute(text("UPDATE prompts SET created_at = now() - make_interval(days => :d) WHERE id = :id"),
                 {"d": days, "id": row["id"]})


class TestCreate:
    def test_creates_prompt(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "greeting", "Hello {{name}}")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "greeting"
        assert doc["content"] == "Hello {{name}}"
        assert doc["id"] is not None

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "p", "c")
        assert doc["_id"] == doc["id"]

    def test_create_with_legacy_mongo_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "p", "c", legacy_mongo_id="507f1f77bcf86cd799439011")
        assert doc["legacy_mongo_id"] == "507f1f77bcf86cd799439011"


class TestGet:
    def test_get_by_id_and_user(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        assert repo.get(created["id"], "user-other") is None

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None

    def test_get_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "user-1",
            "p",
            "c",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        fetched = repo.get_by_legacy_id("507f1f77bcf86cd799439011", "user-1")
        assert fetched["id"] == created["id"]


class TestGetForRendering:
    def test_returns_prompt_without_user_scoping(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        fetched = repo.get_for_rendering(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get_for_rendering("00000000-0000-0000-0000-000000000000") is None


class TestListForUser:
    def test_lists_only_own_prompts(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "a1", "c1")
        repo.create("alice", "a2", "c2")
        repo.create("bob", "b1", "c3")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)


class TestUpdate:
    def test_updates_name_and_content(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "old-content")
        repo.update(created["id"], "user-1", "new", "new-content")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "new"
        assert fetched["content"] == "new-content"

    def test_update_wrong_user_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "old-content")
        repo.update(created["id"], "user-other", "new", "new-content")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "old"

    def test_update_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create(
            "user-1",
            "old",
            "old-content",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        assert repo.update_by_legacy_id(
            "507f1f77bcf86cd799439011",
            "user-1",
            "new",
            "new-content",
        ) is True
        fetched = repo.get_by_legacy_id("507f1f77bcf86cd799439011", "user-1")
        assert fetched["name"] == "new"
        assert fetched["content"] == "new-content"


class TestDelete:
    def test_deletes_prompt(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        repo.delete(created["id"], "user-1")
        assert repo.get(created["id"], "user-1") is None

    def test_delete_wrong_user_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        repo.delete(created["id"], "user-other")
        assert repo.get(created["id"], "user-1") is not None

    def test_delete_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "user-1",
            "p",
            "c",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        assert repo.delete_by_legacy_id("507f1f77bcf86cd799439011", "user-1") is True
        assert repo.get(created["id"], "user-1") is None


class TestGetAny:
    def test_resolves_by_uuid(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "p", "c")
        fetched = repo.get_any(created["id"], "user-1")
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_resolves_by_legacy_mongo_id(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create(
            "user-1",
            "p",
            "c",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        fetched = repo.get_any("507f1f77bcf86cd799439011", "user-1")
        assert fetched is not None
        assert fetched["legacy_mongo_id"] == "507f1f77bcf86cd799439011"

    def test_other_user_returns_none_for_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create(
            "owner",
            "p",
            "c",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        assert repo.get_any("507f1f77bcf86cd799439011", "intruder") is None

    def test_non_uuid_non_legacy_does_not_raise(self, pg_conn):
        """Garbage ids must return None cleanly without poisoning the txn.

        Regression guard: the old ``get()`` path did a bare
        ``CAST(:id AS uuid)`` which raises and leaves the enclosing
        transaction in an aborted state for the rest of the request.
        """
        repo = _repo(pg_conn)
        assert repo.get_any("not_a_uuid_or_objectid", "user-1") is None
        # Follow-up query must still succeed on the same connection.
        created = repo.create("user-1", "p", "c")
        assert repo.get_any(created["id"], "user-1") is not None


class TestFindOrCreate:
    def test_creates_when_missing(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.find_or_create("sys", "template", "content")
        assert doc["id"] is not None

    def test_returns_existing_on_match(self, pg_conn):
        repo = _repo(pg_conn)
        first = repo.find_or_create("sys", "template", "content")
        second = repo.find_or_create("sys", "template", "content")
        assert first["id"] == second["id"]

    def test_different_content_creates_new(self, pg_conn):
        repo = _repo(pg_conn)
        first = repo.find_or_create("sys", "template", "v1")
        second = repo.find_or_create("sys", "template", "v2")
        assert first["id"] != second["id"]


class TestBriefListing:
    def test_ids_cover_own_and_extra_rows_newest_first(self, pg_conn):
        repo = _repo(pg_conn)
        own = [repo.create("u", f"p{i}", "long text") for i in range(2)]
        _age(pg_conn, own[0], 1)
        shared = repo.create("other", "theirs", "c")
        repo.create("other", "hidden", "c")
        rows = repo.list_ids_for_user("u", extra_ids=[str(shared["id"]), "not-a-uuid"])
        assert {r["id"] for r in rows} == {str(own[0]["id"]), str(own[1]["id"]), str(shared["id"])}
        assert all(set(r) == {"id", "user_id"} for r in rows)
        assert [r["id"] for r in rows if r["user_id"] == "u"] == [str(own[1]["id"]), str(own[0]["id"])]
        assert [r["id"] for r in repo.list_ids_for_user("u")] == [str(own[1]["id"]), str(own[0]["id"])]

    def test_brief_rows_carry_the_name_and_never_the_content(self, pg_conn):
        repo = _repo(pg_conn)
        first = repo.create("u", "first", "secret text")
        second = repo.create("u", "second", "more text")
        _age(pg_conn, first, 1)
        rows = repo.list_brief([str(first["id"]), str(second["id"]), "nope"])
        assert rows == [
            {"id": str(second["id"]), "user_id": "u", "name": "second"},
            {"id": str(first["id"]), "user_id": "u", "name": "first"},
        ]
        assert repo.list_brief([]) == []
