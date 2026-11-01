"""A chunk's knowledge name reaches the model but never a client or the stored turn.

``source_name`` is the name of the knowledge a chunk came from in its owner's
library. The prompt names it so a question like "Summarize test-1" finds its
chunks, but a widget or shared-link reader must not learn what the owner's
knowledge is called, so the chat stream and the stored sources leave it out.
The connector attribution next to it ("From Google Drive") is meant to be shown
and stays.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text as sql_text

from docsgpt.api.answer.services.prompt_renderer import format_docs_for_prompt


def _docs():
    return [
        {
            "text": "Install with pip. " * 20,
            "title": "01-quickstart.md",
            "filename": "01-quickstart.md",
            "source": "docs/01-quickstart.md",
            "source_name": "test-1",
            "connector_key": "google_drive",
            "connector_name": "Google Drive",
            "url": "https://drive.google.com/file/d/f1/view",
        }
    ]


def _agent(docs):
    agent = MagicMock()
    agent.gen.side_effect = lambda query: iter([{"answer": "Install it with pip."}, {"sources": docs}])
    agent.tool_calls = []
    agent.compression_metadata = None
    agent.compression_saved = False
    return agent


def _run(resource, agent, **kwargs):
    base = dict(
        question="Summarize test-1",
        agent=agent,
        conversation_id=None,
        user_api_key=None,
        decoded_token={"sub": "owner-1"},
        should_persist=False,
        model_id="gpt-4",
    )
    base.update(kwargs)
    return list(resource.complete_stream(**base))


def _source_event(stream):
    events = [json.loads(chunk.split("data: ", 1)[1]) for chunk in stream if '"type": "source"' in chunk]
    assert len(events) == 1
    return events[0]["source"]


@pytest.mark.unit
class TestSourceNameStaysInThePrompt:
    def test_stream_source_event_leaves_out_the_knowledge_name(self, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        docs = _docs()
        with flask_app.app_context():
            sent = _source_event(_run(BaseAnswerResource(), _agent(docs)))

        assert "source_name" not in sent[0]
        assert sent[0]["connector_name"] == "Google Drive"
        assert sent[0]["url"] == "https://drive.google.com/file/d/f1/view"
        assert sent[0]["title"] == "01-quickstart.md"

    def test_the_agents_own_docs_keep_the_name_for_the_prompt(self, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        docs = _docs()
        with flask_app.app_context():
            _run(BaseAnswerResource(), _agent(docs))

        assert docs[0]["source_name"] == "test-1"
        assert "<knowledge>test-1</knowledge>" in format_docs_for_prompt(docs)

    def test_stored_turn_sources_leave_out_the_knowledge_name(self, pg_conn, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource
        from tests.api.answer.test_base_routes import _patch_db_session

        with flask_app.app_context(), _patch_db_session(pg_conn):
            _run(BaseAnswerResource(), _agent(_docs()), should_persist=True)

        stored = pg_conn.execute(
            sql_text(
                "SELECT m.sources FROM conversation_messages m "
                "JOIN conversations c ON c.id = m.conversation_id WHERE c.user_id = 'owner-1'"
            )
        ).scalar()
        assert len(stored) == 1
        assert "source_name" not in stored[0]
        assert stored[0]["connector_name"] == "Google Drive"
