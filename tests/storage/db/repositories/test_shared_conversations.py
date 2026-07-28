"""Tests for SharedConversationsRepository against a real Postgres instance."""

from __future__ import annotations


from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.shared_conversations import SharedConversationsRepository


def _conv(conn) -> dict:
    return ConversationsRepository(conn).create("user-1", "test conv")


def _repo(conn) -> SharedConversationsRepository:
    return SharedConversationsRepository(conn)


class TestCreate:
    def test_creates_share(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        share = repo.create(conv["id"], "user-1", is_promptable=False, first_n_queries=3)
        assert share["conversation_id"] is not None
        assert share["user_id"] == "user-1"
        assert share["is_promptable"] is False
        assert share["first_n_queries"] == 3
        assert share["uuid"] is not None

    def test_create_promptable_with_api_key(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        share = repo.create(
            conv["id"], "user-1",
            is_promptable=True,
            first_n_queries=5,
            api_key="ak-prompt",
        )
        assert share["is_promptable"] is True
        assert share["api_key"] == "ak-prompt"


class TestFindByUuid:
    def test_finds_by_uuid(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        share = repo.create(conv["id"], "user-1", first_n_queries=2)
        found = repo.find_by_uuid(str(share["uuid"]))
        assert found["id"] == share["id"]

    def test_not_found(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.find_by_uuid("00000000-0000-0000-0000-000000000000") is None


class TestFindExisting:
    def test_finds_matching_share(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.create(conv["id"], "user-1", is_promptable=False, first_n_queries=3)
        found = repo.find_existing(conv["id"], "user-1", False, 3)
        assert found is not None
        assert found["first_n_queries"] == 3

    def test_no_match_different_params(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.create(conv["id"], "user-1", is_promptable=False, first_n_queries=3)
        assert repo.find_existing(conv["id"], "user-1", True, 3) is None

    def test_finds_with_api_key(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.create(conv["id"], "user-1", is_promptable=True, first_n_queries=5, api_key="ak-1")
        found = repo.find_existing(conv["id"], "user-1", True, 5, api_key="ak-1")
        assert found is not None


class TestListForConversation:
    def test_lists_shares(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        repo.create(conv["id"], "user-1", first_n_queries=1)
        repo.create(conv["id"], "user-1", first_n_queries=2)
        results = repo.list_for_conversation(conv["id"])
        assert len(results) == 2


class TestFindByUuidShapeGate:
    """Regression: the public ``/api/shared_conversation/<identifier>``
    route pipes its URL path segment straight into ``find_by_uuid``. A
    non-UUID input (legacy ObjectId, garbage) must resolve to ``None``
    rather than raise ``InvalidTextRepresentation`` and poison the
    transaction — otherwise the 404 ``might have broken url`` response
    is masked by a blanket 400."""

    @staticmethod
    def _assert_txn_alive(conn) -> None:
        from sqlalchemy import text as _text

        assert conn.execute(_text("SELECT 1")).scalar() == 1

    def test_legacy_mongo_id_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.find_by_uuid("507f1f77bcf86cd799439011") is None
        self._assert_txn_alive(pg_conn)

    def test_garbage_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.find_by_uuid("../../etc/passwd") is None
        self._assert_txn_alive(pg_conn)

    def test_uuid_happy_path_still_works(self, pg_conn):
        conv = _conv(pg_conn)
        repo = _repo(pg_conn)
        share = repo.create(conv["id"], "user-1", first_n_queries=1)
        found = repo.find_by_uuid(str(share["uuid"]))
        assert found is not None


class TestReassignApiKey:
    def test_rewrites_promptable_share_keys(self, pg_conn):
        # A promptable share stores the backing agent's key; on rotation it must
        # follow the key so the public share endpoint keeps returning a valid one.
        from sqlalchemy import text

        repo = _repo(pg_conn)
        c1, c2, c3 = _conv(pg_conn), _conv(pg_conn), _conv(pg_conn)
        repo.create(c1["id"], "u", is_promptable=True, api_key="sc-old")
        repo.create(c2["id"], "u", is_promptable=True, api_key="sc-old")
        repo.create(c3["id"], "u", is_promptable=True, api_key="sc-other")

        moved = repo.reassign_api_key(old_key="sc-old", new_key="sc-new")
        assert moved == 2

        def _count(key):
            return pg_conn.execute(
                text("SELECT COUNT(*) FROM shared_conversations WHERE api_key = :k"),
                {"k": key},
            ).scalar()

        assert _count("sc-old") == 0
        assert _count("sc-new") == 2
        assert _count("sc-other") == 1

    def test_noop_on_blank_keys(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.reassign_api_key(old_key="", new_key="x") == 0
        assert repo.reassign_api_key(old_key="x", new_key="") == 0
