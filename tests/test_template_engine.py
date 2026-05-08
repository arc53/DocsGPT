from unittest.mock import patch

import pytest

from application.templates.template_engine import TemplateEngine, TemplateRenderError


@pytest.fixture
def engine():
    return TemplateEngine()


# ── render ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRender:
    def test_simple_variable(self, engine):
        result = engine.render("Hello {{ name }}", {"name": "World"})
        assert result == "Hello World"

    def test_empty_template_returns_empty(self, engine):
        assert engine.render("", {"x": 1}) == ""

    def test_none_template_returns_empty(self, engine):
        assert engine.render(None, {"x": 1}) == ""

    def test_no_variables(self, engine):
        assert engine.render("plain text", {}) == "plain text"

    def test_multiple_variables(self, engine):
        tpl = "{{ a }} and {{ b }}"
        assert engine.render(tpl, {"a": "X", "b": "Y"}) == "X and Y"

    def test_nested_dict_access(self, engine):
        tpl = "{{ data.key }}"
        assert engine.render(tpl, {"data": {"key": "value"}}) == "value"

    def test_loop(self, engine):
        tpl = "{% for i in items %}{{ i }} {% endfor %}"
        result = engine.render(tpl, {"items": ["a", "b", "c"]})
        assert result.strip() == "a b c"

    def test_conditional(self, engine):
        tpl = "{% if show %}yes{% else %}no{% endif %}"
        assert engine.render(tpl, {"show": True}) == "yes"
        assert engine.render(tpl, {"show": False}) == "no"

    def test_syntax_error_raises_template_render_error(self, engine):
        with pytest.raises(TemplateRenderError, match="syntax error"):
            engine.render("{% if %}", {})

    def test_undefined_variable_chainable(self, engine):
        # ChainableUndefined should NOT raise; it silently returns empty
        result = engine.render("{{ missing }}", {})
        assert result == ""

    def test_autoescape_html(self, engine):
        result = engine.render("{{ content }}", {"content": "<script>alert(1)</script>"})
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_trim_blocks(self, engine):
        tpl = "{% if True %}\nyes\n{% endif %}"
        result = engine.render(tpl, {})
        assert result.strip() == "yes"

    def test_general_exception_raises_template_render_error(self, engine):
        with patch.object(engine._env, "from_string", side_effect=RuntimeError("boom")):
            with pytest.raises(TemplateRenderError, match="rendering failed"):
                engine.render("{{ x }}", {"x": 1})


# ── validate_template ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestValidateTemplate:
    def test_valid_template(self, engine):
        assert engine.validate_template("{{ name }}") is True

    def test_empty_template_valid(self, engine):
        assert engine.validate_template("") is True

    def test_none_template_valid(self, engine):
        assert engine.validate_template(None) is True

    def test_invalid_syntax(self, engine):
        assert engine.validate_template("{% if %}") is False

    def test_plain_text_valid(self, engine):
        assert engine.validate_template("just plain text") is True

    def test_complex_valid_template(self, engine):
        tpl = "{% for x in items %}{{ x.name }}{% endfor %}"
        assert engine.validate_template(tpl) is True

    def test_general_exception_returns_false(self, engine):
        with patch.object(engine._env, "from_string", side_effect=RuntimeError("boom")):
            assert engine.validate_template("{{ x }}") is False


# ── extract_variables ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractVariables:
    def test_empty_template(self, engine):
        assert engine.extract_variables("") == set()

    def test_none_template(self, engine):
        assert engine.extract_variables(None) == set()

    def test_syntax_error_returns_empty(self, engine):
        assert engine.extract_variables("{% if %}") == set()

    def test_general_exception_returns_empty(self, engine):
        with patch.object(engine._env, "parse", side_effect=RuntimeError("boom")):
            assert engine.extract_variables("{{ x }}") == set()


# ── extract_tool_usages ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractToolUsages:
    def test_empty_template(self, engine):
        assert engine.extract_tool_usages("") == {}

    def test_none_template(self, engine):
        assert engine.extract_tool_usages(None) == {}

    def test_syntax_error_returns_empty(self, engine):
        assert engine.extract_tool_usages("{% if %}") == {}

    def test_getattr_single_tool(self, engine):
        tpl = "{{ tools.memory.notes }}"
        result = engine.extract_tool_usages(tpl)
        assert "memory" in result
        assert "notes" in result["memory"]

    def test_getattr_tool_without_action(self, engine):
        tpl = "{{ tools.search }}"
        result = engine.extract_tool_usages(tpl)
        assert "search" in result
        assert None in result["search"]

    def test_getitem_bracket_notation(self, engine):
        tpl = '{{ tools["calendar"]["events"] }}'
        result = engine.extract_tool_usages(tpl)
        assert "calendar" in result
        assert "events" in result["calendar"]

    def test_multiple_tools(self, engine):
        tpl = "{{ tools.memory.notes }} {{ tools.search.query }}"
        result = engine.extract_tool_usages(tpl)
        assert "memory" in result
        assert "search" in result

    def test_same_tool_multiple_actions(self, engine):
        tpl = "{{ tools.memory.notes }} {{ tools.memory.tasks }}"
        result = engine.extract_tool_usages(tpl)
        assert "memory" in result
        assert "notes" in result["memory"]
        assert "tasks" in result["memory"]

    def test_non_tools_getattr_ignored(self, engine):
        tpl = "{{ data.something }}"
        result = engine.extract_tool_usages(tpl)
        assert result == {}

    def test_general_parse_error_returns_empty(self, engine):
        with patch.object(engine._env, "parse", side_effect=RuntimeError("boom")):
            assert engine.extract_tool_usages("{{ tools.x }}") == {}

    def test_tools_in_loop(self, engine):
        tpl = "{% for item in tools.memory.notes %}{{ item }}{% endfor %}"
        result = engine.extract_tool_usages(tpl)
        assert "memory" in result
        assert "notes" in result["memory"]

    def test_tools_in_conditional(self, engine):
        tpl = "{% if tools.search.results %}found{% endif %}"
        result = engine.extract_tool_usages(tpl)
        assert "search" in result
        assert "results" in result["search"]
