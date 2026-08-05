"""Tests for application/agents/workflows/cel_evaluator.py"""

import pytest

from application.agents.workflows.cel_evaluator import (
    CelEvaluationError,
    _convert_value,
    build_activation,
    cel_to_python,
    evaluate_cel,
    validate_cel_expression,
)
import celpy.celtypes


class TestConvertValue:

    @pytest.mark.unit
    def test_bool_true(self):
        result = _convert_value(True)
        assert isinstance(result, celpy.celtypes.BoolType)
        assert bool(result) is True

    @pytest.mark.unit
    def test_bool_false(self):
        result = _convert_value(False)
        assert isinstance(result, celpy.celtypes.BoolType)
        assert bool(result) is False

    @pytest.mark.unit
    def test_int(self):
        result = _convert_value(42)
        assert isinstance(result, celpy.celtypes.IntType)
        assert int(result) == 42

    @pytest.mark.unit
    def test_float(self):
        result = _convert_value(3.14)
        assert isinstance(result, celpy.celtypes.DoubleType)
        assert float(result) == pytest.approx(3.14)

    @pytest.mark.unit
    def test_string(self):
        result = _convert_value("hello")
        assert isinstance(result, celpy.celtypes.StringType)
        assert str(result) == "hello"

    @pytest.mark.unit
    def test_list(self):
        result = _convert_value([1, "two", 3.0])
        assert isinstance(result, celpy.celtypes.ListType)

    @pytest.mark.unit
    def test_dict(self):
        result = _convert_value({"key": "value"})
        assert isinstance(result, celpy.celtypes.MapType)

    @pytest.mark.unit
    def test_none(self):
        result = _convert_value(None)
        assert isinstance(result, celpy.celtypes.BoolType)
        assert bool(result) is False

    @pytest.mark.unit
    def test_other_type_converts_to_string(self):
        result = _convert_value(object())
        assert isinstance(result, celpy.celtypes.StringType)


class TestBuildActivation:

    @pytest.mark.unit
    def test_converts_dict_values(self):
        state = {"name": "Alice", "age": 30, "active": True}
        result = build_activation(state)
        assert "name" in result
        assert "age" in result
        assert "active" in result

    @pytest.mark.unit
    def test_empty_state(self):
        assert build_activation({}) == {}


class TestEvaluateCel:

    @pytest.mark.unit
    def test_simple_comparison(self):
        assert evaluate_cel("x > 5", {"x": 10}) is True
        assert evaluate_cel("x > 5", {"x": 3}) is False

    @pytest.mark.unit
    def test_string_comparison(self):
        assert evaluate_cel('name == "Alice"', {"name": "Alice"}) is True
        assert evaluate_cel('name == "Alice"', {"name": "Bob"}) is False

    @pytest.mark.unit
    def test_arithmetic(self):
        assert evaluate_cel("x + y", {"x": 3, "y": 4}) == 7

    @pytest.mark.unit
    def test_boolean_logic(self):
        assert evaluate_cel("a && b", {"a": True, "b": True}) is True
        assert evaluate_cel("a && b", {"a": True, "b": False}) is False
        assert evaluate_cel("a || b", {"a": False, "b": True}) is True

    @pytest.mark.unit
    def test_empty_expression_raises(self):
        with pytest.raises(CelEvaluationError, match="Empty expression"):
            evaluate_cel("", {})

    @pytest.mark.unit
    def test_whitespace_expression_raises(self):
        with pytest.raises(CelEvaluationError, match="Empty expression"):
            evaluate_cel("   ", {})

    @pytest.mark.unit
    def test_invalid_expression_raises(self):
        with pytest.raises(CelEvaluationError):
            evaluate_cel("invalid!!!", {})

    @pytest.mark.unit
    def test_missing_variable_raises(self):
        with pytest.raises(CelEvaluationError):
            evaluate_cel("undefined_var > 5", {})


class TestCelToPython:

    @pytest.mark.unit
    def test_bool(self):
        result = cel_to_python(celpy.celtypes.BoolType(True))
        assert result is True

    @pytest.mark.unit
    def test_int(self):
        result = cel_to_python(celpy.celtypes.IntType(42))
        assert result == 42

    @pytest.mark.unit
    def test_double(self):
        result = cel_to_python(celpy.celtypes.DoubleType(3.14))
        assert result == pytest.approx(3.14)

    @pytest.mark.unit
    def test_string(self):
        result = cel_to_python(celpy.celtypes.StringType("hello"))
        assert result == "hello"

    @pytest.mark.unit
    def test_list(self):
        cel_list = celpy.celtypes.ListType([
            celpy.celtypes.IntType(1),
            celpy.celtypes.IntType(2),
        ])
        result = cel_to_python(cel_list)
        assert result == [1, 2]

    @pytest.mark.unit
    def test_map(self):
        cel_map = celpy.celtypes.MapType({
            celpy.celtypes.StringType("key"): celpy.celtypes.StringType("value"),
        })
        result = cel_to_python(cel_map)
        assert result == {"key": "value"}

    @pytest.mark.unit
    def test_unknown_type_passthrough(self):
        result = cel_to_python("raw_value")
        assert result == "raw_value"


class TestCelErrorMessages:
    """State/condition expressions are authored by users in the builder, so
    their errors have to read like guidance, not like a parser dump."""

    @pytest.mark.unit
    def test_template_syntax_gets_a_targeted_hint(self):
        """``{{query}}`` is valid in agent/end templates but not here.

        The docs used to document ``{{variable}}`` for Set State nodes, so
        users type it, get a bare caret dump, and have no way to learn that
        this one field is CEL.
        """
        with pytest.raises(CelEvaluationError) as exc:
            evaluate_cel("{{query}}", {"query": "hi"})
        message = str(exc.value)
        # The pre-fix message was "CEL error: {{query}}\n       ^\n", which
        # already contained "CEL", "query" and "{{" — so assert on the
        # guidance itself, not on incidental substrings.
        assert "not {{ }} template syntax" in message
        assert "Write query instead of {{query}}" in message

    @pytest.mark.unit
    def test_undeclared_reference_error_is_short(self):
        """celpy embeds the whole activation — thousands of chars, and it
        contains the user's own query text, which then lands in logs."""
        with pytest.raises(CelEvaluationError) as exc:
            evaluate_cel("customer_email", {"query": "a very secret question"})
        message = str(exc.value)
        assert len(message) <= 240, f"error is {len(message)} chars"
        assert "customer_email" in message
        assert "a very secret question" not in message
        assert "NameContainer" not in message

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "secret",
        [
            "SUPER-SECRET-VALUE",
            # An identifier-shaped value is indistinguishable from a variable
            # name, so it must be redacted too — this is the realistic case
            # (a one-word user query) and the earlier redaction let it through.
            "invoice",
            "SECRET",
        ],
    )
    def test_error_does_not_echo_state_values(self, secret):
        """Config errors skip sanitize_api_error now, so they must not carry
        state contents — a shared agent's runner is not its owner."""
        with pytest.raises(CelEvaluationError) as exc:
            evaluate_cel("int(query)", {"query": secret})
        assert secret not in str(exc.value)

    @pytest.mark.unit
    def test_error_keeps_the_exception_class(self):
        """Redaction must not swallow the one safe diagnostic."""
        with pytest.raises(CelEvaluationError) as exc:
            evaluate_cel("int(query)", {"query": "nope"})
        assert "ValueError" in str(exc.value)

    @pytest.mark.unit
    def test_long_error_is_truncated(self):
        """Backstop for celpy messages that survive activation-stripping."""
        from application.agents.workflows.cel_evaluator import _summarize_cel_error

        summary = _summarize_cel_error(Exception("word " * 200))
        assert len(summary) <= 200
        assert summary.endswith("…")

    @pytest.mark.unit
    def test_validate_rejects_empty_expression(self):
        with pytest.raises(CelEvaluationError, match="Empty expression"):
            validate_cel_expression("   ")

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "expression",
        [
            'query == "{{y}}"',  # braces inside a string literal
            '{{"a": 1}: 2}',     # map literal used as a map key
        ],
    )
    def test_valid_cel_containing_braces_is_not_rejected(self, expression):
        """The hint must never fire on expressions that actually compile."""
        validate_cel_expression(expression)

    @pytest.mark.unit
    def test_valid_expression_still_evaluates(self):
        assert evaluate_cel('query + "!"', {"query": "hi"}) == "hi!"


class TestValidateCelExpression:
    """Save-time gate: a workflow that cannot run should not save clean."""

    @pytest.mark.unit
    def test_accepts_valid_expression(self):
        validate_cel_expression("query + \"!\"")

    @pytest.mark.unit
    def test_rejects_template_syntax(self):
        with pytest.raises(CelEvaluationError, match="CEL"):
            validate_cel_expression("{{query}}")

    @pytest.mark.unit
    def test_rejects_syntax_error(self):
        with pytest.raises(CelEvaluationError):
            validate_cel_expression("query +")

    @pytest.mark.unit
    def test_accepts_reference_unknown_at_save_time(self):
        """Only syntax is knowable when saving — state is built at runtime,
        so an unresolved name must not block saving a valid workflow."""
        validate_cel_expression("node_abc_output + customer_email")
