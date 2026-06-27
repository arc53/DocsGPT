"""Unit tests for ArtifactGeneratorTool: spec validation, merge-patch, and renderer injection safety.

No DB or sandbox: these exercise the pure logic (schema gate + RFC 7386 merge)
and the FIXED renderer programs directly (executed in-process against a temp dir)
to prove a spec value containing Python/quotes is rendered as literal text.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from application.agents.tools.artifact_generator import (
    _KIND_INFO,
    _RENDERERS,
    ArtifactGeneratorTool,
    merge_patch,
)

pytest.importorskip("pptx")
pytest.importorskip("docx")
pytest.importorskip("openpyxl")
pytest.importorskip("reportlab")


def _tool():
    return ArtifactGeneratorTool(
        tool_config={"conversation_id": "conv-1", "tool_id": "t-1"}, user_id="u-1"
    )


# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------


def test_validate_accepts_minimal_presentation():
    assert _tool()._validate("presentation", {"slides": [{"title": "x"}]}) is None


def test_validate_rejects_missing_required_key():
    err = _tool()._validate("presentation", {"title": "no slides"})
    assert err["status"] == "error"
    assert "invalid presentation spec" in err["error"]


def test_validate_rejects_unknown_key():
    err = _tool()._validate("document", {"sections": [], "bogus": 1})
    assert err["status"] == "error"


def test_validate_rejects_wrong_type():
    err = _tool()._validate("spreadsheet", {"sheets": "not-a-list"})
    assert err["status"] == "error"


def test_validate_rejects_non_object_spec():
    err = _tool()._validate("pdf", "just a string")
    assert err["status"] == "error"
    assert "spec must be a JSON object" in err["error"]


def test_create_rejects_unknown_kind():
    out = _tool()._create(kind="hologram", spec={})
    assert out["status"] == "error"
    assert "unsupported kind" in out["error"]


# ---------------------------------------------------------------------------
# RFC 7386 JSON merge-patch
# ---------------------------------------------------------------------------


def test_merge_patch_adds_and_overwrites():
    assert merge_patch({"a": 1, "b": 2}, {"b": 3, "c": 4}) == {"a": 1, "b": 3, "c": 4}


def test_merge_patch_null_deletes_key():
    assert merge_patch({"a": 1, "b": 2}, {"b": None}) == {"a": 1}


def test_merge_patch_recurses_into_objects():
    assert merge_patch({"x": {"a": 1, "b": 2}}, {"x": {"b": None, "c": 3}}) == {"x": {"a": 1, "c": 3}}


def test_merge_patch_replaces_array_wholesale():
    # RFC 7386: arrays are replaced, not merged element-wise.
    assert merge_patch({"l": [1, 2, 3]}, {"l": [9]}) == {"l": [9]}


def test_merge_patch_non_object_patch_replaces_target():
    assert merge_patch({"a": 1}, "scalar") == "scalar"


def test_merge_patch_does_not_mutate_inputs():
    target = {"a": {"b": 1}}
    patch = {"a": {"c": 2}}
    merge_patch(target, patch)
    assert target == {"a": {"b": 1}}
    assert patch == {"a": {"c": 2}}


# ---------------------------------------------------------------------------
# Renderer injection safety
# ---------------------------------------------------------------------------


def _render_in_process(kind: str, spec: dict) -> str:
    """Execute the FIXED renderer program against a temp dir; return the output path."""
    workdir = tempfile.mkdtemp()
    spec_path = os.path.join(workdir, "spec.json")
    out_path = os.path.join(workdir, f"out.{_KIND_INFO[kind]['ext']}")
    with open(spec_path, "w") as handle:
        json.dump(spec, handle)
    program = _RENDERERS[kind].format(spec_path=spec_path, out_path=out_path)
    namespace: dict = {}
    exec(compile(program, "<renderer>", "exec"), namespace, namespace)  # noqa: S102
    return out_path


def test_renderer_does_not_execute_spec_code(capfd, tmp_path):
    # A spec whose values are Python source / shell payloads must be treated as
    # literal text. If the renderer string-interpolated the spec it would run
    # this; instead it json.loads the spec as data, so nothing executes.
    sentinel = tmp_path / "pwned.txt"
    payload = (
        f"'''__import__('os').system('echo PWNED > {sentinel}')'''; "
        "print('SHOULD_NOT_PRINT')"
    )
    spec = {
        "title": payload,
        "slides": [{"title": payload, "bullets": [payload], "notes": payload}],
    }
    out_path = _render_in_process("presentation", spec)

    captured = capfd.readouterr()
    assert "SHOULD_NOT_PRINT" not in captured.out
    assert "PWNED" not in captured.out
    assert not sentinel.exists()
    assert os.path.getsize(out_path) > 0


def test_renderer_keeps_injection_text_as_literal_content():
    from pptx import Presentation

    payload = "'''; import os; os.system('echo HACK'); x = '''"
    spec = {"slides": [{"title": payload, "bullets": [payload]}]}
    prs = Presentation(_render_in_process("presentation", spec))
    assert len(prs.slides) == 1
    assert prs.slides[0].shapes.title.text == payload


def test_pdf_renderer_escapes_markup_and_does_not_execute():
    payload = "<b>not bold</b> & \"</para>\" '''os.system('x')'''"
    spec = {"title": payload, "blocks": [{"type": "paragraph", "text": payload}]}
    out_path = _render_in_process("pdf", spec)
    assert os.path.getsize(out_path) > 0


# ---------------------------------------------------------------------------
# html kind: schema, renderer injection safety, output escaping
# ---------------------------------------------------------------------------


def test_validate_accepts_html_spec():
    spec = {
        "title": "Report",
        "blocks": [
            {"type": "heading", "text": "Intro", "level": 2},
            {"type": "paragraph", "text": "Body."},
            {"type": "list", "ordered": True, "items": ["a", "b"]},
            {"type": "table", "headers": ["h"], "rows": [["c"]]},
            {"type": "code", "text": "print(1)"},
        ],
    }
    assert _tool()._validate("html", spec) is None


def test_validate_rejects_html_unknown_block_key():
    err = _tool()._validate("html", {"blocks": [{"type": "paragraph", "text": "x", "bogus": 1}]})
    assert err["status"] == "error"


def test_validate_rejects_html_bad_heading_level():
    err = _tool()._validate("html", {"blocks": [{"type": "heading", "text": "x", "level": 9}]})
    assert err["status"] == "error"


def test_html_renderer_does_not_execute_spec_code(capfd, tmp_path):
    # The renderer json.loads the spec as data; a value that is Python source
    # must never run. If the program string-interpolated the spec it would.
    sentinel = tmp_path / "pwned.txt"
    payload = (
        f"'''__import__('os').system('echo PWNED > {sentinel}')'''; "
        "print('SHOULD_NOT_PRINT')"
    )
    spec = {"title": payload, "blocks": [{"type": "paragraph", "text": payload}]}
    out_path = _render_in_process("html", spec)

    captured = capfd.readouterr()
    assert "SHOULD_NOT_PRINT" not in captured.out
    assert "PWNED" not in captured.out
    assert not sentinel.exists()
    assert os.path.getsize(out_path) > 0


def test_html_renderer_escapes_spec_markup():
    # Spec text carrying live markup must appear HTML-ESCAPED in the output, so
    # no raw <script>/<img onerror> tag from spec content reaches the document.
    script = "<script>alert(1)</script>"
    img = '<img src=x onerror="alert(2)">'
    spec = {
        "title": script,
        "blocks": [
            {"type": "paragraph", "text": img},
            {"type": "heading", "text": "<b>h</b>", "level": 1},
            {"type": "list", "items": ["<i>x</i>"]},
            {"type": "table", "headers": ["<u>th</u>"], "rows": [["<em>td</em>"]]},
            {"type": "code", "text": "</code><script>x</script>"},
        ],
    }
    with open(_render_in_process("html", spec), encoding="utf-8") as handle:
        html_doc = handle.read()

    # No live tag from spec content survives.
    assert "<script>alert(1)</script>" not in html_doc
    assert "<img src=x onerror=" not in html_doc
    assert "<b>h</b>" not in html_doc
    assert "<i>x</i>" not in html_doc
    assert "<u>th</u>" not in html_doc
    assert "<em>td</em>" not in html_doc
    # The escaped forms are present instead.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_doc
    assert "&lt;img src=x onerror=" in html_doc
    # The fixed structural HTML the renderer emits is intact.
    assert "<!doctype html>" in html_doc
    assert "<p>" in html_doc and "</p>" in html_doc
    assert "<table>" in html_doc and "<pre><code>" in html_doc
