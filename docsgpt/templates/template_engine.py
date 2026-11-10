import functools
import logging
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Set

from jinja2 import (
    ChainableUndefined,
    nodes,
    TemplateSyntaxError,
)
from jinja2.compiler import CodeGenerator, Frame, optimizeconst
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.filters import make_attrgetter
from jinja2.runtime import Context
from jinja2.sandbox import SandboxedEnvironment, SandboxedEscapeFormatter, SandboxedFormatter
from jinja2.utils import _PassArg, pass_context
from markupsafe import Markup

logger = logging.getLogger(__name__)

#: The longest string or list one operator or filter may build. Prompts are
#: capped well below this, so only a template that multiplies its own text
#: reaches it.
MAX_TEMPLATE_SEQUENCE = 1_000_000
#: The largest integer, in bits, ``*`` or ``**`` may produce (about 4,900
#: digits, past what Python will print as text anyway).
MAX_TEMPLATE_INT_BITS = 16_384

# One ``%`` conversion: an optional ``(key)``, flags, width, precision, a
# length modifier and the conversion character (``%%`` takes no value).
_PERCENT_SPEC = re.compile(r"%(?:\([^)]*\))?[-#0 +]*(\*|\d+)?(?:\.(\*|\d+)?)?[hlL]?(.)", re.DOTALL)


def _refuse(message: str) -> None:
    raise SecurityError(message)


def _check_percent_format(fmt: str, args: Any) -> None:
    """Refuse a ``%`` format whose width or precision would pad past the cap.

    Args:
        fmt: The format string.
        args: The value(s) formatted into it; a ``*`` width reads its number from them.

    Raises:
        SecurityError: When a width or precision is over ``MAX_TEMPLATE_SEQUENCE``.
    """
    if "%" not in fmt:
        return
    values = args if isinstance(args, tuple) else (args,)
    # The conversions take their values in order: a ``*`` width or precision
    # takes the next one as its size, then the conversion takes its own, so
    # only the values a ``*`` takes are sizes (``"%*d" % (10, 1234567)``).
    position = 0
    for match in _PERCENT_SPEC.finditer(fmt):
        width, precision, conversion = match.groups()
        for size in (width, precision):
            if size == "*":
                value = values[position] if position < len(values) else None
                position += 1
                if isinstance(value, int) and abs(value) > MAX_TEMPLATE_SEQUENCE:
                    _refuse("format width too large")
            elif size and int(size) > MAX_TEMPLATE_SEQUENCE:
                _refuse("format width too large")
        if conversion != "%":
            position += 1


def _check_width(width: Any) -> None:
    if isinstance(width, int) and width > MAX_TEMPLATE_SEQUENCE:
        _refuse("width too large")
    if isinstance(width, str) and len(width) > MAX_TEMPLATE_SEQUENCE:
        _refuse("width too large")


def _check_replace(value: Any, old: Any = None, new: Any = None, count: Any = None, *_: Any) -> None:
    if not isinstance(value, str) or not isinstance(old, str) or not isinstance(new, str):
        return
    if len(new) <= len(old):
        return
    hits = len(value) + 1 if not old else value.count(old)
    if isinstance(count, int) and count >= 0:
        hits = min(hits, count)
    if len(value) + hits * (len(new) - len(old)) > MAX_TEMPLATE_SEQUENCE:
        _refuse("replace result too large")


# A run of digits in a ``str.format`` field spec: its width or precision (a
# fill character is a single character, so it never joins a run).
_SPEC_NUMBER = re.compile(r"\d+")


def _check_format_spec(spec: str) -> None:
    """Refuse a ``str.format`` field whose width or precision would pad past the cap."""
    for number in _SPEC_NUMBER.findall(spec or ""):
        if len(number) > 7 or int(number) > MAX_TEMPLATE_SEQUENCE:
            _refuse("format width too large")


def _text_length(value: Any) -> int:
    return len(value) if isinstance(value, str) else len(str(value))


def _check_joined(parts: List[Any], separator: Any = "") -> None:
    """Refuse joining ``parts`` when the result would pass the cap."""
    total = _text_length(separator) * max(len(parts) - 1, 0)
    for part in parts:
        total += _text_length(part)
        if total > MAX_TEMPLATE_SEQUENCE:
            _refuse("joined text too long")


def _bounded_join(parts: Any) -> str:
    """``str_join`` for the ``~`` operator, refusing a result past the cap."""
    texts = [str(part) for part in parts]
    _check_joined(texts)
    return "".join(texts)


class _BoundedFormatter(SandboxedFormatter):
    """The sandbox's ``str.format`` formatter, refusing a width or precision past the cap."""

    def format_field(self, value: Any, format_spec: str) -> Any:
        _check_format_spec(format_spec)
        return super().format_field(value, format_spec)


class _BoundedEscapeFormatter(_BoundedFormatter, SandboxedEscapeFormatter):
    pass


class _BoundedCodeGenerator(CodeGenerator):
    """Compiles ``~`` to a join that refuses a result past the cap.

    ``~`` is not an operator the sandbox can intercept: Jinja writes it as a
    call to its own ``str_join``, so doubling a string in a loop reached a
    gigabyte in about thirty steps.
    """

    @optimizeconst
    def visit_Concat(self, node: nodes.Concat, frame: Frame) -> None:
        if frame.eval_ctx.volatile or frame.eval_ctx.autoescape:
            super().visit_Concat(node, frame)
            return
        self.write("environment.bounded_join((")
        for arg in node.nodes:
            self.visit(arg, frame)
            self.write(", ")
        self.write("))")


def _check_str_method(name: str, text: str, args: tuple, kwargs: Mapping[str, Any]) -> None:
    """Refuse a ``str`` method call from a template that would build an oversized string."""
    if name in ("ljust", "rjust", "center", "zfill"):
        _check_width(args[0] if args else kwargs.get("width"))
    elif name == "expandtabs":
        size = args[0] if args else kwargs.get("tabsize", 8)
        if isinstance(size, int) and len(text) + text.count("\t") * max(size, 0) > MAX_TEMPLATE_SEQUENCE:
            _refuse("expanded text too long")
    elif name == "replace":
        _check_replace(text, *args, **{k: v for k, v in kwargs.items() if k == "count"})


def _filter_guard(name: str, args: tuple, kwargs: Mapping[str, Any], environment: Any) -> tuple:
    """Refuse a filter call that would build an oversized string before it runs.

    Returns:
        The filter's positional arguments; ``join`` gets its value as a list,
        read once for the check.
    """
    if name == "join" and args:
        value = args[0] if isinstance(args[0], (str, list, tuple)) else list(args[0])
        attribute = args[2] if len(args) > 2 else kwargs.get("attribute")
        separator = args[1] if len(args) > 1 else kwargs.get("d", "")
        items = list(value)
        if attribute is not None:
            getter = make_attrgetter(environment, attribute)
            items = [getter(item) for item in items]
        _check_joined(items, separator)
        return (value, *args[1:])
    if name == "center":
        _check_width(args[1] if len(args) > 1 else kwargs.get("width"))
    elif name == "indent":
        _check_width(args[1] if len(args) > 1 else kwargs.get("width"))
    elif name == "format" and args and isinstance(args[0], str):
        _check_percent_format(args[0], args[1:] or tuple(kwargs.values()))
    elif name == "replace" and args:
        _check_replace(*args, **{k: v for k, v in kwargs.items() if k in ("old", "new", "count")})
    return args


def _runtime_filter(name: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a filter so it only ever runs while rendering, with size checks.

    Jinja folds a filter applied to constants while it compiles, so a prompt
    as short as ``{{ "x" | center(100000000) }}`` built its result just by
    being checked. A ``pass_context`` filter is never folded.

    Args:
        name: The filter's name, which picks its size check.
        func: The filter as Jinja registers it.

    Returns:
        A context filter that checks its arguments, then calls ``func``.
    """
    pass_arg = _PassArg.from_obj(func)

    @pass_context
    @functools.wraps(func)
    def wrapper(context: Context, *args: Any, **kwargs: Any) -> Any:
        args = _filter_guard(name, args, kwargs, context.environment)
        if pass_arg is _PassArg.context:
            return func(context, *args, **kwargs)
        if pass_arg is _PassArg.eval_context:
            return func(context.eval_ctx, *args, **kwargs)
        if pass_arg is _PassArg.environment:
            return func(context.environment, *args, **kwargs)
        return func(*args, **kwargs)

    return wrapper


class BoundedSandboxedEnvironment(SandboxedEnvironment):
    """A sandbox that computes nothing a template writes while compiling it, and caps what it builds.

    Jinja constant-folds expressions as it compiles, in a sandbox too, so
    checking ``{{ "x" * 100000000 }}`` built 100 MB and ``{{ 10 ** 200000 }}``
    a 200,000-digit number. Intercepted operators are never folded
    (``BinExpr.as_const`` raises ``Impossible`` for them), filters are
    wrapped as context filters, which are never folded either, and both
    refuse results past ``MAX_TEMPLATE_SEQUENCE`` / ``MAX_TEMPLATE_INT_BITS``
    when the template renders.
    """

    intercepted_binops = frozenset({"*", "**", "%", "+"})
    code_generator_class = _BoundedCodeGenerator

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.filters = {name: _runtime_filter(name, func) for name, func in self.filters.items()}

    #: The join compiled templates call for ``~`` (``_BoundedCodeGenerator``).
    bounded_join = staticmethod(_bounded_join)

    def wrap_str_format(self, value: Any) -> Optional[Callable[..., str]]:
        """The sandbox's ``str.format`` / ``format_map``, refusing a field width or precision past the cap."""
        if super().wrap_str_format(value) is None:
            return None
        text = value.__self__
        formatter = (
            _BoundedEscapeFormatter(self, escape=text.escape) if isinstance(text, Markup) else _BoundedFormatter(self)
        )
        is_format_map = value.__name__ == "format_map"

        def wrapper(*args: Any, **kwargs: Any) -> str:
            if is_format_map:
                if kwargs:
                    raise TypeError("format_map() takes no keyword arguments")
                if len(args) != 1:
                    raise TypeError(f"format_map() takes exactly one argument ({len(args)} given)")
                kwargs, args = args[0], ()
            return type(text)(formatter.vformat(text, args, kwargs))

        return functools.update_wrapper(wrapper, value)

    def call(__self, __context: Context, __obj: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: N805
        """Call ``__obj`` from a template, refusing a ``str`` method that would build an oversized string."""
        owner = getattr(__obj, "__self__", None)
        if isinstance(owner, str) and not isinstance(__obj, functools.partial):
            name = getattr(__obj, "__name__", "")
            if name == "join" and args:
                parts = list(args[0])
                _check_joined(parts, owner)
                args = (parts, *args[1:])
            else:
                _check_str_method(name, owner, args, kwargs)
        return super().call(__context, __obj, *args, **kwargs)

    def call_binop(self, context: Context, operator: str, left: Any, right: Any) -> Any:
        """Run ``+``, ``*``, ``**`` or ``%``, refusing one whose result would be oversized.

        Args:
            context: The render context.
            operator: The operator, one of ``intercepted_binops``.
            left: The left operand.
            right: The right operand.

        Returns:
            The operator's result.

        Raises:
            SecurityError: When the result would pass the size caps.
        """
        if operator == "+":
            sized = (str, bytes, list, tuple)
            if isinstance(left, sized) and isinstance(right, sized) and len(left) + len(right) > MAX_TEMPLATE_SEQUENCE:
                _refuse("joined sequence too long")
        elif operator == "*":
            self._check_multiply(left, right)
        elif operator == "**":
            self._check_power(left, right)
        elif operator == "%" and isinstance(left, str):
            _check_percent_format(left, right)
        return super().call_binop(context, operator, left, right)

    @staticmethod
    def _check_multiply(left: Any, right: Any) -> None:
        for seq, times in ((left, right), (right, left)):
            if isinstance(seq, (str, bytes, list, tuple)) and isinstance(times, int):
                if len(seq) * times > MAX_TEMPLATE_SEQUENCE:
                    _refuse("repeated sequence too long")
                return
        if isinstance(left, int) and isinstance(right, int):
            if left.bit_length() + right.bit_length() > MAX_TEMPLATE_INT_BITS:
                _refuse("integer too large")

    @staticmethod
    def _check_power(base: Any, exponent: Any) -> None:
        if not isinstance(base, int) or not isinstance(exponent, int) or exponent <= 0:
            return
        if abs(base) <= 1:
            return
        if (abs(base).bit_length() - 1) * exponent > MAX_TEMPLATE_INT_BITS:
            _refuse("integer too large")


class TemplateRenderError(Exception):
    """Raised when template rendering fails"""

    pass


class TemplateEngine:
    """Jinja2-based template engine for dynamic prompt rendering"""

    def __init__(self):
        # Rendered output is an LLM prompt, not HTML — autoescaping would
        # corrupt injected values (e.g. document content: "<" -> "&lt;").
        # The sandbox still blocks unsafe attribute/method access.
        self._env = BoundedSandboxedEnvironment(
            undefined=ChainableUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False,
        )

    def render(self, template_content: str, context: Dict[str, Any]) -> str:
        """
        Render template with provided context.

        Args:
            template_content: Raw template string with Jinja2 syntax
            context: Dictionary of variables to inject into template

        Returns:
            Rendered template string

        Raises:
            TemplateRenderError: If template syntax is invalid or variables undefined
        """
        if not template_content:
            return ""
        try:
            template = self._env.from_string(template_content)
            return template.render(**context)
        except TemplateSyntaxError as e:
            error_msg = f"Template syntax error at line {e.lineno}: {e.message}"
            logger.error(error_msg)
            raise TemplateRenderError(error_msg) from e
        except UndefinedError as e:
            error_msg = f"Undefined variable in template: {e.message}"
            logger.error(error_msg)
            raise TemplateRenderError(error_msg) from e
        except SecurityError as e:
            error_msg = f"Template security violation: {str(e)}"
            logger.error(error_msg)
            raise TemplateRenderError(error_msg) from e
        except Exception as e:
            error_msg = f"Template rendering failed: {str(e)}"
            logger.error(error_msg)
            raise TemplateRenderError(error_msg) from e

    def validate_template(self, template_content: str) -> bool:
        """
        Validate template syntax without rendering.

        Args:
            template_content: Template string to validate

        Returns:
            True if template is syntactically valid
        """
        if not template_content:
            return True
        try:
            self._env.from_string(template_content)
            return True
        except TemplateSyntaxError as e:
            logger.debug(f"Template syntax invalid at line {e.lineno}: {e.message}")
            return False
        except Exception as e:
            logger.debug(f"Template validation error: {type(e).__name__}: {str(e)}")
            return False

    def extract_variables(self, template_content: str) -> Set[str]:
        """
        Extract all variable names from template.

        Args:
            template_content: Template string to analyze

        Returns:
            Set of variable names found in template
        """
        if not template_content:
            return set()
        try:
            ast = self._env.parse(template_content)
            return set(self._env.get_template_module(ast).make_module().keys())
        except TemplateSyntaxError as e:
            logger.debug(f"Cannot extract variables - syntax error at line {e.lineno}")
            return set()
        except Exception as e:
            logger.debug(f"Cannot extract variables: {type(e).__name__}")
            return set()

    def references_variable(self, template_content: str, name: str, via: Set[str] = frozenset()) -> bool:
        """Whether the template reads ``name``, directly or as ``ns.name`` / ``ns['name']``.

        Args:
            template_content: Template string to analyze.
            name: The variable to look for.
            via: Namespaces the variable may also be read through, such as
                ``{"agent"}`` for ``agent.name``.

        Returns:
            True when the template reads the variable; False for a template
            that does not parse.
        """
        if not template_content or name not in template_content:
            return False
        try:
            ast = self._env.parse(template_content)
        except Exception:
            return False
        for node in ast.find_all((nodes.Name, nodes.Getattr, nodes.Getitem)):
            if isinstance(node, nodes.Name):
                if node.name == name and node.ctx == "load":
                    return True
                continue
            owner = node.node
            if not isinstance(owner, nodes.Name) or owner.name not in via:
                continue
            if isinstance(node, nodes.Getattr) and node.attr == name:
                return True
            if isinstance(node, nodes.Getitem) and isinstance(node.arg, nodes.Const) and node.arg.value == name:
                return True
        return False

    def extract_tool_usages(
        self, template_content: str
    ) -> Dict[str, Set[Optional[str]]]:
        """Extract tool and action references from a template"""
        if not template_content:
            return {}
        try:
            ast = self._env.parse(template_content)
        except TemplateSyntaxError as e:
            logger.debug(f"extract_tool_usages - syntax error at line {e.lineno}")
            return {}
        except Exception as e:
            logger.debug(f"extract_tool_usages - parse error: {type(e).__name__}")
            return {}

        usages: Dict[str, Set[Optional[str]]] = {}

        def record(path: List[str]) -> None:
            if not path:
                return
            tool_name = path[0]
            action_name = path[1] if len(path) > 1 else None
            if not tool_name:
                return
            tool_entry = usages.setdefault(tool_name, set())
            tool_entry.add(action_name)

        # Only record maximal chains: ``tools.memory.view`` must not also
        # record the intermediate ``tools.memory`` node, whose missing
        # action (None) means "run all actions" downstream.
        getattr_nodes = list(ast.find_all(nodes.Getattr))
        inner_getattrs = {
            id(n.node) for n in getattr_nodes if isinstance(n.node, nodes.Getattr)
        }
        for node in getattr_nodes:
            if id(node) in inner_getattrs:
                continue
            path = []
            current = node
            while isinstance(current, nodes.Getattr):
                path.append(current.attr)
                current = current.node
            if isinstance(current, nodes.Name) and current.name == "tools":
                path.reverse()
                record(path)

        getitem_nodes = list(ast.find_all(nodes.Getitem))
        inner_getitems = {
            id(n.node) for n in getitem_nodes if isinstance(n.node, nodes.Getitem)
        }
        for node in getitem_nodes:
            if id(node) in inner_getitems:
                continue
            path = []
            current = node
            while isinstance(current, nodes.Getitem):
                key = current.arg
                if isinstance(key, nodes.Const) and isinstance(key.value, str):
                    path.append(key.value)
                else:
                    path = []
                    break
                current = current.node
            if path and isinstance(current, nodes.Name) and current.name == "tools":
                path.reverse()
                record(path)

        return usages
