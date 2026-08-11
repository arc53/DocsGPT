"""Tests for WorkflowRunsRepository against a real Postgres instance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from application.storage.db.repositories.workflows import WorkflowsRepository
from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository


def _wf(conn) -> dict:
    return WorkflowsRepository(conn).create("user-1", "test wf")


def _repo(conn) -> WorkflowRunsRepository:
    return WorkflowRunsRepository(conn)


class TestCreate:
    def test_creates_run(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        run = repo.create(wf["id"], "user-1", "completed")
        assert run["status"] == "completed"
        assert run["user_id"] == "user-1"
        assert run["id"] is not None

    def test_create_with_details(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        now = datetime.now(timezone.utc)
        run = repo.create(
            wf["id"], "user-1", "completed",
            inputs={"query": "hello"},
            result={"output": "world"},
            steps=[
                {"node_id": "n1", "status": "completed"},
                {"node_id": "n2", "status": "completed"},
            ],
            ended_at=now,
        )
        assert run["inputs"] == {"query": "hello"}
        assert run["result"] == {"output": "world"}
        assert len(run["steps"]) == 2
        assert run["ended_at"] is not None

    def test_create_with_started_at_and_legacy_id(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        now = datetime.now(timezone.utc)
        run = repo.create(
            wf["id"],
            "user-1",
            "completed",
            started_at=now,
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        # ``row_to_dict`` coerces datetimes to ISO strings at the SELECT
        # boundary; round-trip via ``fromisoformat`` to compare values.
        assert datetime.fromisoformat(run["started_at"]) == now
        assert run["legacy_mongo_id"] == "507f1f77bcf86cd799439011"


class TestGet:
    def test_get_existing(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        created = repo.create(wf["id"], "user-1", "completed")
        fetched = repo.get(created["id"])
        assert fetched["id"] == created["id"]

    def test_get_nonexistent(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000") is None

    def test_get_by_legacy_id(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        created = repo.create(
            wf["id"], "user-1", "completed",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        fetched = repo.get_by_legacy_id("507f1f77bcf86cd799439011")
        assert fetched["id"] == created["id"]


class TestListForWorkflow:
    def test_lists_runs(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        repo.create(wf["id"], "user-1", "completed")
        repo.create(wf["id"], "user-1", "failed")
        runs = repo.list_for_workflow(wf["id"])
        assert len(runs) == 2

    def test_empty_list(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        assert repo.list_for_workflow(wf["id"]) == []


class TestMarkStaleRunningFailed:
    def test_fails_old_running_run(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        run = repo.create(wf["id"], "user-1", "running", started_at=old)

        reaped = repo.mark_stale_running_failed(
            datetime.now(timezone.utc) - timedelta(hours=1)
        )
        assert reaped == 1
        fetched = repo.get(run["id"])
        assert fetched["status"] == "failed"
        assert fetched["ended_at"] is not None
        assert "did not complete" in (fetched["result"] or {}).get("error", "")
        # ended_at is the reap time, not when the run died; the marker says so.
        assert (fetched["result"] or {}).get("failed_reason") == "stale_reaper"

    def test_leaves_recent_running_and_terminal_runs(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        now = datetime.now(timezone.utc)
        recent = repo.create(wf["id"], "user-1", "running", started_at=now)
        # A terminal run that started long ago must not be touched (has ended_at).
        done = repo.create(
            wf["id"], "user-1", "completed",
            started_at=now - timedelta(hours=2), ended_at=now - timedelta(hours=2),
        )

        reaped = repo.mark_stale_running_failed(now - timedelta(hours=1))
        assert reaped == 0
        assert repo.get(recent["id"])["status"] == "running"
        assert repo.get(done["id"])["status"] == "completed"
