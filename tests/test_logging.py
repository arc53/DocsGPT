from unittest.mock import patch

import pytest

from application.logging import build_stack_data


@pytest.mark.unit
class TestBuildStackData:

    def test_raises_on_none_obj(self):
        with pytest.raises(ValueError, match="cannot be None"):
            build_stack_data(None)

    def test_auto_discovers_attributes(self):
        class Obj:
            name = "test"
            count = 5

        result = build_stack_data(Obj())
        assert result["name"] == "test"
        assert result["count"] == 5

    def test_include_attributes(self):
        class Obj:
            name = "test"
            count = 5
            hidden = "secret"

        result = build_stack_data(Obj(), include_attributes=["name"])
        assert result["name"] == "test"
        assert "hidden" not in result

    def test_exclude_attributes(self):
        class Obj:
            pass

        obj = Obj()
        obj.name = "test"
        obj.secret = "hidden"
        result = build_stack_data(
            obj,
            include_attributes=["name", "secret"],
            exclude_attributes=["secret"],
        )
        assert "secret" not in result
        assert result["name"] == "test"

    def test_list_of_dicts(self):
        class Obj:
            pass

        obj = Obj()
        obj.items = [{"a": 1}, {"b": 2}]
        result = build_stack_data(obj, include_attributes=["items"])
        assert result["items"] == [{"a": 1}, {"b": 2}]

    def test_list_of_objects(self):
        class Inner:
            def __init__(self, v):
                self.val = v

        class Obj:
            pass

        obj = Obj()
        obj.items = [Inner(1), Inner(2)]
        result = build_stack_data(obj, include_attributes=["items"])
        assert result["items"] == [{"val": 1}, {"val": 2}]

    def test_list_of_strings(self):
        class Obj:
            pass

        obj = Obj()
        obj.tags = [1, 2, 3]
        result = build_stack_data(obj, include_attributes=["tags"])
        assert result["tags"] == ["1", "2", "3"]

    def test_dict_attribute(self):
        class Obj:
            pass

        obj = Obj()
        obj.meta = {"key": 123}
        result = build_stack_data(obj, include_attributes=["meta"])
        assert result["meta"] == {"key": "123"}

    def test_none_attribute_skipped(self):
        class Obj:
            pass

        obj = Obj()
        obj.empty = None
        result = build_stack_data(obj, include_attributes=["empty"])
        assert "empty" not in result

    def test_custom_data_merged(self):
        class Obj:
            name = "test"

        result = build_stack_data(
            Obj(),
            include_attributes=["name"],
            custom_data={"extra": "val"},
        )
        assert result["extra"] == "val"

    def test_attribute_error_handled(self):
        class Obj:
            pass

        result = build_stack_data(Obj(), include_attributes=["nonexistent"])
        assert result == {}


@pytest.mark.unit
class TestLogActivity:

    def test_log_activity_decorator_yields(self):
        from application.logging import log_activity

        class FakeAgent:
            endpoint = "test"
            user = "user1"
            user_api_key = "key1"
            query = "hi"

        @log_activity()
        def my_gen(agent, log_context=None):
            yield "chunk1"
            yield "chunk2"

        with patch("application.logging._log_activity_to_db"):
            result = list(my_gen(FakeAgent()))
        assert result == ["chunk1", "chunk2"]

    def test_log_activity_handles_exception(self):
        from application.logging import log_activity

        class FakeAgent:
            endpoint = "test"
            user = "user1"
            user_api_key = ""

        @log_activity()
        def failing_gen(agent, log_context=None):
            yield "ok"
            raise RuntimeError("boom")

        with patch("application.logging._log_activity_to_db"), pytest.raises(
            RuntimeError, match="boom"
        ):
            list(failing_gen(FakeAgent()))

    def test_log_activity_emits_lifecycle_events(self, caplog):
        import logging as _logging

        from application.logging import log_activity

        class FakeAgent:
            endpoint = "test"
            user = "user1"
            user_api_key = "k"
            query = "q"
            agent_id = "agent-7"
            conversation_id = "conv-3"

        @log_activity()
        def gen(agent, log_context=None):
            yield "x"

        with patch("application.logging._log_activity_to_db"), \
                caplog.at_level(_logging.INFO, logger="root"):
            list(gen(FakeAgent()))

        messages = [r.message for r in caplog.records]
        assert "activity_started" in messages
        assert "activity_finished" in messages

        started = next(r for r in caplog.records if r.message == "activity_started")
        finished = next(r for r in caplog.records if r.message == "activity_finished")

        assert started.endpoint == "test"
        assert started.user_id == "user1"
        assert started.agent_id == "agent-7"
        assert started.conversation_id == "conv-3"
        assert started.parent_activity_id is None  # top-level activity

        assert finished.activity_id == started.activity_id
        assert finished.status == "ok"
        assert isinstance(finished.duration_ms, int)
        assert finished.duration_ms >= 0
        assert finished.error_class is None

    def test_log_activity_records_parent_activity_id_when_nested(self, caplog):
        # Sub-agents / workflow_agents wrap an outer @log_activity gen;
        # the inner activity_started event must link to the outer's id.
        import logging as _logging

        from application.logging import log_activity

        class FakeAgent:
            endpoint = "outer"
            user = "user1"
            user_api_key = ""
            query = ""

        class InnerAgent:
            endpoint = "inner"
            user = "user1"
            user_api_key = ""
            query = ""

        @log_activity()
        def inner_gen(agent, log_context=None):
            yield "i"

        @log_activity()
        def outer_gen(agent, log_context=None):
            yield from inner_gen(InnerAgent())

        with patch("application.logging._log_activity_to_db"), \
                caplog.at_level(_logging.INFO, logger="root"):
            list(outer_gen(FakeAgent()))

        starts = [r for r in caplog.records if r.message == "activity_started"]
        assert len(starts) == 2
        outer_start, inner_start = starts
        assert outer_start.endpoint == "outer"
        assert outer_start.parent_activity_id is None
        assert inner_start.endpoint == "inner"
        assert inner_start.parent_activity_id == outer_start.activity_id

    def test_log_activity_records_error_status_on_failure(self, caplog):
        import logging as _logging

        from application.logging import log_activity

        class FakeAgent:
            endpoint = "boom"
            user = "user1"
            user_api_key = ""
            query = ""

        @log_activity()
        def failing(agent, log_context=None):
            yield "before"
            raise ValueError("bad thing")

        with patch("application.logging._log_activity_to_db"), \
                caplog.at_level(_logging.INFO, logger="root"), \
                pytest.raises(ValueError):
            list(failing(FakeAgent()))

        finished = next(r for r in caplog.records if r.message == "activity_finished")
        assert finished.status == "error"
        assert finished.error_class == "ValueError"

    def test_log_activity_emits_response_summary_aggregates(self, caplog):
        # Replaces the ``agent_response`` event that ``run_agent_logic``
        # used to emit only on the Celery webhook path: every Flask
        # activity now gets the same aggregates on ``activity_finished``.
        import logging as _logging

        from application.logging import log_activity

        class FakeAgent:
            endpoint = "stream"
            user = "user1"
            user_api_key = ""
            query = "q"

        @log_activity()
        def streaming(agent, log_context=None):
            yield {"answer": "Hello "}
            yield {"answer": "world"}
            yield {"thought": "thinking..."}
            yield {"sources": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
            yield {"tool_calls": [{"name": "search"}, {"name": "fetch"}]}
            yield "ignored-non-dict"
            yield {"unrecognised": "noop"}

        with patch("application.logging._log_activity_to_db"), \
                caplog.at_level(_logging.INFO, logger="root"):
            list(streaming(FakeAgent()))

        finished = next(r for r in caplog.records if r.message == "activity_finished")
        assert finished.answer_length == len("Hello world")
        assert finished.thought_length == len("thinking...")
        assert finished.source_count == 3
        assert finished.tool_call_count == 2

    def test_log_activity_aggregates_initialise_to_zero(self, caplog):
        # No yields → summary fields still present and zero (so Axiom
        # schemas don't get a missing-field hole on empty activities).
        import logging as _logging

        from application.logging import log_activity

        class FakeAgent:
            endpoint = "stream"
            user = "user1"
            user_api_key = ""
            query = ""

        @log_activity()
        def empty(agent, log_context=None):
            return
            yield  # pragma: no cover — generator marker

        with patch("application.logging._log_activity_to_db"), \
                caplog.at_level(_logging.INFO, logger="root"):
            list(empty(FakeAgent()))

        finished = next(r for r in caplog.records if r.message == "activity_finished")
        assert finished.answer_length == 0
        assert finished.thought_length == 0
        assert finished.source_count == 0
        assert finished.tool_call_count == 0


@pytest.mark.unit
class TestAccumulateResponseSummary:
    """Direct coverage of the dispatch table — easier to enumerate edge
    cases here than in end-to-end ``log_activity`` tests."""

    def _ctx(self):
        from application.logging import LogContext

        return LogContext(
            endpoint="e", activity_id="a", user="u", api_key="k", query="q"
        )

    def test_answer_appends_length(self):
        from application.logging import _accumulate_response_summary

        ctx = self._ctx()
        _accumulate_response_summary({"answer": "abcd"}, ctx)
        _accumulate_response_summary({"answer": "ef"}, ctx)
        assert ctx.answer_length == 6
        assert ctx.thought_length == 0

    def test_non_dict_items_are_ignored(self):
        from application.logging import _accumulate_response_summary

        ctx = self._ctx()
        for item in ("string", 123, None, ["list"], object()):
            _accumulate_response_summary(item, ctx)
        assert ctx.answer_length == 0
        assert ctx.source_count == 0

    def test_sources_must_be_list(self):
        # A malformed payload (sources=str) shouldn't crash the
        # accumulator — drop it silently rather than half-count it.
        from application.logging import _accumulate_response_summary

        ctx = self._ctx()
        _accumulate_response_summary({"sources": "not-a-list"}, ctx)
        assert ctx.source_count == 0

    def test_tool_calls_counted(self):
        from application.logging import _accumulate_response_summary

        ctx = self._ctx()
        _accumulate_response_summary(
            {"tool_calls": [{"name": "a"}, {"name": "b"}]}, ctx
        )
        assert ctx.tool_call_count == 2


