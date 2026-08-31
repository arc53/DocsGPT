"""The stream liveness heartbeat must be time-based, not output-based —
and it is also how a superseded stream learns to stop.

Regression cover for two production failures:

- a 20-minute agent tool loop force-failed by the reconciler at minute 6,
  because the old heartbeat only stamped when a chunk flowed and a tool call
  emits nothing while it runs;
- a stream whose row was deleted by the user's retry running four further
  minutes and twelve further LLM rounds into a void.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from application.storage.db.repositories.conversations import HeartbeatState


def _reservation(message_id="11111111-1111-1111-1111-111111111111"):
    return {"conversation_id": "22222222-2222-2222-2222-222222222222",
            "message_id": message_id}


def _silent_then_answer(silence_seconds):
    """A generator that emits nothing for a while, then answers.

    Models the real silent windows: a provider round emitting only tool-call
    deltas, or the body of a ``read_webpage``/``code_executor`` call.
    """

    def _gen(*args, **kwargs):
        time.sleep(silence_seconds)
        yield {"answer": "done"}

    return _gen


def _chatty(chunks=200, gap=0.02):
    """A long multi-round stream that keeps emitting."""

    def _gen(*args, **kwargs):
        for i in range(chunks):
            time.sleep(gap)
            yield {"answer": f"chunk{i}"}

    return _gen


def _service(state=HeartbeatState.STAMPED):
    service = MagicMock()
    service.save_user_question.return_value = _reservation()
    service.heartbeat_message.return_value = True
    service.heartbeat_message_state.return_value = state
    return service


@pytest.mark.unit
class TestHeartbeatTicker:
    def _run(self, flask_app, gen, service=None, interval=0.05):
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            resource.conversation_service = service or _service()

            agent = MagicMock()
            agent.gen.side_effect = gen

            with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", interval):
                out = list(
                    resource.complete_stream(
                        question="q",
                        agent=agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_persist=True,
                    )
                )
            return resource.conversation_service, out

    def test_heartbeats_during_a_fully_silent_stream(
        self, mock_mongo_db, flask_app
    ):
        """No chunks flow for 0.4 s; the ticker must still stamp."""
        service, _ = self._run(flask_app, _silent_then_answer(0.4))

        assert service.heartbeat_message_state.call_count > 2

    def test_ticker_stops_when_the_stream_ends(self, mock_mongo_db, flask_app):
        service, _ = self._run(flask_app, _silent_then_answer(0.1))
        settled = service.heartbeat_message_state.call_count

        time.sleep(0.3)

        assert service.heartbeat_message_state.call_count == settled

    def test_ticker_stops_on_client_abort(self, mock_mongo_db, flask_app):
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            service = _service()
            resource.conversation_service = service

            agent = MagicMock()
            agent.gen.side_effect = _chatty()

            with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", 0.05):
                gen = resource.complete_stream(
                    question="q",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_persist=True,
                )
                next(gen)
                next(gen)
                time.sleep(0.15)
                gen.close()

            settled = service.heartbeat_message_state.call_count
            time.sleep(0.3)

            assert service.heartbeat_message_state.call_count == settled

    def test_no_ticker_without_a_reserved_row(self, mock_mongo_db, flask_app):
        """Headless/continuation rounds have no row to stamp."""
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            service = _service()
            resource.conversation_service = service

            agent = MagicMock()
            agent.gen.side_effect = _silent_then_answer(0.2)

            with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", 0.05):
                list(
                    resource.complete_stream(
                        question="q",
                        agent=agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_persist=False,
                    )
                )

            service.heartbeat_message_state.assert_not_called()

    def test_ticker_stops_when_row_goes_terminal(self, mock_mongo_db, flask_app):
        """A terminal row stops the ticker but must NOT cancel the stream."""
        service = _service(HeartbeatState.TERMINAL)
        service, out = self._run(
            flask_app, _silent_then_answer(0.6), service=service,
        )

        # The ticker bailed on its first TERMINAL rather than stamping ~12
        # times over 0.6 s of silence...
        assert service.heartbeat_message_state.call_count == 1
        # ...and the stream still finished and finalized, so a
        # reconciler-swept row can still be reclaimed.
        assert any('"type": "end"' in chunk for chunk in out)
        service.finalize_message.assert_called_once()


@pytest.mark.unit
class TestSupersededStreamCancellation:
    """A deleted row must stop the work, not just quiet the logs."""

    def _run_with_missing_row(self, flask_app, gen, interval=0.05):
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            service = _service(HeartbeatState.MISSING)
            resource.conversation_service = service

            agent = MagicMock()
            agent.gen.side_effect = gen

            with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", interval):
                out = list(
                    resource.complete_stream(
                        question="q",
                        agent=agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_persist=True,
                    )
                )
            return service, out

    def test_stream_stops_early_when_its_row_is_deleted(
        self, mock_mongo_db, flask_app
    ):
        """The generator must not be drained to completion."""
        service, out = self._run_with_missing_row(flask_app, _chatty(chunks=400))

        # 400 chunks × 0.02 s ≈ 8 s if drained; cancellation lands far sooner.
        assert len(out) < 200, f"stream was not cancelled early ({len(out)})"

    def test_superseded_stream_does_not_persist(self, mock_mongo_db, flask_app):
        """Nothing to write — the row is gone. No finalize, no save."""
        service, _ = self._run_with_missing_row(flask_app, _chatty(chunks=400))

        service.finalize_message.assert_not_called()
        service.save_conversation.assert_not_called()

    def test_superseded_stream_emits_no_error_to_the_client(
        self, mock_mongo_db, flask_app
    ):
        """It is not a failure: the user replaced this turn deliberately."""
        _, out = self._run_with_missing_row(flask_app, _chatty(chunks=400))

        assert not any('"type": "error"' in chunk for chunk in out)

    def test_live_row_is_never_cancelled(self, mock_mongo_db, flask_app):
        """The common case must be untouched."""
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            service = _service(HeartbeatState.STAMPED)
            resource.conversation_service = service

            agent = MagicMock()
            agent.gen.side_effect = _chatty(chunks=30)

            with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", 0.05):
                out = list(
                    resource.complete_stream(
                        question="q",
                        agent=agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_persist=True,
                    )
                )

            assert any('"type": "end"' in chunk for chunk in out)
            service.finalize_message.assert_called_once()

    def test_db_error_does_not_cancel_the_stream(self, mock_mongo_db, flask_app):
        """A transient blip must never be mistaken for a deleted row."""
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            service = _service()
            service.heartbeat_message_state.side_effect = RuntimeError("pool")
            resource.conversation_service = service

            agent = MagicMock()
            agent.gen.side_effect = _chatty(chunks=30)

            with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", 0.05):
                out = list(
                    resource.complete_stream(
                        question="q",
                        agent=agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_persist=True,
                    )
                )

            assert any('"type": "end"' in chunk for chunk in out)
            service.finalize_message.assert_called_once()
