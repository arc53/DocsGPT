"""Every usage row says what kind of run it came from and which workspace it was spent in.

Each run opens one billing context (``billed_to``) naming its payer, its kind and its team; the usage decorators
stamp ``token_usage.run_kind`` and ``token_usage.team_id`` from it. A call that runs as a team's principal in a run
that named no team is that team's spend.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from docsgpt.quotas.payer import RUN_KINDS, billed_to, current_run_billing, published_access_payer
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.usage import gen_token_usage
from docsgpt.workspaces.principal import principal_id

# Every module that opens a connection on the paths these tests drive.
_DB_TARGETS = (
    "docsgpt.quotas.service.db_readonly",
    "docsgpt.quotas.payer.db_readonly",
    "docsgpt.agents.headless_runner.db_readonly",
    "docsgpt.usage.db_session",
    "docsgpt.api.answer.routes.base.db_readonly",
)


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _yield():
        yield pg_conn

    for target in _DB_TARGETS:
        monkeypatch.setattr(target, _yield)
    return pg_conn


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "adam", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    return tid, principal_id(tid)


def _team_agent(conn, principal):
    return AgentsRepository(conn).create(
        principal, "Team bot", "published", key=f"k-{uuid.uuid4().hex[:8]}", access_payer_id="adam",
        created_by="adam", default_model_id="m", agent_type="classic",
    )


def _rows(conn):
    return [
        (row.user_id, row.run_kind, row.team_id)
        for row in conn.execute(text("SELECT user_id, run_kind, team_id::text AS team_id FROM token_usage ORDER BY id"))
    ]


class _RunsAsLLM:
    """An LLM built from some identity, as every agent, title, workflow and judge LLM is."""

    def __init__(self, sub, agent_id=None, key=None):
        self.decoded_token = {"sub": sub}
        self.user_api_key = key
        self.agent_id = agent_id
        self.token_usage = {"prompt_tokens": 0, "generated_tokens": 0}


@gen_token_usage
def _call(self, model, messages, stream, tools, **kwargs):
    return "an answer"


def _model_call(sub, agent_id=None, key=None):
    _call(_RunsAsLLM(sub, agent_id, key), "m", [{"role": "user", "content": "hi"}], False, None)


def _stream(decoded_token, agent_id=None, key=None, *, external=False, public_link=False, workspace_team_id=None,
            on_executor=None, side_llm_sub=None):
    """Drive ``complete_stream``'s wrapper the way ``/stream``, ``/api/answer`` and ``/v1`` do."""
    from docsgpt.api.answer.routes.base import _traced_stream

    class _Resource:
        @_traced_stream
        def complete_stream(self, question, agent, conversation_id, user_api_key, decoded_token,
                            agent_id=None, request_id=None, trace=None, _continuation=None, workspace_team_id=None):
            # The agent's LLM is built from the run's identity, as in a real turn.
            _model_call(decoded_token["sub"], agent_id, user_api_key)
            if side_llm_sub:
                # A side LLM (title, compression, a judge) built with another identity.
                _model_call(side_llm_sub)
            yield "data: done\n\n"

    agent = MagicMock(name="agent")
    agent.tool_executor.external_caller = external
    agent.tool_executor.public_link_caller = public_link
    agent.tool_executor.workspace_team_id = on_executor
    agent.decision_record = None
    list(_Resource().complete_stream("q", agent, None, key, decoded_token,
                                     agent_id=str(agent_id) if agent_id else None,
                                     workspace_team_id=workspace_team_id))


def _stub_runner(monkeypatch, agent_id, key):
    """Stub the agent: each run makes one model call under the identity it was built with (the agent's owner)."""
    from docsgpt.agents import headless_runner as hr

    def _create(*_args, **kwargs):
        agent = MagicMock(name="agent")
        agent.llm.token_usage = {}

        def _gen(query):
            _model_call(kwargs["decoded_token"]["sub"], agent_id, key)
            yield {"answer": "ok"}

        agent.gen.side_effect = _gen
        return agent

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr.RetrieverCreator, "create_retriever",
                        classmethod(lambda cls, *a, **kw: MagicMock(search=MagicMock(return_value=[]))))
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: MagicMock(headless_denials=[], cannot_complete=None))
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: _create(*a, **kw)))
    for target, value in (
        ("docsgpt.core.model_utils.validate_model_id", True),
        ("docsgpt.core.model_utils.get_provider_from_model_id", "openai"),
        ("docsgpt.core.model_utils.get_api_key_for_provider", "k"),
        ("docsgpt.utils.calculate_doc_token_budget", 1000),
    ):
        monkeypatch.setattr(target, MagicMock(return_value=value))


def _continue(monkeypatch, agent, conversation):
    from docsgpt.background import continuation

    _stub_runner(monkeypatch, agent["id"], agent["key"])
    monkeypatch.setattr(continuation, "db_readonly", MagicMock())
    monkeypatch.setattr(continuation, "_agent_config", lambda *a: agent)
    continuation._run_turn(conversation, [], [{"source": "job", "title": "done"}], message_id="m-1")


# ---------------------------------------------------------------------------
# The billing context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBillingContext:
    def test_the_run_kinds(self):
        assert RUN_KINDS == ("chat", "schedule", "published", "knowledge", "monitor", "drafter")

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ValueError, match="run kind"):
            with billed_to("eddie", kind="made_up"):
                pass

    def test_it_carries_kind_team_and_a_slot_for_limits(self):
        limits = object()
        with billed_to("eddie", "r-1", kind="chat", team_id="t-1", limits=limits) as run:
            assert current_run_billing() is run
        assert (run.payer, run.request_id, run.kind, run.team_id, run.limits) == ("eddie", "r-1", "chat", "t-1", limits)
        assert current_run_billing() is None

    def test_a_block_inside_a_run_of_the_same_payer_is_part_of_it(self):
        limits = object()
        with billed_to("eddie", kind="chat", team_id="t-1", limits=limits):
            with billed_to("eddie") as inner:
                assert (inner.kind, inner.team_id, inner.limits) == ("chat", "t-1", limits)

    def test_a_block_for_another_payer_starts_its_own_run(self):
        with billed_to("eddie", kind="chat", team_id="t-1", limits=object()):
            with billed_to("adam") as inner:
                assert (inner.kind, inner.team_id, inner.limits) == (None, None, None)


# ---------------------------------------------------------------------------
# Each run kind writes its kind and workspace
# ---------------------------------------------------------------------------


class TestChats:
    def test_a_chat_in_personal_is_a_personal_chat(self, db):
        _stream({"sub": "eddie"})

        assert _rows(db) == [("eddie", "chat", None)]

    def test_a_chat_in_a_team_without_an_agent_is_the_teams(self, db):
        team, _ = _team(db)

        _stream({"sub": "eddie"}, workspace_team_id=team)

        assert _rows(db) == [("eddie", "chat", team)]

    def test_a_resumed_chat_takes_its_workspace_from_the_executor(self, db):
        team, _ = _team(db)

        _stream({"sub": "eddie"}, on_executor=team)

        assert _rows(db) == [("eddie", "chat", team)]

    def test_a_members_chat_with_a_team_agent(self, db):
        team, principal = _team(db)
        agent = _team_agent(db, principal)

        _stream({"sub": "eddie"}, agent["id"], agent["key"], workspace_team_id=team)

        assert _rows(db) == [("eddie", "chat", team)]

    def test_a_side_llm_built_with_another_identity_bills_the_chatter(self, db):
        _stream({"sub": "eddie"}, side_llm_sub="lena")

        assert _rows(db) == [("eddie", "chat", None), ("eddie", "chat", None)]


class TestPublishedTraffic:
    def test_key_traffic_on_a_team_agent(self, db):
        team, principal = _team(db)
        agent = _team_agent(db, principal)

        _stream({"sub": principal}, agent["id"], agent["key"], external=True, workspace_team_id=team)

        assert _rows(db) == [("adam", "published", team)]

    def test_a_signed_in_public_link_caller_chatting_in_personal_is_the_agents_teams_traffic(self, db):
        team, principal = _team(db)
        agent = _team_agent(db, principal)

        _stream({"sub": "stranger"}, agent["id"], agent["key"], public_link=True)

        assert _rows(db) == [("adam", "published", team)]

    def test_key_traffic_on_a_personal_agent_is_personal(self, db):
        agent = AgentsRepository(db).create("lena", "Mine", "published", key=f"k-{uuid.uuid4().hex[:8]}",
                                            default_model_id="m", agent_type="classic")

        _stream({"sub": "lena"}, agent["id"], agent["key"], external=True)

        assert _rows(db) == [("lena", "published", None)]

    def test_a_webhook_run(self, db, monkeypatch):
        from docsgpt.agents.headless_runner import run_agent_headless

        team, principal = _team(db)
        agent = _team_agent(db, principal)
        _stub_runner(monkeypatch, agent["id"], agent["key"])

        run_agent_headless(agent, "{}", endpoint="webhook", payer=published_access_payer(agent))

        assert _rows(db) == [("adam", "published", team)]


class TestHeadlessRuns:
    def test_a_schedule(self, db, monkeypatch):
        from docsgpt.agents.headless_runner import run_agent_headless

        team, principal = _team(db)
        agent = _team_agent(db, principal)
        _stub_runner(monkeypatch, agent["id"], agent["key"])

        run_agent_headless(agent, "report", endpoint="schedule", payer="eddie")

        assert _rows(db) == [("eddie", "schedule", team)]

    def test_a_schedule_on_a_personal_agent_is_personal(self, db, monkeypatch):
        from docsgpt.agents.headless_runner import run_agent_headless

        agent = AgentsRepository(db).create("lena", "Mine", "published", key=f"k-{uuid.uuid4().hex[:8]}",
                                            default_model_id="m", agent_type="classic")
        _stub_runner(monkeypatch, agent["id"], agent["key"])

        run_agent_headless(agent, "report", endpoint="schedule", payer="lena")

        assert _rows(db) == [("lena", "schedule", None)]

    def test_a_continuation_of_a_members_chat(self, db, monkeypatch):
        team, principal = _team(db)
        agent = _team_agent(db, principal)

        _continue(monkeypatch, agent, {"id": str(uuid.uuid4()), "user_id": "eddie", "agent_id": str(agent["id"]),
                                       "team_id": team, "is_shared_usage": False})

        assert _rows(db) == [("eddie", "chat", team)]

    def test_a_continuation_of_key_traffic(self, db, monkeypatch):
        team, principal = _team(db)
        agent = _team_agent(db, principal)

        _continue(monkeypatch, agent, {"id": str(uuid.uuid4()), "user_id": principal,
                                       "agent_id": str(agent["id"]), "team_id": team, "is_shared_usage": False})

        assert _rows(db) == [("adam", "published", team)]

    def test_a_continuation_of_a_link_chat_is_published_traffic(self, db, monkeypatch):
        agent = AgentsRepository(db).create("lena", "Mine", "published", key=f"k-{uuid.uuid4().hex[:8]}",
                                            default_model_id="m", agent_type="classic")

        _continue(monkeypatch, agent, {"id": str(uuid.uuid4()), "user_id": "stranger",
                                       "agent_id": str(agent["id"]), "team_id": None, "is_shared_usage": True})

        assert _rows(db) == [("stranger", "published", None)]


class TestBackgroundJob:
    def test_the_job_keeps_its_runs_kind_and_workspace(self, db, monkeypatch):
        from docsgpt.background import celery_runner

        team, principal = _team(db)
        agent = _team_agent(db, principal)

        def _job(job_id, payload):
            _model_call(payload["user"], agent["id"], agent["key"])
            return {"state": "finished"}

        monkeypatch.setattr(celery_runner, "_run_job", _job)
        executor = MagicMock(user="eddie", user_api_key=None, agent_id=agent["id"], external_caller=False,
                             public_link_caller=False, api_write_allowlist=[], conversation_id="c", message_id="m")
        with billed_to("eddie", kind="chat", team_id=team):
            payload = celery_runner.worker_payload(executor, {"id": "t", "name": "x"}, "act", {})
        assert (payload["payer"], payload["run_kind"], payload["team_id"]) == ("eddie", "chat", team)

        celery_runner.run_job("j", payload)

        assert _rows(db) == [("eddie", "chat", team)]

    def test_a_payload_with_an_unknown_kind_still_runs(self, db, monkeypatch):
        from docsgpt.background import celery_runner

        monkeypatch.setattr(celery_runner, "_run_job", lambda job_id, payload: _model_call("eddie") or {})

        celery_runner.run_job("j", {"user": "eddie", "payer": "eddie", "run_kind": "made_up"})

        assert _rows(db) == [("eddie", None, None)]


class TestMonitorJudge:
    def test_the_judge_is_a_monitor_run_in_the_agents_team(self, db, monkeypatch):
        from contextlib import nullcontext

        from docsgpt.monitors import tick
        from docsgpt.quotas.service import QuotaService

        team, principal = _team(db)
        agent = _team_agent(db, principal)
        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, *a, **kw: None))

        def _judge(**kwargs):
            _model_call(kwargs["user_id"])
            return MagicMock(match=True, tokens=3)

        monkeypatch.setattr("docsgpt.monitors.judge.judge", _judge)
        monkeypatch.setattr(tick, "db_session", lambda: nullcontext(MagicMock()))
        monitor = {"id": "m-1", "user_id": "eddie", "agent_id": str(agent["id"]), "monitor_spec": {}}

        outcome, _ = tick._judge(monitor, MagicMock(), MagicMock())

        assert outcome == "match"
        assert _rows(db) == [("eddie", "monitor", team)]


class TestGraphExtraction:
    def test_building_a_team_sources_knowledge(self, db, monkeypatch):
        from docsgpt.graphrag import extraction

        team, principal = _team(db)
        monkeypatch.setattr(extraction, "_build_graph", lambda source_id, user, chunks, **kw: _model_call(user))

        extraction.extract_graph_for_source("s-1", principal, [], config=MagicMock(), payer="eddie")

        assert _rows(db) == [("eddie", "knowledge", team)]

    def test_building_a_personal_sources_knowledge(self, db, monkeypatch):
        from docsgpt.graphrag import extraction

        monkeypatch.setattr(extraction, "_build_graph", lambda source_id, user, chunks, **kw: _model_call(user))

        extraction.extract_graph_for_source("s-1", "lena", [], config=MagicMock())

        assert _rows(db) == [("lena", "knowledge", None)]


class TestDrafter:
    def _run(self, monkeypatch, team_id):
        from docsgpt.drafter import runner
        from docsgpt.drafter.recipe import DraftRequest

        class _Turn:
            calls = 1
            sent_chars = 0

            def __init__(self, req, *args, **kwargs):
                self.req = req

            def run(self, stop):
                _model_call(self.req.user_id)
                yield {"type": "message", "text": "ok"}

        monkeypatch.setattr(runner, "_Turn", _Turn)
        req = DraftRequest(user_id="eddie", recipe="agent", messages=[], context={}, request_id="drafter:1",
                           team_id=team_id)
        recipe = MagicMock(reads_workspace=False)
        ws = MagicMock()
        ws.summary.return_value = ""
        list(runner.run_draft(req, recipe, ws, {"id": "m"}, llm_factory=lambda *a: MagicMock()))

    def test_a_draft_in_a_team_workspace(self, db, monkeypatch):
        team, _ = _team(db)

        self._run(monkeypatch, team)

        assert _rows(db) == [("eddie", "drafter", team)]

    def test_a_draft_in_personal(self, db, monkeypatch):
        self._run(monkeypatch, None)

        assert _rows(db) == [("eddie", "drafter", None)]

    def test_the_request_records_its_workspace(self, monkeypatch):
        from flask import Flask

        from docsgpt.drafter import service

        team = str(uuid.uuid4())
        monkeypatch.setattr("docsgpt.workspaces.context.current_workspace",
                            lambda conn=None: MagicMock(is_team=True, team_id=team))
        with Flask(__name__).test_request_context("/"):
            assert service.request_team_id() == team

    def test_a_refused_workspace_reads_as_personal(self, monkeypatch):
        from flask import Flask

        from docsgpt.drafter import service
        from docsgpt.workspaces.context import WorkspaceError

        def _refused(conn=None):
            raise WorkspaceError(404, "workspace_not_found", "no")

        monkeypatch.setattr("docsgpt.workspaces.context.current_workspace", _refused)
        with Flask(__name__).test_request_context("/"):
            assert service.request_team_id() is None


# ---------------------------------------------------------------------------
# The principal fallback
# ---------------------------------------------------------------------------


class TestPrincipalFallback:
    def test_a_call_as_a_principal_outside_any_run_is_its_teams(self, db):
        team, principal = _team(db)
        agent = _team_agent(db, principal)

        _model_call(principal, agent["id"], agent["key"])

        # Never stored as the principal; the key keeps the agent's own limit counting.
        assert _rows(db) == [(None, None, team)]

    def test_a_run_that_named_no_team_falls_back_to_the_principals(self, db):
        team, principal = _team(db)
        agent = _team_agent(db, principal)

        with billed_to("adam", kind="published"):
            _model_call(principal, agent["id"], agent["key"])

        assert _rows(db) == [("adam", "published", team)]

    def test_a_run_that_named_a_team_keeps_it(self, db):
        team, principal = _team(db)
        other, _ = _team(db)
        agent = _team_agent(db, principal)

        with billed_to("adam", kind="published", team_id=other):
            _model_call(principal, agent["id"], agent["key"])

        assert _rows(db) == [("adam", "published", other)]


# ---------------------------------------------------------------------------
# Reading usage back
# ---------------------------------------------------------------------------

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 12, 1, tzinfo=timezone.utc)


def _use(conn, user_id="eddie", tokens=10, cost=0.0, when=NOW, **fields):
    TokenUsageRepository(conn).insert(user_id=user_id, prompt_tokens=tokens, cost=cost, timestamp=when, **fields)


def _agent_id(conn, name="A"):
    return str(AgentsRepository(conn).create("lena", name, "draft")["id"])


class TestUsageTotalsForBuckets:
    def test_one_query_sums_each_bucket(self, pg_conn):
        _use(pg_conn, tokens=10, cost=1.0)
        _use(pg_conn, tokens=20, cost=2.0, api_key="k")
        _use(pg_conn, tokens=40, cost=4.0, agent_id=_agent_id(pg_conn))
        _use(pg_conn, tokens=80, when=START - timedelta(days=1))
        _use(pg_conn, tokens=160, source="schedule")
        _use(pg_conn, user_id="lena", tokens=320)

        totals = TokenUsageRepository(pg_conn).usage_totals_for_buckets("eddie", START, ("all", "agent", "direct"))

        assert totals == {"all": (70, 7.0), "agent": (60, 6.0), "direct": (10, 1.0)}

    def test_it_agrees_with_usage_totals(self, pg_conn):
        _use(pg_conn, tokens=10, cost=1.0)
        _use(pg_conn, tokens=20, cost=2.0, api_key="k")
        repo = TokenUsageRepository(pg_conn)

        totals = repo.usage_totals_for_buckets("eddie", START, ("all", "agent"))

        assert totals["all"] == repo.usage_totals(user_id="eddie", start=START, bucket="all")
        assert totals["agent"] == repo.usage_totals(user_id="eddie", start=START, bucket="agent")

    def test_an_unknown_bucket_is_refused(self, pg_conn):
        with pytest.raises(ValueError):
            TokenUsageRepository(pg_conn).usage_totals_for_buckets("eddie", START, ("all", "x; DROP TABLE"))


class TestUsageByKind:
    def test_sums_each_kind_and_unattributed_rows_under_none(self, pg_conn):
        _use(pg_conn, tokens=10, cost=1.0, run_kind="chat")
        _use(pg_conn, tokens=20, run_kind="chat")
        _use(pg_conn, tokens=40, cost=4.0, run_kind="schedule")
        _use(pg_conn, tokens=80)
        _use(pg_conn, tokens=160, run_kind="chat", when=START - timedelta(days=1))
        _use(pg_conn, user_id="lena", tokens=320, run_kind="chat")

        assert TokenUsageRepository(pg_conn).usage_by_kind("eddie", START) == {
            "chat": (30, 1.0), "schedule": (40, 4.0), None: (80, 0.0),
        }


class TestTeamUsage:
    def test_the_teams_rows_only(self, pg_conn):
        team, other = str(uuid.uuid4()), str(uuid.uuid4())
        agent, gone = _agent_id(pg_conn, "Desk"), _agent_id(pg_conn, "Old")
        _use(pg_conn, tokens=10, cost=1.0, run_kind="chat", team_id=team)
        _use(pg_conn, tokens=20, cost=2.0, run_kind="drafter", team_id=team)
        _use(pg_conn, tokens=40, cost=4.0, run_kind="schedule", team_id=team, agent_id=agent, request_id="r1")
        _use(pg_conn, tokens=40, cost=4.0, run_kind="schedule", team_id=team, agent_id=agent, request_id="r1")
        _use(pg_conn, user_id="dana", tokens=5, cost=0.5, run_kind="published", team_id=team, agent_id=gone)
        # A key's row with nobody to bill counts but names no person.
        _use(pg_conn, user_id=None, api_key="k", tokens=1, team_id=team, agent_id=gone)
        # Personal, another team's, last month's and rollup rows never count.
        _use(pg_conn, tokens=1000, run_kind="chat")
        _use(pg_conn, tokens=1000, run_kind="chat", team_id=other)
        _use(pg_conn, tokens=1000, run_kind="chat", team_id=team, when=START - timedelta(days=1))
        _use(pg_conn, tokens=1000, run_kind="chat", team_id=team, source="schedule")

        report = TokenUsageRepository(pg_conn).team_usage(team, START, END)

        assert report["totals"] == {"tokens": 116, "cost": 11.5, "people": 2}
        assert report["split"] == {"chats": {"tokens": 30, "cost": 3.0}, "runs": {"tokens": 86, "cost": 8.5}}
        assert report["by_person"] == [
            {"user_id": "eddie", "tokens": 110, "cost": 11.0},
            {"user_id": "dana", "tokens": 5, "cost": 0.5},
        ]
        assert report["by_agent"] == [
            {"agent_id": agent, "tokens": 80, "cost": 8.0, "requests": 1, "people": 1},
            {"agent_id": gone, "tokens": 6, "cost": 0.5, "requests": 2, "people": 1},
        ]

    def test_the_lists_are_capped(self, pg_conn):
        team = str(uuid.uuid4())
        for n in range(3):
            _use(pg_conn, user_id=f"u{n}", tokens=10 + n, team_id=team)

        report = TokenUsageRepository(pg_conn).team_usage(team, START, END, limit=2)

        assert [p["user_id"] for p in report["by_person"]] == ["u2", "u1"]

    def test_a_malformed_team_id_reports_nothing(self, pg_conn):
        report = TokenUsageRepository(pg_conn).team_usage("not-a-team", START, END)

        assert report["totals"] == {"tokens": 0, "cost": 0.0, "people": 0} and report["by_person"] == []
