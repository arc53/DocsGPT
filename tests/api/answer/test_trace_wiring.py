"""``complete_stream`` owns the request's execution trace and writes it once."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from docsgpt import tracing
from docsgpt.core.settings import settings


@pytest.fixture(autouse=True)
def _tracing_on(monkeypatch):
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(settings, "TRACES_OTEL_EXPORT", False)


@contextmanager
def _captured_flushes():
    """Record every flushed trace instead of writing it."""
    flushed = []

    def _fake_flush(trace, status=None, **_kwargs):
        if trace is None or trace.flushed:
            return
        trace.flushed = True
        trace.finish(status)
        flushed.append(trace)

    with patch("docsgpt.tracing.flush", side_effect=_fake_flush):
        yield flushed


def _agent(events):
    agent = MagicMock()

    def _gen(query):
        with tracing.span(tracing.KIND_AGENT, "invoke_agent Fake"):
            with tracing.span(tracing.KIND_LLM, "chat m"):
                pass
            yield from events

    agent.gen.side_effect = _gen
    agent.tool_calls = []
    agent.compression_metadata = None
    agent.compression_saved = False
    return agent


def _run(resource, agent, **kwargs):
    base = dict(
        question="q",
        agent=agent,
        conversation_id=None,
        user_api_key=None,
        decoded_token={"sub": "u-trace"},
        should_persist=False,
    )
    base.update(kwargs)
    return list(resource.complete_stream(**base))


@pytest.mark.unit
class TestTraceLifecycle:
    def test_normal_turn_flushes_once_with_ids(self, flask_app, mock_mongo_db):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context(), _captured_flushes() as flushed:
            _run(BaseAnswerResource(), _agent([{"answer": "hi"}]), request_id="req-1")
        (trace,) = flushed
        assert trace.request_id == "req-1"
        assert trace.user_id == "u-trace"
        assert trace.status == "ok"
        assert [s.name for s in trace.spans] == ["invoke_agent Fake", "chat m"]

    def test_route_trace_is_reused(self, flask_app, mock_mongo_db):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        route_trace = tracing.start_trace(source="answer", capture_otel_context=False)
        with tracing.activate(route_trace):
            with tracing.span(tracing.KIND_RETRIEVAL, "retrieval"):
                pass
        with flask_app.app_context(), _captured_flushes() as flushed:
            _run(
                BaseAnswerResource(),
                _agent([{"answer": "hi"}]),
                request_id="req-2",
                trace=route_trace,
            )
        assert flushed == [route_trace]
        assert route_trace.source == "answer"
        assert [s.kind for s in route_trace.spans] == ["retrieval", "agent", "llm"]

    def test_mock_trace_is_ignored(self, flask_app, mock_mongo_db):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context(), _captured_flushes() as flushed:
            _run(BaseAnswerResource(), _agent([{"answer": "hi"}]), trace=MagicMock())
        assert len(flushed) == 1
        assert isinstance(flushed[0], tracing.Trace)

    def test_continuation_keeps_saved_request_id(self, flask_app, mock_mongo_db):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        agent = _agent([])
        agent.gen_continuation.side_effect = lambda **_kw: iter([{"answer": "done"}])
        with flask_app.app_context(), _captured_flushes() as flushed:
            _run(
                BaseAnswerResource(),
                agent,
                question="",
                request_id="fresh",
                _continuation={
                    "messages": [],
                    "tools_dict": {},
                    "pending_tool_calls": [],
                    "tool_actions": [],
                    "request_id": "saved-req",
                },
            )
        assert flushed[0].request_id == "saved-req"

    def test_agent_error_marks_trace_error(self, flask_app, mock_mongo_db):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        agent = MagicMock()
        agent.gen.side_effect = RuntimeError("upstream down")
        with flask_app.app_context(), _captured_flushes() as flushed:
            stream = _run(BaseAnswerResource(), agent)
        assert any('"type": "error"' in s for s in stream)
        assert flushed[0].status == "error"

    def test_yielded_error_marks_trace_error(self, flask_app, mock_mongo_db):
        """A failed workflow node yields an error event instead of raising."""
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context(), _captured_flushes() as flushed:
            _run(
                BaseAnswerResource(),
                _agent([{"type": "error", "error": "node failed"}]),
            )
        assert flushed[0].status == "error"

    def test_abandoned_stream_still_flushes(self, flask_app, mock_mongo_db):
        from docsgpt.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context(), _captured_flushes() as flushed:
            gen = BaseAnswerResource().complete_stream(
                question="q",
                agent=_agent([{"answer": "a"}, {"answer": "b"}]),
                conversation_id=None,
                user_api_key=None,
                decoded_token={"sub": "u"},
                should_persist=False,
            )
            next(gen)
            gen.close()
        assert len(flushed) == 1


@pytest.mark.unit
class TestTraceWithPersistence:
    def test_message_and_conversation_ids_bound(self, pg_conn, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource
        from tests.api.answer.test_base_routes import _patch_db_session

        with flask_app.app_context(), _patch_db_session(pg_conn), _captured_flushes() as flushed:
            _run(
                BaseAnswerResource(),
                _agent([{"answer": "persisted"}]),
                should_persist=True,
                model_id="gpt-4",
                request_id="req-p",
            )
        trace = flushed[0]
        assert trace.message_id
        assert trace.conversation_id
        from sqlalchemy import text as sql_text

        row = pg_conn.execute(
            sql_text("SELECT data FROM user_logs WHERE user_id = 'u-trace'")
        ).fetchone()
        assert row[0]["request_id"] == "req-p"
        assert row[0]["message_id"] == trace.message_id

    def test_paused_turn_is_flushed_paused(self, pg_conn, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource
        from tests.api.answer.test_base_routes import _patch_db_session

        agent = _agent(
            [
                {
                    "type": "tool_calls_pending",
                    "data": {"pending_tool_calls": [{"call_id": "c1"}]},
                }
            ]
        )
        agent._pending_continuation = {
            "messages": [],
            "tools_dict": {},
            "pending_tool_calls": [{"call_id": "c1"}],
        }
        with flask_app.app_context(), _patch_db_session(pg_conn), patch(
            "docsgpt.api.answer.services.continuation_service.ContinuationService.save_state",
            return_value=True,
        ), _captured_flushes() as flushed:
            _run(BaseAnswerResource(), agent, should_persist=True, model_id="gpt-4")
        assert flushed[0].status == "paused"


@pytest.mark.unit
class TestProcessorTraceSetup:
    def test_build_agent_mints_request_id_inside_the_trace(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        seen = {}

        class _Stop(Exception):
            pass

        def _initialize():
            seen["trace"] = tracing.current_trace()
            with tracing.span(tracing.KIND_RETRIEVAL, "retrieval"):
                pass
            raise _Stop()

        processor = StreamProcessor({"question": "q"}, {"sub": "u1"}, trace_source="answer")
        with patch.object(processor, "initialize", side_effect=_initialize):
            with pytest.raises(_Stop):
                processor.build_agent("q")
        trace = processor.trace
        assert seen["trace"] is trace
        assert trace.source == "answer"
        assert processor.request_id and trace.request_id == processor.request_id
        assert trace.user_id == "u1"
        assert [s.kind for s in trace.spans] == ["retrieval"]
        assert tracing.current_trace() is None

    def test_client_supplied_request_id_is_ignored(self):
        """Quotas count distinct request ids; a client must not choose its own."""
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({"request_id": "client-rid"}, {"sub": "u1"})
        with patch.object(processor, "initialize", side_effect=RuntimeError("stop")):
            with pytest.raises(RuntimeError):
                processor.build_agent("q")
        assert processor.request_id and processor.request_id != "client-rid"

    def test_refused_request_still_writes_its_trace(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({}, {"sub": "u1"})

        def _initialize():
            with tracing.span(tracing.KIND_RETRIEVAL, "retrieval"):
                pass

        with patch.object(processor, "initialize", side_effect=_initialize), patch.object(
            processor, "pre_fetch_docs", return_value=(None, None)
        ), patch.object(processor, "pre_fetch_tools", return_value=None), patch.object(
            processor, "create_agent", return_value=MagicMock()
        ), patch.object(processor, "_exposure_partition", return_value=([], [])):
            processor.build_agent("q")
        with _captured_flushes() as flushed:
            processor.flush_unclaimed_trace()
        (trace,) = flushed
        assert trace.status == "error"
        assert [s.kind for s in trace.spans] == ["retrieval"]

    def test_handed_off_trace_is_left_to_the_stream(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({}, {"sub": "u1"})
        processor.trace = tracing.start_trace(source="stream", capture_otel_context=False)
        assert processor.handoff_trace() is processor.trace
        with _captured_flushes() as flushed:
            processor.flush_unclaimed_trace()
        assert flushed == []

    def test_tracing_disabled_leaves_no_trace(self, monkeypatch):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        monkeypatch.setattr(settings, "TRACES_ENABLED", False)
        processor = StreamProcessor({}, {"sub": "u1"})
        with patch.object(processor, "initialize", side_effect=RuntimeError("stop")):
            with pytest.raises(RuntimeError):
                processor.build_agent("q")
        assert processor.trace is None
        assert processor.request_id


@pytest.mark.unit
class TestRouteFlushesRefusedRequests:
    def test_unauthorized_answer_request_writes_its_trace(self, mock_mongo_db, flask_app):
        """The route registers the flush, and the hook never replaces the response."""
        import json

        from flask_restx import Api

        from docsgpt.api.answer.routes.answer import answer_ns

        api = Api(flask_app)
        api.add_namespace(answer_ns)
        client = flask_app.test_client()
        processor = MagicMock()
        processor.decoded_token = None
        processor.flush_unclaimed_trace.return_value = "not a response"
        with patch(
            "docsgpt.api.answer.routes.answer.StreamProcessor", return_value=processor
        ), patch(
            "docsgpt.api.answer.routes.answer.AnswerResource.validate_request",
            return_value=None,
        ):
            resp = client.post(
                "/api/answer",
                data=json.dumps({"question": "q"}),
                content_type="application/json",
            )
        assert resp.status_code == 401
        processor.flush_unclaimed_trace.assert_called_once_with()
