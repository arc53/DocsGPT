"""Tests for tool-result sanitization at the executor fan-out point.

``result_full`` fans out to the conversation row, ``tool_call_attempts``,
and (via the executor's return value) the LLM copy — sanitizing at the
source protects every lane at once.
"""

import pytest

from application.agents.tool_executor import (
    RESULT_FULL_MAX_CHARS,
    bound_result_full,
    sanitize_tool_result,
)


@pytest.mark.unit
class TestSanitizeToolResult:
    def test_strips_nul_bytes(self):
        assert sanitize_tool_result("a\x00b\x00c") == "abc"

    def test_strips_control_chars_keeps_whitespace(self):
        assert (
            sanitize_tool_result("line1\nline2\ttab\rret\x01\x08\x0b\x1f\x7fend")
            == "line1\nline2\ttab\rret" + "end"
        )

    def test_clean_string_returned_unchanged(self):
        s = "perfectly normal résumé text\nwith newlines"
        assert sanitize_tool_result(s) is s

    def test_recurses_into_dicts_including_keys(self):
        got = sanitize_tool_result({"k\x00ey": {"inner": "v\x00al"}})
        assert got == {"key": {"inner": "val"}}

    def test_recurses_into_lists_and_tuples(self):
        assert sanitize_tool_result(["a\x00", ("b\x00",)]) == ["a", ("b",)]

    def test_non_string_scalars_pass_through(self):
        for value in (42, 3.14, True, None, b"\x00raw"):
            assert sanitize_tool_result(value) == value


@pytest.mark.unit
class TestBoundResultFull:
    def test_short_text_unchanged(self):
        assert bound_result_full("short") == "short"

    def test_text_at_limit_unchanged(self):
        s = "x" * RESULT_FULL_MAX_CHARS
        assert bound_result_full(s) == s

    def test_oversized_text_truncated_with_marker(self):
        s = "x" * (RESULT_FULL_MAX_CHARS + 1000)
        got = bound_result_full(s)
        assert len(got) < len(s)
        assert "truncated" in got
        # The marker names the original size so the audit copy is honest
        # about what was dropped.
        assert str(len(s)) in got
