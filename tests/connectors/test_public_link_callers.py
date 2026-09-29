"""Someone reaching an agent only through its public link can't approve for the owner.

A signed-in stranger with the link runs the agent like a teammate, but a
write on the owner's connected account (a tool in owner mode) is refused
unless the owner allowlisted it, exactly as for an API-key caller. Their own
account (member mode) stays theirs to approve, and teammates keep the card.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from docsgpt.security.encryption import encrypt_json

ACTION = "telegram_send_message"


@contextmanager
def _db(conn, *modules):
    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        stack.enter_context(patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield))
        stack.enter_context(patch.multiple("docsgpt.connectors.resolve", db_readonly=_yield))
        for module in modules:
            stack.enter_context(patch.multiple(module, db_session=_yield, db_readonly=_yield))
        yield


def _connection(conn, user: str) -> str:
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, "
            "account_label, encrypted_credentials) VALUES (:u, 'telegram', 'telegram', 'api_key', "
            "'connected', :u, :e) RETURNING id"
        ),
        {"u": user, "e": encrypt_json({"credentials": {"token": f"{user}-token"}}, user)},
    ).scalar())


def _tool(connection_id: str, mode: str = "owner") -> dict:
    return {
        "id": "tool-1", "user_id": "alice", "name": "telegram", "config": {},
        "actions": [{"name": ACTION, "active": True, "require_approval": False}],
        "connection_id": connection_id, "credential_mode": mode,
    }


def _pause(executor, tool, action=ACTION):
    call = SimpleNamespace(id="call-1", name=action, arguments="{}", thought_signature=None)
    with patch("docsgpt.agents.tool_executor.ToolActionParser") as parser:
        parser.return_value.parse_args.return_value = ("t1", action, {})
        return executor.check_pause({"t1": tool}, call, "OpenAILLM")


def _executor(public: bool, allowlist=None):
    from docsgpt.agents.tool_executor import ToolExecutor

    return ToolExecutor(user="bob", public_link_caller=public, api_write_allowlist=allowlist)


class TestWritesOnTheOwnersAccount:
    def test_public_link_write_is_refused_without_a_card(self, pg_conn):
        cid = _connection(pg_conn, "alice")
        with _db(pg_conn):
            pause = _pause(_executor(public=True), _tool(cid))
        assert pause["pause_type"] == "headless_denied"
        assert pause["error_type"] == "tool_not_allowed"
        assert "public link" in pause["deny_reason"]
        assert "Access details" in pause["deny_reason"]

    def test_allowlisted_write_runs(self, pg_conn):
        cid = _connection(pg_conn, "alice")
        with _db(pg_conn):
            assert _pause(_executor(public=True, allowlist=[f"tool-1:{ACTION}"]), _tool(cid)) is None

    def test_allowlist_covers_only_its_action(self, pg_conn):
        cid = _connection(pg_conn, "alice")
        with _db(pg_conn):
            pause = _pause(_executor(public=True, allowlist=["tool-1:telegram_send_image"]), _tool(cid))
        assert pause["pause_type"] == "headless_denied"

    def test_teammate_keeps_the_approval_card(self, pg_conn):
        cid = _connection(pg_conn, "alice")
        with _db(pg_conn):
            pause = _pause(_executor(public=False), _tool(cid))
        assert pause["pause_type"] == "awaiting_approval"

    def test_own_account_in_member_mode_is_not_refused(self, pg_conn):
        cid = _connection(pg_conn, "alice")
        _connection(pg_conn, "bob")
        with _db(pg_conn):
            assert _pause(_executor(public=True), _tool(cid, mode="member")) is None


def _team_grant(conn, agent_id: str, owner: str, member: str) -> None:
    from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
    from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
    from docsgpt.storage.db.repositories.teams import TeamsRepository

    team = TeamsRepository(conn).create("T", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), "agent", agent_id, owner, owner, access_level="viewer", target_user_id=member,
    )


class TestPublicLinkDetection:
    SP = "docsgpt.api.answer.services.stream_processor"

    def _agent(self, conn, shared=True) -> str:
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        return str(AgentsRepository(conn).create(
            "alice", "A", "published", key=f"k-{uuid.uuid4().hex}", shared=shared,
        )["id"])

    def _run(self, conn, agent_id: str, caller: str):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({"agent_id": agent_id}, {"sub": caller})
        with _db(conn, self.SP):
            processor._configure_agent()
        return processor

    @pytest.mark.parametrize(("caller", "public"), [("alice", False), ("stranger", True)])
    def test_only_a_link_user_is_a_public_caller(self, pg_conn, caller, public):
        processor = self._run(pg_conn, self._agent(pg_conn), caller)
        assert processor.agent_config["public_link_caller"] is public

    def test_teammate_of_a_public_agent_is_not_a_link_user(self, pg_conn):
        agent_id = self._agent(pg_conn)
        _team_grant(pg_conn, agent_id, "alice", "bob")
        processor = self._run(pg_conn, agent_id, "bob")
        assert processor.is_shared_usage is True
        assert processor.agent_config["public_link_caller"] is False

    def test_run_executor_carries_the_flag(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({}, {"sub": "stranger"})
        processor.agent_config = {
            "agent_type": "classic", "prompt_id": "default", "user_api_key": "k",
            "public_link_caller": True, "api_write_allowlist": [f"tool-1:{ACTION}"],
        }
        processor._get_prompt_content = MagicMock(return_value="p")
        processor.prompt_renderer = MagicMock(render_prompt=MagicMock(return_value="p"))
        processor._enabled_tool_names = MagicMock(return_value=set())
        processor.model_id = "m1"
        with patch(f"{self.SP}.get_provider_from_model_id", return_value="openai"), \
                patch(f"{self.SP}.get_api_key_for_provider", return_value="key"), \
                patch("docsgpt.llm.llm_creator.LLMCreator.create_llm", return_value=MagicMock()), \
                patch("docsgpt.llm.handlers.handler_creator.LLMHandlerCreator.create_handler"), \
                patch("docsgpt.agents.agent_creator.AgentCreator.create_agent") as create:
            processor.create_agent()
        executor = create.call_args.kwargs["tool_executor"]
        assert executor.public_link_caller is True
        assert executor.api_write_allowlist == {f"tool-1:{ACTION}"}

    def test_resumed_run_stays_a_public_caller(self, monkeypatch):
        from docsgpt.agents import agent_creator as ac_mod
        from docsgpt.api.answer.services import continuation_service as cont_mod
        from docsgpt.api.answer.services.stream_processor import StreamProcessor
        from docsgpt.llm import llm_creator as llm_creator_mod
        from docsgpt.llm.handlers import handler_creator as handler_mod

        cont_service = MagicMock()
        cont_service.claim_state.return_value = {
            "messages": [], "pending_tool_calls": [], "tools_dict": {}, "tool_schemas": [],
            "client_tools": None,
            "agent_config": {"model_id": "m1", "llm_name": "openai", "api_key": "k", "user_api_key": "uk",
                             "agent_type": "ClassicAgent", "public_link_caller": True},
        }
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
        created = {}
        monkeypatch.setattr(
            ac_mod.AgentCreator, "create_agent", lambda *a, **kw: created.update(kw) or MagicMock(),
        )
        processor = StreamProcessor({}, {"sub": "stranger"})
        processor.resume_from_tool_actions(tool_actions=[], conversation_id=str(uuid.uuid4()))
        assert created["tool_executor"].public_link_caller is True


class TestWorkflowNodes:
    """A node's tools follow the same caller rules as the run that started it."""

    def test_node_executor_inherits_the_run_policy(self, monkeypatch):
        from docsgpt.agents.tool_executor import ToolExecutor
        from docsgpt.agents.workflows.node_agent import WorkflowNodeAgentFactory, _WorkflowNodeMixin
        from docsgpt.agents.workflows.schemas import NodeType, Workflow, WorkflowGraph, WorkflowNode
        from docsgpt.agents.workflows.workflow_engine import WorkflowEngine

        class _Base:
            def __init__(self, decoded_token=None, **_kwargs):
                self.tool_executor = ToolExecutor(user=(decoded_token or {}).get("sub"))

        class _NodeAgent(_WorkflowNodeMixin, _Base):
            def gen(self, _prompt):
                yield {"answer": "ok"}

        built = []
        monkeypatch.setattr(
            WorkflowNodeAgentFactory, "create",
            staticmethod(lambda agent_type, **kw: built.append(_NodeAgent(**kw)) or built[-1]),
        )
        monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _name: None)
        run_executor = ToolExecutor(
            user="stranger", headless=True, tool_allowlist=["t9"], external_caller=True,
            public_link_caller=True, api_write_allowlist=[f"tool-1:{ACTION}"],
        )
        agent = SimpleNamespace(
            endpoint="stream", llm_name="openai", model_id="gpt-4o-mini", api_key="k", chat_history=[],
            decoded_token={"sub": "stranger"}, user="stranger", _resolve_owner_id=lambda: "alice",
            tool_executor=run_executor,
        )
        engine = WorkflowEngine(WorkflowGraph(workflow=Workflow(name="wf"), nodes=[], edges=[]), agent)
        engine.state["query"] = "q"
        node = WorkflowNode(
            id="a1", workflow_id="wf", type=NodeType.AGENT, title="A", position={"x": 0, "y": 0},
            config={"agent_type": "classic", "system_prompt": "s", "tools": []},
        )
        list(engine._execute_agent_node(node))

        node_executor = built[0].tool_executor
        assert node_executor.headless is True
        assert node_executor.tool_allowlist == {"t9"}
        assert node_executor.external_caller is True
        assert node_executor.public_link_caller is True
        assert node_executor.api_write_allowlist == {f"tool-1:{ACTION}"}


def _stored_tool(name: str, action: dict, config: dict) -> dict:
    return {"id": "tool-9", "user_id": "alice", "name": name, "config": config, "actions": [action]}


def _api_tool(method: str) -> dict:
    tool = _stored_tool("api_tool", {}, {"actions": {"call": {"url": "https://x.test", "method": method,
                                                              "active": True, "require_approval": False}}})
    tool["actions"] = []
    return tool


class TestOwnerHeldCredentialsWithoutAConnection:
    """Writes with the owner's stored credentials are gated like connected ones."""

    def _caller(self, **flags):
        from docsgpt.agents.tool_executor import ToolExecutor

        flags.setdefault("user", "bob")
        return ToolExecutor(**flags)

    @pytest.mark.parametrize("flags", [{"public_link_caller": True}, {"external_caller": True, "user": "alice"}])
    def test_api_tool_write_is_refused(self, flags):
        pause = _pause(self._caller(**flags), _api_tool("POST"), action="call")
        assert pause["pause_type"] == "headless_denied"
        assert "Access details" in pause["deny_reason"]

    def test_api_tool_read_runs(self):
        assert _pause(self._caller(public_link_caller=True), _api_tool("GET"), action="call") is None

    def test_allowlisted_api_tool_write_runs(self):
        caller = self._caller(public_link_caller=True, api_write_allowlist=["tool-9:call"])
        assert _pause(caller, _api_tool("POST"), action="call") is None

    def test_mcp_tool_with_stored_sign_in_is_gated(self):
        tool = _stored_tool("mcp_tool", {"name": "create_issue", "active": True},
                            {"server_url": "https://m.test/mcp", "auth_type": "bearer"})
        pause = _pause(self._caller(public_link_caller=True), tool, action="create_issue")
        assert pause["pause_type"] == "headless_denied"

    def test_mcp_tool_without_credentials_is_not_gated(self):
        tool = _stored_tool("mcp_tool", {"name": "create_issue", "active": True},
                            {"server_url": "https://m.test/mcp", "auth_type": "none"})
        assert _pause(self._caller(public_link_caller=True), tool, action="create_issue") is None

    def test_teammate_is_not_gated(self):
        assert _pause(self._caller(), _api_tool("POST"), action="call") is None


class TestScheduledRunsForOthers:
    """A scheduled run acts as the owner, for someone who can't approve for them."""

    def test_public_link_schedule_cannot_write_on_the_owners_account(self, pg_conn):
        from docsgpt.agents.tool_executor import ToolExecutor

        cid = _connection(pg_conn, "alice")
        executor = ToolExecutor(user="alice", headless=True, public_link_caller=True)
        with _db(pg_conn):
            pause = _pause(executor, _tool(cid))
        assert pause["pause_type"] == "headless_denied"
        assert "public link" in pause["deny_reason"]

    def test_owners_own_schedule_is_not_gated(self, pg_conn):
        from docsgpt.agents.tool_executor import ToolExecutor

        cid = _connection(pg_conn, "alice")
        with _db(pg_conn):
            assert _pause(ToolExecutor(user="alice", headless=True), _tool(cid)) is None
