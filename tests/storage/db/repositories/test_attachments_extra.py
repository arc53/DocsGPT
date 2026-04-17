"""Extra tests for AttachmentsRepository covering remaining branches."""



class TestResolveIds:
    def test_empty_ids_returns_empty_dict(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        assert AttachmentsRepository(pg_conn).resolve_ids([]) == {}

    def test_filters_none_values(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        assert AttachmentsRepository(pg_conn).resolve_ids([None]) == {}

    def test_dedupes_ids(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )

        att = AttachmentsRepository(pg_conn).create(
            "u", "f.txt", "/p",
        )
        pk = str(att["id"])
        got = AttachmentsRepository(pg_conn).resolve_ids([pk, pk])
        assert got[pk] == pk

    def test_legacy_preferred_over_pk(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )

        # Create two attachments: one with legacy id matching another's pk
        repo = AttachmentsRepository(pg_conn)
        first = repo.create("u", "f1.txt", "/p1")
        first_id = str(first["id"])
        repo.create(
            "u", "f2.txt", "/p2",
            legacy_mongo_id=first_id,  # legacy id matches first's pk
        )
        got = repo.resolve_ids([first_id])
        # Legacy-first: should map to the second row (the one with matching legacy)
        assert first_id in got


class TestGetByLegacyId:
    def test_returns_none_when_not_found(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        assert (
            AttachmentsRepository(pg_conn).get_by_legacy_id("legacy-missing")
            is None
        )

    def test_with_user_scope(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        repo = AttachmentsRepository(pg_conn)
        repo.create(
            "u-a", "f.txt", "/p",
            legacy_mongo_id="legacy-1",
        )
        assert repo.get_by_legacy_id("legacy-1", user_id="u-a") is not None
        # Wrong user
        assert repo.get_by_legacy_id("legacy-1", user_id="u-b") is None


class TestAttachmentsUpdate:
    def test_update_no_filtered_fields_returns_false(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        att = AttachmentsRepository(pg_conn).create("u", "f.txt", "/p")
        got = AttachmentsRepository(pg_conn).update(
            str(att["id"]), "u", {"not_a_column": "v"},
        )
        assert got is False

    def test_update_sets_scalar_fields(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        att = AttachmentsRepository(pg_conn).create("u", "f.txt", "/p")
        got = AttachmentsRepository(pg_conn).update(
            str(att["id"]), "u",
            {"openai_file_id": "oa-123"},
        )
        assert got is True

    def test_update_any_with_uuid(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        repo = AttachmentsRepository(pg_conn)
        att = repo.create("u", "f.txt", "/p")
        assert repo.update_any(str(att["id"]), "u", {"openai_file_id": "x"}) is True

    def test_update_any_falls_back_to_legacy(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        repo = AttachmentsRepository(pg_conn)
        repo.create(
            "u", "f.txt", "/p", legacy_mongo_id="legacy-abc",
        )
        # Passes legacy id, not UUID
        assert (
            repo.update_any("legacy-abc", "u", {"openai_file_id": "x"})
            is True
        )

    def test_update_by_legacy_id_no_fields(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        repo = AttachmentsRepository(pg_conn)
        repo.create("u", "f.txt", "/p", legacy_mongo_id="leg-1")
        got = repo.update_by_legacy_id("leg-1", "u", {"bogus": "x"})
        assert got is False

    def test_update_by_legacy_id_not_found(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        got = AttachmentsRepository(pg_conn).update_by_legacy_id(
            "no-match", "u", {"openai_file_id": "x"},
        )
        assert got is False

    def test_update_by_legacy_id_wrong_user_leaves_row_untouched(self, pg_conn):
        """IDOR regression: a caller with user B's id must not be able to
        mutate user A's attachment by guessing/reusing its legacy id."""
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        repo = AttachmentsRepository(pg_conn)
        repo.create(
            "user-a", "f.txt", "/p",
            legacy_mongo_id="shared-legacy",
            openai_file_id="original",
        )
        got = repo.update_any(
            "shared-legacy", "user-b", {"openai_file_id": "hijacked"},
        )
        assert got is False
        row = repo.get_by_legacy_id("shared-legacy", user_id="user-a")
        assert row is not None
        assert row["openai_file_id"] == "original"

    def test_update_by_legacy_id_same_user_succeeds(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        repo = AttachmentsRepository(pg_conn)
        repo.create(
            "user-a", "f.txt", "/p",
            legacy_mongo_id="shared-legacy-2",
            openai_file_id="original",
        )
        got = repo.update_any(
            "shared-legacy-2", "user-a", {"openai_file_id": "updated"},
        )
        assert got is True
        row = repo.get_by_legacy_id("shared-legacy-2", user_id="user-a")
        assert row is not None
        assert row["openai_file_id"] == "updated"

    def test_update_by_legacy_id_rejects_none_user(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        repo = AttachmentsRepository(pg_conn)
        repo.create(
            "user-a", "f.txt", "/p",
            legacy_mongo_id="needs-user",
            openai_file_id="original",
        )
        got = repo.update_by_legacy_id(
            "needs-user", None, {"openai_file_id": "nope"},
        )
        assert got is False
        row = repo.get_by_legacy_id("needs-user", user_id="user-a")
        assert row is not None
        assert row["openai_file_id"] == "original"


class TestAttachmentsShapeGate:
    """Regression: the UUID branch of ``update_any`` (via ``update``) and
    ``get`` / ``get_any`` must never feed a non-UUID into
    ``CAST(:id AS uuid)`` — the cast aborts the txn otherwise."""

    @staticmethod
    def _assert_txn_alive(conn) -> None:
        from sqlalchemy import text as _text

        assert conn.execute(_text("SELECT 1")).scalar() == 1

    def test_get_any_legacy_shape_txn_survives(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        repo = AttachmentsRepository(pg_conn)
        # ObjectId shape that no row exists for.
        assert repo.get_any("507f1f77bcf86cd799439077", "user-a") is None
        self._assert_txn_alive(pg_conn)

    def test_update_any_unknown_legacy_id_txn_survives(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        repo = AttachmentsRepository(pg_conn)
        assert repo.update_any(
            "507f1f77bcf86cd799439088", "user-a",
            {"openai_file_id": "x"},
        ) is False
        self._assert_txn_alive(pg_conn)
