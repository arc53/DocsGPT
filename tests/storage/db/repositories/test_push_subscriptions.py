"""Tests for PushSubscriptionsRepository and ConversationUnreadRepository."""

from __future__ import annotations

from sqlalchemy import text

from docsgpt.storage.db.repositories.conversation_unread import ConversationUnreadRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.push_subscriptions import PushSubscriptionsRepository

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc"


def _save(repo, user_id="u1", endpoint=ENDPOINT, **overrides):
    fields = {"user_id": user_id, "endpoint": endpoint, "p256dh": "p" * 87, "auth": "a" * 22}
    fields.update(overrides)
    return repo.upsert(**fields)


class TestUpsert:
    def test_saves_and_lists_for_the_user(self, pg_conn):
        repo = PushSubscriptionsRepository(pg_conn)
        row = _save(repo, user_agent="Firefox")
        assert row["endpoint"] == ENDPOINT
        assert row["failure_count"] == 0
        assert [r["endpoint"] for r in repo.list_for_user("u1")] == [ENDPOINT]
        assert repo.list_for_user("u2") == []
        assert repo.count_for_user("u1") == 1

    def test_same_endpoint_moves_to_the_latest_user_and_new_keys(self, pg_conn):
        repo = PushSubscriptionsRepository(pg_conn)
        _save(repo, user_id="u1")
        repo.record_failure(str(repo.list_for_user("u1")[0]["id"]))
        moved = _save(repo, user_id="u2", p256dh="q" * 87)
        assert moved["user_id"] == "u2"
        assert moved["p256dh"] == "q" * 87
        assert moved["failure_count"] == 0
        assert repo.list_for_user("u1") == []

    def test_keeps_only_the_newest_per_user(self, pg_conn):
        repo = PushSubscriptionsRepository(pg_conn)
        for i in range(4):
            _save(repo, endpoint=f"{ENDPOINT}{i}")
        removed = repo.trim_for_user("u1", keep=2)
        assert removed == 2
        assert sorted(r["endpoint"] for r in repo.list_for_user("u1")) == [f"{ENDPOINT}2", f"{ENDPOINT}3"]


class TestDeliveryBookkeeping:
    def test_success_resets_failures(self, pg_conn):
        repo = PushSubscriptionsRepository(pg_conn)
        sub_id = str(_save(repo)["id"])
        assert repo.record_failure(sub_id) == 1
        assert repo.record_failure(sub_id) == 2
        repo.record_success(sub_id)
        row = repo.list_for_user("u1")[0]
        assert row["failure_count"] == 0
        assert row["last_success_at"] is not None
        assert row["last_failure_at"] is not None

    def test_failure_of_a_gone_row_is_none(self, pg_conn):
        repo = PushSubscriptionsRepository(pg_conn)
        assert repo.record_failure("00000000-0000-0000-0000-000000000000") is None
        assert repo.record_failure("not-a-uuid") is None

    def test_delete_by_id_and_by_endpoint_are_scoped(self, pg_conn):
        repo = PushSubscriptionsRepository(pg_conn)
        sub_id = str(_save(repo)["id"])
        assert repo.delete_for_user("u2", ENDPOINT) is False
        assert repo.delete_for_user("u1", ENDPOINT) is True
        _save(repo)
        sub_id = str(repo.list_for_user("u1")[0]["id"])
        assert repo.delete(sub_id) is True
        assert repo.delete(sub_id) is False
        assert repo.delete("bad") is False


class TestUnread:
    def _conversation(self, conn, user_id="u1"):
        return str(ConversationsRepository(conn).create(user_id, "chat")["id"])

    def test_mark_and_clear(self, pg_conn):
        repo = ConversationUnreadRepository(pg_conn)
        cid = self._conversation(pg_conn)
        assert repo.mark_unread(cid, "u1") is True
        unread_at = pg_conn.execute(
            text("SELECT unread_at FROM conversations WHERE id = CAST(:id AS uuid)"), {"id": cid}
        ).scalar()
        assert unread_at is not None
        assert repo.mark_read(cid, "u1") is True
        assert repo.mark_read(cid, "u1") is False

    def test_only_the_owner(self, pg_conn):
        repo = ConversationUnreadRepository(pg_conn)
        cid = self._conversation(pg_conn)
        assert repo.mark_unread(cid, "someone-else") is False
        repo.mark_unread(cid, "u1")
        assert repo.mark_read(cid, "someone-else") is False
        assert repo.mark_unread("bad-id", "u1") is False
        assert repo.mark_read("bad-id", "u1") is False

    def test_marking_does_not_reorder_the_sidebar(self, pg_conn):
        conversations = ConversationsRepository(pg_conn)
        cid = self._conversation(pg_conn)
        before = conversations.get_any(cid, "u1")
        ConversationUnreadRepository(pg_conn).mark_unread(cid, "u1")
        after = conversations.get_any(cid, "u1")
        assert after["date"] == before["date"]
        assert after["unread_at"] is not None
