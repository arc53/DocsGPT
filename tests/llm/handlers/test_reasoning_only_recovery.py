"""Regression tests for the silent-loss recovery in ``handle_streaming``.

Bug the recovery guards against: a stream ends cleanly (``finish_reason=stop``
or plain exhaustion) after emitting only reasoning ("thought") chunks and
zero visible content — observed in prod when cross-provider fallback lands
on a model that returns ``reasoning_content`` deltas without any ``content``
deltas. Downstream then saves ``response=""`` and marks the message
``status=complete``: the user sees nothing.

The recovery is a plain, bounded re-send of the same request (same
messages, same tools, no system nudge). Behavior-preserving because a
system message like "produce final answer now, no more thinking or tools"
measurably shortens the model's reasoning by ~30% in A/B tests, which
hurts answer quality on the common path more than the tail failure rate
justifies. Critically: does not fire when the model genuinely chose to
say nothing (no thoughts either), and does not recurse if the recovery
itself also lands reasoning-only.
"""

from types import SimpleNamespace
from typing import Any, Dict, Generator, List

import pytest

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


# Scripted streams. Each element is either:
#  * a str                                    -> content delta (yielded)
#  * {"type": "thought", "thought": "..."}    -> reasoning delta
#  * "STOP"                                   -> synthesises a stop choice
# The scripts mirror what OpenAILLM._raw_gen_stream / _responses_gen_stream
# actually yield to the handler.

STOP_SENTINEL = "__STOP__"


def _stop_choice():
    """Provider-agnostic stop-finish chunk (matches OpenAI chat/completions
    delta with content=None and finish_reason='stop')."""
    delta = SimpleNamespace(content=None, tool_calls=None)
    return SimpleNamespace(delta=delta, finish_reason="stop", message=None)


class ScriptedHandler(LLMHandler):
    """Concrete LLMHandler that iterates a supplied script.

    Note: because ``FakeLLM._responding_provider = "openai"`` (set below),
    ``LLMHandler._parse_for_response`` routes choice-object parsing to
    ``OpenAILLMHandler.parse_response`` rather than to this class's
    ``parse_response``. The scripted stop chunks are shape-compatible
    with an OpenAI chat/completions delta (``SimpleNamespace(delta=…,
    finish_reason="stop")``) so OpenAI's parser handles them cleanly.
    ``parse_response`` here exists only for the abstract-class contract
    and as a fallback if a test flips the provider off.
    """

    def parse_response(self, response: Any) -> LLMResponse:
        # Only reached when ``agent.llm._responding_provider`` is None /
        # non-string; otherwise ``_parse_for_response`` routes to the
        # per-provider handler.
        finish = getattr(response, "finish_reason", "") or ""
        delta = getattr(response, "delta", None)
        content = getattr(delta, "content", None) if delta else None
        return LLMResponse(
            content=content or "",
            tool_calls=[],
            finish_reason=finish,
            raw_response=response,
        )

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {"role": "tool", "tool_call_id": tool_call.id, "content": str(result)}

    def _iterate_stream(self, response: Any) -> Generator:
        for item in response:
            if item == STOP_SENTINEL:
                yield _stop_choice()
            else:
                yield item


def _script_generator(script):
    """Return a fresh generator each time (agent.llm.gen_stream is called
    for the recovery re-stream)."""

    def factory():
        for item in script:
            yield item

    return factory


class FakeLLM:
    """Minimal agent.llm stand-in — recovery reads ``model_id``, calls
    ``gen_stream`` for the re-stream, and _handle_response consults it.
    Tracks how many times ``gen_stream`` was invoked and what ``tools``
    argument it received (so tests can pin that the recovery preserves
    the original tools list — no ``tools=None`` behavior change)."""

    def __init__(self, recovery_script=None):
        self.model_id = "test-model"
        self._responding_provider = "openai"
        self._fallback_llm = None
        self._stream_reached_finish = False
        self._recovery_script = recovery_script
        self.gen_stream_calls = 0
        self.gen_stream_tools_seen = []

    def gen_stream(self, model, messages, tools=None, **kwargs):
        self.gen_stream_calls += 1
        self.gen_stream_tools_seen.append(tools)
        # First recovery call returns the scripted stream. Subsequent
        # calls (there shouldn't be any) return empty — the recovery is
        # supposed to be one-shot.
        if self._recovery_script is None:
            return iter([])
        script = self._recovery_script
        self._recovery_script = None  # one-shot
        return iter(script)


def _fake_agent(recovery_script=None):
    llm = FakeLLM(recovery_script=recovery_script)
    return SimpleNamespace(llm=llm, model_id="test-model", tools=None), llm


def _drain(handler, agent, primary_script) -> List[Any]:
    """Feed ``primary_script`` into handle_streaming and return every event
    it yielded downstream. The response arg is any iterable — the handler
    calls ``_iterate_stream(response)`` on it."""
    events = []
    for event in handler.handle_streaming(agent, iter(primary_script), {}, []):
        events.append(event)
    return events


class TestReasoningOnlyRecovery:
    def test_recovers_when_stream_ends_reasoning_only(self):
        """Primary emits thoughts + finish=stop with no content →
        recovery call fires and its content lands as visible chunks."""
        primary = [
            {"type": "thought", "thought": "Composing analysis..."},
            {"type": "thought", "thought": " almost done."},
            STOP_SENTINEL,
        ]
        recovery = ["Final answer: ", "hello world.", STOP_SENTINEL]
        agent, llm = _fake_agent(recovery_script=recovery)
        handler = ScriptedHandler()

        events = _drain(handler, agent, primary)

        thoughts = [e for e in events if isinstance(e, dict) and e.get("type") == "thought"]
        strs = [e for e in events if isinstance(e, str)]

        assert len(thoughts) == 2  # primary thoughts flow through
        assert "".join(strs) == "Final answer: hello world."
        assert llm.gen_stream_calls == 1  # exactly one recovery call

    def test_no_recovery_when_answer_already_yielded(self):
        """Primary emits some content before stop → no recovery, no extra
        provider call."""
        primary = [
            {"type": "thought", "thought": "Thinking briefly..."},
            "The answer is 42.",
            STOP_SENTINEL,
        ]
        agent, llm = _fake_agent(recovery_script=["SHOULD NOT FIRE", STOP_SENTINEL])
        handler = ScriptedHandler()

        events = _drain(handler, agent, primary)

        strs = [e for e in events if isinstance(e, str)]
        assert "".join(strs) == "The answer is 42."
        assert llm.gen_stream_calls == 0  # no recovery

    def test_no_recovery_when_reasoning_buffer_empty(self):
        """Primary emits only finish=stop (model genuinely said nothing)
        → no recovery; a rescue call would just repeat the same failure
        and burn budget for nothing."""
        primary = [STOP_SENTINEL]
        agent, llm = _fake_agent(recovery_script=["SHOULD NOT FIRE", STOP_SENTINEL])
        handler = ScriptedHandler()

        events = _drain(handler, agent, primary)

        assert events == []  # nothing to yield, nothing recovered
        assert llm.gen_stream_calls == 0

    def test_recovery_that_also_reasons_only_does_not_recurse(self):
        """If the recovery stream itself ends reasoning-only, the second
        pass must NOT trigger another recovery (bounded to one attempt
        per outer stream via ``_answer_recovered``)."""
        primary = [
            {"type": "thought", "thought": "primary reasoning"},
            STOP_SENTINEL,
        ]
        # Recovery emits more thoughts and stops — still no content. The
        # outer recovery guard must catch that we already tried, so we
        # exit with 0 answers instead of looping.
        recovery = [
            {"type": "thought", "thought": "recovery reasoning"},
            STOP_SENTINEL,
        ]
        agent, llm = _fake_agent(recovery_script=recovery)
        handler = ScriptedHandler()

        events = _drain(handler, agent, primary)

        strs = [e for e in events if isinstance(e, str)]
        assert strs == []  # no answer surfaced (bug still visible)
        assert llm.gen_stream_calls == 1  # but exactly one recovery, not many

    def test_recovery_is_a_plain_resend_no_nudge_added(self):
        """The recovery must NOT add a system nudge to messages — a
        behavior-modifying instruction ("no thinking, write the answer")
        measurably shortens the model's reasoning, hurting answer
        quality on the common path. The re-send is deliberately
        behavior-preserving: same messages, same tools."""
        primary = [
            {"type": "thought", "thought": "reasoning..."},
            STOP_SENTINEL,
        ]
        recovery = ["recovered", STOP_SENTINEL]
        agent, llm = _fake_agent(recovery_script=recovery)

        seen_messages: List[List[Dict]] = []
        orig_gen_stream = llm.gen_stream

        def capturing_gen_stream(model, messages, tools=None, **kwargs):
            seen_messages.append(list(messages))
            return orig_gen_stream(model, messages, tools=tools, **kwargs)

        llm.gen_stream = capturing_gen_stream
        starting = [{"role": "user", "content": "hi"}]
        handler = ScriptedHandler()

        list(handler.handle_streaming(agent, iter(primary), {}, starting))

        assert len(seen_messages) == 1, "recovery must fire exactly once"
        assert seen_messages[0] == starting, (
            "recovery must forward the original messages verbatim — no "
            "system nudge, no other mutation"
        )

    def test_recovery_preserves_agent_tools(self):
        """The recovery must forward ``agent.tools`` unchanged — passing
        ``tools=None`` would prevent the model from calling further tools
        even when they might legitimately be part of finishing the
        answer, and is another behavior change we want to avoid."""
        primary = [
            {"type": "thought", "thought": "reasoning..."},
            STOP_SENTINEL,
        ]
        recovery = ["recovered", STOP_SENTINEL]
        agent, llm = _fake_agent(recovery_script=recovery)
        agent.tools = [{"type": "function", "function": {"name": "search"}}]
        handler = ScriptedHandler()

        list(handler.handle_streaming(agent, iter(primary), {}, []))

        assert llm.gen_stream_calls == 1
        assert llm.gen_stream_tools_seen == [agent.tools]

    @pytest.mark.parametrize(
        "primary_last_chunk", [STOP_SENTINEL, None],
        ids=["explicit-stop", "no-stop-chunk-just-exhaustion"],
    )
    def test_recovery_fires_on_both_explicit_stop_and_bare_exhaustion(
        self, primary_last_chunk,
    ):
        """Providers that emit finish_reason=stop AND providers whose
        stream just exhausts (no parseable stop chunk) must both trigger
        recovery when reasoning-only."""
        primary = [{"type": "thought", "thought": "hmm"}]
        if primary_last_chunk:
            primary.append(primary_last_chunk)
        recovery = ["ok done", STOP_SENTINEL]
        agent, llm = _fake_agent(recovery_script=recovery)
        handler = ScriptedHandler()

        events = _drain(handler, agent, primary)
        strs = [e for e in events if isinstance(e, str)]
        assert "".join(strs) == "ok done"
        assert llm.gen_stream_calls == 1

    @pytest.mark.parametrize(
        "attr,value",
        [("json_schema", {"type": "object"}), ("json_object", True)],
        ids=["json_schema", "json_object"],
    )
    def test_no_recovery_when_structured_output_configured(self, attr, value):
        """Structured-output agents must NOT trigger recovery. The
        primary call was built with response_format/response_schema; the
        recovery here would drop those (it doesn't rebuild _llm_gen's
        kwargs), so a rescue would emit unconstrained content that
        downstream schema validation rejects. Better to surface the
        empty answer than silently violate the contract."""
        primary = [
            {"type": "thought", "thought": "reasoning..."},
            STOP_SENTINEL,
        ]
        recovery = ["SHOULD NOT FIRE", STOP_SENTINEL]
        agent, llm = _fake_agent(recovery_script=recovery)
        setattr(agent, attr, value)
        handler = ScriptedHandler()

        events = _drain(handler, agent, primary)

        assert llm.gen_stream_calls == 0
        assert not [e for e in events if isinstance(e, str)]

    def test_recovery_forwards_agent_llm_params(self):
        """Sampling params (temperature, max_tokens, top_p, …) live on
        the agent, and the primary call gets them via ``_llm_gen``. The
        recovery must forward them too so the rescued answer matches
        the intended output distribution — otherwise you'd get a
        default-temperature response for an agent configured with,
        say, temperature=0.1."""
        primary = [
            {"type": "thought", "thought": "reasoning..."},
            STOP_SENTINEL,
        ]
        recovery = ["ok", STOP_SENTINEL]
        agent, llm = _fake_agent(recovery_script=recovery)
        agent.llm_params = {"temperature": 0.1, "max_tokens": 256}

        seen_kwargs: List[Dict] = []
        orig = llm.gen_stream

        def capturing(model, messages, tools=None, **kwargs):
            seen_kwargs.append(dict(kwargs))
            return orig(model, messages, tools=tools, **kwargs)

        llm.gen_stream = capturing
        handler = ScriptedHandler()
        list(handler.handle_streaming(agent, iter(primary), {}, []))

        assert len(seen_kwargs) == 1
        assert seen_kwargs[0]["temperature"] == 0.1
        assert seen_kwargs[0]["max_tokens"] == 256

    def test_recovery_forces_tools_none_at_cap(self):
        """When ``_iteration >= MAX_TOOL_ITERATIONS`` the current call
        is the cap-triggered finalize round: it was sent with
        ``tools=None`` plus a "no more tools" system message. If it
        reasons-only-stops, the recovery MUST NOT reopen tools — the
        finalize contract exists precisely so no more tool calls run."""
        from application.llm.handlers.base import MAX_TOOL_ITERATIONS

        primary = [
            {"type": "thought", "thought": "reasoning..."},
            STOP_SENTINEL,
        ]
        recovery = ["ok", STOP_SENTINEL]
        agent, llm = _fake_agent(recovery_script=recovery)
        agent.tools = [{"type": "function", "function": {"name": "search"}}]
        handler = ScriptedHandler()

        list(handler.handle_streaming(
            agent, iter(primary), {}, [],
            _iteration=MAX_TOOL_ITERATIONS,
        ))

        assert llm.gen_stream_calls == 1
        assert llm.gen_stream_tools_seen == [None], (
            "recovery at MAX_TOOL_ITERATIONS must pass tools=None to "
            "honour the finalize round's contract"
        )

    def test_recovery_forces_tools_none_when_context_limit_reached(self):
        """Same contract as the cap case, different trigger: when the
        agent flagged ``context_limit_reached=True`` mid-loop, the
        preceding round was already sent with ``tools=None`` + a wrap-
        up system message. Recovery must not reopen tools there either."""
        primary = [
            {"type": "thought", "thought": "reasoning..."},
            STOP_SENTINEL,
        ]
        recovery = ["ok", STOP_SENTINEL]
        agent, llm = _fake_agent(recovery_script=recovery)
        agent.tools = [{"type": "function", "function": {"name": "search"}}]
        agent.context_limit_reached = True
        handler = ScriptedHandler()

        list(handler.handle_streaming(agent, iter(primary), {}, []))

        assert llm.gen_stream_calls == 1
        assert llm.gen_stream_tools_seen == [None]
