"""Responses API prompt-cache continuity and context counting.

GPT-5.6 and later cache only at breakpoints. A turn that resends its history
unchained (after a compression, a restart, or a chain past its budget) used to
replay each earlier turn's calls as one batch, which renders differently from
the round-by-round live turn, so nothing past the system prompt was read from
the cache. And the reasoning every replayed call carries was never counted, so
the context checks saw half of what the provider was sent.
"""

from __future__ import annotations

import types
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.core.model_settings import ModelCapabilities

pytestmark = pytest.mark.unit


def _make_llm(monkeypatch, *, breakpoints: bool, store: bool = False):
    monkeypatch.setattr("docsgpt.llm.openai.OpenAI", MagicMock())
    monkeypatch.setattr("docsgpt.llm.openai.StorageCreator", types.SimpleNamespace(get_storage=lambda: None))
    monkeypatch.setattr(
        "docsgpt.llm.openai.settings",
        types.SimpleNamespace(
            OPENAI_API_KEY="k", API_KEY="k", OPENAI_BASE_URL="", AZURE_DEPLOYMENT_NAME="dep",
            OPENAI_RESPONSES_STORE=store, OPENAI_REASONING_SUMMARY="auto",
            OPENAI_RESPONSES_TRUNCATION_AUTO=False, OPENAI_PROMPT_CACHE_KEY=False,
            OPENAI_PROMPT_CACHE_RETENTION=None,
        ),
    )
    from docsgpt.llm.openai import OpenAILLM

    llm = OpenAILLM(api_key="k")
    llm.capabilities = ModelCapabilities(
        supports_tools=True, api_flavor="responses", prompt_cache_breakpoints=breakpoints
    )
    return llm


def _agent(history: List[Dict[str, Any]], *, chain: str = "chain-1", llm: Any = None):
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
    agent.llm = llm or types.SimpleNamespace(_uses_responses_api=lambda: True, responses_chain_key=lambda: chain)
    return agent


def _reasoning(item_id: str, chars: int = 800) -> Dict[str, Any]:
    return {"type": "reasoning", "id": item_id, "summary": [], "encrypted_content": "e" * chars}


def _call(call_id: str) -> Dict[str, Any]:
    return {"call_id": call_id, "tool_name": "code", "action_name": "run_code",
            "arguments": {"code": call_id}, "result": f"out {call_id}"}


def _turn(*, rounds: List[List[str]], record_rounds: bool, chain: str = "chain-1") -> Dict[str, Any]:
    """A finished turn whose calls ran in ``rounds``, each round sharing one reasoning item."""
    reasoning_for_calls = {cid: [_reasoning(f"rs_{n}")] for n, ids in enumerate(rounds) for cid in ids}
    state = {"chain_key": chain, "reasoning_for_calls": reasoning_for_calls,
             "reasoning_items": [_reasoning("rs_final")]}
    if record_rounds:
        state["call_rounds"] = rounds
    return {
        "prompt": "run the pipeline",
        "response": "done",
        "tool_calls": [_call(cid) for ids in rounds for cid in ids],
        "metadata": {"responses_state": state},
    }


class TestToolCallRounds:
    def test_recorded_rounds_are_used(self):
        from docsgpt.agents.base import _tool_call_rounds

        state = {"call_rounds": [["a", "b"], ["c"]], "reasoning_for_calls": {}}
        assert _tool_call_rounds(["a", "b", "c"], state) == [[0, 1], [2]]

    def test_older_rows_are_grouped_by_their_shared_reasoning(self):
        from docsgpt.agents.base import _tool_call_rounds

        state = {"reasoning_for_calls": {"a": [{"id": "r1"}], "b": [{"id": "r1"}], "c": [{"id": "r2"}]}}
        assert _tool_call_rounds(["a", "b", "c"], state) == [[0, 1], [2]]

    def test_a_call_with_no_round_information_stays_with_the_round_before(self):
        from docsgpt.agents.base import _tool_call_rounds

        state = {"reasoning_for_calls": {"a": [{"id": "r1"}], "c": [{"id": "r2"}]}}
        assert _tool_call_rounds(["a", "b", "c"], state) == [[0, 1], [2]]

    def test_without_responses_state_the_turn_is_one_round(self):
        from docsgpt.agents.base import _tool_call_rounds

        assert _tool_call_rounds(["a", "b", "c"], None) == [[0, 1, 2]]


class TestRoundByRoundReplay:
    @pytest.mark.parametrize("record_rounds", [True, False])
    def test_each_round_replays_its_calls_then_its_results(self, record_rounds):
        agent = _agent([_turn(rounds=[["a", "b"], ["c"]], record_rounds=record_rounds)])

        messages = agent._build_messages("system", "next question")

        assert [m["role"] for m in messages] == [
            "system", "user", "assistant", "tool", "tool", "assistant", "tool", "assistant", "user"
        ]
        first, second = messages[2], messages[5]
        assert [c["id"] for c in first["tool_calls"]] == ["a", "b"]
        assert [r["id"] for r in first["responses_reasoning_items"]] == ["rs_0"]
        assert [m["tool_call_id"] for m in messages[3:5]] == ["a", "b"]
        assert [c["id"] for c in second["tool_calls"]] == ["c"]
        assert [r["id"] for r in second["responses_reasoning_items"]] == ["rs_1"]
        assert messages[7]["content"] == "done"

    def test_the_replay_matches_the_live_responses_input(self, monkeypatch):
        """Round by round, the replay renders as the live turn sent it: reasoning, calls, results."""
        llm = _make_llm(monkeypatch, breakpoints=False)
        agent = _agent([_turn(rounds=[["a", "b"], ["c"]], record_rounds=True)])
        messages = agent._build_messages("system", "next question")

        items = llm._to_responses_input(messages)

        kinds = [i.get("type") or i.get("role") for i in items]
        assert kinds == [
            "system", "user",
            "reasoning", "function_call", "function_call", "function_call_output", "function_call_output",
            "reasoning", "function_call", "function_call_output",
            "reasoning", "assistant", "user",
        ]

    def test_other_providers_keep_one_batch(self):
        agent = _agent([_turn(rounds=[["a", "b"], ["c"]], record_rounds=True)])
        agent.llm = types.SimpleNamespace(_uses_responses_api=lambda: False)

        messages = agent._build_messages("system", "next question")

        assert [m["role"] for m in messages] == [
            "system", "user", "assistant", "tool", "tool", "tool", "assistant", "user"
        ]


class TestCacheBreakpoints:
    def _messages(self):
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": [{"type": "text", "text": "second question"},
                                         {"type": "text", "text": "[files]"}]},
        ]

    def test_each_user_message_marks_its_question(self, monkeypatch):
        llm = _make_llm(monkeypatch, breakpoints=True)

        items, _ = llm._build_responses_input(self._messages(), None)

        users = [i for i in items if i.get("role") == "user"]
        assert [p.get("prompt_cache_breakpoint") for p in users[0]["content"]] == [{"mode": "explicit"}]
        assert [p.get("prompt_cache_breakpoint") for p in users[1]["content"]] == [{"mode": "explicit"}, None]
        system = next(i for i in items if i.get("role") == "system")
        assert "prompt_cache_breakpoint" not in system["content"][0]

    def test_chained_requests_mark_the_new_question_too(self, monkeypatch):
        llm = _make_llm(monkeypatch, breakpoints=True, store=True)

        items, prev = llm._build_responses_input(self._messages(), "resp_prev")

        assert prev == "resp_prev"
        users = [i for i in items if i.get("role") == "user"]
        assert users[-1]["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}

    def test_models_without_the_capability_get_no_breakpoints(self, monkeypatch):
        """Earlier models reject the field (gpt-5.5: 400 "prompt_cache_breakpoint is not supported")."""
        llm = _make_llm(monkeypatch, breakpoints=False)

        items, _ = llm._build_responses_input(self._messages(), None)

        assert "prompt_cache_breakpoint" not in str(items)

    def test_the_callers_messages_are_not_mutated(self, monkeypatch):
        llm = _make_llm(monkeypatch, breakpoints=True)
        messages = self._messages()

        llm._build_responses_input(messages, None)

        assert "prompt_cache_breakpoint" not in str(messages)


class TestCallRounds:
    def test_each_response_with_calls_is_one_round(self, monkeypatch):
        llm = _make_llm(monkeypatch, breakpoints=False)
        call = lambda cid: types.SimpleNamespace(id=cid)  # noqa: E731

        llm._remember_reasoning([call("a"), call("b")], [_reasoning("r1")])
        llm._remember_reasoning([call("c")], [])
        llm._remember_reasoning([], [_reasoning("r3")])

        assert llm.export_responses_state()["call_rounds"] == [["a", "b"], ["c"]]

    def test_rounds_survive_export_and_import_and_reset_per_turn(self, monkeypatch):
        llm = _make_llm(monkeypatch, breakpoints=False)
        llm._call_rounds = [["a"], ["b"]]
        state = llm.export_responses_state()

        fresh = _make_llm(monkeypatch, breakpoints=False)
        assert fresh.import_responses_state(state)
        assert fresh._call_rounds == [["a"], ["b"]]

        fresh.start_responses_turn()
        assert fresh._call_rounds == []


class TestReasoningIsCounted:
    def test_reasoning_items_are_counted_once_per_id(self):
        from docsgpt.api.answer.services.compression.token_counter import TokenCounter

        items = [_reasoning("r1", 800), _reasoning("r1", 800), _reasoning("r2", 1600)]
        assert TokenCounter.count_reasoning_items(items) == 800 // 8 + 1600 // 8

    def test_a_turn_counts_its_calls_reasoning_and_its_answers(self):
        from docsgpt.api.answer.services.compression.token_counter import TokenCounter

        turn = _turn(rounds=[["a", "b"], ["c"]], record_rounds=True)
        # rs_0 (shared by a and b), rs_1, rs_final: 800 characters each.
        assert TokenCounter.replayed_reasoning_tokens(turn) == 3 * 100

    def test_history_counts_include_reasoning_only_when_asked(self):
        from docsgpt.api.answer.services.compression.token_counter import TokenCounter

        history = [_turn(rounds=[["a"]], record_rounds=True)]
        without = TokenCounter.count_query_tokens(history)
        with_reasoning = TokenCounter.count_query_tokens(history, include_reasoning=True)
        assert with_reasoning - without == 2 * 100

    def test_built_messages_count_the_reasoning_they_carry(self):
        from docsgpt.api.answer.services.compression.token_counter import TokenCounter

        bare = [{"role": "assistant", "content": "x"}]
        carrying = [{"role": "assistant", "content": "x", "responses_reasoning_items": [_reasoning("r1", 1600)]}]
        assert TokenCounter.count_message_tokens(carrying) - TokenCounter.count_message_tokens(bare) == 200

    def test_the_compression_check_counts_reasoning_on_the_responses_api(self):
        from docsgpt.api.answer.services.compression.threshold_checker import CompressionThresholdChecker

        conversation = {"queries": [_turn(rounds=[["a"]], record_rounds=True)]}
        seen = {}

        def fake_count(conv, include_reasoning=False):
            seen["include_reasoning"] = include_reasoning
            return 0

        module = "docsgpt.api.answer.services.compression.threshold_checker"
        with patch(f"{module}.get_token_limit", return_value=1000), \
                patch(f"{module}.TokenCounter.count_effective_conversation_tokens", side_effect=fake_count):
            for flavor, expected in (("responses", True), ("chat_completions", False)):
                with patch(f"{module}.get_model_capabilities", return_value={"api_flavor": flavor}):
                    CompressionThresholdChecker(0.8).should_compress(conversation, "m")
                assert seen["include_reasoning"] is expected

    def test_history_truncation_counts_the_reasoning_it_replays(self):
        turn = _turn(rounds=[["a"]], record_rounds=True)
        agent = _agent([turn])
        text_only = _agent([turn], chain="another-target")

        budget = 150
        # Text alone fits; with its 200 tokens of reasoning the turn does not.
        assert text_only._truncate_history_to_fit([turn], budget) == [turn]
        assert agent._truncate_history_to_fit([turn], budget) == []

    def test_the_tool_loop_counts_reasoning_the_llm_holds_for_its_calls(self, monkeypatch):
        llm = _make_llm(monkeypatch, breakpoints=False)
        llm._reasoning_for_calls = {"live_1": [_reasoning("r_live", 2400)]}
        agent = _agent([], llm=llm)
        messages = [{"role": "assistant", "content": None,
                     "tool_calls": [{"id": "live_1", "function": {"name": "f", "arguments": "{}"}}]}]

        assert agent._pending_reasoning_tokens(messages) == 300


class TestAttachmentBlockPlacement:
    def _merge(self, monkeypatch, *, breakpoints: bool, content: Any):
        from docsgpt.llm.handlers.openai import OpenAILLMHandler

        handler = OpenAILLMHandler.__new__(OpenAILLMHandler)
        plan = types.SimpleNamespace(files=[], capabilities=types.SimpleNamespace(synthetic_pdf=False))
        llm = types.SimpleNamespace(capabilities=ModelCapabilities(prompt_cache_breakpoints=breakpoints))
        carrier = {"role": "user", "content": content}
        monkeypatch.setattr("docsgpt.agents.attachment_context.render_attachment_block", lambda p: "[files]")
        _, merged, _ = handler.merge_attachment_plan(llm, [carrier], carrier, plan)
        return merged["content"]

    def test_with_breakpoints_the_question_stays_first_and_alone(self, monkeypatch):
        content = self._merge(monkeypatch, breakpoints=True, content="what is in F1?")
        assert content == [{"type": "text", "text": "what is in F1?"}, {"type": "text", "text": "[files]"}]

    def test_with_breakpoints_files_follow_the_text_parts(self, monkeypatch):
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
        content = self._merge(monkeypatch, breakpoints=True, content=[{"type": "text", "text": "q"}, image])
        assert content == [{"type": "text", "text": "q"}, {"type": "text", "text": "[files]"}, image]

    def test_without_breakpoints_the_block_still_leads(self, monkeypatch):
        assert self._merge(monkeypatch, breakpoints=False, content="q") == "[files]\n\nq"
