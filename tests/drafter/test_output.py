"""Reading a model's text answer: the JSON object in it, wherever it sits."""

from __future__ import annotations

import json
import time

import pytest

from docsgpt.drafter.output import parse_echoed_event, parse_json_object

CODE = {"content": "Answer like this:\n```python\nprint(1)\n```\nThen stop."}


@pytest.mark.unit
class TestParseJsonObject:
    def test_code_fences_inside_a_value_after_prose(self):
        assert parse_json_object("Here it is: " + json.dumps(CODE)) == CODE

    def test_code_fences_inside_a_value_in_a_fenced_answer(self):
        assert parse_json_object(f"```json\n{json.dumps(CODE, indent=2)}\n```") == CODE

    def test_braces_in_prose_before_the_object(self):
        assert parse_json_object('Use {name} in it. {"a": 1}') == {"a": 1}

    def test_the_first_object_wins(self):
        assert parse_json_object('{"a": 1} and then {"b": 2}') == {"a": 1}

    def test_a_nested_object_is_read_whole(self):
        assert parse_json_object('Sure: {"a": {"b": [1, {"c": 2}]}} done') == {"a": {"b": [1, {"c": 2}]}}

    @pytest.mark.parametrize("raw", ['{"a": ', "{not json}", "[1, 2]"])
    def test_no_object_that_decodes(self, raw):
        assert parse_json_object(raw) is None


@pytest.mark.unit
class TestBudgets:
    """The model's text and echoed history are read in about linear time, whatever they hold."""

    BUDGET = 0.5

    def _fast(self, fn, *args):
        started = time.perf_counter()
        result = fn(*args)
        assert time.perf_counter() - started < self.BUDGET
        return result

    def test_many_unclosed_braces_are_linear(self):
        assert self._fast(parse_json_object, "x{" * 60_000) is None

    def test_an_object_after_a_few_braces_in_prose_is_still_found(self):
        assert parse_json_object("Use {a}, {b} and {c}: " + json.dumps(CODE)) == CODE

    def test_deep_nesting_is_no_object(self):
        assert parse_json_object("[" * 100_000) is None
        assert parse_json_object("{" + '"a":[' * 100_000) is None


@pytest.mark.unit
class TestParseEchoedEvent:
    def test_an_event_the_panel_sent_back(self):
        assert parse_echoed_event(json.dumps({"type": "questions", "questions": []})) == {
            "type": "questions", "questions": []}

    @pytest.mark.parametrize("raw", ["plain words", 'Sure: {"a": 1}', "[1]", "", None, 5, "{" * 100_000])
    def test_anything_else_is_no_event(self, raw):
        assert parse_echoed_event(raw) is None

    def test_echoed_text_is_never_scanned(self):
        started = time.perf_counter()
        assert parse_echoed_event("x{" * 60_000) is None
        assert time.perf_counter() - started < 0.1
