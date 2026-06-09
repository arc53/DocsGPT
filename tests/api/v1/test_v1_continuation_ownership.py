"""Foreign-``conversation_id`` ownership gate on the ``/v1`` continuation path.

A ``/v1`` tool continuation persists its final answer into a client-supplied
``conversation_id``. Ownership IS enforced deep in the stack:

    route → ``build_continuation_from_messages`` → ``build_agent("")``
          → ``initialize`` → ``_load_conversation_history``
          → ``get_conversation(conversation_id, owner)``  ← owner-scoped read
          → ``None`` for a foreign conversation
          → ``ValueError("Conversation not found or unauthorized")``
          → route's ``except ValueError`` → HTTP 400

…but the existing E2E suite mocks ``build_agent``, so this security gate is
never actually exercised. This test seeds a conversation owned by user A and an
agent owned by user B, then POSTs a continuation with B's api_key targeting A's
conversation. The ownership read runs against the **real** DB (not mocked): we
only short-circuit ``StreamProcessor.initialize`` to the
``_load_conversation_history`` step so the test doesn't have to stand up the
full agent/model/source/retriever machinery to reach the gate.

Asserted: the route returns 400 AND no assistant turn is appended to A's
conversation (the foreign write is rejected before persistence).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

import pytest
from flask import Flask
from sqlalchemy import text

from application.api.answer.services import stream_processor as sp_mod
from application.api.v1.routes import v1_bp
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.conversations import ConversationsRepository

# Reuse the route-level DB wiring + seed helpers from the tool-pause suite.
from tests.api.v1.test_v1_tool_pause_finalization import (
    _seed_user,
    _wire_v1_route_db,
)


CLIENT_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}


def _seed_conversation(conn, user_id: str, name: str) -> str:
    """Create a conversation owned by ``user_id`` with one finalized turn."""
    repo = ConversationsRepository(conn)
    conv = repo.create(user_id, name)
    conv_id = str(conv["id"])
    repo.reserve_message(
        conv_id,
        prompt="hello",
        placeholder_response="hi there",
        status="complete",
    )
    return conv_id


def _seed_agent(conn, user_id: str, key: str) -> None:
    AgentsRepository(conn).create(user_id, "Weather Agent", "published", key=key)


def _build_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(v1_bp)
    return app


def _row_count(conn, conv_id: str) -> int:
    return conn.execute(
        text(
            "SELECT count(*) FROM conversation_messages "
            "WHERE conversation_id = CAST(:c AS uuid)"
        ),
        {"c": conv_id},
    ).scalar()


def _only_run_history_load(self) -> None:
    """Stand-in for ``StreamProcessor.initialize`` that runs ONLY the
    ownership-checked history load.

    The real ownership gate (``_load_conversation_history`` →
    ``get_conversation(conversation_id, owner)``) is NOT mocked — it runs
    against the real DB. We skip the surrounding agent/model/source/retriever
    configuration only so the test can reach the gate without provisioning a
    full agent runtime; the ``ValueError`` raised by the gate for a foreign
    conversation propagates exactly as in production.
    """
    self._load_conversation_history()


@pytest.mark.integration
class TestForeignConversationOwnership:
    """A continuation targeting another user's conversation is rejected at the
    ownership gate (400) and never appends a turn to that conversation."""

    PENDING_MESSAGES: List[Dict[str, Any]] = [
        {"role": "user", "content": "weather in SF?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": json.dumps({"city": "SF"}),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_abc", "content": "72F sunny"},
    ]

    def test_continuation_into_foreign_conversation_is_rejected(
        self, pg_engine, monkeypatch
    ):
        user_a = f"userA-{uuid.uuid4().hex[:8]}"  # owns the conversation
        user_b = f"userB-{uuid.uuid4().hex[:8]}"  # owns the agent (the caller)
        api_key = f"key-{uuid.uuid4().hex[:8]}"

        with pg_engine.begin() as conn:
            _seed_user(conn, user_a)
            _seed_user(conn, user_b)
            # Agent owned by B → the v1 route resolves decoded_token={"sub": B}.
            _seed_agent(conn, user_b, api_key)
            # Conversation owned by A, with one existing complete turn.
            conv_id = _seed_conversation(conn, user_a, "A's private chat")

        with pg_engine.connect() as conn:
            rows_before = _row_count(conn, conv_id)
        assert rows_before == 1  # the seeded turn

        app = _build_app()

        # Drive the REAL ownership read; only short-circuit the surrounding
        # initialize steps so we reach the gate without a full agent runtime.
        with _wire_v1_route_db(pg_engine, monkeypatch):
            monkeypatch.setattr(
                sp_mod.StreamProcessor, "initialize", _only_run_history_load
            )
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        # B (the agent owner) tries to write into A's conversation.
                        "conversation_id": conv_id,
                        "messages": self.PENDING_MESSAGES,
                        "tools": [CLIENT_TOOL],
                        "docsgpt": {"save_conversation": True},
                    },
                )

        # The ownership gate raised ValueError → route returns 400.
        assert resp.status_code == 400, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["error"]["type"] == "invalid_request"

        # No assistant turn was appended to A's conversation — the foreign
        # write was rejected before any persistence.
        with pg_engine.connect() as conn:
            rows_after = _row_count(conn, conv_id)
        assert rows_after == rows_before == 1

    def test_owner_can_continue_into_own_conversation(self, pg_engine, monkeypatch):
        """Control: the SAME continuation into the caller's OWN conversation
        passes the ownership gate (no 400 from the gate). Proves the 400 above
        is the ownership check firing, not an unrelated error in the path.
        """
        owner = f"owner-{uuid.uuid4().hex[:8]}"
        api_key = f"key-{uuid.uuid4().hex[:8]}"

        with pg_engine.begin() as conn:
            _seed_user(conn, owner)
            _seed_agent(conn, owner, api_key)
            # Conversation owned by the agent owner (the caller).
            conv_id = _seed_conversation(conn, owner, "owner's chat")

        app = _build_app()

        # Capture whether the gate passed: a flag the stubbed initialize sets
        # only if ``_load_conversation_history`` returned without raising.
        gate = {"passed": False}

        def _history_then_flag(self):
            self._load_conversation_history()
            gate["passed"] = True
            # Stop here: returning lets build_continuation_from_messages proceed
            # to create_agent, which needs a full runtime we deliberately skip.
            # Raise a sentinel the test recognises, distinct from the ownership
            # ValueError, so we can assert the gate itself did not reject us.
            raise RuntimeError("__gate_passed_sentinel__")

        with _wire_v1_route_db(pg_engine, monkeypatch):
            monkeypatch.setattr(
                sp_mod.StreamProcessor, "initialize", _history_then_flag
            )
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "conversation_id": conv_id,
                        "messages": (
                            TestForeignConversationOwnership.PENDING_MESSAGES
                        ),
                        "tools": [CLIENT_TOOL],
                        "docsgpt": {"save_conversation": True},
                    },
                )

        # The ownership read accepted the owner (gate passed); the request then
        # fails on the deliberately-skipped runtime (500), NOT on a 400 from the
        # gate. This isolates the ownership decision from the rest of the path.
        assert gate["passed"] is True
        assert resp.status_code == 500, resp.get_data(as_text=True)
