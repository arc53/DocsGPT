"""A hallucinated tool call must be correctable and must not loop.

A first-session user's model invented ``note_view`` (a real tool in the repo,
but not one they had enabled) and called it 22 times in five and a half
minutes. Two defects turned one hallucination into 22 paid model calls: the
parse-failure branch returned no list of valid tools — unlike the sibling
tool-not-found branch, which does — and nothing noticed that the identical call
had already failed. The only bound was ``MAX_TOOL_ITERATIONS = 25`` per turn.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from application.agents.tool_executor import ToolExecutor


def _tools_dict():
    return {
        "t1": {"name": "memory", "actions": [], "config": {}},
        "t2": {"name": "read_webpage", "actions": [], "config": {}},
    }


def _call(name, arguments="{}", call_id="c1"):
    call = Mock()
    call.name = name
    call.arguments = arguments
    call.id = call_id
    return call


def _drain(executor, call, tools=None):
    """Run ``execute`` to completion and return (events, result)."""
    gen = executor.execute(tools if tools is not None else _tools_dict(), call, "OpenAILLM")
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as stop:
            return events, stop.value


@pytest.mark.unit
class TestHallucinatedToolCalls:
    def test_a_registered_name_with_bad_arguments_is_not_blamed_on_the_name(self):
        """Only the half that actually failed may be reported."""
        executor = ToolExecutor()
        tools = _tools_dict()
        executor._name_to_tool = {"memory_view": ("t1", "memory_view")}
        _events, (result, _call_id) = _drain(
            executor, _call("memory_view", arguments="{not json"), tools=tools
        )
        assert "arguments were not a valid JSON object" in result, result
        assert "the tool name could not be resolved" not in result, result

    def test_parse_failure_tells_the_model_which_tools_exist(self):
        executor = ToolExecutor()
        # Unresolvable name AND unusable arguments: the branch under test.
        events, (result, _call_id) = _drain(executor, _call("bash", arguments="not json"))

        assert executor.tool_calls[0]["status"] == "error"
        reported = executor.tool_calls[0]["result"]
        assert "memory" in reported and "read_webpage" in reported, reported
        assert "memory" in result and "read_webpage" in result, result

    def test_tool_not_found_still_lists_available_tools(self):
        executor = ToolExecutor()
        _events, (result, _call_id) = _drain(executor, _call("note_view"))
        assert "memory" in result

    def test_repeated_identical_failure_is_cut_short(self):
        """The third identical failing call must be refused without re-running."""
        executor = ToolExecutor()
        for index in range(3):
            _drain(executor, _call("note_view", call_id=f"c{index}"))

        assert len(executor.tool_calls) == 3
        last = executor.tool_calls[-1]["result"]
        assert "has already failed" in last, last
        assert "Stop calling it" in last, last

    def test_a_different_failing_call_is_not_suppressed(self):
        executor = ToolExecutor()
        for index in range(3):
            _drain(executor, _call("note_view", call_id=f"c{index}"))
        _events, (result, _call_id) = _drain(executor, _call("todo_view", call_id="other"))
        assert "has already failed" not in result, result
        assert "no such tool" in result, result

    def test_the_guard_does_not_fire_on_the_first_two_attempts(self):
        executor = ToolExecutor()
        for index in range(2):
            _events, (result, _call_id) = _drain(executor, _call("note_view", call_id=f"c{index}"))
            assert "has already failed" not in result, result


@pytest.mark.unit
class TestErrorNamesWhatTheModelCanCall:
    def test_prefers_llm_visible_action_names_over_tool_names(self):
        """The model calls action names, so those are what the error must list."""
        executor = ToolExecutor()
        tools_dict = {
            "t1": {
                "name": "artifact_generator",
                "actions": [
                    {
                        "name": "create_artifact",
                        "description": "D",
                        "active": True,
                        "parameters": {"properties": {}},
                    }
                ],
            }
        }
        executor.prepare_tools_for_llm(tools_dict)
        _events, (result, _call_id) = _drain(executor, _call("make_a_pdf"), tools=tools_dict)
        assert "create_artifact" in result
