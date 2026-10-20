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
    agent_calls=None,
    background=None,
    stop_jobs=None,
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
        agent._get_truncated_tool_calls.return_value = list(agent_calls or [])
        with patch.object(base_mod, "bind_background_turn", return_value=background), patch(
            "docsgpt.background.service.stop_turn_jobs", side_effect=stop_jobs
        ), patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", 0.05), patch.object(
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

    def test_an_answer_that_finishes_asks_for_the_unread_mark(self, mock_mongo_db, flask_app):
        # Finished while the user may be elsewhere: the chat is marked unread
        # unless they are watching it (the service decides).
        service, _, _, _ = _run(flask_app, _chatty(chunks=3, gap=0), stop_after=None)
        kwargs = service.finalize_message.call_args.kwargs
        assert kwargs.get("mark_unread_when_away") is True

    def test_a_stopped_answer_does_not_ask_for_the_unread_mark(self, mock_mongo_db, flask_app):
        service, _, _, _ = _run(flask_app, _chatty(), stop_after=0.2)
        assert service.finalize_message.called
        for call in service.finalize_message.call_args_list:
            assert not call.kwargs.get("mark_unread_when_away")

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
        # Saved with its code, so a reload words it as the live stream did
        # and the chat isn't marked failed for it.
        assert (failed[0].kwargs.get("metadata") or {}).get("error_code") == "client_disconnect"

    def test_a_stopped_turn_keeps_its_logs_entry(self, mock_mongo_db, flask_app):
        # Logs lists running chats; once stopped it must list the turn as
        # a finished one, as it does a turn that ran out or failed.
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        with patch.object(BaseAnswerResource, "_persist_turn_log") as logged:
            _run(flask_app, _chatty(), stop_after=0.2)
        assert logged.call_count == 1
        kwargs = logged.call_args.kwargs
        assert kwargs["message_id"] == MESSAGE_ID
        assert kwargs["response"].startswith("c0 ")
        assert kwargs["extra"] == {"stopped": True}
        assert kwargs.get("error") is None

    def test_a_stop_on_the_last_frame_logs_the_turn_once(self, mock_mongo_db, flask_app):
        # The answer finished and was logged; the Stop lands as the stream
        # yields its final frame. That close must not log the turn again.
        from docsgpt.api.answer.routes import base as base_mod
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            resource.conversation_service = _service()
            agent = MagicMock()
            agent.gen.side_effect = _chatty(chunks=3, gap=0)
            with patch.object(base_mod, "stop_requested", return_value=True), patch.object(
                base_mod, "clear_stop"
            ), patch.object(base_mod, "publish_user_event"), patch.object(
                BaseAnswerResource, "_persist_turn_log"
            ) as logged:
                stream = resource.complete_stream(
                    question="q",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_persist=True,
                    visibility="listed",
                )
                for frame in stream:
                    if _frame_type(frame) == "end":
                        stream.close()
                        break
        assert logged.call_count == 1

    def test_a_dropped_connection_writes_no_logs_entry(self, mock_mongo_db, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        gone = threading.Event()

        def _gen(*args, **kwargs):
            for i in range(200):
                time.sleep(0.005)
                if i == 5:
                    gone.set()
                yield {"answer": f"c{i} "}

        with patch.object(BaseAnswerResource, "_persist_turn_log") as logged:
            _run(flask_app, _gen, stop_after=None, client_gone=gone)
        assert logged.call_count == 0

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


HANDED_OFF = {"call_id": "c1", "tool_name": "artifact_generator", "status": "pending", "job_id": "j1"}


def _background():
    from docsgpt.background.context import BackgroundContext

    return BackgroundContext(user_id="u", conversation_id=CONVERSATION_ID, origin_message_id=MESSAGE_ID)


@pytest.mark.unit
class TestStopWithBackgroundJobs:
    def test_a_stopped_turn_keeps_the_calls_it_had_not_reported(self, mock_mongo_db, flask_app):
        # The agent reports its calls only when its turn ends; a Stop cut it
        # short, and the message lost its job card and the job's file.
        service, _, _, _ = _run(flask_app, _chatty(), stop_after=0.2, agent_calls=[HANDED_OFF])
        saved = service.finalize_message.call_args.kwargs["tool_calls"]
        assert [c["job_id"] for c in saved] == ["j1"]

    def test_a_stop_before_any_text_keeps_them_too(self, mock_mongo_db, flask_app):
        service, _, _, _ = _run(flask_app, _thinking(), stop_after=0.2, agent_calls=[HANDED_OFF])
        failed = [c for c in service.finalize_message.call_args_list if c.kwargs.get("status") == "failed"]
        assert [c["job_id"] for c in failed[0].kwargs["tool_calls"]] == ["j1"]

    def test_a_stop_cancels_the_turns_jobs_after_saving_it(self, mock_mongo_db, flask_app, monkeypatch):
        # After: a job that already ended shows its outcome on the saved entry.
        service = _service()
        monkeypatch.setitem(globals(), "_service", lambda: service)
        captured = []

        def _record(conversation_id, message_id, user_id):
            captured.append((conversation_id, message_id, user_id, service.finalize_message.called))

        _run(flask_app, _chatty(), stop_after=0.2, background=_background(), stop_jobs=_record)
        assert captured == [(CONVERSATION_ID, MESSAGE_ID, "u", True)]

    def test_a_dropped_connection_leaves_the_jobs_running(self, mock_mongo_db, flask_app):
        # A job is meant to outlive a closed tab.
        gone = threading.Event()
        calls = []

        def _gen(*args, **kwargs):
            for i in range(200):
                time.sleep(0.005)
                if i == 5:
                    gone.set()
                yield {"answer": f"c{i} "}

        _run(flask_app, _gen, stop_after=None, client_gone=gone, background=_background(),
             stop_jobs=lambda *a: calls.append(a), agent_calls=[HANDED_OFF])
        assert calls == []

    def test_a_failure_to_stop_the_jobs_still_ends_the_stream(self, mock_mongo_db, flask_app):
        def _boom(*args):
            raise RuntimeError("db down")

        _, out, _, _ = _run(flask_app, _chatty(), stop_after=0.2, background=_background(), stop_jobs=_boom)
        assert _frame_type(out[-1]) == "end"


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
