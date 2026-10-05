"""Tests for BackgroundJobsRepository."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository


def _conversation(conn, user_id: str = "u1") -> str:
    return str(ConversationsRepository(conn).create(user_id, "chat")["id"])


def _job(repo: BackgroundJobsRepository, conversation_id: str, **overrides):
    fields = {
        "user_id": "u1",
        "conversation_id": conversation_id,
        "tool_name": "code_executor",
        "action_name": "run_code",
        "tool_call_id": f"m:{uuid.uuid4().hex[:8]}",
        "max_seconds": 1000,
        "args": {"code": "print(1)"},
        "lease_owner": "host:1:abc",
    }
    fields.update(overrides)
    return repo.create(**fields)


def _age(conn, job_id: str, column: str, seconds: int) -> None:
    conn.execute(
        text(f"UPDATE background_jobs SET {column} = now() - make_interval(secs => :s) WHERE id = CAST(:id AS uuid)"),
        {"s": seconds, "id": job_id},
    )


class TestCreate:
    def test_writes_a_working_row_with_a_deadline(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, created = _job(repo, _conversation(pg_conn), kind="code_exec")
        assert created is True
        assert row["status"] == "working"
        assert row["delivery_state"] == "pending"
        assert row["runner"] == "inprocess"
        assert row["kind"] == "code_exec"
        assert row["args"] == {"code": "print(1)"}
        assert row["deadline_at"] > row["started_at"]
        assert row["auto_resume"] is True

    def test_same_call_twice_returns_the_first_row(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        first, _ = _job(repo, conversation_id, tool_call_id="m1:c1")
        second, created = _job(repo, conversation_id, tool_call_id="m1:c1", args={"code": "other"})
        assert created is False
        assert second["id"] == first["id"]
        assert second["args"] == {"code": "print(1)"}

    def test_strips_nul_bytes_from_args(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn), args={"code": "a\x00b"})
        assert row["args"] == {"code": "ab"}

    def test_job_without_conversation(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, created = repo.create(
            user_id="u1", tool_name="api_tool", action_name="get", max_seconds=60, workflow_run_id=str(uuid.uuid4())
        )
        assert created is True
        assert row["conversation_id"] is None


class TestReads:
    def test_get_is_scoped_to_the_user(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn))
        assert repo.get(row["id"], user_id="u1")["id"] == row["id"]
        assert repo.get(row["id"], user_id="someone-else") is None
        assert repo.get(row["id"])["id"] == row["id"]

    def test_get_tolerates_a_malformed_id(self, pg_conn):
        assert BackgroundJobsRepository(pg_conn).get("not-a-uuid", user_id="u1") is None

    def test_get_in_conversation_refuses_other_conversations(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        mine = _conversation(pg_conn)
        other = _conversation(pg_conn)
        row, _ = _job(repo, mine)
        assert repo.get_in_conversation(row["id"], "u1", mine)["id"] == row["id"]
        assert repo.get_in_conversation(row["id"], "u1", other) is None

    def test_list_for_conversation_newest_first(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        first, _ = _job(repo, conversation_id)
        _age(pg_conn, first["id"], "created_at", 30)
        second, _ = _job(repo, conversation_id)
        _job(repo, _conversation(pg_conn))
        listed = repo.list_for_conversation(conversation_id, "u1")
        assert [r["id"] for r in listed] == [second["id"], first["id"]]
        assert repo.list_for_conversation(conversation_id, "someone-else") == []

    def test_count_working(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        a, _ = _job(repo, conversation_id)
        _job(repo, conversation_id)
        _job(repo, _conversation(pg_conn))
        repo.finish(a["id"], status="completed", result={"text": "ok"}, retention_days=7)
        assert repo.count_working(conversation_id=conversation_id) == 1
        assert repo.count_working(user_id="u1") == 2


class TestLiveness:
    def test_heartbeat_touches_only_the_owners_working_jobs(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        mine, _ = _job(repo, conversation_id, lease_owner="me")
        theirs, _ = _job(repo, conversation_id, lease_owner="them")
        _age(pg_conn, mine["id"], "heartbeat_at", 120)
        _age(pg_conn, theirs["id"], "heartbeat_at", 120)
        assert repo.heartbeat("me") == 1
        stale = {r["id"] for r in repo.find_stale_working(stale_seconds=60)}
        assert stale == {theirs["id"]}

    def test_find_stale_working_filters_by_runner(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        inproc, _ = _job(repo, conversation_id)
        sandbox, _ = _job(repo, conversation_id, runner="sandbox")
        for row in (inproc, sandbox):
            _age(pg_conn, row["id"], "heartbeat_at", 120)
        found = repo.find_stale_working(stale_seconds=60, runners=("sandbox",))
        assert [r["id"] for r in found] == [sandbox["id"]]

    def test_find_past_deadline(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        late, _ = _job(repo, conversation_id)
        _job(repo, conversation_id)
        pg_conn.execute(
            text("UPDATE background_jobs SET deadline_at = now() - interval '2 minutes' WHERE id = CAST(:id AS uuid)"),
            {"id": late["id"]},
        )
        assert [r["id"] for r in repo.find_past_deadline(grace_seconds=60)] == [late["id"]]
        assert repo.find_past_deadline(grace_seconds=600) == []

    def test_progress_updates_only_while_working(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn))
        assert repo.update_progress(row["id"], progress={"percent": 40}, output_tail="step 2") is True
        got = repo.get(row["id"])
        assert got["progress"]["percent"] == 40
        assert got["output_tail"] == "step 2"
        repo.finish(row["id"], status="completed", retention_days=7)
        assert repo.update_progress(row["id"], progress={"percent": 90}) is False

    def test_set_runner_merges_external(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn), external={"a": 1})
        assert repo.set_runner(row["id"], runner="sandbox", external={"cmd_id": "c1"}, lease_owner=None)
        got = repo.get(row["id"])
        assert got["runner"] == "sandbox"
        assert got["external"] == {"a": 1, "cmd_id": "c1"}
        assert got["lease_owner"] is None


class TestFinish:
    def test_finish_is_terminal_once(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn))
        done = repo.finish(row["id"], status="completed", result={"text": "42"}, retention_days=7)
        assert done["status"] == "completed"
        assert done["result"] == {"text": "42"}
        assert done["finished_at"] is not None
        assert done["expires_at"] > done["finished_at"]
        assert repo.finish(row["id"], status="failed", error={"message": "late"}, retention_days=7) is None
        assert repo.get(row["id"])["status"] == "completed"

    def test_finish_rejects_a_non_final_status(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn))
        with pytest.raises(ValueError):
            repo.finish(row["id"], status="working", retention_days=7)

    def test_request_cancel_scoped_and_idempotent(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn))
        assert repo.request_cancel(row["id"], "someone-else") is None
        first = repo.request_cancel(row["id"], "u1")
        assert first["cancel_requested_at"] is not None
        assert first["status"] == "working"
        again = repo.request_cancel(row["id"], "u1")
        assert again["cancel_requested_at"] == first["cancel_requested_at"]


class TestDelivery:
    def test_claim_is_exactly_once(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn))
        repo.finish(row["id"], status="completed", retention_days=7)
        claimed = repo.claim_delivery(row["id"], "claimed_by_poll")
        assert claimed["delivery_state"] == "claimed_by_poll"
        assert claimed["delivered_at"] is not None
        assert repo.claim_delivery(row["id"], "resumed") is None

    def test_claim_needs_a_final_job(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn))
        assert repo.claim_delivery(row["id"], "resumed") is None

    def test_mark_followup(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        row, _ = _job(repo, _conversation(pg_conn))
        repo.finish(row["id"], status="completed", retention_days=7)
        repo.claim_delivery(row["id"], "resumed")
        message_id = str(uuid.uuid4())
        assert repo.set_followup(row["id"], message_id) is True
        assert repo.get(row["id"])["followup_message_id"] == message_id

    def test_fold_claims_final_pending_jobs_of_the_conversation(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        done, _ = _job(repo, conversation_id)
        polled, _ = _job(repo, conversation_id)
        running, _ = _job(repo, conversation_id)
        elsewhere, _ = _job(repo, _conversation(pg_conn))
        for row in (done, polled, elsewhere):
            repo.finish(row["id"], status="completed", retention_days=7)
        repo.claim_delivery(polled["id"], "claimed_by_poll")
        folded = repo.claim_foldable(conversation_id, "u1")
        assert [r["id"] for r in folded] == [done["id"]]
        assert repo.get(done["id"])["delivery_state"] == "folded"
        assert repo.get(running["id"])["delivery_state"] == "pending"
        assert repo.claim_foldable(conversation_id, "u1") == []

    def test_find_undelivered(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        late, _ = _job(repo, conversation_id)
        fresh, _ = _job(repo, conversation_id)
        manual, _ = _job(repo, conversation_id, auto_resume=False)
        for row in (late, fresh, manual):
            repo.finish(row["id"], status="completed", retention_days=7)
        for row in (late, manual):
            _age(pg_conn, row["id"], "finished_at", 600)
        found = repo.find_undelivered(older_than_seconds=120)
        assert [r["id"] for r in found] == [late["id"]]


class TestRetention:
    def test_cleanup_deletes_expired_final_jobs_only(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        old, _ = _job(repo, conversation_id)
        kept, _ = _job(repo, conversation_id)
        running, _ = _job(repo, conversation_id)
        repo.finish(old["id"], status="completed", retention_days=7)
        repo.finish(kept["id"], status="completed", retention_days=7)
        pg_conn.execute(
            text("UPDATE background_jobs SET expires_at = now() - interval '1 minute' WHERE id = CAST(:id AS uuid)"),
            {"id": old["id"]},
        )
        assert repo.cleanup_expired() == 1
        assert repo.get(old["id"]) is None
        assert repo.get(kept["id"]) is not None
        assert repo.get(running["id"]) is not None

    def test_jobs_go_with_their_conversation(self, pg_conn):
        repo = BackgroundJobsRepository(pg_conn)
        conversation_id = _conversation(pg_conn)
        row, _ = _job(repo, conversation_id)
        ConversationsRepository(pg_conn).delete(conversation_id, "u1")
        assert repo.get(row["id"]) is None
