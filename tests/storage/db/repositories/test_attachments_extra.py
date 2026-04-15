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
        got = repo.update_by_legacy_id("leg-1", {"bogus": "x"})
        assert got is False

    def test_update_by_legacy_id_not_found(self, pg_conn):
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )
        got = AttachmentsRepository(pg_conn).update_by_legacy_id(
            "no-match", {"openai_file_id": "x"},
        )
        assert got is False
