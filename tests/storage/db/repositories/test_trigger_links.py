"""Tests for TriggerLinksRepository and TriggerHitsRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.trigger_links import TriggerHitsRepository, TriggerLinksRepository


def _monitor(conn) -> dict:
    conv = str(ConversationsRepository(conn).create("u1", "chat")["id"])
    now = datetime.now(timezone.utc)
    return MonitorsRepository(conn).create(
        user_id="u1",
        conversation_id=conv,
        agent_id=None,
        description="deploy finished",
        source_type="webhook",
        spec={"source": {"type": "webhook"}},
        on_match="tell me",
        end_at=now + timedelta(days=1),
        next_run_at=now + timedelta(days=1),
        max_wakes=1,
    )


def _link(conn, monitor, **overrides) -> dict:
    fields = {
        "monitor_id": monitor["id"],
        "user_id": "u1",
        "conversation_id": monitor["conversation_id"],
        "token_hash": "hash-1",
        "kind": "webhook",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "max_hits": 2,
    }
    fields.update(overrides)
    return TriggerLinksRepository(conn).create(**fields)


class TestLinks:
    def test_live_lookup_hides_revoked_expired_and_used_up_links(self, pg_conn):
        repo = TriggerLinksRepository(pg_conn)
        monitor = _monitor(pg_conn)
        link = _link(pg_conn, monitor)
        assert repo.get_live("hash-1", "webhook")["id"] == link["id"]
        assert repo.get_live("hash-1", "approval") is None
        assert repo.count_hit(link["id"])["hit_count"] == 1
        assert repo.count_hit(link["id"])["hit_count"] == 2
        assert repo.count_hit(link["id"]) is None
        assert repo.get_live("hash-1", "webhook") is None
        assert repo.get_unexpired("hash-1", "webhook") is not None

        expired = _link(pg_conn, monitor, token_hash="hash-2", expires_at=datetime.now(timezone.utc) - timedelta(1))
        assert repo.get_live("hash-2", "webhook") is None and repo.count_hit(expired["id"]) is None

        _link(pg_conn, monitor, token_hash="hash-3")
        assert repo.revoke_for_monitor(monitor["id"]) == 3
        assert repo.get_live("hash-3", "webhook") is None
        assert repo.revoke_for_monitor(monitor["id"]) == 0

    def test_revoke_by_kind(self, pg_conn):
        repo = TriggerLinksRepository(pg_conn)
        monitor = _monitor(pg_conn)
        _link(pg_conn, monitor)
        _link(pg_conn, monitor, token_hash="hash-a", kind="approval", max_hits=1)
        assert repo.revoke_for_monitor(monitor["id"], kinds=["webhook"]) == 1
        assert repo.get_live("hash-a", "approval") is not None

    def test_first_decision_wins(self, pg_conn):
        repo = TriggerLinksRepository(pg_conn)
        monitor = _monitor(pg_conn)
        _link(pg_conn, monitor, token_hash="hash-a", kind="approval", max_hits=1, approval_spec={"question": "Q?"})
        first = repo.decide("hash-a", {"decision": "approve", "comment": "ok"})
        assert first["decision"]["decision"] == "approve" and first["hit_count"] == 1
        assert repo.decide("hash-a", {"decision": "reject"}) is None
        assert repo.get_unexpired("hash-a", "approval")["decision"]["decision"] == "approve"
        assert repo.decide("hash-1", {"decision": "approve"}) is None

    def test_monitor_delete_cascades_links_and_hits(self, pg_conn):
        monitor = _monitor(pg_conn)
        link = _link(pg_conn, monitor)
        TriggerHitsRepository(pg_conn).insert(link["id"], "k", {"a": 1})
        pg_conn.execute(text("DELETE FROM schedules WHERE id = CAST(:id AS uuid)"), {"id": monitor["id"]})
        assert TriggerLinksRepository(pg_conn).get(link["id"]) is None
        assert pg_conn.execute(text("SELECT COUNT(*) FROM trigger_hits")).scalar() == 0


class TestHits:
    def test_a_delivery_is_stored_once_and_claimed_once(self, pg_conn):
        repo = TriggerHitsRepository(pg_conn)
        link = _link(pg_conn, _monitor(pg_conn))
        hit = repo.insert(link["id"], "wh_1", {"body": {"x": "a\x00"}})
        assert hit["status"] == "pending" and hit["payload"] == {"body": {"x": "a"}}
        assert repo.insert(link["id"], "wh_1", {}) is None
        assert repo.claim(hit["id"])["status"] == "processed"
        assert repo.claim(hit["id"]) is None
        repo.mark(hit["id"], "ignored", "check did not pass")
        assert repo.get(hit["id"])["status"] == "ignored"

    def test_stuck_and_cleanup(self, pg_conn):
        repo = TriggerHitsRepository(pg_conn)
        link = _link(pg_conn, _monitor(pg_conn))
        old = repo.insert(link["id"], "a", {})
        done = repo.insert(link["id"], "b", {})
        repo.mark(done["id"], "processed")
        pg_conn.execute(text("UPDATE trigger_hits SET received_at = now() - interval '10 days'"))
        assert [h["id"] for h in repo.list_stuck(age_seconds=60)] == [old["id"]]
        assert repo.cleanup_older_than(7) == 1
        repo.delete(old["id"])
        assert repo.get(old["id"]) is None
