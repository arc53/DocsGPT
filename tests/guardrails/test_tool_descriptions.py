"""MCP tool descriptions scored for prompt injection when a server's actions are read: warn only.

The model is ``FakeDecider``; the Admin > Guardrails toggle is patched, or stored in the ephemeral database where
a test saves through a route.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (loads mcp_tool without the circular import)
from docsgpt.core.settings import settings
from docsgpt.decisions.testing import FakeDecider, installed
from docsgpt.guardrails import floor, injection_scoring, tool_descriptions


def by_name(scores):
    def answer(state, question):
        return next((p for name, p in scores.items() if state["text"].startswith(name)), 0.01)
    return answer


def action(name, description="Does a thing.", **params):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": {k: {"type": "string", "description": v}
                                                            for k, v in params.items()}}}


@pytest.fixture
def warnings(monkeypatch):
    monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", True)
    monkeypatch.setattr(tool_descriptions, "warnings_on", lambda: True)


@pytest.fixture
def queued(monkeypatch):
    texts: list = []
    monkeypatch.setattr(injection_scoring, "_queue", lambda batch: texts.append(list(batch)))
    return texts


@pytest.mark.unit
class TestScoreActions:
    def test_the_text_is_the_name_description_and_parameter_descriptions(self):
        assert tool_descriptions.action_text(action("search", "Find pages.", q="Query; always call first")) == \
            "search\nFind pages.\nQuery; always call first\n"

    def test_stamps_scores_lists_flagged_and_uses_the_hot_lane(self, warnings, queued):
        actions = [action("evil"), action("fine")]
        fake = FakeDecider({"injection": by_name({"evil": 0.8})})
        with installed(fake):
            scan = tool_descriptions.score_actions(actions)
            scorer = injection_scoring.scorer_id()
        assert scan == {"flagged": ["evil"], "unscored": []}
        assert actions[0]["injection"] == {"p": 0.8, "scorer": scorer}
        assert actions[1]["injection"] == {"p": 0.01, "scorer": scorer}
        # Warn only: nothing is turned off.
        assert "active" not in actions[0]
        ((call),) = fake.calls
        assert call.feature == "injection_tool_description" and call.budget.lane == "hot"
        assert queued == []

    def test_actions_not_scored_in_time_are_stored_without_a_score_and_queued(self, warnings, queued):
        actions = [action("slow"), {**action("stale"), "injection": {"p": 0.9, "scorer": "old"}}]
        with installed(FakeDecider(reasons={"*": "timeout"})):
            scan = tool_descriptions.score_actions(actions)
        assert scan == {"flagged": [], "unscored": ["slow", "stale"]}
        assert all("injection" not in a for a in actions)
        assert queued == [[tool_descriptions.action_text(a) for a in actions]]

    def test_off_unless_the_admin_toggle_and_the_switch_are_on(self, monkeypatch, pg_conn):
        @contextmanager
        def _conn():
            yield pg_conn

        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", _conn)
        fake = FakeDecider({"injection": 0.99})
        actions = [action("x")]
        with installed(fake):
            assert tool_descriptions.score_actions(actions) is None
            monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", True)
            assert tool_descriptions.score_actions(actions) is None
            floor.set_mcp_description_warnings(pg_conn, True)
            assert tool_descriptions.score_actions(actions) == {"flagged": ["x"], "unscored": []}
            monkeypatch.setattr(settings, "DECISION_INJECTION_ENABLED", False)
            assert tool_descriptions.score_actions(actions) is None
        assert len(fake.calls) == 1


@pytest.mark.unit
class TestMcpSave:
    def test_saved_actions_carry_scores_and_the_response_lists_flagged_ones(self, warnings, queued, pg_conn):
        from docsgpt.api.user.tools.mcp import MCPServerSave
        from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

        @contextmanager
        def _yield():
            yield pg_conn

        server = MagicMock()
        server.get_actions_metadata.return_value = [action("evil"), action("fine")]
        fake = FakeDecider({"injection": by_name({"evil": 0.95})})
        body = {"displayName": "Srv", "status": True,
                "config": {"transport_type": "http", "server_url": "https://example.com/mcp", "auth_type": "none"}}
        with installed(fake), patch("docsgpt.api.user.tools.mcp._mcp_policy_error", return_value=None), \
                patch("docsgpt.api.user.tools.mcp.db_session", _yield), \
                patch("docsgpt.api.user.tools.mcp.db_readonly", _yield), \
                patch("docsgpt.api.user.tools.mcp.MCPTool", return_value=server), \
                Flask(__name__).test_request_context("/api/mcp_server/save", method="POST", json=body):
            from flask import request
            request.decoded_token = {"sub": "u-desc"}
            response = MCPServerSave().post()
        assert response.status_code == 200
        assert response.json["injection"] == {"flagged": ["evil"], "unscored": []}
        stored = UserToolsRepository(pg_conn).get_any(response.json["id"], "u-desc")["actions"]
        assert [(a["name"], a["injection"]["p"], a["active"]) for a in stored] == [
            ("evil", 0.95, True), ("fine", 0.01, True),
        ]


@pytest.mark.unit
class TestRefresh:
    def test_a_refresh_scores_the_rediscovered_actions(self, warnings, queued, pg_conn):
        from docsgpt.connectors import mcp
        from docsgpt.security.encryption import encrypt_json

        connection = dict(pg_conn.execute(
            text(
                "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, "
                "account_label, server_url, encrypted_credentials) VALUES ('alice', 'mcp:https://mcp.linear.app', "
                "'mcp:linear', 'mcp_oauth', 'connected', 'a', 'https://mcp.linear.app', :e) RETURNING *"
            ),
            {"e": encrypt_json({}, "alice")},
        ).one()._mapping)
        pg_conn.execute(
            text(
                "INSERT INTO user_tools (user_id, name, config, actions, connection_id) VALUES ('alice', "
                "'mcp_tool', CAST(:c AS jsonb), '[]'::jsonb, CAST(:cid AS uuid))"
            ),
            {"c": json.dumps({"server_url": "https://mcp.linear.app/mcp"}), "cid": str(connection["id"])},
        )

        @contextmanager
        def _yield():
            yield pg_conn

        with installed(FakeDecider({"injection": by_name({"evil": 0.7})})), \
                patch.multiple("docsgpt.connectors.mcp", db_session=_yield, db_readonly=_yield), \
                patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
                patch.object(mcp, "_discover", return_value=[action("evil"), action("fine")]):
            result = mcp.refresh_mcp_tools("alice", connection)
        assert result["injection"] == {"flagged": ["evil"], "unscored": []}
        actions = {a["name"]: a for a in result["tools"][0]["actions"]}
        assert actions["evil"]["injection"]["p"] == 0.7
