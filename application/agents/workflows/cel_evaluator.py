from typing import Any, Dict

import celpy
import celpy.celtypes


class CelEvaluationError(Exception):
    pass


def _convert_value(value: Any) -> Any:
    if isinstance(value, bool):
        return celpy.celtypes.BoolType(value)
    if isinstance(value, int):
        return celpy.celtypes.IntType(value)
    if isinstance(value, float):
        return celpy.celtypes.DoubleType(value)
    if isinstance(value, str):
        return celpy.celtypes.StringType(value)
    if isinstance(value, list):
        return celpy.celtypes.ListType([_convert_value(item) for item in value])
    if isinstance(value, dict):
        return celpy.celtypes.MapType(
            {celpy.celtypes.StringType(k): _convert_value(v) for k, v in value.items()}
        )
    if value is None:
        return celpy.celtypes.BoolType(False)
    return celpy.celtypes.StringType(str(value))


def build_activation(state: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _convert_value(v) for k, v in state.items()}


def evaluate_cel(expression: str, state: Dict[str, Any]) -> Any:
    if not expression or not expression.strip():
        raise CelEvaluationError("Empty expression")
    try:
        env = celpy.Environment()
        ast = env.compile(expression)
        program = env.program(ast)
        activation = build_activation(state)
        result = program.evaluate(activation)
    except celpy.CELEvalError as exc:
        raise CelEvaluationError(f"CEL evaluation error: {exc}") from exc
    except Exception as exc:
        raise CelEvaluationError(f"CEL error: {exc}") from exc
    return cel_to_python(result)


def cel_to_python(value: Any) -> Any:
    if isinstance(value, celpy.celtypes.BoolType):
        return bool(value)
    if isinstance(value, celpy.celtypes.IntType):
        return int(value)
    if isinstance(value, celpy.celtypes.DoubleType):
        return float(value)
    if isinstance(value, celpy.celtypes.StringType):
        return str(value)
    if isinstance(value, celpy.celtypes.ListType):
        return [cel_to_python(item) for item in value]
    if isinstance(value, celpy.celtypes.MapType):
        return {str(k): cel_to_python(v) for k, v in value.items()}
    return value
