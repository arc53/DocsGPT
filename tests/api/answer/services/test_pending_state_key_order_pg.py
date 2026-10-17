"""A paused tool turn resumes with the exact tool block and history it paused with.

Background (b2b-sl rerun, 2026-10-02): resumed rounds hit a constant ~3k
cached tokens. The pause stored the turn's tools, tool calls and messages in
``jsonb`` columns, and ``jsonb`` re-sorts object keys (shorter keys first).
The resume rebuilt the tools from the re-sorted data (a client ``search``
tool's ``query, k`` came back as ``k, query``; a client tool's ``ct0`` key
jumped ahead of a server tool's id), so the rendered tools block differed
from the paused call's and the provider prompt cache broke right after the
system prompt.
"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.agents.tool_executor import ToolExecutor

pytestmark = pytest.mark.integration

OWNER = "owner"
SERVER_TOOL_ID = "6f1c2b8e-4c35-4f43-9d55-0c7b8e1d2a10"

CLIENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the attached documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for."},
                    "k": {"type": "integer", "description": "How many hits."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_by_id",
            "description": "Fetch one document.",
            "parameters": {
                "type": "object",
                "properties": {"document_id": {"type": "string"}, "page": {"type": "integer"}},
            },
        },
    },
]

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "total": {"type": "number"}},
    "required": ["summary", "total"],
}


def _server_tools() -> dict:
    return {
        SERVER_TOOL_ID: {
            "name": "notes",
            "actions": [
                {
                    "name": "write_note",
                    "description": "Write a note.",
                    "active": True,
                    "parameters": {
                        "properties": {
                            "title": {"type": "string", "filled_by_llm": True, "required": True},
                            "body": {"type": "string", "filled_by_llm": True},
                        },
                    },
                }
            ],
        }
    }


def _paused_turn() -> tuple[dict, list, list, list]:
    """Tools, tool schemas, pending calls and messages as the paused agent had them."""
    executor = ToolExecutor(user=OWNER)
    tools_dict = executor.merge_client_tools(_server_tools(), copy.deepcopy(CLIENT_TOOLS))
    tool_schemas = executor.prepare_tools_for_llm(tools_dict)
    pending = [
        {
            "call_id": "call_1",
            "name": "search",
            "tool_name": "search",
            "action_name": "search",
            "llm_name": "search",
            "arguments": {"query": "invoice total", "k": 3},
            "tool_id": "ct0",
            "client_side": True,
        }
    ]
    messages = [
        {"role": "system", "content": "You answer from the attached files."},
        {"role": "user", "content": "What is the invoice total?"},
    ]
    return tools_dict, tool_schemas, pending, messages


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.answer.services.continuation_service.db_readonly", _yield), patch(
        "docsgpt.api.answer.services.continuation_service.db_session", _yield,
    ):
        yield


def _conversation(conn) -> str:
    from docsgpt.storage.db.repositories.conversations import ConversationsRepository

    return str(ConversationsRepository(conn).create(OWNER, "paused")["id"])


def _dumps(value) -> str:
    return json.dumps(value)


class TestPausedStateKeepsKeyOrder:
    def test_stored_payloads_round_trip_byte_identical(self, pg_conn):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        tools_dict, tool_schemas, pending, messages = _paused_turn()
        agent_config = {"agent_type": "ClassicAgent", "json_schema": SCHEMA, "prompt": "p"}
        conv_id = _conversation(pg_conn)
        with _patch_db(pg_conn):
            service = ContinuationService()
            service.save_state(
                conv_id, OWNER, messages=messages, pending_tool_calls=pending,
                tools_dict=tools_dict, tool_schemas=tool_schemas,
                agent_config=agent_config, client_tools=CLIENT_TOOLS,
            )
            state = service.claim_state(conv_id, OWNER)

        assert _dumps(state["tool_schemas"]) == _dumps(tool_schemas)
        assert _dumps(state["tools_dict"]) == _dumps(tools_dict)
        assert _dumps(state["client_tools"]) == _dumps(CLIENT_TOOLS)
        assert _dumps(state["pending_tool_calls"]) == _dumps(pending)
        assert _dumps(state["messages"]) == _dumps(messages)
        assert _dumps(state["agent_config"]["json_schema"]) == _dumps(SCHEMA)

    def test_resumed_agent_renders_the_paused_tools(self, pg_conn, monkeypatch):
        """save_state -> claim_state -> resume -> ``_prepare_tools``: same bytes."""
        from docsgpt.api.answer.services import stream_processor as sp_mod
        from docsgpt.api.answer.services.continuation_service import ContinuationService
        from docsgpt.llm import llm_creator as llm_creator_mod

        tools_dict, tool_schemas, pending, messages = _paused_turn()
        agent_config = {
            "model_id": "gpt-test", "llm_name": "openai", "api_key": "k", "user_api_key": None,
            "agent_type": "ClassicAgent", "agent_id": None, "prompt": "p", "json_schema": None,
        }
        conv_id = _conversation(pg_conn)
        llm = MagicMock()
        llm.capabilities = None
        monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: llm)
        with _patch_db(pg_conn):
            ContinuationService().save_state(
                conv_id, OWNER, messages=messages, pending_tool_calls=pending,
                tools_dict=tools_dict, tool_schemas=tool_schemas,
                agent_config=agent_config, client_tools=CLIENT_TOOLS,
            )
            processor = sp_mod.StreamProcessor({}, {"sub": OWNER})
            agent, _, resumed_tools, _, _, _ = processor.resume_from_tool_actions(
                tool_actions=[{"call_id": "call_1", "result": "41.20"}], conversation_id=conv_id,
            )

        assert _dumps(agent.tools) == _dumps(tool_schemas)
        agent._prepare_tools(resumed_tools)
        assert _dumps(agent.tools) == _dumps(tool_schemas)

