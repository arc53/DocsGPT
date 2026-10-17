"""``/v1`` key holders are external callers, though the run uses the owner's identity.

The route hands ``StreamProcessor`` the owner's token so state and logs land
under the owner, which made ``is_external_api_caller`` see the owner and let
a key holder run (or approve) writes on the owner's connected accounts.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.security.encryption import encrypt_json

SP = "docsgpt.api.answer.services.stream_processor"


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        for module in (SP, "docsgpt.connectors.service", "docsgpt.connectors.resolve"):
            stack.enter_context(patch(f"{module}.db_readonly", _yield))
        stack.enter_context(patch(f"{SP}.db_session", _yield))
        stack.enter_context(patch("docsgpt.connectors.service.db_session", _yield))
        yield


def _run_executor(processor):
    """The ``ToolExecutor`` the agent run gets from ``create_agent``."""
    processor._get_prompt_content = MagicMock(return_value="p")
    processor.prompt_renderer = MagicMock(render_prompt=MagicMock(return_value="p"))
    processor._enabled_tool_names = MagicMock(return_value=set())
    processor.model_id = "m1"
    with patch(f"{SP}.get_provider_from_model_id", return_value="openai"), \
            patch(f"{SP}.get_api_key_for_provider", return_value="key"), \
            patch("docsgpt.llm.llm_creator.LLMCreator.create_llm", return_value=MagicMock()), \
            patch("docsgpt.llm.handlers.handler_creator.LLMHandlerCreator.create_handler"), \
            patch("docsgpt.agents.agent_creator.AgentCreator.create_agent") as create:
        processor.create_agent()
    return create.call_args.kwargs["tool_executor"]


class TestV1KeyHolderWrites:
    def test_connected_write_is_refused_for_a_v1_key_holder(self, pg_conn):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        key = f"k-{uuid.uuid4().hex}"
        AgentsRepository(pg_conn).create("alice", "A", "published", key=key)
        connection = str(pg_conn.execute(
            text(
                "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, "
                "encrypted_credentials) VALUES ('alice', 'telegram', 'telegram', 'api_key', 'connected', :e) "
                "RETURNING id"
            ),
            {"e": encrypt_json({"credentials": {"token": "t"}}, "alice")},
        ).scalar())
        tool = {
            "id": "tool-1", "user_id": "alice", "name": "telegram", "config": {},
            "actions": [{"name": "telegram_send_message", "active": True, "require_approval": False}],
            "connection_id": connection, "credential_mode": "owner",
        }

        # What /v1 builds: the key in the body and the owner's token.
        processor = StreamProcessor({"api_key": key}, {"sub": "alice"}, external_caller=True)
        with _db(pg_conn):
            processor._configure_agent()
            executor = _run_executor(processor)
            call = SimpleNamespace(id="c1", name="telegram_send_message", arguments="{}", thought_signature=None)
            with patch("docsgpt.agents.tool_executor.ToolActionParser") as parser:
                parser.return_value.parse_args.return_value = ("t1", "telegram_send_message", {})
                pause = executor.check_pause({"t1": tool}, call, "OpenAILLM")
        assert executor.external_caller is True
        assert pause["pause_type"] == "headless_denied"
        assert pause["error_type"] == "tool_not_allowed"

    def test_resume_stays_external_even_when_state_says_otherwise(self, monkeypatch):
        """State saved before this fix recorded the key holder as not external."""
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
                             "agent_type": "ClassicAgent", "external_api_caller": False},
        }
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
        created = {}
        monkeypatch.setattr(
            ac_mod.AgentCreator, "create_agent", lambda *a, **kw: created.update(kw) or MagicMock(),
        )
        processor = StreamProcessor({}, {"sub": "alice"}, external_caller=True)
        processor.resume_from_tool_actions(tool_actions=[], conversation_id=str(uuid.uuid4()))
        assert created["tool_executor"].external_caller is True


@pytest.mark.unit
class TestV1Route:
    def test_route_marks_the_processor_external(self):
        from docsgpt.api.v1.routes import v1_bp

        app = Flask(__name__)
        app.register_blueprint(v1_bp)
        processor = MagicMock()
        processor.decoded_token = {"sub": "owner"}
        processor.agent_config = {"user_api_key": "k"}
        processor.agent_id = None
        processor.build_agent.return_value = MagicMock()
        helper = MagicMock()
        helper.check_usage.return_value = None
        helper.complete_stream.return_value = iter(['data: {"type": "end"}'])
        helper.process_response_stream.return_value = {
            "error": None, "conversation_id": "c", "answer": "ok", "sources": [], "tool_calls": [], "thought": "",
        }

        @contextmanager
        def _conn():
            yield MagicMock()

        with patch("docsgpt.api.v1.routes._lookup_agent",
                   return_value={"id": "agent-1", "name": "Agent", "user_id": "owner"}), \
                patch("docsgpt.api.v1.routes.translate_request",
                      return_value={"question": "hi", "api_key": "k"}), \
                patch("docsgpt.api.v1.routes.StreamProcessor", return_value=processor) as cls, \
                patch("docsgpt.api.v1.routes._V1AnswerHelper", return_value=helper), \
                patch("docsgpt.api.v1.routes.db_readonly", _conn), \
                patch("docsgpt.api.v1.routes.translate_response", return_value={"id": "x", "choices": []}):
            with app.test_client() as client:
                resp = client.post(
                    "/v1/chat/completions", headers={"Authorization": "Bearer k"},
                    json={"messages": [{"role": "user", "content": "hi"}]},
                )
        assert resp.status_code == 200
        assert cls.call_args.kwargs.get("external_caller") is True
