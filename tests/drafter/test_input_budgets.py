"""Request values are measured before they are cleaned, and one turn's history sent to the model has a budget."""

import json
import time
from unittest.mock import patch

import pytest

from docsgpt.drafter import agent_recipe, prompt_recipe, runner
from docsgpt.drafter.fencing import clean_text
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest
from docsgpt.drafter.topics_recipe import TOPICS_RECIPE
from tests.drafter.test_topics_recipe import _ws as _topics_ws


def _under(seconds: float, fn, *args):
    started = time.perf_counter()
    result = fn(*args)
    assert time.perf_counter() - started < seconds
    return result


@pytest.mark.unit
class TestCleanTextReadsOnlyWhatItKeeps:
    def test_huge_value_with_a_small_limit_is_fast(self) -> None:
        text = _under(0.1, clean_text, "word " * 2_000_000, 300)
        assert len(text) == 300 and text.endswith("…")
        assert text == clean_text(("word " * 2_000_000)[:5000], 300)

    def test_text_mostly_invisible_is_still_cut_with_an_ellipsis(self) -> None:
        text = clean_text("​" * 2_000_000 + "tail", 300)
        assert text.endswith("…") and len(text) <= 300

    def test_normal_text_is_unchanged(self) -> None:
        value = "Line one\r\nLine​ two\x00 " * 20
        assert clean_text(value, 10_000) == value.replace("\r\n", "\n").replace("​", "").replace("\x00", "")\
            .strip()


@pytest.mark.unit
class TestPromptContextCaps:
    def test_raw_text_far_over_the_cap_is_refused_before_cleaning(self) -> None:
        raw = {"mode": "improve", "prompt": {"content": "x" * (prompt_recipe.RAW_READ_MAX + 1)}}
        with patch.object(prompt_recipe, "clean_text", wraps=prompt_recipe.clean_text) as cleaned:
            with pytest.raises(BadDraftRequest, match="too long"):
                prompt_recipe.parse_context(raw)
        assert all(len(call.args[0] or "") <= prompt_recipe.RAW_READ_MAX for call in cleaned.call_args_list)

    def test_text_that_cleans_under_the_cap_is_still_accepted(self) -> None:
        content = "a" * (prompt_recipe.READ_MAX - 10) + "\r\n" * 50
        context = prompt_recipe.parse_context({"mode": "improve", "prompt": {"content": content}})
        assert context["prompt"]["content"].startswith("a" * 100)

    def test_text_over_the_cap_after_cleaning_is_refused_as_before(self) -> None:
        with pytest.raises(BadDraftRequest, match="too long"):
            prompt_recipe.parse_context({"mode": "improve", "prompt": {"content": "a" * (prompt_recipe.READ_MAX + 1)}})


@pytest.mark.unit
class TestAgentContextCaps:
    def test_raw_prompt_draft_far_over_the_cap_is_refused_before_cleaning(self) -> None:
        raw = {"form": {"prompt_draft": {"name": "n", "content": "x" * (prompt_recipe.RAW_READ_MAX + 1)}}}
        with patch.object(agent_recipe, "clean_text", wraps=agent_recipe.clean_text) as cleaned:
            with pytest.raises(BadDraftRequest, match="too long"):
                agent_recipe.parse_context(raw)
        assert all(len(call.args[0] or "") <= prompt_recipe.RAW_READ_MAX for call in cleaned.call_args_list)

    def test_earlier_cleans_only_what_it_keeps(self) -> None:
        earlier = ["", "  "] + [f"step message {n}" for n in range(50_000)]
        with patch.object(agent_recipe, "clean_text", wraps=agent_recipe.clean_text) as cleaned:
            context = agent_recipe.parse_context({"earlier": earlier})
        assert context["earlier"] == [f"step message {n}" for n in range(agent_recipe.MAX_EARLIER)]
        sent = set(earlier)
        assert sum(1 for call in cleaned.call_args_list if call.args[0] in sent) == agent_recipe.MAX_EARLIER + 2


def _history_req(messages: list[dict]) -> DraftRequest:
    return DraftRequest("alice", "topics", messages, {"agent_id": "a1"}, "drafter:t")


def _sent(messages: list[dict]) -> list[dict]:
    built = runner.build_messages(_history_req(messages), TOPICS_RECIPE, _topics_ws(), tool_mode=True,
                                  allow_questions=False)
    return built[1:]


@pytest.mark.unit
class TestHistoryBudget:
    def test_a_normal_conversation_is_sent_whole(self) -> None:
        messages = [{"role": "user", "content": "Suggest topics."},
                    {"role": "assistant", "content": "plain words"},
                    {"role": "user", "content": "More about billing."}]
        sent = _sent(messages)
        assert [m["role"] for m in sent] == ["user", "assistant", "user"]
        assert sent[0]["content"] == "Suggest topics."

    def test_oldest_messages_are_dropped_past_the_budget(self) -> None:
        big = "y" * 100_000
        messages = []
        for n in range(11):
            messages += [{"role": "user", "content": f"request {n}"}, {"role": "assistant", "content": big}]
        messages.append({"role": "user", "content": "the latest request"})
        sent = _sent(messages)
        assert sum(len(m["content"] or "") for m in sent[:-1]) <= runner.HISTORY_CHARS
        assert sent[0]["role"] == "user"
        assert sent[-1]["content"].endswith("The user's request:\nthe latest request")
        assert len(sent) < len(messages)
        # The newest messages are the ones kept.
        assert sent[-3]["content"] == "request 10"

    def test_the_latest_request_is_always_sent(self) -> None:
        messages = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "z" * 120_000},
                    {"role": "user", "content": "u" * 8000}]
        with patch.object(runner, "HISTORY_CHARS", 10):
            sent = _sent(messages)
        assert len(sent) == 1 and sent[0]["content"].endswith("u" * 8000)

    def test_replayed_turns_keep_their_call_pairs(self) -> None:
        proposal = json.dumps({"type": "proposal", "message": "Here.", "proposal": {"topics": []}})
        messages = [{"role": "user", "content": "x" * 50}, {"role": "assistant", "content": proposal},
                    {"role": "user", "content": "again"}]
        sent = _sent(messages)
        assert sent[0]["content"] == "x" * 50
