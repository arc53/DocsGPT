"""The prompt recipe through ``POST /api/drafter/stream``: drafted on the prompt's own text."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.api.user.drafter.test_drafter_routes import _events, _stream, _types
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
    def test_improve_reads_nothing_from_the_workspace(self, client):
        fake = FakeLLM(calls(tool_call("submit_proposal", {
            "message": "Removed the date.",
            "edits": [{"find": "Today is {{ system.date }}.\n", "replace": "", "reason": "DocsGPT adds the date."}],
        })))
        context = {"mode": "improve", "prompt": {"id": "p1", "name": "Shipping", "content": PERSONA}}
        with patch("docsgpt.storage.db.session.db_readonly") as reader:
            events = _events(_stream(client, _body(context), fake))
        reader.assert_not_called()
        assert _types(events) == ["status:reading", "status:drafting", "proposal", "end"]
        proposal = events[2]["proposal"]
        assert proposal["result"] == "You answer shipping questions.\nBe brief."
        assert proposal["template_mode"] == {"before": True, "after": False}
        assert proposal["checks"] == ["to_persona"]

    def test_write_returns_a_name_and_text(self, client):
        fake = FakeLLM(calls(tool_call("submit_proposal", {
            "message": "Wrote it.", "name": "HR helper", "content": "You help employees.", "reason": "A persona.",
        })))
        context = {"mode": "write", "prompt": {"id": None, "name": "", "content": ""}}
        events = _events(_stream(client, _body(context, "An HR handbook helper"), fake))
        assert events[2]["proposal"]["name"] == "HR helper"

    def test_nothing_to_improve_is_a_bad_request(self, client):
        context = {"mode": "improve", "prompt": {"id": "p1", "name": "x", "content": " "}}
        events = _events(_stream(client, _body(context)))
        assert events[0]["code"] == "bad_request"
