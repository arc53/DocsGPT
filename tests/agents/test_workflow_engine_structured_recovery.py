"""Engine robustness: fenced/prose structured output recovery in _parse_structured_output."""

from __future__ import annotations

from application.agents.workflows.workflow_engine import WorkflowEngine


def _engine() -> WorkflowEngine:
    return WorkflowEngine.__new__(WorkflowEngine)


def test_parse_structured_output_bare_json():
    ok, val = _engine()._parse_structured_output('{"x": true}')
    assert ok and val == {"x": True}


def test_parse_structured_output_json_fence():
    ok, val = _engine()._parse_structured_output('```json\n{"a": 1, "b": null}\n```')
    assert ok and val == {"a": 1, "b": None}


def test_parse_structured_output_unlabelled_fence():
    ok, val = _engine()._parse_structured_output("text\n```\n{\"y\": [1, 2]}\n```\nmore")
    assert ok and val == {"y": [1, 2]}


def test_parse_structured_output_prose_wrapped_object():
    ok, val = _engine()._parse_structured_output('Result: {"z": "v"} done')
    assert ok and val == {"z": "v"}


def test_parse_structured_output_non_json():
    ok, val = _engine()._parse_structured_output("not json at all")
    assert ok is False and val is None


def test_parse_structured_output_empty():
    ok, val = _engine()._parse_structured_output("   ")
    assert ok is False and val is None


def test_strip_json_fence_prefers_fence_over_braces():
    out = WorkflowEngine._strip_json_fence('lead {"outer": 1} ```json\n{"in": 2}\n```')
    assert out == '{"in": 2}'
