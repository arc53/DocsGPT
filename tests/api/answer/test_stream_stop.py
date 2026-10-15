"""Stopping a chat answer from another page, and the start/finish events.

The Stop on Activity › Now only stores a flag; the stream's heartbeat thread
polls it and the emit loop ends the stream as a client abort, keeping the
partial answer.
"""

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.storage.db.repositories.conversations import HeartbeatState, MessageUpdateOutcome

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
    service.finalize_message.return_value = MessageUpdateOutcome.UPDATED
    return service


def _chatty(chunks=200, gap=0.02):
    def _gen(*args, **kwargs):
        for i in range(chunks):
            time.sleep(gap)
            yield {"answer": f"c{i} "}

    return _gen


def _thinking(chunks=200, gap=0.02):
    """A stream that never writes answer text: only metadata lines."""

    def _gen(*args, **kwargs):
        for _ in range(chunks):
            time.sleep(gap)
            yield {"metadata": {}}

    return _gen


def _frame_type(frame: str):
    """The ``type`` of one SSE frame, or ``None`` for a non-JSON one."""
    data = [line[len("data: "):] for line in frame.splitlines() if line.startswith("data: ")]
    try:
        return json.loads(data[0]).get("type") if data else None
    except ValueError:
        return None


def _frame_payload(frame: str) -> dict:
    """The JSON payload of one SSE frame."""
    return json.loads(next(line for line in frame.splitlines() if line.startswith("data: "))[len("data: "):])


def _frame_id(frame: str) -> int:
    """The ``id:`` of one SSE frame."""
    return int(next(line for line in frame.splitlines() if line.startswith("id: "))[4:])


def _run(
    flask_app,
    gen,
    *,
    stop_after: float | None,
    visibility: str = "listed",
    client_gone: threading.Event | None = None,
    continuation: dict | None = None,
    requested=None,
    clear=None,
):
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
        agent.gen_continuation.side_effect = gen
        if client_gone is not None:
            agent.client_disconnected = client_gone
        with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", 0.05), patch.object(
            base_mod, "STREAM_STOP_POLL_SECONDS", 0.02
        ), patch.object(base_mod, "stop_requested", side_effect=requested or _requested), patch.object(
            base_mod, "clear_stop", side_effect=clear
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
                    _continuation=continuation,
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

    def test_a_stop_still_lands_past_the_heartbeat_ceiling(self, mock_mongo_db, flask_app):
        # The ticker stops stamping after STREAM_HEARTBEAT_MAX_SECONDS; it
        # is also what reads the Stop, so it must keep reading it.
        from docsgpt.api.answer.routes import base as base_mod

        with patch.object(base_mod, "STREAM_HEARTBEAT_MAX_SECONDS", 0.1):
            service, out, _, _ = _run(flask_app, _chatty(), stop_after=0.5)
        answers = [line for line in out if '"type": "answer"' in line]
        assert 0 < len(answers) < 200
        assert service.finalize_message.called

    def test_the_open_tab_gets_the_end(self, mock_mongo_db, flask_app):
        # The chat tab is still listening: it must see the stream end, not
        # just a closed socket it has to reconnect after.
        _, out, _, _ = _run(flask_app, _chatty(), stop_after=0.2)
        assert _frame_type(out[-1]) == "end"
        # Numbered after the last frame, as the journal has it, so a tab
        # that reconnects later resumes past it.
        assert _frame_id(out[-1]) == _frame_id(out[-2]) + 1

    def test_a_stop_before_any_text_ends_with_the_error(self, mock_mongo_db, flask_app):
        _, out, _, _ = _run(flask_app, _thinking(), stop_after=0.2)
        assert _frame_type(out[-1]) == "error"

    def test_a_stop_before_any_text_is_named_a_stop(self, mock_mongo_db, flask_app):
        # Not a disconnect: the chat says the user stopped it, and the stored
        # row carries the code so the sidebar does not mark the chat failed.
        service, out, _, _ = _run(flask_app, _thinking(), stop_after=0.2)
        assert _frame_payload(out[-1])["code"] == "stopped"
        failed = [
            call for call in service.finalize_message.call_args_list if call.kwargs.get("status") == "failed"
        ]
        assert len(failed) == 1
        assert failed[0].kwargs["metadata"]["error_code"] == "stopped"

    def test_a_close_after_a_stop_request_is_a_stop(self, mock_mongo_db, flask_app):
        # The chat's own Stop stores the request, then closes the stream; the
        # close can reach the stream before its ticker sees the request.
        gone = threading.Event()

        def _gen(*args, **kwargs):
            for i in range(200):
                time.sleep(0.005)
                if i == 5:
                    gone.set()
                yield {"metadata": {}}

        def _requested(message_id):
            # Only the abort handler, on the stream's own thread, sees it: the
            # close wins the race.
            return gone.is_set() and threading.current_thread() is threading.main_thread()

        service, _, _, _ = _run(flask_app, _gen, stop_after=None, client_gone=gone, requested=_requested)
        failed = [
            call for call in service.finalize_message.call_args_list if call.kwargs.get("status") == "failed"
        ]
        assert len(failed) == 1
        assert failed[0].kwargs["metadata"]["error_code"] == "stopped"

    def test_a_disconnect_before_any_text_is_still_a_disconnect(self, mock_mongo_db, flask_app):
        gone = threading.Event()

        def _gen(*args, **kwargs):
            for i in range(200):
                time.sleep(0.005)
                if i == 5:
                    gone.set()
                yield {"metadata": {}}

        service, _, _, _ = _run(flask_app, _gen, stop_after=None, client_gone=gone)
        failed = [
            call for call in service.finalize_message.call_args_list if call.kwargs.get("status") == "failed"
        ]
        assert len(failed) == 1
        assert (failed[0].kwargs.get("metadata") or {}).get("error_code") != "stopped"

    def test_a_gone_client_gets_nothing_more(self, mock_mongo_db, flask_app):
        # /v1: the route saw the client leave; nothing is written after.
        gone = threading.Event()

        def _gen(*args, **kwargs):
            for i in range(200):
                time.sleep(0.005)
                if i == 5:
                    gone.set()
                yield {"answer": f"c{i} "}

        _, out, _, _ = _run(flask_app, _gen, stop_after=None, client_gone=gone)
        assert _frame_type(out[-1]) not in ("end", "error")

    def test_a_resumed_answer_drops_a_stop_left_from_before(self, mock_mongo_db, flask_app):
        # A Stop that reached the paused turn after its stream ended is still
        # stored; the resumed turn reuses the message id and must not obey it.
        stored = {MESSAGE_ID}
        _, out, _, _ = _run(
            flask_app,
            _chatty(chunks=20, gap=0.01),
            stop_after=None,
            continuation={
                "reserved_message_id": MESSAGE_ID,
                "messages": [],
                "tools_dict": {},
                "pending_tool_calls": [],
                "tool_actions": [],
            },
            requested=lambda message_id: message_id in stored,
            clear=stored.discard,
        )
        assert len([line for line in out if '"type": "answer"' in line]) == 20

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
