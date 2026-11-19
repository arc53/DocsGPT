"""A turn resolves who pays and what limits it runs under once, in its setup, and its stream carries that on.

The setup gate checks the turn's limits (the agent's own limit, then the payer's allowance) as soon as its caller and
agent are known, and resolves its billing: payer, run kind, workspace and the limits each model call is checked
against. The stream the setup starts runs under the same billing, so it reuses what the gate resolved instead of
reading the agent and the payer's policies again. The live checks before each model call are untouched.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask
from sqlalchemy import event

from docsgpt.quotas.payer import current_run_billing
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.principal import principal_id

# Every module that opens a connection while a turn's billing is resolved.
_DB_TARGETS = (
    "docsgpt.api.answer.routes.base.db_readonly",
    "docsgpt.quotas.payer.db_readonly",
    "docsgpt.quotas.service.db_readonly",
    "docsgpt.quotas.run_limits.db_readonly",
)


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _yield():
        yield pg_conn

    for target in _DB_TARGETS:
        monkeypatch.setattr(target, _yield)
    return pg_conn


@contextmanager
def _counting(conn):
    """Collect every statement ``conn`` runs inside the block."""
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(conn, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(conn, "before_cursor_execute", record)


def _reads(statements, table):
    return [s for s in statements if f"FROM {table}" in s]


def _resources():
    from docsgpt.api.answer.routes.answer import AnswerResource
    from docsgpt.api.answer.routes.stream import StreamResource
    from docsgpt.api.v1.routes import _V1AnswerHelper

    return {"/stream": StreamResource, "/api/answer": AnswerResource, "/v1": _V1AnswerHelper}


def _turn(resource_cls, *, sub, agent_id=None, key=None, external=False, team_id=None, carry=True):
    """Run a turn's setup gate, then start its stream the way each route does; returns both billings.

    The agent the setup builds carries what the gate resolved (``StreamProcessor.create_agent``).
    """
    from docsgpt.api.answer.routes.base import _traced_stream

    processor = SimpleNamespace(
        agent_config={"user_api_key": key, "external_api_caller": external},
        decoded_token={"sub": sub},
        agent_id=str(agent_id) if agent_id else None,
        workspace_team_id=team_id,
        request_id=str(uuid.uuid4()),
    )
    seen = {}
    with Flask(__name__).app_context():
        with resource_cls().setup_gate(processor) as setup_billing:
            seen["setup"] = setup_billing

    class _Resource:
        @_traced_stream
        def complete_stream(self, question, agent, conversation_id, user_api_key, decoded_token,
                            agent_id=None, request_id=None, trace=None, _continuation=None, workspace_team_id=None):
            seen["stream"] = current_run_billing()
            yield "data: done\n\n"

    agent = MagicMock(name="agent")
    agent.tool_executor.external_caller = external
    agent.tool_executor.workspace_team_id = team_id
    agent.decision_record = None
    agent.run_admission = getattr(processor, "run_admission", None) if carry else None
    list(_Resource().complete_stream(
        "q", agent, None, key, processor.decoded_token, agent_id=processor.agent_id,
        request_id=processor.request_id, workspace_team_id=team_id,
    ))
    return seen["setup"], seen["stream"]


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "adam", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    return tid, principal_id(tid)


def _summary(billing):
    limits = billing.limits
    return (
        billing.payer, billing.kind, billing.team_id,
        None if limits is None else (limits.payer, limits.outside, limits.limited),
    )


@pytest.mark.unit
class TestOneResolutionPerTurn:
    @pytest.mark.parametrize("route", ["/stream", "/api/answer", "/v1"])
    def test_a_members_chat_with_a_limited_team_agent(self, db, route):
        team, principal = _team(db)
        agent = AgentsRepository(db).create(
            principal, "Team bot", "published", key=f"k-{uuid.uuid4().hex[:8]}", access_payer_id="adam",
            limited_token_mode=True, token_limit=1000,
        )
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="eddie", token_limit=100)

        with _counting(db) as statements:
            setup, stream = _turn(_resources()[route], sub="eddie", agent_id=agent["id"], team_id=team)

        assert _summary(setup) == _summary(stream) == ("eddie", "chat", team, ("eddie", False, True))
        assert len(_reads(statements, "quota_policies")) == 1
        assert len(_reads(statements, "agents")) == 1

    @pytest.mark.parametrize("route", ["/stream", "/api/answer", "/v1"])
    def test_key_traffic_on_a_team_agent_bills_the_publisher(self, db, route):
        team, principal = _team(db)
        agent = AgentsRepository(db).create(
            principal, "Team bot", "published", key=f"k-{uuid.uuid4().hex[:8]}", access_payer_id="adam",
        )

        with _counting(db) as statements:
            setup, stream = _turn(
                _resources()[route], sub=principal, agent_id=agent["id"], key=agent["key"], external=True,
                team_id=team,
            )

        assert _summary(setup) == _summary(stream) == ("adam", "published", team, ("adam", True, False))
        assert len(_reads(statements, "quota_policies")) == 1
        assert len(_reads(statements, "agents")) == 1

    def test_a_signed_in_public_link_visitor_pays_for_their_own_chat(self, db):
        _team_id, principal = _team(db)
        agent = AgentsRepository(db).create(
            principal, "Team bot", "published", key=f"k-{uuid.uuid4().hex[:8]}", access_payer_id="adam",
        )

        with _counting(db) as statements:
            setup, stream = _turn(_resources()["/stream"], sub="stranger", agent_id=agent["id"], key=agent["key"])

        assert _summary(setup) == _summary(stream) == ("stranger", "chat", None, ("stranger", False, False))
        assert len(_reads(statements, "quota_policies")) == 1
        assert len(_reads(statements, "agents")) == 1

    def test_a_chat_without_an_agent(self, db):
        with _counting(db) as statements:
            setup, stream = _turn(_resources()["/stream"], sub="eddie")

        assert _summary(setup) == _summary(stream) == ("eddie", "chat", None, ("eddie", False, False))
        assert len(_reads(statements, "quota_policies")) == 1
        assert _reads(statements, "agents") == []


@pytest.mark.unit
class TestTheStreamStillResolvesWhatSetupDidNot:
    def test_a_stream_without_a_carried_billing_resolves_its_own(self, db):
        """A resumed turn's agent carries nothing: its stream resolves its billing as it always has."""
        team, principal = _team(db)
        agent = AgentsRepository(db).create(
            principal, "Team bot", "published", key=f"k-{uuid.uuid4().hex[:8]}", access_payer_id="adam",
        )

        setup, stream = _turn(
            _resources()["/stream"], sub=principal, agent_id=agent["id"], key=agent["key"], external=True,
            team_id=team, carry=False,
        )

        assert _summary(setup) == _summary(stream) == ("adam", "published", team, ("adam", True, False))

    def test_a_billing_resolved_for_other_inputs_is_not_reused(self, db):
        """The stream reuses the setup's billing only for the same caller, agent, key and workspace."""
        from docsgpt.api.answer.routes.base import _traced_stream

        processor = SimpleNamespace(
            agent_config={"user_api_key": None, "external_api_caller": False},
            decoded_token={"sub": "eddie"}, agent_id=None, workspace_team_id=None, request_id="r-1",
        )
        with Flask(__name__).app_context():
            with _resources()["/stream"]().setup_gate(processor):
                pass
        seen = {}

        class _Resource:
            @_traced_stream
            def complete_stream(self, question, agent, conversation_id, user_api_key, decoded_token,
                                agent_id=None, request_id=None, trace=None, workspace_team_id=None):
                seen["stream"] = current_run_billing()
                yield "data: done\n\n"

        agent = MagicMock(name="agent")
        agent.tool_executor.external_caller = False
        agent.tool_executor.workspace_team_id = None
        agent.decision_record = None
        agent.run_admission = processor.run_admission
        list(_Resource().complete_stream("q", agent, None, None, {"sub": "lena"}, request_id="r-1"))

        assert seen["stream"].payer == "lena"
        assert seen["stream"].limits.payer == "lena"

    def test_a_stop_reached_during_setup_is_checked_again_by_the_stream(self, db):
        """The stream gets the setup's resolved limits, not its stop: its first call checks usage itself."""
        from docsgpt.quotas.run_limits import RunLimitReached

        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="eddie", token_limit=100)
        processor = SimpleNamespace(
            agent_config={"user_api_key": None, "external_api_caller": False},
            decoded_token={"sub": "eddie"}, agent_id=None, workspace_team_id=None, request_id="r-1",
        )
        with Flask(__name__).app_context():
            with _resources()["/stream"]().setup_gate(processor) as billing:
                billing.limits.reached = RunLimitReached(MagicMock())

        stream_limits = processor.run_admission.stream_limits()

        assert stream_limits is not billing.limits
        assert stream_limits.reached is None
        assert stream_limits.limited is True


@pytest.mark.unit
class TestTheAgentCarriesIt:
    def test_the_agent_the_processor_creates_carries_the_setup_billing(self):
        from unittest.mock import patch

        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({}, {"sub": "u1"})
        processor.run_admission = admission = object()
        processor._get_prompt_content = MagicMock(return_value="prompt")
        processor.agent_config = {"agent_type": "classic", "prompt_id": "custom", "user_api_key": None}
        processor.model_id = "m1"
        processor.prompt_renderer = MagicMock()
        with (
            patch("docsgpt.api.answer.services.stream_processor.get_provider_from_model_id", return_value="openai"),
            patch("docsgpt.api.answer.services.stream_processor.get_api_key_for_provider", return_value="key"),
            patch("docsgpt.llm.llm_creator.LLMCreator.create_llm", return_value=MagicMock()),
            patch("docsgpt.llm.handlers.handler_creator.LLMHandlerCreator.create_handler", return_value=MagicMock()),
            patch("docsgpt.agents.agent_creator.AgentCreator.create_agent", return_value=MagicMock()),
            patch.object(StreamProcessor, "_enabled_tool_names", return_value=set()),
        ):
            agent = processor.create_agent()

        assert agent.run_admission is admission
