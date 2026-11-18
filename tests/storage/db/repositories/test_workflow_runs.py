"""Tests for WorkflowRunsRepository against a real Postgres instance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository


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


class TestSetProgress:
    _PROGRESS = {
        "done": 2,
        "total": 5,
        "current": {"node_id": "n3", "title": "Draft reply", "type": "agent", "started_at": "2026-10-14T10:00:00+00:00"},
    }

    def test_records_progress_on_a_running_run(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        run = repo.create(wf["id"], "user-1", "running")
        assert repo.set_progress(str(run["id"]), "user-1", self._PROGRESS) is True
        assert repo.get(run["id"])["progress"] == self._PROGRESS

    def test_leaves_finished_and_foreign_runs(self, pg_conn):
        wf = _wf(pg_conn)
        repo = _repo(pg_conn)
        done = repo.create(wf["id"], "user-1", "completed")
        running = repo.create(wf["id"], "user-1", "running")
        assert repo.set_progress(str(done["id"]), "user-1", self._PROGRESS) is False
        assert repo.set_progress(str(running["id"]), "user-2", self._PROGRESS) is False
        assert repo.get(done["id"])["progress"] is None
        assert repo.get(running["id"])["progress"] is None


AGENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
AGENT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class TestListForUser:
    def _seed(self, conn):
        wf = _wf(conn)
        repo = _repo(conn)
        base = datetime(2026, 10, 1, tzinfo=timezone.utc)
        rows = [
            ("user-1", "completed", AGENT_A, base),
            ("user-1", "failed", AGENT_B, base + timedelta(hours=1)),
            ("user-1", "running", AGENT_A, base + timedelta(hours=2)),
            ("user-1", "completed", None, base + timedelta(hours=3)),
            ("user-2", "completed", AGENT_A, base + timedelta(hours=4)),
        ]
        ids = []
        for user, status, agent, started in rows:
            inputs = {"query": f"q-{len(ids)}"}
            if agent:
                inputs["agent_id"] = agent
            ids.append(str(repo.create(wf["id"], user, status, inputs=inputs, started_at=started)["id"]))
        return base, ids

    def test_lists_only_the_users_runs_newest_first(self, pg_conn):
        _, ids = self._seed(pg_conn)
        runs = _repo(pg_conn).list_for_user("user-1")
        assert [str(r["id"]) for r in runs] == [ids[3], ids[2], ids[1], ids[0]]

    def test_filters_by_agent_status_and_since(self, pg_conn):
        base, ids = self._seed(pg_conn)
        repo = _repo(pg_conn)
        assert [str(r["id"]) for r in repo.list_for_user("user-1", agent_id=AGENT_A)] == [ids[2], ids[0]]
        assert [str(r["id"]) for r in repo.list_for_user("user-1", agent_id=AGENT_A.upper())] == [ids[2], ids[0]]
        assert [str(r["id"]) for r in repo.list_for_user("user-1", status="failed")] == [ids[1]]
        since = base + timedelta(minutes=90)
        assert [str(r["id"]) for r in repo.list_for_user("user-1", since=since)] == [ids[3], ids[2]]

    def test_an_agent_allowlist_hides_other_and_agentless_runs(self, pg_conn):
        _, ids = self._seed(pg_conn)
        repo = _repo(pg_conn)
        assert [str(r["id"]) for r in repo.list_for_user("user-1", agent_ids={AGENT_A})] == [ids[2], ids[0]]
        assert repo.list_for_user("user-1", agent_ids=set()) == []
        assert repo.list_for_user("user-1", agent_id=AGENT_B, agent_ids={AGENT_A}) == []

    def test_limit(self, pg_conn):
        _, ids = self._seed(pg_conn)
        assert [str(r["id"]) for r in _repo(pg_conn).list_for_user("user-1", limit=2)] == [ids[3], ids[2]]

    def test_listing_leaves_out_the_heavy_columns(self, pg_conn):
        wf = _wf(pg_conn)
        _repo(pg_conn).create(wf["id"], "user-1", "completed", result={"big": "x" * 100}, steps=[{"node_id": "n"}])
        run = _repo(pg_conn).list_for_user("user-1")[0]
        assert "result" not in run and "steps" not in run
        assert run["step_count"] == 1
