"""Clarifying questions in chat (``ask_user``).

Covers when the tool is attached, how a call pauses (question cards) or ends
the turn with markdown (text), the one-round limit, and the resume with an
answer or a skip.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from docsgpt.agents.questions import (
    QuestionsInvalid,
    normalize_questions,
    render_questions_text,
)
from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.agents.tools.ask_user import (
    ASK_USER,
    NOT_ALONE_TEXT,
    ONE_ROUND_TEXT,
    SHOWN_AS_TEXT,
    SKIPPED_TEXT,
    add_ask_user_tool,
    questions_mode,
)
from docsgpt.llm.handlers.base import LLMHandler, LLMResponse, ToolCall

ARGS = {
    "message": "Two things first:",
    "questions": [
        {"text": "Team size?", "options": ["1-10", "11-50"], "note": "Plans differ by seats."},
        {"text": "Company name?", "options": [], "placeholder": "Acme"},
    ],
}


class Handler(LLMHandler):
    """A handler whose stream and responses are the test's own ``LLMResponse`` objects."""

    def parse_response(self, response: Any) -> LLMResponse:
        return response

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {"role": "tool", "content": str(result), "tool_call_id": tool_call.id}

    def _iterate_stream(self, response: Any):
        yield from response


def _executor(mode: str | None) -> tuple[ToolExecutor, Dict]:
    executor = ToolExecutor()
    executor.questions = mode
    tools: Dict = {}
    add_ask_user_tool(tools, enabled=True)
    executor.prepare_tools_for_llm(tools)
    return executor, tools


def _call(call_id: str = "c1", args: Dict | None = None, name: str = ASK_USER) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=json.dumps(ARGS if args is None else args))


def _agent(executor: ToolExecutor) -> Mock:
    agent = Mock()
    agent.model_id = "m"
    agent.tools = []
    agent._check_context_limit = Mock(return_value=False)
    agent.context_limit_reached = False
    agent.llm.__class__.__name__ = "MockLLM"
    agent.tool_executor = executor
    agent._execute_tool_action = lambda tools, call: executor.execute(tools, call, "MockLLM")
    return agent


def _drain(gen) -> tuple[List[Any], Any]:
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as stop:
            return events, stop.value


def _tool_round(*calls: ToolCall) -> List[LLMResponse]:
    return [LLMResponse(content="", tool_calls=list(calls), finish_reason="tool_calls", raw_response={})]


# ---------------------------------------------------------------------------
# Shape and text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQuestionsShape:
    def test_normalizes_ids_options_and_typed_questions(self):
        message, questions = normalize_questions(ARGS)

        assert message == "Two things first:"
        assert questions[0]["id"] == "q1"
        assert questions[0]["options"] == [{"id": "a", "label": "1-10", "input": None, "exclusive": False},
                                           {"id": "b", "label": "11-50", "input": None, "exclusive": False}]
        assert questions[1]["placeholder"] == "Acme" and questions[1]["multi"] is False

    def test_one_option_makes_a_typed_question(self):
        _, questions = normalize_questions({"questions": [{"text": "Sure?", "options": ["Yes"],
                                                           "placeholder": "Yes, or why not"}]})
        assert questions[0]["options"] == [] and questions[0]["placeholder"] == "Yes, or why not"

    # chat_amb_policy_r3: refused twice, so the model wrote a [Store Name] template instead of asking.
    FIRST_TRY = {"message": "I'll draft your shipping policy:", "questions": [
        {"options": ["Input for business/store name"], "placeholder": "e.g. Aurora Goods",
         "text": "What's your store or business name?"},
        {"text": "Which regions do you ship to?", "multi": True},
        {"options": ["Flat rate", "Free over a threshold", "Calculated at checkout", "Input for rates"],
         "text": "How do you charge for shipping?"},
    ]}
    SECOND_TRY = {"message": "I'll draft your shipping policy:", "questions": [
        {"options": [{"input": "Store name", "placeholder": "e.g. Aurora Goods"}],
         "text": "What's your store or business name?"},
        {"multi": True, "options": ["Domestic only", "Domestic + international",
                                    "Input for specific countries/regions"], "text": "Which regions do you ship to?"},
    ]}

    def test_an_input_only_question_becomes_a_typed_one(self):
        _, questions = normalize_questions(self.FIRST_TRY)
        store, regions, rates = questions
        assert store["options"] == [] and store["placeholder"] == "e.g. Aurora Goods"
        assert regions["options"] == [] and regions["multi"] is False
        # Typing is what "Something else…" is for: an "Input for …" option beside real ones is left out.
        assert [o["label"] for o in rates["options"]] == ["Flat rate", "Free over a threshold",
                                                         "Calculated at checkout"]

    def test_a_label_less_input_option_is_a_typed_question_with_its_placeholder(self):
        _, questions = normalize_questions(self.SECOND_TRY)
        assert questions[0]["options"] == [] and questions[0]["placeholder"] == "Store name"
        assert [o["label"] for o in questions[1]["options"]] == ["Domestic only", "Domestic + international"]
        assert questions[1]["multi"] is True

    def test_a_single_input_for_string_gives_its_placeholder(self):
        _, questions = normalize_questions({"questions": [{"text": "Your city?", "options": ["Input for city"]}]})
        assert questions[0]["options"] == [] and questions[0]["placeholder"] == "city"

    def test_renders_markdown_without_placeholders(self):
        text = render_questions_text(*normalize_questions(ARGS))

        assert text == (
            "Two things first:\n\n"
            "**1. Team size?**  \n*Plans differ by seats.*  \na) 1-10  \nb) 11-50\n\n"
            "**2. Company name?**"
        )
        assert "Acme" not in text

    def test_an_option_can_open_a_field_to_type_in(self):
        _, questions = normalize_questions({"questions": [{"text": "Where to?", "options": [
            "Lisbon", {"label": "Another city", "input": "City name"},
        ]}]})
        assert questions[0]["options"][1] == {"id": "b", "label": "Another city", "input": "City name",
                                              "exclusive": False}

    def test_an_exclusive_option_goes_last_in_a_multi_question(self):
        _, questions = normalize_questions({"questions": [{"text": "Topics?", "multi": True, "options": [
            {"label": "No topics", "exclusive": True}, "Billing", "Returns",
        ]}]})
        options = questions[0]["options"]
        assert [o["label"] for o in options] == ["Billing", "Returns", "No topics"]
        assert [o["id"] for o in options] == ["a", "b", "c"]
        assert options[-1]["exclusive"] is True and not options[0]["exclusive"]

    def test_exclusive_means_nothing_in_a_single_choice_question(self):
        _, questions = normalize_questions({"questions": [{"text": "Tone?", "options": [
            "Warm", {"label": "Formal", "exclusive": True},
        ]}]})
        assert [o["exclusive"] for o in questions[0]["options"]] == [False, False]

    def test_two_exclusive_options_are_refused(self):
        with pytest.raises(QuestionsInvalid, match="at most one"):
            normalize_questions({"questions": [{"text": "Checks?", "multi": True, "options": [
                {"label": "None", "exclusive": True}, {"label": "All", "exclusive": True}, "PII",
            ]}]})

    def test_a_blank_input_is_no_input(self):
        _, questions = normalize_questions({"questions": [{"text": "Q?", "options": [
            {"label": "A", "input": "  "}, {"label": "B", "input": None}, {"text": "C"},
        ]}]})
        assert [o["input"] for o in questions[0]["options"]] == [None, None, None]

    def test_the_text_shows_an_input_option_with_its_placeholder(self):
        text = render_questions_text(*normalize_questions({"questions": [{"text": "Where?", "multi": True,
                                                                          "options": [
            {"label": "None", "exclusive": True}, "Lisbon", {"label": "Elsewhere", "input": "City"},
        ]}]}))
        assert text == "**1. Where?**  \na) Lisbon  \nb) Elsewhere: _City_  \nc) None"

    def test_the_schema_offers_input_and_exclusive(self):
        from docsgpt.agents.questions import CHAT_QUESTIONS_SCHEMA

        items = CHAT_QUESTIONS_SCHEMA["properties"]["questions"]["items"]["properties"]["options"]["items"]
        option = next(branch for branch in items["anyOf"] if branch.get("type") == "object")
        assert set(option["properties"]) == {"label", "input", "exclusive"}

    def test_the_description_shows_an_option_object(self):
        from docsgpt.agents.tools.ask_user import AskUserTool

        description = AskUserTool().get_actions_metadata()[0]["description"]
        assert '{"label": "Another city", "input": "City name"}' in description

    def test_the_rules_steer_options(self):
        from docsgpt.agents.tools.ask_user import AskUserTool

        description = AskUserTool().get_actions_metadata()[0]["description"]
        options = __import__("docsgpt.agents.questions", fromlist=["x"]).CHAT_QUESTIONS_SCHEMA[
            "properties"]["questions"]["items"]["properties"]["options"]["description"]
        for text in (description, options):
            assert "input" in text
        assert "Something else" in options and "contact" in options

    def test_the_description_steers_when_and_how_to_ask(self):
        from docsgpt.agents.tools.ask_user import AskUserTool

        description = AskUserTool().get_actions_metadata()[0]["description"]
        # Ask for the user's specifics rather than writing a template full of placeholders.
        assert "placeholder" in description and "shipping policy" in description
        # Ask with the tool, never as prose.
        assert "never as questions written in your answer" in description
        # multi when several options can apply, no "Multiple X" option.
        assert "multi" in description and "several of these" in description.lower()
        # Clear requests are still answered without asking.
        assert "Never ask for small talk or about something already clear" in description

    def test_only_cards_asks_for_cards(self):
        assert questions_mode("cards") == "cards"
        assert questions_mode(None) == "text"
        assert questions_mode("CARDS") == "text"


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------


SEARCH_TOOL = {
    "id": "search",
    "name": "search",
    "actions": [{"name": "search", "description": "Search", "active": True, "parameters": {"properties": {}}}],
    "config": {},
}


@pytest.mark.unit
class TestAttachment:
    def _agent(self, *, mode="text", headless=False, scope=None, json_schema=None, tools=True):
        from docsgpt.agents.classic_agent import ClassicAgent

        llm = Mock()
        llm._supports_tools = tools
        llm.__class__.__name__ = "MockLLM"
        executor = ToolExecutor(headless=headless)
        executor.questions = mode
        executor.allowed_tool_ids = scope
        return ClassicAgent(
            endpoint="stream", llm_name="openai", model_id="m", api_key="k",
            llm=llm, llm_handler=Mock(), tool_executor=executor, json_schema=json_schema,
        )

    def _attached(self, agent, tools_dict=None) -> bool:
        tools_dict = {"search": dict(SEARCH_TOOL)} if tools_dict is None else tools_dict
        agent._prepare_tools(tools_dict)
        return any(t.get("name") == ASK_USER for t in tools_dict.values())

    def test_a_turn_with_no_other_tools_does_not_get_it(self):
        """Without tools the model is called with none, so its answers stay cacheable."""
        agent = self._agent(mode="cards")
        assert not self._attached(agent, {})
        assert not agent.tools

    def test_a_saved_entry_alone_is_not_another_tool(self):
        tools_dict: Dict = {}
        add_ask_user_tool(tools_dict, enabled=True)
        assert not self._attached(self._agent(mode="cards"), tools_dict)

    @pytest.mark.parametrize("mode", ["cards", "text"])
    def test_an_interactive_chat_turn_gets_it(self, mode):
        agent = self._agent(mode=mode)
        assert self._attached(agent)
        assert ASK_USER in {t["function"]["name"] for t in agent.tools}

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"mode": None},
            {"headless": True},
            {"scope": []},
            {"json_schema": {"type": "object", "properties": {"a": {"type": "string"}}}},
            {"tools": False},
        ],
        ids=["no-mode", "headless", "workflow-node", "structured-output", "no-tool-support"],
    )
    def test_other_turns_do_not(self, kwargs):
        assert not self._attached(self._agent(**kwargs))

    def test_a_saved_entry_is_dropped_when_the_turn_offers_no_questions(self):
        tools_dict: Dict = {}
        add_ask_user_tool(tools_dict, enabled=True)
        assert not self._attached(self._agent(mode=None), tools_dict)

    def test_a_client_tool_of_the_same_name_keeps_it(self):
        client = {"name": "client_ask", "client_side": True, "actions": [{"name": ASK_USER, "parameters": {}}]}
        tools_dict = {"client": client}
        assert add_ask_user_tool(tools_dict, enabled=True) is False
        assert tools_dict == {"client": client}

    def test_it_is_server_attached_and_never_headless(self):
        from docsgpt.agents.default_tools import is_headless_excluded_tool, is_server_attached_tool

        assert is_server_attached_tool(ASK_USER)
        assert is_headless_excluded_tool(ASK_USER)


# ---------------------------------------------------------------------------
# check_pause
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPause:
    def test_cards_pause_on_awaiting_answer_with_normalized_questions(self):
        executor, tools = _executor("cards")
        pause = executor.check_pause(tools, _call(), "MockLLM")

        assert pause["pause_type"] == "awaiting_answer"
        assert pause["message"] == "Two things first:"
        assert [q["id"] for q in pause["questions"]] == ["q1", "q2"]
        assert pause["arguments"] == {"message": pause["message"], "questions": pause["questions"]}
        assert executor.questions_asked is True

    def test_text_runs_the_call(self):
        executor, tools = _executor("text")
        assert executor.check_pause(tools, _call(), "MockLLM") is None

    def test_a_second_round_is_refused(self):
        executor, tools = _executor("cards")
        executor.questions_asked = True
        pause = executor.check_pause(tools, _call(), "MockLLM")

        assert pause["pause_type"] == "headless_denied"
        assert pause["model_text"] == ONE_ROUND_TEXT

    def test_beside_other_calls_it_is_refused_without_using_the_round(self):
        executor, tools = _executor("cards")
        executor.calls_this_round = 2
        pause = executor.check_pause(tools, _call(), "MockLLM")

        assert pause["model_text"] == NOT_ALONE_TEXT
        assert executor.questions_asked is False

    def test_invalid_questions_get_one_corrected_try(self):
        executor, tools = _executor("cards")
        bad = {"questions": [{"text": "Sure?", "multi": True, "options": [
            {"label": "None", "exclusive": True}, {"label": "All", "exclusive": True}, "PII"]}]}

        first = executor.check_pause(tools, _call(args=bad), "MockLLM")
        assert first["pause_type"] == "headless_denied"
        assert "Fix them" in first["model_text"]
        assert executor.questions_asked is False

        second = executor.check_pause(tools, _call("c2", args=bad), "MockLLM")
        assert "Don't try again" in second["model_text"]
        assert executor.questions_asked is True


# ---------------------------------------------------------------------------
# The LLM handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandler:
    def test_cards_pause_event_carries_the_questions(self):
        executor, tools = _executor("cards")
        events, (_messages, pending) = _drain(Handler().handle_tool_calls(_agent(executor), [_call()], tools, []))

        (event,) = [e for e in events if e.get("type") == "tool_call"]
        assert event["data"]["status"] == "awaiting_answer"
        assert event["data"]["message"] == "Two things first:"
        assert event["data"]["questions"][1]["placeholder"] == "Acme"
        assert pending[0]["pause_type"] == "awaiting_answer"

    def test_cards_streaming_pauses_the_turn(self):
        executor, tools = _executor("cards")
        agent = _agent(executor)
        events = list(Handler().handle_streaming(agent, _tool_round(_call()), tools, []))

        assert events[-1]["type"] == "tool_calls_pending"
        assert agent._pending_continuation["pending_tool_calls"][0]["questions"]
        agent.llm.gen_stream.assert_not_called()

    def test_a_refusal_is_sent_to_the_model_and_kept_as_a_failed_call(self):
        executor, tools = _executor("cards")
        executor.questions_asked = True
        events, (messages, pending) = _drain(Handler().handle_tool_calls(_agent(executor), [_call()], tools, []))

        assert pending is None
        assert messages[-1] == {"role": "tool", "content": ONE_ROUND_TEXT, "tool_call_id": "c1"}
        assert executor.tool_calls[-1]["status"] == "error"

    def test_text_streaming_ends_the_turn_with_the_questions(self):
        executor, tools = _executor("text")
        agent = _agent(executor)
        events = list(Handler().handle_streaming(agent, _tool_round(_call()), tools, []))

        answer = render_questions_text(*normalize_questions(ARGS))
        assert events[-1] == answer
        agent.llm.gen_stream.assert_not_called()
        (record,) = executor.tool_calls
        assert record["status"] == "success"
        assert record["result"] == SHOWN_AS_TEXT
        assert record["shown_as"] == "text"
        assert record["arguments"]["questions"][0]["id"] == "q1"
        assert executor.questions_shown_as_text is True
        # The marker survives the projection the chat reloads.
        (saved,) = executor.get_truncated_tool_calls()
        assert saved["shown_as"] == "text"

    def test_text_non_streaming_ends_the_turn_with_the_questions(self):
        executor, tools = _executor("text")
        agent = _agent(executor)
        first = LLMResponse(content="", tool_calls=[_call()], finish_reason="tool_calls", raw_response={})
        _events, final = _drain(Handler().handle_non_streaming(agent, first, tools, []))

        assert final == render_questions_text(*normalize_questions(ARGS))
        agent.llm.gen.assert_not_called()

    def test_a_second_text_round_in_the_turn_lets_the_model_answer(self):
        executor, tools = _executor("text")
        executor.questions_asked = True
        agent = _agent(executor)
        agent.llm.gen_stream = Mock(
            return_value=[LLMResponse(content="Assuming a small team.", tool_calls=[], finish_reason="stop",
                                      raw_response={})]
        )
        events = list(Handler().handle_streaming(agent, _tool_round(_call()), tools, []))

        assert "Assuming a small team." in events
        agent.llm.gen_stream.assert_called_once()


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


class _ResumeHarness:
    """Resumes a paused ``ask_user`` call on a real agent whose LLM, handler and executor are mocks."""

    PENDING = {
        "call_id": "c1",
        "name": ASK_USER,
        "llm_name": ASK_USER,
        "tool_name": ASK_USER,
        "tool_id": ASK_USER,
        "action_name": ASK_USER,
        "arguments": ARGS,
        "pause_type": "awaiting_answer",
        "message": "Two things first:",
        "questions": normalize_questions(ARGS)[1],
        "thought_signature": None,
    }

    def _agent(self, guardrails: Dict | None = None):
        from docsgpt.agents.classic_agent import ClassicAgent

        llm = Mock()
        llm._supports_tools = True
        llm._supports_structured_output = Mock(return_value=False)
        llm.__class__.__name__ = "MockLLM"
        handler = Mock()
        handler.process_message_flow = Mock(return_value=iter([]))
        handler.create_tool_message = Mock(
            side_effect=lambda tc, result: {"role": "tool", "tool_call_id": tc.id, "content": result}
        )
        executor = Mock()
        executor.tool_calls = []
        executor.prepare_tools_for_llm = Mock(return_value=[])
        executor.get_truncated_tool_calls = Mock(return_value=[])
        agent = ClassicAgent(
            endpoint="stream", llm_name="openai", model_id="m", api_key="k",
            llm=llm, llm_handler=handler, tool_executor=executor,
            agent_config={"guardrails": guardrails} if guardrails else None,
        )
        return agent, executor

    def _resume(self, action, guardrails: Dict | None = None, pending: List[Dict] | None = None):
        agent, executor = self._agent(guardrails)
        messages: List[Dict] = []
        pending = pending if pending is not None else [dict(self.PENDING)]
        events = list(agent.gen_continuation(messages, {}, pending, [action] if action else []))
        self.last_agent = agent
        return events, messages, executor


@pytest.mark.unit
class TestResume(_ResumeHarness):

    def test_an_answer_reaches_the_model_and_the_message(self):
        events, messages, executor = self._resume({"call_id": "c1", "answer": "Team size? → 11-50"})

        assert messages[-1]["content"] == "Team size? → 11-50"
        (record,) = executor.tool_calls
        assert record["tool_name"] == ASK_USER and record["action_name"] == ASK_USER
        assert record["status"] == "success"
        assert record["result"] == "Team size? → 11-50"
        assert record["arguments"] == {"message": "Two things first:", "questions": self.PENDING["questions"]}
        assert not executor.execute.called

    def test_a_long_answer_is_capped(self):
        _events, messages, _executor = self._resume({"call_id": "c1", "answer": "x" * 9000})
        assert len(messages[-1]["content"]) <= 4000

    @pytest.mark.parametrize("action", [{"call_id": "c1", "skipped": True}, None], ids=["skipped", "missing"])
    def test_a_skip_lets_the_model_assume(self, action):
        _events, messages, executor = self._resume(action)

        assert messages[-1]["content"] == SKIPPED_TEXT
        assert executor.tool_calls[0]["status"] == "skipped"

    def test_a_huge_answer_is_cut_before_it_is_cleaned(self, monkeypatch):
        import docsgpt.drafter.fencing as fencing
        from docsgpt.agents.questions import ANSWER_CHARS

        seen: List[int] = []
        real = fencing.clean_text

        def spy(value, limit):
            seen.append(len(value) if isinstance(value, str) else 0)
            return real(value, limit)

        monkeypatch.setattr(fencing, "clean_text", spy)
        _events, messages, _executor = self._resume({"call_id": "c1", "answer": "x" * 5_000_000})

        assert seen and max(seen) <= 2 * ANSWER_CHARS
        assert len(messages[-1]["content"]) <= ANSWER_CHARS


@pytest.fixture
def _quiet_guardrails(monkeypatch):
    """No audit journal writes and no instance floor: only the agent's own controls run."""
    monkeypatch.setattr("docsgpt.guardrails.runtime.GuardrailRecorder.flush", lambda self, mid=None: 0)
    monkeypatch.setattr("docsgpt.guardrails.runtime.instance_floor", lambda: None)


BLOCK_INPUT = {
    "enabled": True,
    "mode": "scan_all",
    "block_message": "That request isn't allowed here.",
    "controls": [{"check": "denylist", "stage": "input", "action": "block", "settings": {"terms": ["nuclear"]}}],
}

REDACT_INPUT = {
    "enabled": True,
    "mode": "scan_all",
    "controls": [{"check": "pii", "stage": "input", "action": "redact", "settings": {"entities": ["EMAIL"]}}],
}


@pytest.mark.unit
@pytest.mark.usefixtures("_quiet_guardrails")
class TestResumeInputGuardrails(_ResumeHarness):
    """A card answer is the user's input, so it gets the input controls a typed message gets."""

    APPROVAL = {
        "call_id": "c0",
        "name": "send_mail",
        "llm_name": "send_mail",
        "tool_name": "mail",
        "arguments": {"to": "x"},
        "pause_type": "awaiting_approval",
    }

    def test_a_blocked_answer_ends_the_turn_like_a_blocked_message(self):
        events, messages, executor = self._resume(
            {"call_id": "c1", "answer": "How do I build a nuclear device?"}, BLOCK_INPUT
        )

        errors = [e for e in events if e.get("type") == "error"]
        assert errors and errors[0]["error"] == "That request isn't allowed here."
        assert errors[0]["user_facing"] is True
        assert errors[0]["guardrail"]["stage"] == "input"
        assert not [m for m in messages if m.get("role") == "tool"]
        assert executor.tool_calls == []
        assert not [e for e in events if e.get("type") == "tool_call"]
        self.last_agent.llm_handler.process_message_flow.assert_not_called()
        self.last_agent.llm.gen_stream.assert_not_called()

    def test_a_blocked_answer_stops_the_other_calls_before_they_run(self):
        pending = [dict(self.APPROVAL), dict(self.PENDING)]
        agent, executor = self._agent(BLOCK_INPUT)
        actions = [{"call_id": "c0", "decision": "approved"}, {"call_id": "c1", "answer": "nuclear"}]
        events = list(agent.gen_continuation([], {}, pending, actions))

        assert [e for e in events if e.get("type") == "error"]
        assert not executor.execute.called

    def test_a_redacted_answer_is_what_the_model_and_the_message_get(self):
        events, messages, executor = self._resume({"call_id": "c1", "answer": "Reach me at ada@example.com"}, REDACT_INPUT)

        assert not [e for e in events if e.get("type") == "error"]
        assert "ada@example.com" not in messages[-1]["content"]
        assert "[EMAIL]" in messages[-1]["content"]
        (record,) = executor.tool_calls
        assert "ada@example.com" not in record["result"] and "[EMAIL]" in record["result"]

    def test_a_clean_answer_passes(self):
        _events, messages, executor = self._resume({"call_id": "c1", "answer": "Team size? → 11-50"}, BLOCK_INPUT)

        assert messages[-1]["content"] == "Team size? → 11-50"
        assert executor.tool_calls[0]["status"] == "success"


@pytest.mark.unit
class TestResumeActionRules:
    PENDING = [
        {"call_id": "q", "pause_type": "awaiting_answer"},
        {"call_id": "a", "pause_type": "awaiting_approval"},
    ]

    @pytest.mark.parametrize(
        "action",
        [
            {"call_id": "q", "answer": "Yes"},
            {"call_id": "q", "skipped": True},
            {"call_id": "a", "decision": "approved"},
        ],
    )
    def test_fitting_actions_pass(self, action):
        from docsgpt.api.answer.services.continuation_service import question_action_problem

        assert question_action_problem(self.PENDING, [action]) is None

    @pytest.mark.parametrize(
        "action",
        [
            {"call_id": "q", "decision": "approved"},
            {"call_id": "q", "result": "done"},
            {"call_id": "q", "answer": "  "},
            {"call_id": "q"},
            {"call_id": "q", "answer": "Yes", "skipped": True},
            {"call_id": "a", "answer": "Yes"},
            {"call_id": "a", "skipped": True},
        ],
    )
    def test_mixed_up_actions_are_refused(self, action):
        from docsgpt.api.answer.services.continuation_service import question_action_problem

        assert question_action_problem(self.PENDING, [action])


@pytest.mark.unit
class TestRetiredQuestions:
    @pytest.mark.parametrize("reason,word", [("moved_on", "moved on"), ("expired", "expired")])
    def test_unanswered_questions_are_recorded_as_not_answered(self, reason, word):
        from docsgpt.api.answer.services.continuation_service import not_run_entry

        entry = not_run_entry(_ResumeHarness.PENDING, reason)

        assert entry["status"] == "denied"
        assert entry["not_run"] == reason
        assert entry["result"].startswith("Not answered:") and word in entry["result"]
        assert entry["arguments"]["questions"] == _ResumeHarness.PENDING["questions"]


@pytest.mark.unit
class TestPausedTurnState:
    def test_the_mode_and_the_asked_round_survive_a_pause(self):
        from docsgpt.agents.classic_agent import ClassicAgent

        llm = Mock()
        llm._backup_models = []
        executor = ToolExecutor()
        executor.questions = "cards"
        executor.questions_asked = True
        agent = ClassicAgent(
            endpoint="stream", llm_name="openai", model_id="m", api_key="k",
            llm=llm, llm_handler=Mock(), tool_executor=executor,
        )
        state = agent.paused_turn_state()

        assert state["questions"] == "cards"
        assert state["questions_asked"] is True

    def test_a_turn_that_ended_on_text_questions_is_not_chained_onto(self, monkeypatch):
        from docsgpt.agents.classic_agent import ClassicAgent
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "OPENAI_RESPONSES_STORE", True)
        llm = Mock()
        llm._uses_responses_api = Mock(return_value=True)
        llm._last_response_id = "resp_1"
        llm.responses_chain_key = Mock(return_value="key")
        llm.export_responses_state = Mock(return_value={"chain_key": "key"})
        llm._last_usage = None
        executor = ToolExecutor()
        agent = ClassicAgent(
            endpoint="stream", llm_name="openai", model_id="m", api_key="k",
            llm=llm, llm_handler=Mock(), tool_executor=executor,
        )
        assert next(agent._emit_responses_metadata())["metadata"]["response_id"] == "resp_1"

        executor.questions_shown_as_text = True
        metadata = next(agent._emit_responses_metadata())["metadata"]
        assert "response_id" not in metadata
        assert metadata["responses_state"] == {"chain_key": "key"}


BLOCK_OUTPUT = {
    "enabled": True,
    "mode": "scan_all",
    "block_message": "Response withheld.",
    "controls": [{"check": "denylist", "stage": "output", "action": "block", "settings": {"terms": ["seats"]}}],
}

REDACT_OUTPUT = {
    "enabled": True,
    "mode": "scan_all",
    "controls": [{"check": "pii", "stage": "output", "action": "redact", "settings": {"entities": ["EMAIL"]}}],
}


@pytest.mark.unit
@pytest.mark.usefixtures("_quiet_guardrails")
class TestQuestionOutputGuardrails(_ResumeHarness):
    """Question cards are the model's words shown to the user, so they get the output controls an answer gets."""

    def _cards(self, guardrails: Dict) -> tuple[ToolExecutor, Dict, Mock]:
        screening_agent, _ = self._agent(guardrails)
        executor, tools = _executor("cards")
        executor.question_screen = screening_agent._screen_questions
        agent = _agent(executor)
        agent._pending_continuation = None
        return executor, tools, agent

    def test_the_agent_hands_its_screen_to_the_executor(self):
        agent, executor = self._agent(BLOCK_OUTPUT)
        agent._prepare_tools({})
        assert executor.question_screen == agent._screen_questions

    def test_blocked_cards_end_the_streamed_turn_like_a_blocked_answer(self):
        executor, tools, agent = self._cards(BLOCK_OUTPUT)
        events = list(Handler().handle_streaming(agent, _tool_round(_call()), tools, []))

        assert events[-1]["type"] == "error"
        assert events[-1]["error"] == "Response withheld."
        assert events[-1]["user_facing"] is True
        assert events[-1]["guardrail"]["stage"] == "output"
        assert not [e for e in events if isinstance(e, dict) and e.get("type") in ("tool_call", "tool_calls_pending")]
        assert "seats" not in json.dumps([e for e in events if isinstance(e, dict)])
        assert agent._pending_continuation is None
        assert executor.tool_calls == []
        agent.llm.gen_stream.assert_not_called()

    def test_blocked_cards_end_the_non_streamed_turn(self):
        executor, tools, agent = self._cards(BLOCK_OUTPUT)
        first = LLMResponse(content="", tool_calls=[_call()], finish_reason="tool_calls", raw_response={})
        events, final = _drain(Handler().handle_non_streaming(agent, first, tools, []))

        assert [e for e in events if e.get("type") == "error"][0]["guardrail"]["stage"] == "output"
        assert not [e for e in events if e.get("type") in ("tool_call", "tool_calls_pending")]
        assert not final
        assert agent._pending_continuation is None
        agent.llm.gen.assert_not_called()

    def test_redacted_cards_show_and_keep_the_redacted_text(self):
        args = {**ARGS, "message": "Mail ada@example.com or answer:", "questions": [
            {"text": "Team size?", "options": ["1-10", "bob@example.com"], "note": "Or ask cy@example.com."},
            {"text": "Company name?", "options": [], "placeholder": "dee@example.com"},
        ]}
        executor, tools, agent = self._cards(REDACT_OUTPUT)
        events = list(Handler().handle_streaming(agent, _tool_round(_call(args=args)), tools, []))

        (pause,) = [e for e in events if isinstance(e, dict) and e.get("type") == "tool_call"]
        stored = agent._pending_continuation["pending_tool_calls"][0]
        for shown in (pause["data"], stored):
            assert "@example.com" not in json.dumps(shown)
            assert shown["message"] == "Mail [EMAIL] or answer:"
            assert shown["questions"][0]["note"] == "Or ask [EMAIL]."
            assert shown["questions"][0]["options"][1]["label"] == "[EMAIL]"
            assert shown["questions"][1]["placeholder"] == "[EMAIL]"

    def test_clean_cards_are_left_as_they_are(self):
        executor, tools, _agent_ = self._cards(BLOCK_OUTPUT)
        pause = executor.check_pause(tools, _call(args={**ARGS, "questions": [ARGS["questions"][1]]}), "MockLLM")

        message, questions = normalize_questions({**ARGS, "questions": [ARGS["questions"][1]]})
        assert pause["pause_type"] == "awaiting_answer"
        assert pause["arguments"] == {"message": message, "questions": questions}
        assert pause["questions"] == questions

    def test_what_the_cards_leave_out_never_reaches_the_client_or_the_paused_state(self):
        # A 4th question and an extra key are dropped from the cards, so the
        # screen never sees them: neither may ride along in the arguments.
        args = {**ARGS, "leak": "seats secret", "questions": [
            ARGS["questions"][1],
            {"text": "Role?", "options": []},
            {"text": "Region?", "options": []},
            {"text": "How many seats?", "options": []},
        ]}
        executor, tools, agent = self._cards(BLOCK_OUTPUT)
        events = list(Handler().handle_streaming(agent, _tool_round(_call(args=args)), tools, []))

        (pause,) = [e for e in events if isinstance(e, dict) and e.get("type") == "tool_call"]
        stored = agent._pending_continuation["pending_tool_calls"][0]
        for shown in (pause["data"], stored):
            assert "seats" not in json.dumps(shown)
            assert set(shown["arguments"]) == {"message", "questions"}
            assert len(shown["arguments"]["questions"]) == 3

    def _text(self, guardrails: Dict) -> tuple[ToolExecutor, Dict, Mock]:
        screening_agent, _ = self._agent(guardrails)
        executor, tools = _executor("text")
        executor.question_screen = screening_agent._screen_questions
        return executor, tools, _agent(executor)

    def test_redacted_text_questions_show_and_keep_the_redacted_text(self):
        args = {**ARGS, "message": "Mail ada@example.com or answer:", "questions": [
            {"text": "Team size?", "options": ["1-10", "bob@example.com"]},
        ]}
        executor, tools, agent = self._text(REDACT_OUTPUT)
        events = list(Handler().handle_streaming(agent, _tool_round(_call(args=args)), tools, []))

        assert "@example.com" not in json.dumps([e for e in events if isinstance(e, dict)])
        assert "@example.com" not in events[-1]
        assert "Mail [EMAIL] or answer:" in events[-1]
        (record,) = executor.tool_calls
        assert "@example.com" not in json.dumps(record)
        assert record["arguments"]["message"] == "Mail [EMAIL] or answer:"

    def test_blocked_text_questions_end_the_turn_like_a_blocked_answer(self):
        executor, tools, agent = self._text(BLOCK_OUTPUT)
        events = list(Handler().handle_streaming(agent, _tool_round(_call()), tools, []))

        assert events[-1]["type"] == "error"
        assert events[-1]["guardrail"]["stage"] == "output"
        assert not [e for e in events if isinstance(e, dict) and e.get("type") == "tool_call"]
        assert "seats" not in json.dumps([e for e in events if isinstance(e, dict)])
        assert not [e for e in events if isinstance(e, str)]
        assert executor.tool_calls == []
        agent.llm.gen_stream.assert_not_called()

    def test_blocked_text_questions_end_the_non_streamed_turn(self):
        executor, tools, agent = self._text(BLOCK_OUTPUT)
        first = LLMResponse(content="", tool_calls=[_call()], finish_reason="tool_calls", raw_response={})
        events, final = _drain(Handler().handle_non_streaming(agent, first, tools, []))

        assert [e for e in events if e.get("type") == "error"][0]["guardrail"]["stage"] == "output"
        assert not [e for e in events if e.get("type") == "tool_call"]
        assert not final
        agent.llm.gen.assert_not_called()


@pytest.mark.unit
class TestRefusedCallsKeepNoArguments:
    """A refused ``ask_user`` call never shows its questions, so none of the model's raw text may travel with it."""

    LEAKY = {**ARGS, "leak": "seats secret"}

    @pytest.fixture(autouse=True)
    def _journal(self, monkeypatch):
        self.journaled: List[Dict] = []

        def proposed(call_id, tool_name, action_name, arguments, **_kwargs):
            self.journaled.append(arguments)
            return False

        monkeypatch.setattr("docsgpt.agents.tool_executor._record_proposed", proposed)

    def _run(self, executor: ToolExecutor, tools: Dict, args: Dict) -> tuple[List[Dict], List[Dict]]:
        events, (messages, _pending) = _drain(
            Handler().handle_tool_calls(_agent(executor), [_call(args=args)], tools, [])
        )
        return [e for e in events if e.get("type") == "tool_call"], messages

    def _assert_no_raw_text(self, executor: ToolExecutor, shown: List[Dict]) -> None:
        (event,) = shown
        assert event["data"]["arguments"] == {}
        assert executor.tool_calls[-1]["arguments"] == {}
        assert "seats" not in json.dumps([event, executor.tool_calls[-1], self.journaled])
        # The record still tells the chat it was a refused question round.
        assert executor.tool_calls[-1]["status"] == "error"

    @pytest.mark.parametrize("mode", ["cards", "text"])
    def test_a_second_round(self, mode):
        executor, tools = _executor(mode)
        executor.questions_asked = True
        shown, messages = self._run(executor, tools, self.LEAKY)

        self._assert_no_raw_text(executor, shown)
        assert messages[-1]["content"] == ONE_ROUND_TEXT

    def test_a_call_beside_other_tools(self):
        executor, tools = _executor("cards")
        executor.calls_this_round = 2
        pause = executor.check_pause(tools, _call(args=self.LEAKY), "MockLLM")

        assert pause["pause_type"] == "headless_denied"
        assert pause["arguments"] == {}

    @pytest.mark.parametrize("mode", ["cards", "text"])
    def test_invalid_questions(self, mode):
        executor, tools = _executor(mode)
        shown, _messages = self._run(executor, tools, {"message": "seats secret", "questions": []})

        self._assert_no_raw_text(executor, shown)
        assert executor.tool_calls[-1]["error_type" if mode == "cards" else "status"]

    def test_where_questions_cant_be_shown(self):
        executor, tools = _executor(None)
        shown, _messages = self._run(executor, tools, self.LEAKY)

        self._assert_no_raw_text(executor, shown)
        assert executor.tool_calls[-1]["error_type"] == "questions_not_asked"

    def test_the_model_still_gets_its_own_call_back(self):
        executor, tools = _executor("cards")
        executor.questions_asked = True
        _shown, messages = self._run(executor, tools, self.LEAKY)

        (assistant,) = [m for m in messages if m.get("role") == "assistant"]
        (sent,) = assistant["tool_calls"]
        assert json.loads(sent["function"]["arguments"]) == self.LEAKY
        # A later turn replays the kept record: its arguments are still a JSON object.
        assert json.loads(json.dumps(executor.tool_calls[-1]["arguments"])) == {}
