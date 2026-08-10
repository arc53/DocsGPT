"""The stream liveness heartbeat must be time-based, not output-based.

Regression cover for the production failure where a 20-minute agent tool
loop was force-failed by the reconciler at minute 6 — because the old
heartbeat only stamped when a chunk flowed, and a tool call emits nothing
while it runs.
"""

import time
from unittest.mock import MagicMock, patch

import pytest


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


@pytest.mark.unit
class TestHeartbeatTicker:
    def _run(self, flask_app, gen, interval=0.05):
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            service = MagicMock()
            service.save_user_question.return_value = _reservation()
            service.heartbeat_message.return_value = True
            resource.conversation_service = service

            agent = MagicMock()
            agent.gen.side_effect = gen

            with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", interval):
                list(
                    resource.complete_stream(
                        question="q",
                        agent=agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_persist=True,
                    )
                )
            return service

    def test_heartbeats_during_a_fully_silent_stream(
        self, mock_mongo_db, flask_app
    ):
        """No chunks flow for 0.4 s; the ticker must still stamp."""
        service = self._run(flask_app, _silent_then_answer(0.4))

        # 1 seed at generation start + several ticker stamps.
        assert service.heartbeat_message.call_count > 2

    def test_ticker_stops_when_the_stream_ends(self, mock_mongo_db, flask_app):
        service = self._run(flask_app, _silent_then_answer(0.1))
        settled = service.heartbeat_message.call_count

        time.sleep(0.3)

        assert service.heartbeat_message.call_count == settled

    def test_ticker_stops_on_client_abort(self, mock_mongo_db, flask_app):
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            service = MagicMock()
            service.save_user_question.return_value = _reservation()
            service.heartbeat_message.return_value = True
            resource.conversation_service = service

            def _endless(*args, **kwargs):
                while True:
                    time.sleep(0.02)
                    yield {"answer": "chunk"}

            agent = MagicMock()
            agent.gen.side_effect = _endless

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

            settled = service.heartbeat_message.call_count
            time.sleep(0.3)

            assert service.heartbeat_message.call_count == settled

    def test_no_ticker_without_a_reserved_row(self, mock_mongo_db, flask_app):
        """Headless/continuation rounds have no row to stamp."""
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            service = MagicMock()
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

            service.heartbeat_message.assert_not_called()

    def test_ticker_stops_when_row_goes_terminal(self, mock_mongo_db, flask_app):
        """A False return (row already terminal) is the natural stop signal."""
        from application.api.answer.routes import base as base_mod
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            service = MagicMock()
            service.save_user_question.return_value = _reservation()
            # The row is already terminal: every stamp reports "no row updated".
            service.heartbeat_message.return_value = False
            resource.conversation_service = service

            agent = MagicMock()
            agent.gen.side_effect = _silent_then_answer(0.6)

            with patch.object(base_mod, "STREAM_HEARTBEAT_INTERVAL", 0.05):
                list(
                    resource.complete_stream(
                        question="q",
                        agent=agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_persist=True,
                    )
                )

            # The seed and the status-flip stamp are unconditional; the ticker
            # itself must bail on its first False rather than stamping ~12
            # times over the 0.6 s of silence.
            assert service.heartbeat_message.call_count <= 3
