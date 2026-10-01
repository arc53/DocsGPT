"""Tests for AttachmentsRepository against a real Postgres instance."""

from __future__ import annotations


from sqlalchemy import text

from docsgpt.storage.db.repositories.attachments import AttachmentsRepository


def _repo(conn) -> AttachmentsRepository:
    return AttachmentsRepository(conn)


class TestCreate:
    def test_creates_attachment(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "file.pdf", "/uploads/file.pdf")
        assert doc["user_id"] == "user-1"
        assert doc["filename"] == "file.pdf"
        assert doc["upload_path"] == "/uploads/file.pdf"
        assert doc["id"] is not None

    def test_creates_with_optional_fields(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "img.png", "/uploads/img.png",
                          mime_type="image/png", size=1024)
        assert doc["mime_type"] == "image/png"
        assert doc["size"] == 1024

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "f", "/p")
        assert doc["_id"] == doc["id"]

    def test_create_aliases_upload_path_as_path(self, pg_conn):
        # LLM provider code (google_ai/openai/anthropic and handlers/base)
        # reads attachment.get("path") — preserved from the legacy Mongo
        # shape. Repo emits both keys so consumers don't need to know
        # which storage backend produced the dict.
        repo = _repo(pg_conn)
        doc = repo.create("u", "f", "/uploads/x.png")
        assert doc["path"] == "/uploads/x.png"
        assert doc["upload_path"] == "/uploads/x.png"

    def test_get_aliases_upload_path_as_path(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "f", "/uploads/y.pdf")
        fetched = repo.get(created["id"], "u")
        assert fetched is not None
        assert fetched["path"] == "/uploads/y.pdf"

    def test_create_with_legacy_mongo_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create(
            "u",
            "f",
            "/p",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        assert doc["legacy_mongo_id"] == "507f1f77bcf86cd799439011"

    def test_create_strips_null_bytes_from_content_and_metadata(self, pg_conn):
        # A parsed document with embedded NULs (mislabeled binary) must
        # not kill the INSERT — Postgres rejects \x00 in text and jsonb.
        repo = _repo(pg_conn)
        doc = repo.create(
            "u",
            "weird.pdf",
            "/uploads/weird.pdf",
            content="parsed\x00text\x00here",
            metadata={"transcript_lang\x00": "en\x00"},
        )
        assert doc["content"] == "parsedtexthere"
        assert doc["metadata"] == {"transcript_lang": "en"}


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "f", "/p")
        fetched = repo.get(created["id"], "u")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "u") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "f", "/p")
        assert repo.get(created["id"], "other") is None

    def test_get_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "u",
            "f",
            "/p",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        fetched = repo.get_by_legacy_id("507f1f77bcf86cd799439011", "u")
        assert fetched["id"] == created["id"]


class TestListForUser:
    def test_lists_only_own_attachments(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "a1.pdf", "/a1")
        repo.create("alice", "a2.pdf", "/a2")
        repo.create("bob", "b1.pdf", "/b1")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)

    def test_list_empty_for_unknown_user(self, pg_conn):
        repo = _repo(pg_conn)
        results = repo.list_for_user("nonexistent")
        assert results == []


class TestUpdateMetadataIfContentNull:
    """Atomic no-clobber write for failure provenance: the ``content IS
    NULL`` predicate lives in the UPDATE itself, so a success row committed
    by a concurrent duplicate execution can never be overwritten between a
    check and the write."""

    def test_updates_row_without_stored_content(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "f.xlsx", "/p", content=None,
                    metadata={"extraction": {"status": "failed", "error": "first"}},
                    legacy_mongo_id="handle-1")

        updated = repo.update_metadata_if_content_null(
            "handle-1", "u", {"extraction": {"status": "failed", "error": "second"}}
        )

        assert updated is True
        row = repo.get_by_legacy_id("handle-1", "u")
        assert row["metadata"]["extraction"]["error"] == "second"

    def test_refuses_row_with_stored_content(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "f.txt", "/p", content="durable text", token_count=2,
                    metadata={"extraction": {"status": "ok"}},
                    legacy_mongo_id="handle-2")

        updated = repo.update_metadata_if_content_null(
            "handle-2", "u", {"extraction": {"status": "failed", "error": "late loser"}}
        )

        assert updated is False
        row = repo.get_by_legacy_id("handle-2", "u")
        assert row["metadata"]["extraction"]["status"] == "ok"
        assert row["content"] == "durable text"

    def test_missing_row_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.update_metadata_if_content_null("nope", "u", {"x": 1}) is False


class TestListForPlanning:
    """Rows for files attached on earlier turns: metadata only, in the order asked."""

    def test_returns_rows_in_the_requested_order_without_content(self, pg_conn):
        repo = _repo(pg_conn)
        first = repo.create("u", "a.pdf", "/a", content="AAA", token_count=3, metadata={"content_hash": "h1"})
        second = repo.create("u", "b.pdf", "/b", content="BBB", token_count=3)

        rows = repo.list_for_planning([second["id"], first["id"]], "u")

        assert [r["id"] for r in rows] == [second["id"], first["id"]]
        assert all("content" not in r for r in rows)
        assert rows[1]["metadata"]["content_hash"] == "h1"
        assert rows[0]["token_count"] == 3

    def test_other_users_rows_and_unknown_ids_are_skipped(self, pg_conn):
        repo = _repo(pg_conn)
        mine = repo.create("u", "a.pdf", "/a")
        theirs = repo.create("someone-else", "b.pdf", "/b")

        rows = repo.list_for_planning([theirs["id"], "not-a-uuid", mine["id"]], "u")

        assert [r["id"] for r in rows] == [mine["id"]]

    def test_empty(self, pg_conn):
        assert _repo(pg_conn).list_for_planning([], "u") == []


class TestContentHash:
    _HASH = "b" * 64

    def test_create_and_update_store_the_column(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a.pdf", "/a", content_hash=self._HASH)
        assert doc["content_hash"] == self._HASH
        assert repo.update(doc["id"], "u", {"content_hash": "c" * 64})
        assert repo.get(doc["id"], "u")["content_hash"] == "c" * 64

    def test_find_by_hash_returns_the_newest_parsed_row(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "old.pdf", "/old", content="old text", token_count=2, content_hash=self._HASH)
        newest = repo.create("u", "new.pdf", "/new", content="new text", token_count=2, content_hash=self._HASH)
        pg_conn.execute(
            text("UPDATE attachments SET created_at = now() + interval '1 minute' WHERE id = CAST(:id AS uuid)"),
            {"id": newest["id"]},
        )

        found = repo.find_by_hash("u", self._HASH)

        assert found is not None and found["id"] == newest["id"]
        assert found["content"] == "new text"

    def test_find_by_hash_skips_failed_rows_other_users_and_excluded_handles(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("u", "failed.pdf", "/f", content=None, content_hash=self._HASH)
        repo.create("someone-else", "theirs.pdf", "/t", content="x", content_hash=self._HASH)
        repo.create("u", "self.pdf", "/s", content="x", content_hash=self._HASH, legacy_mongo_id="handle-1")

        assert repo.find_by_hash("u", self._HASH, exclude_legacy_id="handle-1") is None
        assert repo.find_by_hash("u", "") is None

    def test_list_for_planning_includes_the_hash(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a.pdf", "/a", content_hash=self._HASH)
        assert repo.list_for_planning([doc["id"]], "u")[0]["content_hash"] == self._HASH


class TestArchiveMembers:
    """A zip's members load right after it, in archive order, wherever the zip is attached."""

    def _archive(self, repo, user="u"):
        parent = repo.create(
            user, "bundle.zip", "/z", content="index", metadata={"archive": {"members": 2}}
        )
        second = repo.create(
            user, "b.txt", "/b", content="b",
            metadata={"parent_attachment_id": str(parent["id"]), "archive_path": "b.txt", "archive_index": 1},
        )
        first = repo.create(
            user, "a.txt", "/a", content="a",
            metadata={"parent_attachment_id": str(parent["id"]), "archive_path": "a.txt", "archive_index": 0},
        )
        return parent, first, second

    def test_list_for_planning_follows_the_zip_with_its_members(self, pg_conn):
        repo = _repo(pg_conn)
        before = repo.create("u", "before.txt", "/x")
        parent, first, second = self._archive(repo)
        after = repo.create("u", "after.txt", "/y")

        rows = repo.list_for_planning([before["id"], parent["id"], after["id"]], "u")

        assert [r["id"] for r in rows] == [before["id"], parent["id"], first["id"], second["id"], after["id"]]
        assert all("content" not in r for r in rows)

    def test_members_named_explicitly_are_not_listed_twice(self, pg_conn):
        repo = _repo(pg_conn)
        parent, first, second = self._archive(repo)

        rows = repo.list_for_planning([parent["id"], first["id"], second["id"]], "u")

        assert [r["id"] for r in rows] == [parent["id"], first["id"], second["id"]]

    def test_expand_archives_adds_full_member_rows(self, pg_conn):
        repo = _repo(pg_conn)
        parent, first, second = self._archive(repo)
        loose = repo.create("u", "loose.txt", "/l", content="loose")

        rows = repo.expand_archives([repo.get(parent["id"], "u"), repo.get(loose["id"], "u")], "u")

        assert [r["id"] for r in rows] == [parent["id"], first["id"], second["id"], loose["id"]]
        assert rows[1]["content"] == "a"

    def test_other_users_rows_never_join_a_zip(self, pg_conn):
        repo = _repo(pg_conn)
        parent, first, second = self._archive(repo)
        repo.create(
            "intruder", "evil.txt", "/e", content="e",
            metadata={"parent_attachment_id": str(parent["id"]), "archive_path": "evil.txt", "archive_index": -1},
        )

        rows = repo.list_for_planning([parent["id"]], "u")

        assert [r["id"] for r in rows] == [parent["id"], first["id"], second["id"]]

    def test_rows_without_archives_pass_through(self, pg_conn):
        repo = _repo(pg_conn)
        loose = repo.create("u", "loose.txt", "/l", content="loose")
        row = repo.get(loose["id"], "u")
        assert repo.expand_archives([row], "u") == [row]
        assert repo.expand_archives([], "u") == []
