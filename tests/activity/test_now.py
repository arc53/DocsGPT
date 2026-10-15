"""Tests for the Activity › Now snapshot against an ephemeral Postgres."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.activity import now as activity_now
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.ingest_chunk_progress import IngestChunkProgressRepository
from docsgpt.storage.db.repositories.pending_tool_state import PendingToolStateRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository


@pytest.fixture(autouse=True)
def _no_markers(monkeypatch):
    monkeypatch.setattr(activity_now, "list_runs", lambda user_id: [])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agent(conn, name: str = "Desk", user_id: str = "u1", workflow_id: str | None = None) -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO agents (user_id, name, status, workflow_id) "
                "VALUES (:u, :n, 'published', CAST(:w AS uuid)) RETURNING id"
            ),
            {"u": user_id, "n": name, "w": workflow_id},
        ).scalar()
    )


def _chat(conn, name: str = "Nordhaven renewal prep", user_id: str = "u1", **kw) -> str:
    return str(ConversationsRepository(conn).create(user_id, name, **kw)["id"])


def _message(conn, conversation_id: str, status: str, *, heartbeat_age: int = 5) -> str:
    row = ConversationsRepository(conn).reserve_message(
        conversation_id, prompt="q", placeholder_response="", status=status,
    )
    conn.execute(
        text(
            "UPDATE conversation_messages SET message_metadata = jsonb_build_object("
            "'last_heartbeat_at', to_jsonb(now() - make_interval(secs => :age))) "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"age": heartbeat_age, "id": str(row["id"])},
    )
    return str(row["id"])


def _kinds(snapshot) -> list[str]:
    return [item["kind"] for item in snapshot["running"]]


class TestRunningChats:
    def test_lists_a_live_answer_in_a_listed_chat(self, pg_conn):
        conv = _chat(pg_conn)
        message_id = _message(pg_conn, conv, "streaming")
        snap = activity_now.build_now(pg_conn, "u1")
        chats = [item for item in snap["running"] if item["kind"] == "chat"]
        assert len(chats) == 1
        assert chats[0]["message_id"] == message_id
        assert chats[0]["conversation_id"] == conv
        assert chats[0]["title"] == "Nordhaven renewal prep"

    def test_skips_stale_hidden_and_finished_answers(self, pg_conn):
        _message(pg_conn, _chat(pg_conn), "streaming", heartbeat_age=600)
        _message(pg_conn, _chat(pg_conn, visibility="hidden"), "streaming")
        _message(pg_conn, _chat(pg_conn), "complete")
        _message(pg_conn, _chat(pg_conn, user_id="u2"), "streaming")
        assert activity_now.build_now(pg_conn, "u1")["running"] == []

    def test_an_answer_paused_for_approval_is_not_running(self, pg_conn):
        # It waits under needs_you; listed here it would offer a Stop.
        conv = _chat(pg_conn)
        message_id = _message(pg_conn, conv, "streaming")
        PendingToolStateRepository(pg_conn).save_state(
            conv, "u1",
            messages=[], tools_dict={}, tool_schemas=[], agent_config={"reserved_message_id": message_id},
            pending_tool_calls=[{"call_id": "c1", "tool_name": "send_email", "pause_type": "awaiting_approval"}],
        )
        assert _kinds(activity_now.build_now(pg_conn, "u1")) == []

    def test_a_resuming_answer_is_running(self, pg_conn):
        conv = _chat(pg_conn)
        message_id = _message(pg_conn, conv, "streaming")
        repo = PendingToolStateRepository(pg_conn)
        repo.save_state(
            conv, "u1",
            messages=[], tools_dict={}, tool_schemas=[], agent_config={"reserved_message_id": message_id},
            pending_tool_calls=[{"call_id": "c1", "tool_name": "send_email", "pause_type": "awaiting_approval"}],
        )
        repo.mark_resuming(conv, "u1")
        assert _kinds(activity_now.build_now(pg_conn, "u1")) == ["chat"]


class TestApiRequests:
    def test_api_answers_on_an_agent_are_one_row(self, pg_conn):
        agent = _agent(pg_conn, "Support bot")
        _message(pg_conn, _chat(pg_conn, agent_id=agent, visibility="hidden"), "streaming")
        _message(pg_conn, _chat(pg_conn, agent_id=agent, visibility="hidden"), "pending")
        # A caller on the shared agent runs under their own user id.
        _message(pg_conn, _chat(pg_conn, user_id="u2", agent_id=agent, visibility="hidden"), "streaming")
        snap = activity_now.build_now(pg_conn, "u1")
        rows = [item for item in snap["running"] if item["kind"] == "api"]
        assert len(rows) == 1
        assert rows[0]["agent_id"] == agent
        assert rows[0]["agent_name"] == "Support bot"
        assert rows[0]["count"] == 3
        assert rows[0]["started_at"]

    def test_skips_other_owners_agents_and_finished_answers(self, pg_conn):
        theirs = _agent(pg_conn, "Their bot", user_id="u2")
        _message(pg_conn, _chat(pg_conn, user_id="u2", agent_id=theirs, visibility="hidden"), "streaming")
        mine = _agent(pg_conn, "Support bot")
        _message(pg_conn, _chat(pg_conn, agent_id=mine, visibility="hidden"), "complete")
        _message(pg_conn, _chat(pg_conn, agent_id=mine, visibility="hidden"), "streaming", heartbeat_age=600)
        assert activity_now.build_now(pg_conn, "u1")["running"] == []

    def test_absorbs_the_agents_workflow_runs(self, pg_conn):
        workflow = TestWorkflowRuns()._workflow(pg_conn)
        agent = _agent(pg_conn, "Renewal Desk", workflow_id=workflow)
        _message(pg_conn, _chat(pg_conn, agent_id=agent, visibility="hidden"), "streaming")
        TestWorkflowRuns()._run(pg_conn, workflow)
        snap = activity_now.build_now(pg_conn, "u1")
        assert _kinds(snap) == ["api"]
        assert snap["running"][0]["workflow"] is True


class TestBackgroundJobs:
    def test_lists_working_jobs_with_their_chat(self, pg_conn):
        conv = _chat(pg_conn, "Halvorsen QBR")
        job, _ = BackgroundJobsRepository(pg_conn).create(
            user_id="u1", tool_name="code_executor", action_name="run",
            max_seconds=600, conversation_id=conv, kind="code_exec",
        )
        snap = activity_now.build_now(pg_conn, "u1")
        jobs = [item for item in snap["running"] if item["kind"] == "job"]
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == str(job["id"])
        assert jobs[0]["conversation_name"] == "Halvorsen QBR"
        assert jobs[0]["tool_name"] == "code_executor"
        assert jobs[0]["tool_label"] == "Code Executor"
        assert jobs[0]["progress"] is None

    def test_a_jobs_progress_is_a_fraction_like_every_other_rows(self, pg_conn):
        # The job stores {"last", "percent"} (background/watch.py); Now's
        # bar reads one 0-1 number for every kind.
        repo = BackgroundJobsRepository(pg_conn)
        job, _ = repo.create(
            user_id="u1", tool_name="code_executor", action_name="run",
            max_seconds=600, conversation_id=_chat(pg_conn), kind="code_exec",
        )
        repo.update_progress(str(job["id"]), progress={"last": "PROGRESS 42%", "percent": 42})
        [item] = [i for i in activity_now.build_now(pg_conn, "u1")["running"] if i["kind"] == "job"]
        assert item["progress"] == 0.42


class TestScheduledRuns:
    def test_lists_a_running_run(self, pg_conn):
        agent = _agent(pg_conn, "Deal Desk")
        schedule = SchedulesRepository(pg_conn).create(
            "u1", agent, "recurring", "score carriers", cron="15 14 * * 2",
            name="Weekly carrier scorecard",
        )
        run = ScheduleRunsRepository(pg_conn).record_pending(
            str(schedule["id"]), "u1", agent, scheduled_for=_now(),
        )
        ScheduleRunsRepository(pg_conn).mark_running(str(run["id"]), None)
        snap = activity_now.build_now(pg_conn, "u1")
        runs = [item for item in snap["running"] if item["kind"] == "schedule"]
        assert len(runs) == 1
        assert runs[0]["title"] == "Weekly carrier scorecard"
        assert runs[0]["agent_name"] == "Deal Desk"
        assert runs[0]["schedule_id"] == str(schedule["id"])


_PROGRESS = {
    "done": 1,
    "total": 3,
    "current": {"node_id": "b", "title": "Draft reply", "type": "agent", "started_at": "2026-10-14T10:00:00+00:00"},
}


class TestWorkflowRuns:
    def _workflow(self, conn) -> str:
        return str(
            conn.execute(
                text("INSERT INTO workflows (user_id, name) VALUES ('u1', 'Renewal flow') RETURNING id")
            ).scalar()
        )

    def _run(
        self, conn, workflow_id: str, progress: dict | None = None, age: int = 0, started_by: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        inputs = {
            "query": "q",
            **({"started_by": started_by} if started_by else {}),
            **({"agent_id": agent_id} if agent_id else {}),
        } if started_by or agent_id else None
        conn.execute(
            text(
                "INSERT INTO workflow_runs (workflow_id, user_id, status, started_at, progress, inputs) "
                "VALUES (CAST(:w AS uuid), 'u1', 'running', now() - make_interval(secs => :age), "
                "CAST(:p AS jsonb), CAST(:i AS jsonb))"
            ),
            {
                "w": workflow_id,
                "p": json.dumps(progress) if progress else None,
                "age": age,
                "i": json.dumps(inputs) if inputs else None,
            },
        )

    def test_a_run_on_its_own_is_listed(self, pg_conn):
        workflow = self._workflow(pg_conn)
        _agent(pg_conn, "Renewal Desk", workflow_id=workflow)
        self._run(pg_conn, workflow)
        snap = activity_now.build_now(pg_conn, "u1")
        flows = [item for item in snap["running"] if item["kind"] == "workflow"]
        assert len(flows) == 1
        assert flows[0]["agent_name"] == "Renewal Desk"

    def _teammates_workflow(self, conn) -> tuple[str, str]:
        """u2's workflow under a private agent and, newer, a shared one; returns (workflow, shared)."""
        workflow = str(
            conn.execute(
                text("INSERT INTO workflows (user_id, name) VALUES ('u2', 'Renewal flow') RETURNING id")
            ).scalar()
        )
        conn.execute(
            text(
                "INSERT INTO agents (user_id, name, status, workflow_id, created_at) "
                "VALUES ('u2', 'Private draft', 'published', CAST(:w AS uuid), now() - interval '1 day')"
            ),
            {"w": workflow},
        )
        return workflow, _agent(conn, "Shared desk", user_id="u2", workflow_id=workflow)

    def test_a_run_is_named_by_the_agent_that_ran_it(self, pg_conn):
        workflow, shared = self._teammates_workflow(pg_conn)
        self._run(pg_conn, workflow, agent_id=shared)
        [flow] = [i for i in activity_now.build_now(pg_conn, "u1")["running"] if i["kind"] == "workflow"]
        assert (flow["agent_id"], flow["agent_name"]) == (shared, "Shared desk")

    def test_an_older_run_never_names_another_users_agent(self, pg_conn):
        # A run from before the agent was recorded falls back to the runner's
        # own agents: the owner's private one is not the teammate's to see.
        workflow, _ = self._teammates_workflow(pg_conn)
        self._run(pg_conn, workflow)
        [flow] = [i for i in activity_now.build_now(pg_conn, "u1")["running"] if i["kind"] == "workflow"]
        assert flow["agent_id"] is None
        assert flow["agent_name"] is None

    def test_a_run_inside_a_running_chat_is_folded_into_it(self, pg_conn):
        workflow = self._workflow(pg_conn)
        agent = _agent(pg_conn, "Renewal Desk", workflow_id=workflow)
        _message(pg_conn, _chat(pg_conn, agent_id=agent), "streaming")
        self._run(pg_conn, workflow)
        snap = activity_now.build_now(pg_conn, "u1")
        assert _kinds(snap) == ["chat"]
        assert snap["running"][0]["workflow"] is True

    def test_a_folded_run_lends_its_step_to_the_chat(self, pg_conn):
        workflow = self._workflow(pg_conn)
        agent = _agent(pg_conn, "Renewal Desk", workflow_id=workflow)
        _message(pg_conn, _chat(pg_conn, agent_id=agent), "streaming")
        self._run(pg_conn, workflow, _PROGRESS)
        chat = activity_now.build_now(pg_conn, "u1")["running"][0]
        assert chat["workflow_progress"] == _PROGRESS

    def test_a_run_on_its_own_carries_its_step(self, pg_conn):
        workflow = self._workflow(pg_conn)
        _agent(pg_conn, "Renewal Desk", workflow_id=workflow)
        self._run(pg_conn, workflow, _PROGRESS)
        flow = activity_now.build_now(pg_conn, "u1")["running"][0]
        assert flow["kind"] == "workflow"
        assert flow["workflow_progress"] == _PROGRESS

    def test_runs_pair_with_hosts_oldest_first(self, pg_conn):
        workflow = self._workflow(pg_conn)
        agent = _agent(pg_conn, "Renewal Desk", workflow_id=workflow)
        _message(pg_conn, _chat(pg_conn, agent_id=agent), "streaming")
        older = {**_PROGRESS, "done": 3}
        self._run(pg_conn, workflow, older, age=60)
        self._run(pg_conn, workflow, _PROGRESS)
        snap = activity_now.build_now(pg_conn, "u1")
        # One chat hosts one run; the second run of the same agent is its own row.
        assert _kinds(snap) == ["chat", "workflow"]
        assert snap["running"][0]["workflow_progress"] == older
        assert snap["running"][1]["workflow_progress"] == _PROGRESS

    def test_a_run_goes_to_the_request_that_started_it(self, pg_conn):
        # An API request starts first, then a chat on the same agent: by age
        # alone, the chat would show the API run's step.
        workflow = self._workflow(pg_conn)
        agent = _agent(pg_conn, "Renewal Desk", workflow_id=workflow)
        api_message = _message(pg_conn, _chat(pg_conn, agent_id=agent, visibility="hidden"), "streaming")
        chat_message = _message(pg_conn, _chat(pg_conn, agent_id=agent), "streaming")
        api_step = {**_PROGRESS, "done": 2}
        self._run(pg_conn, workflow, api_step, age=60, started_by=api_message)
        self._run(pg_conn, workflow, _PROGRESS, started_by=chat_message)
        snap = activity_now.build_now(pg_conn, "u1")
        by_kind = {item["kind"]: item for item in snap["running"]}
        assert sorted(by_kind) == ["api", "chat"]
        assert by_kind["chat"]["workflow_progress"] == _PROGRESS
        assert by_kind["api"]["workflow"] is True
        assert "message_ids" not in by_kind["api"]

    def test_a_scheduled_run_takes_its_own_workflow_run(self, pg_conn):
        workflow = self._workflow(pg_conn)
        agent = _agent(pg_conn, "Renewal Desk", workflow_id=workflow)
        schedule = SchedulesRepository(pg_conn).create("u1", agent, "recurring", "renew", cron="0 9 * * *")
        run = ScheduleRunsRepository(pg_conn).record_pending(str(schedule["id"]), "u1", agent, scheduled_for=_now())
        ScheduleRunsRepository(pg_conn).mark_running(str(run["id"]), None)
        _message(pg_conn, _chat(pg_conn, agent_id=agent), "streaming")
        # The chat's run is older, but this one names the scheduled run.
        self._run(pg_conn, workflow, _PROGRESS, started_by=str(run["id"]))
        snap = activity_now.build_now(pg_conn, "u1")
        by_kind = {item["kind"]: item for item in snap["running"]}
        assert by_kind["schedule"]["workflow_progress"] == _PROGRESS
        assert by_kind["chat"]["workflow"] is False

    def test_a_webhook_run_takes_its_own_workflow_run(self, pg_conn, monkeypatch):
        workflow = self._workflow(pg_conn)
        agent = _agent(pg_conn, "Renewal Desk", workflow_id=workflow)
        monkeypatch.setattr(
            activity_now,
            "list_runs",
            # Started after the chat, so by age the chat would take the run.
            lambda user_id: [{"id": "task-1", "kind": "webhook", "agent_id": agent, "started_at": _now().timestamp()}],
        )
        _message(pg_conn, _chat(pg_conn, agent_id=agent), "streaming", heartbeat_age=30)
        self._run(pg_conn, workflow, _PROGRESS, started_by="task-1")
        by_kind = {item["kind"]: item for item in activity_now.build_now(pg_conn, "u1")["running"]}
        assert by_kind["webhook"]["workflow_progress"] == _PROGRESS
        assert by_kind["chat"]["workflow"] is False


class TestIngest:
    def test_lists_a_source_that_is_embedding(self, pg_conn):
        source = SourcesRepository(pg_conn).create("Carrier handbook 2026.pdf", user_id="u1")
        progress = IngestChunkProgressRepository(pg_conn)
        progress.init_progress(str(source["id"]), 120)
        pg_conn.execute(
            text("UPDATE ingest_chunk_progress SET embedded_chunks = 34 WHERE source_id = CAST(:id AS uuid)"),
            {"id": str(source["id"])},
        )
        snap = activity_now.build_now(pg_conn, "u1")
        ingests = [item for item in snap["running"] if item["kind"] == "ingest"]
        assert len(ingests) == 1
        assert ingests[0]["title"] == "Carrier handbook 2026.pdf"
        assert ingests[0]["progress"] == pytest.approx(34 / 120)
        # No marker (the run started before markers, or Redis lost it): no start time.
        assert ingests[0]["started_at"] is None
        assert ingests[0]["stage"] == "embedding"

    def _marker(self, source_id: str, age: int = 90, **extra) -> dict:
        return {
            "kind": "ingest", "id": f"ingest:{source_id}", "source_id": source_id,
            "name": "Rate cards Q4", "operation": "upload",
            "started_at": datetime.now(timezone.utc).timestamp() - age, **extra,
        }

    def test_a_new_upload_shows_while_its_files_are_read(self, pg_conn, monkeypatch):
        source_id = str(uuid.uuid4())
        monkeypatch.setattr(activity_now, "list_runs", lambda user_id: [self._marker(source_id)])
        snap = activity_now.build_now(pg_conn, "u1")
        assert _kinds(snap) == ["ingest"]
        item = snap["running"][0]
        assert item["source_id"] == source_id
        assert item["title"] == "Rate cards Q4"
        assert item["operation"] == "upload"
        assert item["stage"] == "reading"
        assert item["progress"] is None
        assert item["started_at"]

    def test_a_new_upload_embedding_has_chunks_and_a_start(self, pg_conn, monkeypatch):
        source_id = str(uuid.uuid4())
        IngestChunkProgressRepository(pg_conn).init_progress(source_id, 200)
        monkeypatch.setattr(activity_now, "list_runs", lambda user_id: [self._marker(source_id)])
        item = activity_now.build_now(pg_conn, "u1")["running"][0]
        assert item["stage"] == "embedding"
        assert item["total_chunks"] == 200
        assert item["title"] == "Rate cards Q4"
        assert item["started_at"]

    def test_a_resync_ignores_the_last_runs_progress(self, pg_conn, monkeypatch):
        source = SourcesRepository(pg_conn).create("Carrier handbook 2026.pdf", user_id="u1")
        source_id = str(source["id"])
        IngestChunkProgressRepository(pg_conn).init_progress(source_id, 120)
        pg_conn.execute(
            text(
                "UPDATE ingest_chunk_progress SET embedded_chunks = 120, "
                "last_updated = now() - interval '1 day' WHERE source_id = CAST(:id AS uuid)"
            ),
            {"id": source_id},
        )
        monkeypatch.setattr(
            activity_now, "list_runs", lambda user_id: [self._marker(source_id, name=None, operation="sync")]
        )
        item = activity_now.build_now(pg_conn, "u1")["running"][0]
        assert item["stage"] == "reading"
        assert item["progress"] is None
        assert item["operation"] == "sync"
        assert item["title"] == "Carrier handbook 2026.pdf"

    def test_a_stalled_ingest_is_not_running(self, pg_conn, monkeypatch):
        source_id = str(uuid.uuid4())
        IngestChunkProgressRepository(pg_conn).init_progress(source_id, 200)
        pg_conn.execute(
            text("UPDATE ingest_chunk_progress SET status = 'stalled' WHERE source_id = CAST(:id AS uuid)"),
            {"id": source_id},
        )
        monkeypatch.setattr(activity_now, "list_runs", lambda user_id: [self._marker(source_id)])
        assert activity_now.build_now(pg_conn, "u1")["running"] == []

    def test_stalled_ingests_do_not_crowd_out_a_running_one(self, pg_conn):
        # Stalled rows stay and are old; they must not fill the list's slots.
        sources = SourcesRepository(pg_conn)
        progress = IngestChunkProgressRepository(pg_conn)
        for i in range(activity_now.PER_KIND_LIMIT):
            old = str(sources.create(f"old {i}", user_id="u1")["id"])
            progress.init_progress(old, 10)
            progress.mark_failed(old)
        pg_conn.execute(text("UPDATE ingest_chunk_progress SET last_updated = now() - interval '2 days'"))
        live = str(sources.create("Carrier handbook 2026.pdf", user_id="u1")["id"])
        progress.init_progress(live, 120)
        ingests = [i for i in activity_now.build_now(pg_conn, "u1")["running"] if i["kind"] == "ingest"]
        assert [i["source_id"] for i in ingests] == [live]

    def test_reindexing_a_stalled_source_shows_reading(self, pg_conn, monkeypatch):
        source = SourcesRepository(pg_conn).create("Carrier handbook 2026.pdf", user_id="u1")
        source_id = str(source["id"])
        progress = IngestChunkProgressRepository(pg_conn)
        progress.init_progress(source_id, 120)
        progress.mark_failed(source_id)
        pg_conn.execute(
            text("UPDATE ingest_chunk_progress SET last_updated = now() - interval '1 day' "
                 "WHERE source_id = CAST(:id AS uuid)"),
            {"id": source_id},
        )
        monkeypatch.setattr(
            activity_now, "list_runs", lambda user_id: [self._marker(source_id, name=None, operation="reingest")]
        )
        [item] = activity_now.build_now(pg_conn, "u1")["running"]
        assert item["stage"] == "reading"
        assert item["title"] == "Carrier handbook 2026.pdf"

    def test_a_marker_that_is_not_a_uuid_is_ignored(self, pg_conn, monkeypatch):
        source = SourcesRepository(pg_conn).create("Carrier handbook 2026.pdf", user_id="u1")
        IngestChunkProgressRepository(pg_conn).init_progress(str(source["id"]), 120)
        monkeypatch.setattr(activity_now, "list_runs", lambda user_id: [self._marker("not-a-uuid")])
        ingests = [i for i in activity_now.build_now(pg_conn, "u1")["running"] if i["kind"] == "ingest"]
        # The junk marker still shows as reading; the query just doesn't choke on it.
        assert {i["source_id"] for i in ingests} == {"not-a-uuid", str(source["id"])}

    def test_a_failed_ingest_is_not_running(self, pg_conn):
        # The failure cleared the marker; the closed row must not fall back
        # to "embedding" until the reconciler notices.
        source = SourcesRepository(pg_conn).create("Carrier handbook 2026.pdf", user_id="u1")
        progress = IngestChunkProgressRepository(pg_conn)
        progress.init_progress(str(source["id"]), 120)
        progress.mark_failed(str(source["id"]))
        assert activity_now.build_now(pg_conn, "u1")["running"] == []

    def test_an_ingest_marker_is_not_a_webhook_run(self, pg_conn, monkeypatch):
        monkeypatch.setattr(activity_now, "list_runs", lambda user_id: [self._marker(str(uuid.uuid4()))])
        assert _kinds(activity_now.build_now(pg_conn, "u1")) == ["ingest"]


class TestWebhookRuns:
    def test_lists_markers(self, pg_conn, monkeypatch):
        monkeypatch.setattr(
            activity_now,
            "list_runs",
            lambda user_id: [{"id": "t1", "kind": "webhook", "agent_id": "a1", "agent_name": "Desk", "started_at": 0}],
        )
        snap = activity_now.build_now(pg_conn, "u1")
        assert _kinds(snap) == ["webhook"]
        assert snap["running"][0]["agent_name"] == "Desk"


class TestNeedsYou:
    def _pending(self, conn, conversation_id: str, pause_type: str = "awaiting_approval") -> None:
        PendingToolStateRepository(conn).save_state(
            conversation_id, "u1",
            messages=[], tools_dict={}, tool_schemas=[], agent_config={},
            pending_tool_calls=[{"call_id": "c1", "tool_name": "send_email", "pause_type": pause_type}],
        )

    def test_lists_waiting_approvals(self, pg_conn):
        conv = _chat(pg_conn, "Vendor Renewal Decision")
        self._pending(pg_conn, conv)
        snap = activity_now.build_now(pg_conn, "u1")
        approvals = [item for item in snap["needs_you"] if item["kind"] == "approval"]
        assert len(approvals) == 1
        assert approvals[0]["conversation_id"] == conv
        assert approvals[0]["tools"] == ["send_email"]
        assert snap["approval_conversations"] == [conv]

    def test_a_client_tool_pause_is_not_an_approval(self, pg_conn):
        self._pending(pg_conn, _chat(pg_conn), pause_type="client_tool")
        assert activity_now.build_now(pg_conn, "u1")["needs_you"] == []

    def test_lists_schedules_paused_after_failures(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "SCHEDULE_AUTOPAUSE_FAILURES", 3)
        agent = _agent(pg_conn, "Deal Desk")
        repo = SchedulesRepository(pg_conn)
        auto = repo.create("u1", agent, "recurring", "scan", cron="0 7 * * 1-5", name="Prospect news scan", status="paused")
        repo.create("u1", agent, "recurring", "manual", cron="0 7 * * 1-5", status="paused")
        pg_conn.execute(
            text("UPDATE schedules SET consecutive_failure_count = 3 WHERE id = CAST(:id AS uuid)"),
            {"id": str(auto["id"])},
        )
        snap = activity_now.build_now(pg_conn, "u1")
        paused = [item for item in snap["needs_you"] if item["kind"] == "schedule_paused"]
        assert [item["schedule_id"] for item in paused] == [str(auto["id"])]
        assert paused[0]["failures"] == 3


class TestUpNext:
    def test_counts_runs_in_the_next_day(self, pg_conn):
        agent = _agent(pg_conn, "Helpdesk")
        repo = SchedulesRepository(pg_conn)
        repo.create(
            "u1", agent, "recurring", "triage", cron="0 * * * *", name="Inbox triage",
            # On the hour, as the dispatcher stores it: 24 runs fit the next day.
            next_run_at=_now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1),
        )
        repo.create(
            "u1", None, "once", "remind me", run_at=_now() + timedelta(hours=3),
            next_run_at=_now() + timedelta(hours=3), name="Remind me",
        )
        repo.create(
            "u1", agent, "once", "later", run_at=_now() + timedelta(days=3),
            next_run_at=_now() + timedelta(days=3),
        )
        snap = activity_now.build_now(pg_conn, "u1")
        names = [item["name"] for item in snap["up_next"]]
        assert names == ["Inbox triage", "Remind me"]
        assert snap["up_next"][0]["runs_in_window"] == 24
        assert snap["stats"]["next_24h"] == 25


class TestUpNextOverdue:
    def test_an_overdue_schedule_counts_only_runs_still_ahead(self, pg_conn):
        agent = _agent(pg_conn, "Support")
        SchedulesRepository(pg_conn).create(
            "u1", agent, "recurring", "digest", cron="0 8 * * *", name="Daily digest",
            next_run_at=_now() - timedelta(days=6),
        )
        snap = activity_now.build_now(pg_conn, "u1")
        assert [item["name"] for item in snap["up_next"]] == ["Daily digest"]
        assert snap["up_next"][0]["runs_in_window"] == 1
        assert snap["stats"]["next_24h"] == 1


class TestFailures:
    def test_counts_failed_runs_of_the_last_day(self, pg_conn):
        agent = _agent(pg_conn)
        schedule = SchedulesRepository(pg_conn).create("u1", agent, "recurring", "x", cron="0 7 * * *")
        runs = ScheduleRunsRepository(pg_conn)
        run = runs.record_pending(str(schedule["id"]), "u1", agent, scheduled_for=_now())
        runs.update(str(run["id"]), {"status": "failed", "finished_at": _now()})
        assert activity_now.build_now(pg_conn, "u1")["stats"]["failed_24h"] == 1

    def test_marks_unread_chats_whose_last_job_failed(self, pg_conn):
        conv = _chat(pg_conn)
        jobs = BackgroundJobsRepository(pg_conn)
        job, _ = jobs.create(user_id="u1", tool_name="code_executor", action_name="run", max_seconds=60, conversation_id=conv)
        pg_conn.execute(
            text("UPDATE background_jobs SET status = 'failed', finished_at = now() WHERE id = CAST(:id AS uuid)"),
            {"id": str(job["id"])},
        )
        assert activity_now.build_now(pg_conn, "u1")["failed_conversations"] == []
        pg_conn.execute(
            text("UPDATE conversations SET unread_at = now() WHERE id = CAST(:id AS uuid)"), {"id": conv},
        )
        assert activity_now.build_now(pg_conn, "u1")["failed_conversations"] == [conv]

    def _failed_job(self, conn, conv, minutes_ago):
        job, _ = BackgroundJobsRepository(conn).create(
            user_id="u1", tool_name="code_executor", action_name="run", max_seconds=60, conversation_id=conv,
        )
        conn.execute(
            text(
                "UPDATE background_jobs SET status = 'failed', "
                "finished_at = now() - make_interval(mins => :m) WHERE id = CAST(:id AS uuid)"
            ),
            {"m": minutes_ago, "id": str(job["id"])},
        )

    def _read_then_unread(self, conn, conv, read_minutes_ago):
        conn.execute(
            text(
                "UPDATE conversations SET read_at = now() - make_interval(mins => :m), "
                "unread_at = now() WHERE id = CAST(:id AS uuid)"
            ),
            {"m": read_minutes_ago, "id": conv},
        )

    def test_a_failure_seen_before_does_not_come_back(self, pg_conn):
        # The job failed, the user opened the chat, then a later reply
        # marked it unread again: the failure was already seen.
        conv = _chat(pg_conn)
        self._failed_job(pg_conn, conv, minutes_ago=30)
        self._read_then_unread(pg_conn, conv, read_minutes_ago=20)
        assert activity_now.build_now(pg_conn, "u1")["failed_conversations"] == []

    def test_a_failure_after_the_last_read_is_marked(self, pg_conn):
        # The unread mark lands after the job ends (its follow-up notifies):
        # what matters is that the user hasn't read the chat since.
        conv = _chat(pg_conn)
        self._failed_job(pg_conn, conv, minutes_ago=5)
        self._read_then_unread(pg_conn, conv, read_minutes_ago=30)
        assert activity_now.build_now(pg_conn, "u1")["failed_conversations"] == [conv]

    def test_a_failure_in_a_chat_never_read_is_marked(self, pg_conn):
        conv = _chat(pg_conn)
        self._failed_job(pg_conn, conv, minutes_ago=5)
        pg_conn.execute(
            text("UPDATE conversations SET unread_at = now() + interval '1 minute' WHERE id = CAST(:id AS uuid)"),
            {"id": conv},
        )
        assert activity_now.build_now(pg_conn, "u1")["failed_conversations"] == [conv]

    def test_an_answer_the_user_stopped_is_not_a_failure(self, pg_conn):
        conv = _chat(pg_conn)
        message_id = _message(pg_conn, conv, "failed")
        pg_conn.execute(
            text("UPDATE conversations SET unread_at = now() WHERE id = CAST(:id AS uuid)"), {"id": conv},
        )
        assert activity_now.build_now(pg_conn, "u1")["failed_conversations"] == [conv]
        pg_conn.execute(
            text(
                "UPDATE conversation_messages SET message_metadata = message_metadata || "
                "'{\"error_code\": \"stopped\"}'::jsonb WHERE id = CAST(:id AS uuid)"
            ),
            {"id": message_id},
        )
        assert activity_now.build_now(pg_conn, "u1")["failed_conversations"] == []


class TestOccurrences:
    """Counting a schedule's runs in a window, against one-at-a-time stepping."""

    START = datetime(2026, 5, 4, 8, tzinfo=timezone.utc)
    END = START + timedelta(hours=24)

    @staticmethod
    def _stepped(row: dict, start: datetime, end: datetime) -> int:
        from docsgpt.agents.scheduler_utils import next_cron_run

        # The dispatcher's rule: a run exactly at end_at still happens.
        end_at = row.get("end_at")
        fire = row["next_run_at"]
        if fire >= end:
            return 0
        if fire < start:
            fire = next_cron_run(row["cron"], row["timezone"], after=start - timedelta(seconds=1))
        count = 0
        while fire < end and (end_at is None or fire <= end_at) and count < activity_now.MAX_OCCURRENCES:
            count += 1
            fire = next_cron_run(row["cron"], row["timezone"], after=fire)
        return count

    @pytest.mark.parametrize(
        "next_run_at, cron, end_at",
        [
            (START + timedelta(minutes=30), "30 * * * *", None),  # due in the window
            (START - timedelta(minutes=30), "30 * * * *", None),  # overdue: counted from the start
            (START + timedelta(hours=2), "0 */3 * * *", START + timedelta(hours=10)),  # ends inside
            (START + timedelta(hours=2), "0 */3 * * *", START + timedelta(hours=11)),  # ends on a run
            (START + timedelta(hours=2), "0 */3 * * *", START + timedelta(hours=2)),  # ends on the first
            (START + timedelta(hours=1), "* * * * *", None),  # hits the cap
            (START + timedelta(hours=30), "0 * * * *", None),  # after the window
        ],
    )
    def test_matches_stepping(self, next_run_at, cron, end_at):
        row = {
            "trigger_type": "recurring", "cron": cron, "timezone": "Europe/Warsaw",
            "next_run_at": next_run_at, "end_at": end_at,
        }
        expected = self._stepped(row, self.START, self.END)
        assert activity_now._occurrences(row, self.START, self.END) == expected

    def test_a_bad_cron_counts_once(self):
        row = {
            "trigger_type": "recurring", "cron": "nope", "timezone": "UTC",
            "next_run_at": self.START + timedelta(hours=1), "end_at": None,
        }
        assert activity_now._occurrences(row, self.START, self.END) == 1
