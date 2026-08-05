import re
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


_MAX_ERROR_CHARS = 200


def _summarize_cel_error(exc: Exception) -> str:
    """Reduce a celpy error to a short, value-free description.

    Two problems with the raw text. ``undeclared reference`` errors embed a
    repr of the *entire* activation — every binding, thousands of characters,
    including the user's own query. Others interpolate the offending **value**
    (``invalid literal for int() with base 10: StringType('…')``). Both get
    logged and, now that config errors skip ``sanitize_api_error``, shown. So
    strip the activation dump, drop anything that looks like a quoted value,
    and cap the result.
    """
    text = " ".join(str(exc).split())
    marker = " (in activation"
    if marker in text:
        text = text.split(marker, 1)[0]
    text = text.strip().lstrip("(").strip()

    # Redact quoted fragments by DEFAULT. celpy interpolates state values into
    # messages (``StringType('SECRET')``), and a value that happens to look
    # like an identifier is indistinguishable from a variable name — so allow
    # only the two positions that are known to hold names, not data: the
    # offending variable in "undeclared reference to 'x'", and the exception
    # class in "<class 'ValueError'>".
    def _redact(match: "re.Match[str]") -> str:
        inner = match.group(1)
        prefix = text[max(0, match.start() - 14):match.start()]
        if prefix.endswith("reference to ") or prefix.endswith("<class "):
            return f"'{inner}'"
        return "'…'"

    text = re.sub(r"'([^']*)'", _redact, text)
    text = text.strip().strip('"').strip()
    if len(text) > _MAX_ERROR_CHARS:
        text = text[: _MAX_ERROR_CHARS - 1].rstrip() + "…"
    return text


def _looks_like_template_syntax(expression: str) -> bool:
    """Whether the source contains a ``{{ … }}`` substitution.

    Only consulted **after** compilation has already failed: ``{{`` is legal
    CEL inside a string literal (``x == "{{y}}"``) and at the head of a nested
    map literal (``{{"a": 1}: 2}``), both of which compile fine and must not be
    rejected.
    """
    return "{{" in expression and "}}" in expression


def _template_syntax_error(expression: str) -> "CelEvaluationError":
    inner = expression.split("{{", 1)[1].split("}}", 1)[0].strip()
    suggestion = inner or "query"
    return CelEvaluationError(
        "This field takes a CEL expression, not {{ }} template syntax. "
        f"Write {suggestion} instead of {{{{{suggestion}}}}}."
    )


def _compile(expression: str):
    """Compile, translating failures into actionable messages."""
    try:
        return celpy.Environment().compile(expression)
    except Exception as exc:
        # Agent ``prompt_template`` and end ``output_template`` fields *are*
        # Jinja2, so ``{{query}}`` is correct one panel over. Here it fails to
        # parse with a bare caret, which reads as "the product is broken"
        # rather than "wrong syntax for this field".
        if _looks_like_template_syntax(expression):
            raise _template_syntax_error(expression) from exc
        raise CelEvaluationError(f"CEL error: {_summarize_cel_error(exc)}") from exc


def validate_cel_expression(expression: str) -> None:
    """Compile-check an expression without running it.

    Used at save time. Only syntax is knowable then — workflow state is built
    during a run, so unresolved names are *not* an error here.

    Args:
        expression: The CEL source to check.

    Raises:
        CelEvaluationError: If the expression is empty or does not compile.
    """
    if not expression or not expression.strip():
        raise CelEvaluationError("Empty expression")
    _compile(expression)


def evaluate_cel(expression: str, state: Dict[str, Any]) -> Any:
    if not expression or not expression.strip():
        raise CelEvaluationError("Empty expression")
    ast = _compile(expression)
    try:
        env = celpy.Environment()
        program = env.program(ast)
        activation = build_activation(state)
        result = program.evaluate(activation)
    except celpy.CELEvalError as exc:
        raise CelEvaluationError(
            f"CEL evaluation error: {_summarize_cel_error(exc)}"
        ) from exc
    except Exception as exc:
        raise CelEvaluationError(f"CEL error: {_summarize_cel_error(exc)}") from exc
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
