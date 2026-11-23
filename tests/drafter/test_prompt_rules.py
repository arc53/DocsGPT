"""The prompt rules: tool variables only where the user asked for them."""

from __future__ import annotations

import pytest

from docsgpt.drafter.prompt_rules import tool_variables, tool_variables_problem
from docsgpt.drafter.recipe import DraftRequest

VIEW = "Memory: {{ tools.memory.memory_view }}"


def _req(*user_messages: str) -> DraftRequest:
    messages = [{"role": "user", "content": text} for text in user_messages]
    return DraftRequest(user_id="alice", recipe="prompt", messages=messages, context={}, request_id="r")


@pytest.mark.unit
class TestToolVariables:
    def test_usages_are_tool_and_action_pairs(self):
        content = VIEW + " {{ tools['search']['run'] }} {% if tools.notes %}x{% endif %}"
        assert tool_variables(content) == {("memory", "memory_view"), ("search", "run"), ("notes", None)}

    def test_the_enabled_tools_list_is_not_a_tool(self):
        # ``tools.enabled`` lists the tools attached this turn (the built-in prompts gate a line on it); it runs none.
        content = VIEW + " {% if 'monitor' in tools.enabled %}x{% endif %}"
        assert tool_variables(content) == {("memory", "memory_view")}
        assert tool_variables_problem(content, VIEW, _req("Mention monitors")) is None

    def test_another_action_of_a_tool_already_used_is_added(self):
        content = VIEW + " {{ tools.memory.memory_create }}"
        assert tool_variables_problem(content, VIEW, _req("Make it friendlier")) is not None

    def test_the_variables_already_there_may_stay(self):
        assert tool_variables_problem(VIEW + " Be brief.", VIEW, _req("Make it shorter")) is None

    @pytest.mark.parametrize("ask", [
        "A support bot that can use my tools.",
        "Put {{ system.date }} in it",
        "Add {{ tools.search.run }}",
        "Use tools.memory.memory_create",
    ])
    def test_an_ask_for_something_else_does_not_unlock_it(self, ask):
        assert tool_variables_problem(VIEW, "", _req(ask)) is not None

    @pytest.mark.parametrize("ask", [
        "Put {{ tools.memory.memory_view }} in the prompt",
        "Add tools.memory.memory_view to it",
        "Add {{ tools['memory']['memory_view'] }}",
        "Show {{ tools.memory }} at the top",
    ])
    def test_the_variable_the_user_asked_for_is_allowed(self, ask):
        assert tool_variables_problem(VIEW, "", _req(ask)) is None

    def test_the_problem_names_what_was_not_asked_for(self):
        problem = tool_variables_problem(VIEW, "", _req("Make it friendlier"))
        assert "{{ tools.memory.memory_view }}" in problem
