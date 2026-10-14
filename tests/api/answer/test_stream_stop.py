"""Stopping a chat answer from another page, and the start/finish events.

The Stop on Activity › Now only stores a flag; the stream's heartbeat thread
polls it and the emit loop ends the stream as a client abort, keeping the
partial answer.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.storage.db.repositories.conversations import HeartbeatState

MESSAGE_ID = "11111111-1111-1111-1111-111111111111"
CONVERSATION_ID = "22222222-2222-2222-2222-222222222222"


def _service():
    service = MagicMock()
    service.save_user_question.return_value = {
        "conversation_id": CONVERSATION_ID,
        "message_id": MESSAGE_ID,
    }
    service.heartbeat_message.return_value = True
    service.heartbeat_message_state.return_value = HeartbeatState.STAMPED
    return service


def _chatty(chunks=200, gap=0.02):
    def _gen(*args, **kwargs):
        for i in range(chunks):
            time.sleep(gap)
            yield {"answer": f"c{i} "}

    return _gen


def _run(flask_app, gen, *, stop_after: float | None, visibility: str = "listed"):
    from docsgpt.api.answer.routes import base as base_mod
    from docsgpt.api.answer.routes.base import BaseAnswerResource

    started = time.monotonic()

    def _requested(message_id):
        return stop_after is not None and time.monotonic() - started > stop_after

    published = []
    with flask_app.app_context():
        resource = BaseAnswerResource()
        resource.conversation_service = _service()
        agent = MagicMock()
        agent.gen.side_effect = gen
        with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", 0.05), patch.object(
            base_mod, "STREAM_STOP_POLL_SECONDS", 0.02
        ), patch.object(base_mod, "stop_requested", side_effect=_requested), patch.object(
            base_mod, "clear_stop"
        ) as cleared, patch.object(
            base_mod,
            "publish_user_event",
            side_effect=lambda user, kind, payload, **kw: published.append((user, kind, payload)),
        ):
            out = list(
                resource.complete_stream(
                    question="q",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_persist=True,
                    visibility=visibility,
                )
            )
    return resource.conversation_service, out, published, cleared


@pytest.mark.unit
class TestStopFromActivity:
    def test_a_stop_ends_the_stream_early_and_keeps_the_text(self, mock_mongo_db, flask_app):
        service, out, _, cleared = _run(flask_app, _chatty(), stop_after=0.2)
        answers = [line for line in out if '"type": "answer"' in line]
        assert 0 < len(answers) < 200
        # The abort path saved what was written.
        assert service.finalize_message.called
        cleared.assert_called_with(MESSAGE_ID)

    def test_no_stop_runs_to_the_end(self, mock_mongo_db, flask_app):
        _, out, _, _ = _run(flask_app, _chatty(chunks=20, gap=0.005), stop_after=None)
        assert len([line for line in out if '"type": "answer"' in line]) == 20


@pytest.mark.unit
class TestStartFinishEvents:
    def test_publishes_started_then_finished(self, mock_mongo_db, flask_app):
        _, _, published, _ = _run(flask_app, _chatty(chunks=3, gap=0.0), stop_after=None)
        kinds = [kind for _, kind, _ in published if kind.startswith("message.")]
        assert kinds == ["message.started", "message.finished"]
        assert all(payload["conversation_id"] == CONVERSATION_ID for _, kind, payload in published if kind.startswith("message."))

    def test_hidden_streams_publish_nothing(self, mock_mongo_db, flask_app):
        # API, /v1 and shared-agent answers run under the agent owner; their
        # tabs must not count or refetch for each call.
        _, _, published, _ = _run(
            flask_app, _chatty(chunks=3, gap=0.0), stop_after=None, visibility="hidden"
        )
        assert [kind for _, kind, _ in published if kind.startswith("message.")] == []
