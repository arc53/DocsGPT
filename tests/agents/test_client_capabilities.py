"""What a chat client says it can render (the request's ``capabilities``)."""

from __future__ import annotations

import pytest

from docsgpt.agents.client_capabilities import FORMS, MAX_CAPABILITIES, parse_capabilities


class TestParseCapabilities:
    def test_forms_is_read(self):
        assert parse_capabilities(["forms"]) == frozenset({FORMS})

    @pytest.mark.parametrize("value", [None, "forms", {"forms": True}, 1, True, b"forms"])
    def test_anything_but_a_list_is_none(self, value):
        assert parse_capabilities(value) == frozenset()

    def test_unknown_values_and_non_strings_are_dropped(self):
        assert parse_capabilities(["mermaid", "forms", 3, None, {"a": 1}]) == frozenset({FORMS})

    def test_values_match_exactly(self):
        assert parse_capabilities(["FORMS", " forms"]) == frozenset()

    def test_only_the_first_entries_are_read(self):
        assert parse_capabilities(["x"] * MAX_CAPABILITIES + ["forms"]) == frozenset()
        assert parse_capabilities(["x"] * (MAX_CAPABILITIES - 1) + ["forms"]) == frozenset({FORMS})

    def test_a_tuple_is_a_list(self):
        assert parse_capabilities(("forms",)) == frozenset({FORMS})
