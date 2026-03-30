"""Tests for application/agents/workflows/cel_evaluator.py"""

import pytest

from application.agents.workflows.cel_evaluator import (
    CelEvaluationError,
    _convert_value,
    build_activation,
    cel_to_python,
    evaluate_cel,
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
