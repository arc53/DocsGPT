"""The in-run check: every model call of a run is checked against its payer's allowance and its agent's limit.

A run resolves its limits once, when it starts (``RunLimits.start``), and opens them with its billing. Each model
call then checks them first (``BaseLLM._execute_with_fallback``), so a tool loop stops at the limit: the call that
crosses it completes and the next one is refused with ``RunLimitReached``, which escapes provider fallback and tool
error recovery. The check costs no query while nothing is limited, allows the call when the database fails, and
refuses a team principal as payer before anything is spent.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, List

import pytest

from docsgpt import tracing
from docsgpt.core.run_budget import is_budget_exhausted
from docsgpt.llm.base import BaseLLM
from docsgpt.quotas.agent_limits import AgentLimitExceeded
from docsgpt.quotas.payer import billed_to, current_run_billing
from docsgpt.quotas.run_limits import RunLimitReached, RunLimits
from docsgpt.quotas.service import NoPayerError, QuotaExceeded, QuotaExceededError
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.workspaces.principal import principal_id

MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.fixture
def db(pg_conn, monkeypatch):
    """Every connection the run limits and the usage decorators open is the test's own."""
    opened: List[str] = []

    @contextmanager
    def _readonly():
        opened.append("read")
        yield pg_conn

    @contextmanager
    def _session():
        yield pg_conn

    monkeypatch.setattr("docsgpt.quotas.run_limits.db_readonly", _readonly)
    monkeypatch.setattr("docsgpt.usage.db_session", _session)
    monkeypatch.setattr("docsgpt.quotas.run_limits.settings.QUOTA_PERIOD", "month")
    pg_conn.opened = opened
    return pg_conn


class _StubLLM(BaseLLM):
    """A model whose every call reports ``tokens`` prompt tokens, as a provider's usage does."""

    def __init__(self, tokens: int = 60, payer: str = "dana", **kwargs: Any) -> None:
        super().__init__(decoded_token={"sub": payer}, **kwargs)
        self.tokens = tokens
        self.calls = 0

    def _raw_gen(self, baseself, model, messages, stream, tools=None, **kwargs):
        self.calls += 1
        self._last_usage = {"prompt_tokens": self.tokens, "completion_tokens": 0}
        self._last_usage_claimed = False
        return "an answer"

    def _raw_gen_stream(self, baseself, model, messages, stream, tools=None, **kwargs):
        self.calls += 1
        self._last_usage = {"prompt_tokens": self.tokens, "completion_tokens": 0}
        self._last_usage_claimed = False
        yield "an answer"


def _limit(conn, user_id="dana", tokens=100, bucket="all"):
    QuotaPoliciesRepository(conn).upsert(scope="user", subject_id=user_id, bucket=bucket, token_limit=tokens)


def _spend(conn, user_id="dana", tokens=100, **fields):
    TokenUsageRepository(conn).insert(user_id=user_id, prompt_tokens=tokens, **fields)


def _tool_loop(llm: _StubLLM, rounds: int) -> int:
    """A tool loop: one model call per round until the model is refused; returns the rounds that ran."""
    done = 0
    for _ in range(rounds):
        llm.gen(model="m", messages=MESSAGES)
        done += 1
    return done


class TestTheToolLoopStops:
    def test_the_call_that_crosses_completes_and_the_next_is_refused(self, db):
        _limit(db, tokens=100)
        llm = _StubLLM(tokens=60)
        limits = RunLimits.start("dana", bucket="direct")

        with billed_to("dana", kind="chat", limits=limits):
            with pytest.raises(RunLimitReached) as caught:
                _tool_loop(llm, rounds=5)

        # Call one (0 -> 60) and call two (60 -> 120, the crossing call) ran; the third never reached the provider.
        assert llm.calls == 2
        stop = caught.value
        assert isinstance(stop.exceeded, QuotaExceeded)
        assert (stop.exceeded.budget, stop.exceeded.usage, stop.exceeded.limit) == ("tokens", 120, 100)
        assert stop.error_type == "payer_out_of_allowance"
        assert limits.reached is stop
        # A quota refusal, so every headless caller already stops on it; and it escapes recovery.
        assert isinstance(stop, QuotaExceededError)
        assert is_budget_exhausted(stop)

    def test_a_stream_is_checked_too(self, db):
        _limit(db, tokens=10)
        _spend(db, tokens=10)
        llm = _StubLLM()
        with billed_to("dana", kind="chat", limits=RunLimits.start("dana", bucket="direct")):
            with pytest.raises(RunLimitReached):
                list(llm.gen_stream(model="m", messages=MESSAGES))
        assert llm.calls == 0

    def test_the_request_bucket_counts(self, db):
        _limit(db, tokens=50, bucket="agent")
        _spend(db, tokens=50, api_key="k-any")
        limits = RunLimits.start("dana", bucket="agent")
        with pytest.raises(RunLimitReached) as caught:
            limits.check_call()
        assert caught.value.exceeded.bucket == "agent"
        # The same spend does not count against a direct chat's bucket.
        RunLimits.start("dana", bucket="direct").check_call()

    def test_a_run_with_no_limits_runs_on(self, db):
        llm = _StubLLM(tokens=10_000)
        with billed_to("dana", kind="chat", limits=RunLimits.start("dana", bucket="direct")):
            assert _tool_loop(llm, rounds=4) == 4

    def test_a_call_outside_any_run_is_not_checked(self, db):
        _limit(db, tokens=1)
        _spend(db, tokens=5)
        assert _StubLLM().gen(model="m", messages=MESSAGES) == "an answer"


class TestTheAgentLimit:
    def _agent(self, conn, token_limit=100, **fields):
        return AgentsRepository(conn).create(
            "owner", "Bot", "published", key=f"k-{uuid.uuid4().hex[:8]}", limited_token_mode=True,
            token_limit=token_limit, **fields,
        )

    def test_the_agent_limit_is_checked_first_and_named(self, db):
        agent = self._agent(db, token_limit=100)
        _limit(db, tokens=100)
        _spend(db, tokens=150, agent_id=str(agent["id"]))
        limits = RunLimits.start("dana", bucket="agent", agent=agent)

        with pytest.raises(RunLimitReached) as caught:
            limits.check_call()

        assert isinstance(caught.value.exceeded, AgentLimitExceeded)
        assert caught.value.error_type == "budget_exceeded"
        assert (caught.value.exceeded.dimension, caught.value.exceeded.usage) == ("tokens", 150)
        assert "agent's token limit" in str(caught.value)

    def test_the_agent_row_is_read_by_id_or_key(self, db):
        agent = self._agent(db, token_limit=100)
        # Spend reached through its key counts as the agent's.
        _spend(db, user_id="someone", tokens=100, api_key=agent["key"])
        with pytest.raises(RunLimitReached):
            RunLimits.start("dana", bucket="agent", agent_id=str(agent["id"])).check_call()
        with pytest.raises(RunLimitReached):
            RunLimits.start("dana", bucket="agent", api_key=agent["key"]).check_call()

    def test_the_request_limit_never_stops_a_run_it_let_start(self, db):
        """A run is one request: the run that crosses the request limit completes."""
        agent = AgentsRepository(db).create(
            "owner", "Bot", "published", key=f"k-{uuid.uuid4().hex[:8]}", limited_request_mode=True,
            request_limit=1,
        )
        _spend(db, tokens=5, agent_id=str(agent["id"]), request_id="this-run")
        RunLimits.start("dana", bucket="agent", agent=agent).check_call()


class TestCost:
    def test_no_query_while_nothing_is_limited(self, db):
        agent = AgentsRepository(db).create("owner", "Bot", "published", key="k-free")
        limits = RunLimits.start("dana", bucket="agent", agent=agent)
        db.opened.clear()

        for _ in range(5):
            limits.check_call()

        assert db.opened == []

    def test_one_read_per_call_while_limited(self, db):
        _limit(db, tokens=1_000)
        limits = RunLimits.start("dana", bucket="direct")
        db.opened.clear()
        limits.check_call()
        limits.check_call()
        assert len(db.opened) == 2


class TestFailing:
    def test_a_database_error_inside_the_check_allows_the_call(self, db, monkeypatch, caplog):
        _limit(db, tokens=10)
        _spend(db, tokens=50)
        limits = RunLimits.start("dana", bucket="direct")

        def _broken(*_args, **_kwargs):
            raise RuntimeError("the database went away")

        monkeypatch.setattr(TokenUsageRepository, "usage_totals_for_buckets", _broken)
        with caplog.at_level("ERROR"):
            limits.check_call()

        assert limits.reached is None
        assert "allowing the call" in caplog.text

    def test_a_database_error_at_start_checks_nothing(self, db, monkeypatch):
        def _broken(*_args, **_kwargs):
            raise RuntimeError("the database went away")

        monkeypatch.setattr(QuotaPoliciesRepository, "policies_for_user", _broken)
        limits = RunLimits.start("dana", bucket="direct")
        db.opened.clear()
        limits.check_call()
        assert db.opened == []

    def test_a_principal_payer_fails_closed_at_start(self, db):
        team = TeamsRepository(db).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
        db.opened.clear()

        with pytest.raises(NoPayerError):
            RunLimits.start(principal_id(str(team["id"])), bucket="agent")

        # Refused before any lookup: nothing to fail open on.
        assert db.opened == []

    def test_no_payer_checks_nothing(self, db):
        assert RunLimits.start(None, bucket="direct") is None


class TestRecoveryLetsItThrough:
    def test_fallback_is_not_tried_after_a_stop(self, db):
        _limit(db, tokens=10)
        _spend(db, tokens=10)
        primary = _StubLLM()
        backup = _StubLLM()
        primary._fallback_llm = backup

        with billed_to("dana", kind="chat", limits=RunLimits.start("dana", bucket="direct")):
            with pytest.raises(RunLimitReached):
                primary.gen(model="m", messages=MESSAGES)
            with pytest.raises(RunLimitReached):
                list(primary.gen_stream(model="m", messages=MESSAGES))

        assert (primary.calls, backup.calls) == (0, 0)

    def test_a_stopped_run_stays_stopped_without_another_query(self, db):
        _limit(db, tokens=10)
        _spend(db, tokens=10)
        limits = RunLimits.start("dana", bucket="direct")
        with pytest.raises(RunLimitReached):
            limits.check_call()
        db.opened.clear()
        with pytest.raises(RunLimitReached):
            limits.check_call()
        assert db.opened == []

    def test_a_sub_agent_or_judge_inside_the_run_is_checked(self, db):
        """A nested block naming no kind (a sub-agent, a guardrail judge) keeps the run's limits."""
        _limit(db, tokens=10)
        _spend(db, tokens=10)
        with billed_to("dana", kind="schedule", limits=RunLimits.start("dana", bucket="agent")):
            with billed_to("dana"):
                assert current_run_billing().limits is not None
                with pytest.raises(RunLimitReached):
                    _StubLLM().gen(model="m", messages=MESSAGES)

    def test_a_call_in_a_thread_the_run_hands_work_to_is_checked(self, db):
        _limit(db, tokens=10)
        _spend(db, tokens=10)
        llm = _StubLLM()
        with billed_to("dana", kind="chat", limits=RunLimits.start("dana", bucket="direct")):
            call = tracing.wrap(lambda: llm.gen(model="m", messages=MESSAGES))
            with ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(RunLimitReached):
                    pool.submit(call).result()
        assert llm.calls == 0


class TestAWorkflowStep:
    def test_a_workflow_step_is_checked_and_the_run_stops(self, db, monkeypatch):
        from docsgpt.agents.workflows.node_agent import WorkflowNodeAgentFactory
        from docsgpt.agents.workflows.schemas import NodeType, Workflow, WorkflowEdge, WorkflowGraph, WorkflowNode
        from docsgpt.agents.workflows.workflow_engine import WorkflowEngine

        monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _p: "k")
        _limit(db, tokens=100)

        class _NodeAgent:
            def __init__(self):
                self.llm = _StubLLM(tokens=150)
                self.tool_executor = SimpleNamespace(cannot_complete=None)
                self.attachments: List[Any] = []

            def gen(self, _prompt):
                yield {"answer": self.llm.gen(model="m", messages=MESSAGES)}

        nodes_run = [_NodeAgent(), _NodeAgent()]
        pending = list(nodes_run)
        monkeypatch.setattr(WorkflowNodeAgentFactory, "create", staticmethod(lambda **kwargs: pending.pop(0)))

        def _node(node_id, node_type, **config):
            return WorkflowNode(id=node_id, workflow_id="wf", type=node_type, title=node_id, config=config)

        nodes = [
            _node("start", NodeType.START),
            _node("fetch", NodeType.AGENT, stream_to_user=False),
            _node("summarize", NodeType.AGENT, stream_to_user=False),
            _node("end", NodeType.END),
        ]
        edges = [
            WorkflowEdge(id=f"e{i}", workflow_id="wf", source=a.id, target=b.id)
            for i, (a, b) in enumerate(zip(nodes, nodes[1:]))
        ]
        run_agent = SimpleNamespace(
            endpoint="schedule", llm_name="openai", model_id="m", api_key="k", chat_history=[],
            decoded_token={"sub": "dana"}, cannot_complete=None, llm=_StubLLM(),
        )
        graph = WorkflowGraph(workflow=Workflow(name="Nightly"), nodes=nodes, edges=edges)
        engine = WorkflowEngine(graph, run_agent, workflow_run_id="44444444-4444-4444-4444-444444444444")
        limits = RunLimits.start("dana", bucket="agent")

        with billed_to("dana", kind="schedule", limits=limits):
            events = list(engine.execute({}, "go"))

        # The first step crossed the limit; the second step's call was refused before the provider.
        assert (nodes_run[0].llm.calls, nodes_run[1].llm.calls) == (1, 0)
        assert any(event.get("type") == "error" for event in events)
        assert isinstance(limits.reached, RunLimitReached)


class TestEntryPointsOpenLimits:
    def test_a_background_job_is_checked_against_the_runs_payer(self, db, monkeypatch):
        from docsgpt.background import celery_runner

        _limit(db, user_id="dana", tokens=10)
        _spend(db, user_id="dana", tokens=10)
        seen = {}

        def _body(job_id, payload):
            billing = current_run_billing()
            seen["billing"] = billing
            with pytest.raises(RunLimitReached):
                billing.limits.check_call()
            return {"state": "done"}

        monkeypatch.setattr(celery_runner, "_run_job", _body)
        celery_runner.run_job(
            "job-1",
            {"user": "owner", "payer": "dana", "run_kind": "chat", "team_id": None, "agent_id": None,
             "user_api_key": None},
        )

        assert seen["billing"].payer == "dana"
        assert seen["billing"].limits.payer == "dana"

    def test_a_background_job_of_an_agent_checks_its_limit(self, db, monkeypatch):
        from docsgpt.background import celery_runner

        agent = AgentsRepository(db).create(
            "owner", "Bot", "published", key="k-job", limited_token_mode=True, token_limit=5,
        )
        _spend(db, user_id="someone", tokens=5, agent_id=str(agent["id"]))
        seen = {}

        def _body(job_id, payload):
            with pytest.raises(RunLimitReached) as caught:
                current_run_billing().limits.check_call()
            seen["stop"] = caught.value
            return {"state": "done"}

        monkeypatch.setattr(celery_runner, "_run_job", _body)
        celery_runner.run_job(
            "job-2",
            {"user": "owner", "payer": "dana", "run_kind": "chat", "agent_id": str(agent["id"]),
             "user_api_key": "k-job"},
        )
        assert seen["stop"].error_type == "budget_exceeded"

    def test_a_background_job_whose_payer_is_a_principal_never_runs(self, db, monkeypatch):
        from docsgpt.background import celery_runner

        team = TeamsRepository(db).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
        body = []
        finalized = []
        monkeypatch.setattr(celery_runner, "_run_job", lambda job_id, payload: body.append(job_id))
        monkeypatch.setattr(celery_runner.jobs, "finalize", lambda job_id, **kw: finalized.append((job_id, kw)))

        result = celery_runner.run_job("job-3", {"user": "owner", "payer": principal_id(str(team["id"]))})

        assert result == {"state": "no_payer"}
        assert body == []
        assert finalized[0][1]["status"] == "failed"

    def test_the_monitor_judge_runs_under_limits(self, db, monkeypatch):
        from docsgpt.monitors import judge, tick
        from docsgpt.quotas.service import QuotaService

        monkeypatch.setattr(QuotaService, "check", classmethod(lambda cls, *a, **kw: None))
        _limit(db, user_id="dana", tokens=10)
        _spend(db, user_id="dana", tokens=10)

        def _judge(**_kwargs):
            # The judge's own model call is refused, which the judge reports as a failed call.
            try:
                current_run_billing().limits.check_call()
            except RunLimitReached as exc:
                raise judge.JudgeError(f"the judge call failed ({type(exc).__name__})") from None
            raise AssertionError("the judge's call was not checked")

        monkeypatch.setattr(judge, "judge", _judge)
        monitor = {"id": str(uuid.uuid4()), "user_id": "dana", "agent_id": None, "monitor_spec": {}}

        outcome, _ = tick._judge(monitor, SimpleNamespace(summary="s"), SimpleNamespace(text="t"))

        # Reported as the payer's quota, not as a judge error.
        assert outcome == "quota"

    def test_graph_extraction_runs_under_limits(self, db, monkeypatch):
        from docsgpt.graphrag import extraction

        seen = {}

        def _build(source_id, user, chunks, **kwargs):
            seen["billing"] = current_run_billing()
            return {}

        monkeypatch.setattr(extraction, "_build_graph", _build)
        extraction.extract_graph_for_source("src", "owner", [], config=None, payer="dana")

        assert seen["billing"].kind == "knowledge"
        assert seen["billing"].limits is not None and seen["billing"].limits.payer == "dana"

    def test_graph_extraction_with_no_payer_checks_nothing(self, db, monkeypatch):
        from docsgpt.graphrag import extraction

        seen = {}
        monkeypatch.setattr(
            extraction, "_build_graph", lambda *a, **kw: seen.setdefault("billing", current_run_billing()) and {}
        )
        extraction.extract_graph_for_source("src", "owner", [], config=None)
        assert seen["billing"].limits is None
