"""Regression tests for cross-provider fallback tool-call parsing.

``BaseLLM`` performs model fallback *below* the agent: when a primary
model (e.g. Google) fails, ``BaseLLM._stream_with_fallback`` transparently
fails over to a backup model (e.g. an OpenAI-compatible deployment) inside
the same ``gen_stream`` call. The agent, however, picked its
``LLMHandler`` from the *primary* provider and never switches it.

Before the fix the Google handler tried to ``parse_response`` the
OpenAI-format chunks the backup emits; an OpenAI streaming ``choice`` has
neither ``candidates`` nor ``function_call``, so the Google parser returned
an empty ``finish_reason="stop"`` response — silently dropping the tool
call. The visible symptom: the agent streams its first text and then stops
instead of running the tool loop.

These tests pin down that ``parse_response`` follows the model that
actually responded (tracked via ``BaseLLM._responding_provider``).
"""

from types import SimpleNamespace

from application.llm.handlers.google import GoogleLLMHandler
from application.llm.handlers.openai import OpenAILLMHandler


def _openai_tool_chunk(name, arguments, call_id="call_1", finish_reason="tool_calls"):
    """Build an OpenAI-style streaming ``choice`` carrying a tool call.

    Mirrors what ``OpenAILLM._raw_gen_stream`` yields for a tool call: a
    ``choice`` object with a ``.delta.tool_calls`` list and a
    ``finish_reason``.
    """
    fn = SimpleNamespace(name=name, arguments=arguments)
    tc = SimpleNamespace(id=call_id, function=fn, index=0, type="function")
    delta = SimpleNamespace(content=None, tool_calls=[tc])
    return SimpleNamespace(delta=delta, finish_reason=finish_reason)


def _agent_with_responder(provider):
    return SimpleNamespace(llm=SimpleNamespace(_responding_provider=provider))


class TestParseRouting:
    """``_parse_for_response`` resolves the handler from the responding
    provider, not the one the handler was constructed for."""

    def test_documents_the_bug_google_parser_drops_openai_tool_call(self):
        # Baseline: the Google parser cannot read an OpenAI choice. This is
        # exactly why a naive (un-routed) parse loses the tool call.
        chunk = _openai_tool_chunk("search", '{"q": "x"}')
        parsed = GoogleLLMHandler().parse_response(chunk)
        assert parsed.tool_calls == []
        assert parsed.finish_reason == "stop"

    def test_google_handler_routes_openai_chunk_to_openai_parser(self):
        handler = GoogleLLMHandler()
        agent = _agent_with_responder("openai")
        chunk = _openai_tool_chunk("search", '{"q": "x"}')

        parsed = handler._parse_for_response(agent, chunk)

        assert parsed.finish_reason == "tool_calls"
        assert [tc.name for tc in parsed.tool_calls] == ["search"]
        assert parsed.tool_calls[0].arguments == '{"q": "x"}'

    def test_handler_for_provider_reuses_self_when_provider_matches(self):
        handler = GoogleLLMHandler()
        # Same provider family → reuse self (no behaviour change on the
        # common no-fallback path).
        assert handler._handler_for_provider("google") is handler

    def test_handler_for_provider_returns_openai_for_openai(self):
        handler = GoogleLLMHandler()
        resolved = handler._handler_for_provider("openai")
        assert isinstance(resolved, OpenAILLMHandler)
        assert resolved is not handler
        # Cached: same instance on the second lookup.
        assert handler._handler_for_provider("openai") is resolved

    def test_non_string_provider_falls_back_to_self_parse(self):
        # A Mock/None responder (or any code path that never set the
        # attribute) must not trigger routing — parse with self.
        handler = OpenAILLMHandler()
        agent = SimpleNamespace(llm=SimpleNamespace())  # no _responding_provider
        chunk = _openai_tool_chunk("search", "{}")
        parsed = handler._parse_for_response(agent, chunk)
        assert [tc.name for tc in parsed.tool_calls] == ["search"]


class TestStreamingLoopContinuesUnderFallback:
    """End-to-end: ``handle_streaming`` must run the tool loop when the
    responding model is a different provider than the handler's own."""

    def _make_agent(self, follow_up_chunks):
        agent = SimpleNamespace()
        agent.model_id = "primary-model"
        agent.tools = []
        agent.context_limit_reached = False
        agent._check_context_limit = lambda *a, **k: False
        agent._pending_continuation = None

        llm = SimpleNamespace()
        llm.model_id = "backup-model"
        # Responding model is OpenAI-compatible even though the handler is
        # Google — this is the cross-provider fallback condition.
        llm._responding_provider = "openai"
        llm.gen_stream = lambda **kwargs: iter(follow_up_chunks)
        agent.llm = llm

        tool_executor = SimpleNamespace()
        tool_executor.check_pause = lambda *a, **k: None
        tool_executor._name_to_tool = {}
        agent.tool_executor = tool_executor

        executed = []

        def fake_execute(tools_dict, call):
            executed.append(call)
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("tool result", call.id)

        agent._execute_tool_action = fake_execute
        agent._executed_calls = executed
        return agent

    def test_tool_call_executed_not_dropped(self):
        handler = GoogleLLMHandler()
        # The backup (OpenAI) streams a bit of text, then a tool call.
        stream = [
            "Let me search for relevant provisions",
            _openai_tool_chunk("search", '{"q": "hipoteka"}'),
        ]
        # After the tool runs, the follow-up turn just finishes with text.
        agent = self._make_agent(follow_up_chunks=["Here is the answer."])

        results = list(handler.handle_streaming(agent, iter(stream), {"1": {"name": "t"}}, []))

        # The tool call survived the cross-provider boundary and executed.
        assert len(agent._executed_calls) == 1
        assert agent._executed_calls[0].name == "search"
        # The loop continued: first text + follow-up text both streamed.
        assert "Let me search for relevant provisions" in results
        assert "Here is the answer." in results
