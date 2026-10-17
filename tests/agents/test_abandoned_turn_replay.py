"""An earlier turn that ended on an approval pause is replayed with its text before its tool results.

A finished turn stores the answer it wrote after its tools, so it replays as
calls, results, then the answer. A turn the user walked away from while it
waited on an approval (retired as ``moved_on`` or ``expired``) stores only the
text written before its calls. Replayed after the results, that text read as a
plan that never ran, and a model told the user the calls it had made never
happened.
"""

from __future__ import annotations

import base64
import json
import types
from typing import Any, Dict, List, Optional

import pytest

from docsgpt.core.model_settings import ModelCapabilities

NARRATION = "I'll set up the webhook monitor and check the machine at the same time."
NOT_RUN = "Not run: the conversation moved on before this call was approved."


def _agent(history: List[Dict[str, Any]], *, responses_chain: Optional[str] = None):
    """A bare agent that only builds messages, over ``history``."""
    from docsgpt.agents.base import BaseAgent

    class _Agent(BaseAgent):
        def _gen_inner(self, query, log_context):
            yield from ()

    agent = _Agent.__new__(_Agent)
    agent.chat_history = history
    agent.compressed_summary = None
    agent.model_id = "model"
    agent.model_user_id = None
    agent.user = "user-1"
    agent.multimodal_content = None
    if responses_chain:
        agent.llm = types.SimpleNamespace(
            _uses_responses_api=lambda: True, responses_chain_key=lambda: responses_chain
        )
    else:
        agent.llm = types.SimpleNamespace(_uses_responses_api=lambda: False)
    return agent


def _call(call_id: str, name: str, result: Any, **extra: Any) -> Dict[str, Any]:
    return {
        "call_id": call_id,
        "tool_name": "tool",
        "action_name": name,
        "arguments": {"arg": call_id},
        "result": result,
        "status": "completed",
        **extra,
    }


def _not_run(call_id: str, name: str, reason: str = "moved_on") -> Dict[str, Any]:
    return _call(call_id, name, NOT_RUN, status="denied", not_run=reason)


def _abandoned_turn(**overrides: Any) -> Dict[str, Any]:
    """A turn retired by ``retire_paused_message``: complete, its waiting call not run."""
    turn = {
        "prompt": "Create a webhook link, then run a command on my machine.",
        "response": NARRATION,
        "tool_calls": [
            _call("call-1", "monitor_create", '{"monitor_id": "m-1"}'),
            _not_run("call-2", "run_command"),
        ],
        "metadata": {"pause_retired": "moved_on"},
    }
    turn.update(overrides)
    return turn


def _normal_turn(**overrides: Any) -> Dict[str, Any]:
    turn = {
        "prompt": "What is the weather?",
        "response": "It is sunny.",
        "tool_calls": [_call("call-9", "get_weather", "sunny")],
    }
    turn.update(overrides)
    return turn


def _roles(messages: List[Dict[str, Any]]) -> List[str]:
    return [m["role"] for m in messages]


@pytest.mark.unit
class TestAbandonedTurnReplay:
    def test_the_narration_comes_before_the_results_with_no_closing_message(self):
        messages = _agent([_abandoned_turn()])._build_messages("system", "Did you run anything?")

        assert _roles(messages) == ["system", "user", "assistant", "tool", "tool", "user"]
        carrier = messages[2]
        assert carrier["content"] == NARRATION
        assert [c["id"] for c in carrier["tool_calls"]] == ["call-1", "call-2"]
        assert [m["content"] for m in messages[3:5]] == ['{"monitor_id": "m-1"}', NOT_RUN]
        assert messages[-1] == {"role": "user", "content": "Did you run anything?"}

    def test_an_expired_pause_replays_the_same_way(self):
        turn = _abandoned_turn(
            tool_calls=[_call("call-1", "monitor_create", "ok"), _not_run("call-2", "run_command", "expired")],
            metadata={"pause_retired": "expired"},
        )
        messages = _agent([turn])._build_messages("system", "next")

        assert _roles(messages) == ["system", "user", "assistant", "tool", "tool", "user"]
        assert messages[2]["content"] == NARRATION

    def test_a_not_run_call_marks_the_turn_when_the_metadata_is_missing(self):
        """``not_run`` is written with ``pause_retired``; either one marks the turn."""
        turn = _abandoned_turn()
        del turn["metadata"]
        messages = _agent([turn])._build_messages("system", "next")

        assert _roles(messages) == ["system", "user", "assistant", "tool", "tool", "user"]
        assert messages[2]["content"] == NARRATION

    def test_a_turn_with_no_narration_ends_on_its_results(self):
        messages = _agent([_abandoned_turn(response="")])._build_messages("system", "next")

        assert _roles(messages) == ["system", "user", "assistant", "tool", "tool", "user"]
        assert messages[2]["content"] is None

    def test_every_round_rides_on_the_one_carrier_in_order(self):
        """Approval rounds are flattened on the message, as a finished turn's are."""
        turn = _abandoned_turn(
            response="Creating the monitor.\n\nDone. Now the command.",
            tool_calls=[
                _call("call-1", "monitor_create", "m-1"),
                _call("call-2", "monitor_create", "m-2"),
                _call("call-3", "run_command", "ready"),
                _not_run("call-4", "run_command"),
            ],
        )
        messages = _agent([turn])._build_messages("system", "next")

        assert _roles(messages) == ["system", "user", "assistant", "tool", "tool", "tool", "tool", "user"]
        assert messages[2]["content"] == "Creating the monitor.\n\nDone. Now the command."
        assert [c["id"] for c in messages[2]["tool_calls"]] == ["call-1", "call-2", "call-3", "call-4"]
        assert [m["tool_call_id"] for m in messages[3:7]] == ["call-1", "call-2", "call-3", "call-4"]

    def test_the_thought_rides_on_the_carrier_as_reasoning_content(self):
        """DeepSeek thinking mode rejects a replayed assistant message that drops it."""
        messages = _agent([_abandoned_turn(thought="Both are independent.")])._build_messages("system", "next")

        assert messages[2]["reasoning_content"] == "Both are independent."
        assert not any("reasoning_content" in m for m in messages[3:])

    def test_responses_reasoning_stays_on_the_carrier(self):
        reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "x", "summary": []}
        final = {"type": "reasoning", "id": "rs_2", "encrypted_content": "y", "summary": []}
        turn = _abandoned_turn(
            metadata={
                "pause_retired": "moved_on",
                "responses_state": {
                    "chain_key": "chain",
                    "reasoning_for_calls": {"call-1": [reasoning], "call-2": [reasoning]},
                    "reasoning_items": [reasoning, final],
                },
            }
        )
        messages = _agent([turn], responses_chain="chain")._build_messages("system", "next")

        assert _roles(messages) == ["system", "user", "assistant", "tool", "tool", "user"]
        assert messages[2]["responses_reasoning_items"] == [reasoning, final]
        assert not any("responses_reasoning_items" in m for m in messages[3:])

    def test_only_the_abandoned_turn_changes_in_a_mixed_history(self):
        messages = _agent([_normal_turn(), _abandoned_turn()])._build_messages("system", "next")

        assert _roles(messages) == [
            "system",
            "user", "assistant", "tool", "assistant",
            "user", "assistant", "tool", "tool",
            "user",
        ]
        assert messages[2]["content"] is None and messages[4]["content"] == "It is sunny."
        assert messages[6]["content"] == NARRATION


@pytest.mark.unit
class TestFinishedTurnReplayIsUnchanged:
    def test_calls_then_results_then_the_answer(self):
        messages = _agent([_normal_turn(thought="Look it up.")])._build_messages("system", "next")

        assert _roles(messages) == ["system", "user", "assistant", "tool", "assistant", "user"]
        assert messages[2]["content"] is None
        assert "reasoning_content" not in messages[2]
        assert messages[4] == {"role": "assistant", "content": "It is sunny.", "reasoning_content": "Look it up."}

    def test_a_denied_call_without_not_run_is_a_finished_turn(self):
        """The user denying a call is a decision the turn answered after, not an abandoned pause."""
        turn = _normal_turn(
            tool_calls=[_call("call-9", "run_command", "Tool denied by user", status="denied")],
            response="Understood, I won't run it.",
        )
        messages = _agent([turn])._build_messages("system", "next")

        assert _roles(messages) == ["system", "user", "assistant", "tool", "assistant", "user"]
        assert messages[4]["content"] == "Understood, I won't run it."

    def test_responses_final_reasoning_stays_on_the_answer(self):
        final = {"type": "reasoning", "id": "rs_2", "encrypted_content": "y", "summary": []}
        turn = _normal_turn(metadata={"responses_state": {"chain_key": "chain", "reasoning_items": [final]}})
        messages = _agent([turn], responses_chain="chain")._build_messages("system", "next")

        assert "responses_reasoning_items" not in messages[2]
        assert messages[4]["responses_reasoning_items"] == [final]


# ── the providers take the carrier: text and tool calls in one assistant message ──


def _replayed(**turn_overrides: Any) -> List[Dict[str, Any]]:
    return _agent([_abandoned_turn(**turn_overrides)])._build_messages("system", "Did you run anything?")


def _openai_llm(monkeypatch, flavor: str):
    from tests.llm.test_openai_responses import _make_llm

    return _make_llm(monkeypatch, ModelCapabilities(api_flavor=flavor, supports_tools=True))


@pytest.mark.unit
class TestProvidersTakeTheCarrier:
    def test_chat_completions_keeps_the_text_beside_the_calls(self, monkeypatch):
        llm = _openai_llm(monkeypatch, "chat_completions")
        cleaned = llm._clean_messages_openai(_replayed(thought="Both are independent."))

        assert _roles(cleaned) == ["system", "user", "assistant", "tool", "tool", "user"]
        carrier = cleaned[2]
        assert carrier["content"] == NARRATION
        assert carrier["reasoning_content"] == "Both are independent."
        assert [c["id"] for c in carrier["tool_calls"]] == ["call-1", "call-2"]

    def test_chat_completions_still_sends_a_bare_carrier_without_text(self, monkeypatch):
        llm = _openai_llm(monkeypatch, "chat_completions")
        cleaned = llm._clean_messages_openai(_replayed(response=""))

        assert cleaned[2]["content"] is None

    def test_responses_puts_the_text_before_the_reasoning_and_calls(self, monkeypatch):
        llm = _openai_llm(monkeypatch, "responses")
        reasoning = {"type": "reasoning", "id": "rs_1", "encrypted_content": "x", "summary": []}
        messages = _agent(
            [
                _abandoned_turn(
                    metadata={
                        "pause_retired": "moved_on",
                        "responses_state": {"chain_key": "chain", "reasoning_for_calls": {"call-1": [reasoning]}},
                    }
                )
            ],
            responses_chain="chain",
        )._build_messages("system", "Did you run anything?")
        items = llm._to_responses_input(llm._clean_messages_openai(messages))

        kinds = [item.get("type") or item.get("role") for item in items]
        assert kinds == [
            "system", "user", "assistant", "reasoning", "function_call", "function_call",
            "function_call_output", "function_call_output", "user",
        ]
        assert items[2] == {"role": "assistant", "content": [{"type": "output_text", "text": NARRATION}]}

    def test_responses_keeps_the_text_when_every_call_is_dropped(self, monkeypatch):
        """An orphaned call is dropped with its reasoning; the text it was written with stays."""
        llm = _openai_llm(monkeypatch, "responses")
        items = llm._to_responses_input([
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": NARRATION,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
                "responses_reasoning_items": [{"type": "reasoning", "id": "rs_1"}],
            },
            {"role": "user", "content": "next"},
        ])

        assert items == [
            {"role": "user", "content": [{"type": "input_text", "text": "q"}]},
            {"role": "assistant", "content": [{"type": "output_text", "text": NARRATION}]},
            {"role": "user", "content": [{"type": "input_text", "text": "next"}]},
        ]

    def test_anthropic_puts_the_text_block_before_the_tool_use(self):
        from docsgpt.llm.anthropic import AnthropicLLM

        mapped, system = AnthropicLLM._clean_messages_anthropic(_replayed())

        assert system == "system"
        assert _roles(mapped) == ["user", "assistant", "user"]
        assert [b["type"] for b in mapped[1]["content"]] == ["text", "tool_use", "tool_use"]
        assert mapped[1]["content"][0]["text"] == NARRATION
        assert [b["type"] for b in mapped[2]["content"]] == ["tool_result", "tool_result", "text"]

    def test_gemini_puts_the_text_part_before_the_function_calls(self):
        from docsgpt.llm.google_ai import GoogleLLM

        llm = GoogleLLM.__new__(GoogleLLM)
        llm.capabilities = None
        llm.model_id = "gemini-3.5-flash"
        contents, system = llm._clean_messages_google(_replayed(), "gemini-3.5-flash")

        assert system == "system"
        model = contents[1]
        assert model.role == "model"
        assert model.parts[0].text == NARRATION
        assert [p.function_call.name for p in model.parts[1:]] == ["monitor_create", "run_command"]
        assert [p.function_response.name for p in contents[2].parts if p.function_response] == [
            "monitor_create", "run_command",
        ]

    def test_gemini_keeps_the_thought_signature_on_the_first_call(self):
        from docsgpt.llm.google_ai import GoogleLLM

        llm = GoogleLLM.__new__(GoogleLLM)
        llm.capabilities = None
        llm.model_id = "gemini-3.5-flash"
        signature = base64.b64encode(b"sig").decode()
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": NARRATION,
                "tool_calls": [{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "t", "arguments": json.dumps({})},
                    "thought_signature": signature,
                }],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ]
        contents, _ = llm._clean_messages_google(messages, "gemini-3.5-flash")

        text, call = contents[1].parts
        assert text.text == NARRATION
        assert call.function_call.name == "t" and call.thought_signature == b"sig"


@pytest.mark.unit
class TestCompressionSummaryReadsTheTurnInOrder:
    def _formatted(self, queries: List[Dict[str, Any]]) -> str:
        from docsgpt.api.answer.services.compression.prompt_builder import CompressionPromptBuilder

        return CompressionPromptBuilder()._format_conversation(queries)

    def test_an_abandoned_turn_shows_its_text_before_its_calls(self):
        text = self._formatted([_abandoned_turn(thought="Both are independent.")])

        assert text.index("Agent Thought: Both are independent.") < text.index(f"Assistant: {NARRATION}")
        assert text.index(f"Assistant: {NARRATION}") < text.index("Tool Calls:")
        assert text.count("Assistant:") == 1
        assert "[denied] → Not run:" in text

    def test_a_finished_turn_still_shows_its_answer_after_its_calls(self):
        text = self._formatted([_normal_turn()])

        assert text.index("Tool Calls:") < text.index("Assistant: It is sunny.")
