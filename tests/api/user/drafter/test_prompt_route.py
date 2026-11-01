"""The prompt recipe through ``POST /api/drafter/stream``: the agent's knowledge, scoped to the caller."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from docsgpt.storage.db.repositories.sources import SourcesRepository
from tests.api.user.drafter.test_drafter_routes import _db, _events, _stream, _types
from tests.drafter.fakes import calls, FakeLLM, tool_call

PERSONA = "You answer shipping questions.\nToday is {{ system.date }}.\nBe brief."


@pytest.fixture(scope="module")
def flask_app():
    from docsgpt.app import app

    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _body(context, text="Make it stop quoting prices"):
    return {"recipe": "prompt", "messages": [{"role": "user", "content": text}], "context": context}


@pytest.mark.unit
class TestPromptStream:
    def test_improve_reads_only_the_agents_knowledge_the_caller_can_open(self, client, pg_conn):
        own = SourcesRepository(pg_conn).create("Shipping policies", user_id="alice")
        other = SourcesRepository(pg_conn).create("Bob's payroll", user_id="bob")
        unused = SourcesRepository(pg_conn).create("Old wiki", user_id="alice")
        fake = FakeLLM(calls(tool_call("submit_proposal", {
            "message": "Removed the date.",
            "edits": [{"find": "Today is {{ system.date }}.\n", "replace": "", "reason": "DocsGPT adds the date."}],
        })))
        context = {
            "mode": "improve",
            "prompt": {"id": "p1", "name": "Shipping", "content": PERSONA},
            "agent": {"sources": [str(own["id"]), str(other["id"])], "tools": [], "agent_type": "classic"},
        }
        with _db(pg_conn):
            events = _events(_stream(client, _body(context), fake))
        assert _types(events) == ["status:reading", "status:drafting", "proposal", "end"]
        assert events[0]["counts"] == {"sources": 1, "tools": 0, "prompts": 0, "models": 0}
        proposal = events[2]["proposal"]
        assert proposal["result"] == "You answer shipping questions.\nBe brief."
        assert proposal["template_mode"] == {"before": True, "after": False}
        assert proposal["checks"] == ["to_persona"]
        request = fake.calls[0]["messages"][-1]["content"]
        assert "Shipping policies" in request
        assert "Bob's payroll" not in request and "Old wiki" not in request
        assert unused["id"]

    def test_write_without_an_agent_reads_nothing(self, client):
        fake = FakeLLM(calls(tool_call("submit_proposal", {
            "message": "Wrote it.", "name": "HR helper", "content": "You help employees.", "reason": "A persona.",
        })))
        context = {"mode": "write", "prompt": {"id": None, "name": "", "content": ""}, "agent": None}
        with patch("docsgpt.storage.db.session.db_readonly") as reader:
            events = _events(_stream(client, _body(context, "An HR handbook helper"), fake))
        reader.assert_not_called()
        assert events[2]["proposal"]["name"] == "HR helper"

    def test_nothing_to_improve_is_a_bad_request(self, client):
        context = {"mode": "improve", "prompt": {"id": "p1", "name": "x", "content": " "}}
        events = _events(_stream(client, _body(context)))
        assert events[0]["code"] == "bad_request"
