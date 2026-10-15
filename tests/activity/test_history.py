"""Tests for the Activity › History list against an ephemeral Postgres."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.activity import history
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agent(conn, name="Desk", workflow_id=None) -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO agents (user_id, name, status, workflow_id) "
                "VALUES ('u1', :n, 'published', CAST(:w AS uuid)) RETURNING id"
            ),
            {"n": name, "w": workflow_id},
        ).scalar()
    )


def _schedule_run(conn, status="success", minutes_ago=10, name="Daily digest", agent=None):
    schedule = SchedulesRepository(conn).create(
        "u1", agent, "recurring", "digest", cron="0 15 * * *", name=name,
    )
    runs = ScheduleRunsRepository(conn)
    when = _now() - timedelta(minutes=minutes_ago)
    run = runs.record_pending(str(schedule["id"]), "u1", agent, when)
    runs.update(
        str(run["id"]),
        {
            "status": status, "started_at": when, "finished_at": when + timedelta(seconds=11),
            "prompt_tokens": 100, "generated_tokens": 20,
        },
    )
    return run


def _trace(conn, source="webhook", status="ok", agent=None, workflow_run_id=None, minutes_ago=5):
    conn.execute(
        text(
            "INSERT INTO request_traces (id, user_id, agent_id, source, name, status, started_at, duration_ms, summary, "
            "workflow_run_id) VALUES (gen_random_uuid(), 'u1', CAST(:a AS uuid), :s, :s, :st, :t, 3100, CAST(:sum AS jsonb), "
            "CAST(:w AS uuid))"
        ),
        {
            "a": agent, "s": source, "st": status, "t": _now() - timedelta(minutes=minutes_ago),
            "sum": json.dumps({"input_tokens": 300, "output_tokens": 112}), "w": workflow_run_id,
        },
    )


def _workflow_run(conn, status="completed", minutes_ago=3):
    workflow = str(conn.execute(text("INSERT INTO workflows (user_id, name) VALUES ('u1', 'Renewal') RETURNING id")).scalar())
    agent = _agent(conn, "Renewal Desk", workflow_id=workflow)
    run = str(
        conn.execute(
            text(
                "INSERT INTO workflow_runs (workflow_id, user_id, status, started_at, ended_at) "
                "VALUES (CAST(:w AS uuid), 'u1', :st, :s, :e) RETURNING id"
            ),
            {"w": workflow, "st": status, "s": _now() - timedelta(minutes=minutes_ago, seconds=41),
             "e": _now() - timedelta(minutes=minutes_ago)},
        ).scalar()
    )
    return agent, run


class TestKinds:
    def test_lists_every_kind_newest_first(self, pg_conn):
        _schedule_run(pg_conn, minutes_ago=60)
        _trace(pg_conn, agent=_agent(pg_conn, "Onboarding"), minutes_ago=30)
        _workflow_run(pg_conn, minutes_ago=20)
        conv = str(ConversationsRepository(pg_conn).create("u1", "Halvorsen QBR")["id"])
        job, _ = BackgroundJobsRepository(pg_conn).create(
            user_id="u1", tool_name="code_executor", action_name="run", max_seconds=60, conversation_id=conv,
        )
        pg_conn.execute(
            text("UPDATE background_jobs SET status = 'cancelled', finished_at = :t WHERE id = CAST(:id AS uuid)"),
            {"t": _now() - timedelta(minutes=10), "id": str(job["id"])},
        )
        pg_conn.execute(
            text(
                "INSERT INTO conversation_wakes (user_id, conversation_id, source, title, status, delivered_at, dedupe_key) "
                "VALUES ('u1', CAST(:c AS uuid), 'monitor', 'Rotterdam congestion check woke the chat', 'delivered', :t, "
                "'monitor:1')"
            ),
            {"c": conv, "t": _now() - timedelta(minutes=1)},
        )
        page = history.list_history(pg_conn, "u1")
        assert [r["kind"] for r in page["runs"]] == ["monitor", "job", "workflow", "webhook", "schedule"]
        assert page["has_more"] is False
        by_kind = {r["kind"]: r for r in page["runs"]}
        assert by_kind["schedule"]["tokens"] == 120
        assert by_kind["schedule"]["duration_ms"] == 11000
        assert by_kind["webhook"]["tokens"] == 412
        assert by_kind["webhook"]["title"] == "Onboarding"
        assert by_kind["webhook"]["trace_id"]
        assert by_kind["workflow"]["title"] == "Renewal Desk"
        assert by_kind["job"]["status"] == "cancelled"
        assert by_kind["job"]["title"] == "Code Executor"
        assert by_kind["job"]["conversation_name"] == "Halvorsen QBR"

    def test_running_runs_and_other_users_are_left_out(self, pg_conn):
        schedule = SchedulesRepository(pg_conn).create("u1", None, "recurring", "x", cron="* * * * *")
        ScheduleRunsRepository(pg_conn).record_pending(str(schedule["id"]), "u1", None, _now())
        _trace(pg_conn, source="stream")
        other = SchedulesRepository(pg_conn).create("u2", None, "recurring", "y", cron="* * * * *")
        run = ScheduleRunsRepository(pg_conn).record_pending(str(other["id"]), "u2", None, _now())
        ScheduleRunsRepository(pg_conn).update(str(run["id"]), {"status": "success", "finished_at": _now()})
        assert history.list_history(pg_conn, "u1")["runs"] == []

    def test_a_monitor_without_a_title_takes_the_chats_name(self, pg_conn):
        # conversation_wakes.title is NOT NULL, defaulting to ''.
        conv = str(ConversationsRepository(pg_conn).create("u1", "Halvorsen QBR")["id"])
        pg_conn.execute(
            text(
                "INSERT INTO conversation_wakes (user_id, conversation_id, source, status, delivered_at, dedupe_key) "
                "VALUES ('u1', CAST(:c AS uuid), 'monitor', 'delivered', now(), 'monitor:1')"
            ),
            {"c": conv},
        )
        [run] = history.list_history(pg_conn, "u1")["runs"]
        assert run["title"] == "Halvorsen QBR"

    def test_a_workflow_run_of_a_webhook_is_listed_once(self, pg_conn):
        agent, run = _workflow_run(pg_conn)
        _trace(pg_conn, agent=agent, workflow_run_id=run)
        kinds = [r["kind"] for r in history.list_history(pg_conn, "u1")["runs"]]
        assert kinds == ["webhook"]

    def test_a_workflow_run_of_a_schedule_is_listed_once_without_its_trace(self, pg_conn):
        # Traces are purged sooner than History reaches back, or not
        # recorded at all; the run names the scheduled run that started it.
        agent, run = _workflow_run(pg_conn)
        scheduled = _schedule_run(pg_conn, agent=agent)
        pg_conn.execute(
            text("UPDATE workflow_runs SET inputs = jsonb_build_object('started_by', CAST(:s AS text)) WHERE id = CAST(:r AS uuid)"),
            {"s": str(scheduled["id"]), "r": run},
        )
        kinds = [r["kind"] for r in history.list_history(pg_conn, "u1")["runs"]]
        assert kinds == ["schedule"]

    def test_a_workflow_run_is_named_by_its_agent_and_never_another_users(self, pg_conn):
        # u2's workflow under a private agent and, newer, a shared one; u1 ran the shared one.
        workflow = str(
            pg_conn.execute(text("INSERT INTO workflows (user_id, name) VALUES ('u2', 'Renewal') RETURNING id")).scalar()
        )
        agents = {}
        for name, age in (("Private draft", "2 days"), ("Shared desk", "1 day")):
            agents[name] = str(
                pg_conn.execute(
                    text(
                        "INSERT INTO agents (user_id, name, status, workflow_id, created_at) "
                        "VALUES ('u2', :n, 'published', CAST(:w AS uuid), now() - CAST(:age AS interval)) "
                        "RETURNING id"
                    ),
                    {"n": name, "w": workflow, "age": age},
                ).scalar()
            )
        for inputs in ({"query": "q", "agent_id": agents["Shared desk"]}, None):
            pg_conn.execute(
                text(
                    "INSERT INTO workflow_runs (workflow_id, user_id, status, started_at, ended_at, inputs) "
                    "VALUES (CAST(:w AS uuid), 'u1', 'completed', now() - interval '5 minutes', "
                    "now() - interval '4 minutes', CAST(:i AS jsonb))"
                ),
                {"w": workflow, "i": json.dumps(inputs) if inputs else None},
            )
        runs = history.list_history(pg_conn, "u1", kind="workflow")["runs"]
        assert sorted((r["agent_id"] or "", r["title"]) for r in runs) == [
            ("", "Renewal"),
            (agents["Shared desk"], "Shared desk"),
        ]


class TestFilters:
    def test_by_kind_status_and_text(self, pg_conn):
        _schedule_run(pg_conn, status="success", name="Daily digest")
        _schedule_run(pg_conn, status="timeout", name="Inbox triage")
        _schedule_run(pg_conn, status="failed", name="Prospect news scan")
        _trace(pg_conn, status="error", agent=_agent(pg_conn, "Onboarding"))
        failed = history.list_history(pg_conn, "u1", status="failed")
        assert {r["title"] for r in failed["runs"]} == {"Inbox triage", "Prospect news scan", "Onboarding"}
        only = history.list_history(pg_conn, "u1", kind="schedule", status="failed")
        assert {r["title"] for r in only["runs"]} == {"Inbox triage", "Prospect news scan"}
        assert [r["title"] for r in history.list_history(pg_conn, "u1", query="DIGEST")["runs"]] == ["Daily digest"]

    def test_text_matches_literally(self, pg_conn):
        # A search box takes a substring: "_" and "%" are not wildcards.
        _schedule_run(pg_conn, name="q4_report")
        _schedule_run(pg_conn, name="q4-report")

        def titles(q: str) -> list:
            return [r["title"] for r in history.list_history(pg_conn, "u1", query=q)["runs"]]

        assert titles("q4_report") == ["q4_report"]
        assert titles("%") == []

    def test_a_job_is_found_by_the_name_it_is_shown_with(self, pg_conn):
        # Its title is the tool's id until it is labelled after the query.
        jobs = BackgroundJobsRepository(pg_conn)
        for tool in ("code_executor", "mcp_tool"):
            job, _ = jobs.create(user_id="u1", tool_name=tool, action_name="run", max_seconds=60)
            pg_conn.execute(
                text("UPDATE background_jobs SET status = 'completed', finished_at = now() WHERE id = CAST(:id AS uuid)"),
                {"id": str(job["id"])},
            )
        pg_conn.execute(
            text(
                "INSERT INTO user_tools (user_id, name, custom_name, display_name) "
                "VALUES ('u1', 'mcp_tool', 'Carrier Portal', 'MCP Server')"
            )
        )

        def titles(q: str) -> list:
            return [r["title"] for r in history.list_history(pg_conn, "u1", query=q)["runs"]]

        assert titles("code executor") == ["Code Executor"]
        assert titles("carrier") == ["Carrier Portal"]
        assert titles("mcp_tool") == []

    def test_pages(self, pg_conn):
        for i in range(5):
            _schedule_run(pg_conn, minutes_ago=i + 1, name=f"run {i}")
        first = history.list_history(pg_conn, "u1", limit=2)
        second = history.list_history(pg_conn, "u1", limit=2, offset=2)
        assert [r["title"] for r in first["runs"]] == ["run 0", "run 1"]
        assert first["has_more"] is True
        assert [r["title"] for r in second["runs"]] == ["run 2", "run 3"]

    def test_an_offset_past_bigint_is_an_empty_page(self, pg_conn):
        # Postgres rejects an OFFSET past int8, which answered 500.
        _schedule_run(pg_conn, minutes_ago=1)
        page = history.list_history(pg_conn, "u1", offset=10**20)
        assert page == {"runs": [], "has_more": False}

    def test_old_runs_are_outside_the_window(self, pg_conn):
        _schedule_run(pg_conn, minutes_ago=60 * 24 * 40)
        assert history.list_history(pg_conn, "u1")["runs"] == []
        assert len(history.list_history(pg_conn, "u1", days=60)["runs"]) == 1

    @pytest.mark.parametrize("kwargs", [{"kind": "chat"}, {"status": "running"}])
    def test_rejects_unknown_filters(self, pg_conn, kwargs):
        with pytest.raises(ValueError):
            history.list_history(pg_conn, "u1", **kwargs)
