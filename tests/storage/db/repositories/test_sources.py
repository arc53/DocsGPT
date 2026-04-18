"""Tests for SourcesRepository against a real Postgres instance."""

from __future__ import annotations


from application.storage.db.repositories.sources import SourcesRepository


def _repo(conn) -> SourcesRepository:
    return SourcesRepository(conn)


class TestCreate:
    def test_creates_source_with_user(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("my-source", user_id="user-1", type="url")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "my-source"
        assert doc["type"] == "url"
        assert doc["id"] is not None

    def test_creates_source_with_metadata(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("src", user_id="u", metadata={"url": "https://example.com"})
        assert doc["metadata"] == {"url": "https://example.com"}

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("s", user_id="u")
        assert doc["_id"] == doc["id"]


class TestCreateConnectorFields:
    def test_persists_sync_and_retriever(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create(
            "connector-src",
            user_id="u",
            retriever="classic",
            sync_frequency="daily",
            tokens="1234",
            file_path="/var/lib/docsgpt/u/src",
        )
        assert doc["retriever"] == "classic"
        assert doc["sync_frequency"] == "daily"
        assert doc["tokens"] == "1234"
        assert doc["file_path"] == "/var/lib/docsgpt/u/src"

    def test_remote_data_accepts_dict(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create(
            "s", user_id="u",
            remote_data={"provider": "google_drive", "folder_id": "abc"},
        )
        assert doc["remote_data"] == {"provider": "google_drive", "folder_id": "abc"}

    def test_remote_data_accepts_json_string(self, pg_conn):
        """Legacy Mongo docs store remote_data as a JSON-encoded string."""
        repo = _repo(pg_conn)
        doc = repo.create("s", user_id="u", remote_data='{"provider": "github"}')
        assert doc["remote_data"] == {"provider": "github"}

    def test_remote_data_non_json_string_wrapped(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("s", user_id="u", remote_data="not-json")
        assert doc["remote_data"] == {"raw": "not-json"}

    def test_persists_language_and_model(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create(
            "src", user_id="u",
            language="english", model="text-embedding-3-small",
        )
        assert doc["language"] == "english"
        assert doc["model"] == "text-embedding-3-small"

    def test_persists_explicit_date(self, pg_conn):
        import datetime

        repo = _repo(pg_conn)
        when = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        doc = repo.create("src", user_id="u", date=when)
        assert doc["date"] == when

    def test_persists_legacy_mongo_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("src", user_id="u", legacy_mongo_id="oid_xyz")
        assert doc["legacy_mongo_id"] == "oid_xyz"

    def test_directory_structure_and_file_name_map(self, pg_conn):
        repo = _repo(pg_conn)
        dir_struct = {"docs": {"readme.md": {}}}
        name_map = {"abc123_readme.md": "readme.md"}
        doc = repo.create(
            "s", user_id="u",
            directory_structure=dir_struct,
            file_name_map=name_map,
        )
        assert doc["directory_structure"] == dir_struct
        assert doc["file_name_map"] == name_map


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="user-1")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="user-1")
        assert repo.get(created["id"], "user-other") is None


class TestListForUser:
    def test_lists_only_own_sources(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("s1", user_id="alice")
        repo.create("s2", user_id="alice")
        repo.create("s3", user_id="bob")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)

    def test_limit_and_offset_paginate_at_sql_level(self, pg_conn):
        repo = _repo(pg_conn)
        for i in range(5):
            repo.create(f"s{i}", user_id="u")
        first = repo.list_for_user("u", limit=2, offset=0)
        second = repo.list_for_user("u", limit=2, offset=2)
        third = repo.list_for_user("u", limit=2, offset=4)
        assert len(first) == 2
        assert len(second) == 2
        assert len(third) == 1
        # All ids should be distinct across the three windows (stable order).
        seen = {r["id"] for r in (first + second + third)}
        assert len(seen) == 5

    def test_search_filter_pushed_into_sql(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("Alpha doc", user_id="u")
        repo.create("Beta doc", user_id="u")
        repo.create("Gamma alpha", user_id="u")
        # Case-insensitive substring on name.
        results = repo.list_for_user("u", search_term="alpha")
        names = sorted(r["name"] for r in results)
        assert names == ["Alpha doc", "Gamma alpha"]

    def test_search_filter_escapes_like_wildcards(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("100% coverage", user_id="u")
        repo.create("anything else", user_id="u")
        # ``%`` in input must not match everything.
        results = repo.list_for_user("u", search_term="100%")
        assert len(results) == 1
        assert results[0]["name"] == "100% coverage"

    def test_search_filter_escapes_underscore(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("foo_bar", user_id="u")
        repo.create("fooXbar", user_id="u")
        results = repo.list_for_user("u", search_term="foo_bar")
        assert len(results) == 1
        assert results[0]["name"] == "foo_bar"

    def test_unknown_sort_field_falls_back_safely(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("a", user_id="u")
        repo.create("b", user_id="u")
        # Passing a non-whitelisted column must not raise or execute as SQL.
        results = repo.list_for_user(
            "u", sort_field="nonexistent; DROP TABLE sources--",
        )
        assert len(results) == 2

    def test_sort_by_name_asc(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("charlie", user_id="u")
        repo.create("alpha", user_id="u")
        repo.create("bravo", user_id="u")
        results = repo.list_for_user("u", sort_field="name", sort_order="asc")
        assert [r["name"] for r in results] == ["alpha", "bravo", "charlie"]

    def test_stable_order_with_id_tiebreaker(self, pg_conn):
        """Rows with identical sort keys still paginate deterministically."""
        repo = _repo(pg_conn)
        import datetime
        same_date = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        for i in range(6):
            repo.create(f"dup-{i}", user_id="u", date=same_date)

        # Union of two adjacent windows must be distinct (no row overlap,
        # no row missed) — this fails without an id tiebreaker.
        first = repo.list_for_user("u", limit=3, offset=0)
        second = repo.list_for_user("u", limit=3, offset=3)
        ids = {r["id"] for r in first} | {r["id"] for r in second}
        assert len(ids) == 6


class TestCountForUser:
    def test_returns_zero_for_no_rows(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.count_for_user("nobody") == 0

    def test_counts_only_own_rows(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("x", user_id="alice")
        repo.create("y", user_id="alice")
        repo.create("z", user_id="bob")
        assert repo.count_for_user("alice") == 2
        assert repo.count_for_user("bob") == 1

    def test_count_matches_filtered_list(self, pg_conn):
        repo = _repo(pg_conn)
        for name in ("alpha-1", "alpha-2", "beta-3"):
            repo.create(name, user_id="u")
        listed = repo.list_for_user("u", search_term="alpha")
        count = repo.count_for_user("u", search_term="alpha")
        assert count == len(listed) == 2


class TestUpdate:
    def test_updates_name(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("old", user_id="u")
        repo.update(created["id"], "u", {"name": "new"})
        fetched = repo.get(created["id"], "u")
        assert fetched["name"] == "new"

    def test_updates_metadata(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u", metadata={"a": 1})
        repo.update(created["id"], "u", {"metadata": {"a": 2, "b": 3}})
        fetched = repo.get(created["id"], "u")
        assert fetched["metadata"] == {"a": 2, "b": 3}

    def test_updates_retriever_and_sync_frequency(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u", retriever="classic", sync_frequency="never")
        repo.update(created["id"], "u", {"retriever": "hybrid", "sync_frequency": "weekly"})
        fetched = repo.get(created["id"], "u")
        assert fetched["retriever"] == "hybrid"
        assert fetched["sync_frequency"] == "weekly"

    def test_updates_remote_data_from_string(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u")
        repo.update(created["id"], "u", {"remote_data": '{"provider": "notion"}'})
        fetched = repo.get(created["id"], "u")
        assert fetched["remote_data"] == {"provider": "notion"}

    def test_update_disallowed_field_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u")
        repo.update(created["id"], "u", {"id": "00000000-0000-0000-0000-000000000000"})
        fetched = repo.get(created["id"], "u")
        assert fetched["id"] == created["id"]

    def test_update_wrong_user_is_noop(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("old", user_id="u")
        repo.update(created["id"], "other-user", {"name": "new"})
        fetched = repo.get(created["id"], "u")
        assert fetched["name"] == "old"


class TestDelete:
    def test_deletes_source(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u")
        deleted = repo.delete(created["id"], "u")
        assert deleted is True
        assert repo.get(created["id"], "u") is None

    def test_delete_nonexistent_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        deleted = repo.delete("00000000-0000-0000-0000-000000000000", "u")
        assert deleted is False

    def test_delete_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("s", user_id="u")
        deleted = repo.delete(created["id"], "other-user")
        assert deleted is False
        assert repo.get(created["id"], "u") is not None
