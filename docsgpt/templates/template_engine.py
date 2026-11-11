import contextlib
import functools
import itertools
import logging
import re
from collections.abc import Iterator as IteratorABC, MappingView, Sized
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Set

from jinja2 import (
    ChainableUndefined,
    nodes,
    TemplateSyntaxError,
)
from jinja2.compiler import CodeGenerator, Frame, operators, optimizeconst
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.filters import make_attrgetter
from jinja2.runtime import Context, LoopContext, Undefined
from jinja2.sandbox import SandboxedEnvironment, SandboxedEscapeFormatter, SandboxedFormatter
from jinja2.utils import _PassArg, generate_lorem_ipsum, Namespace, pass_context
from markupsafe import Markup

logger = logging.getLogger(__name__)

#: The longest string or list one operator, filter or method call may build,
#: on top of the text the render was given (``_RenderBudget``). Prompts are
#: capped well below this, so only a template that multiplies its own text
#: reaches it.
MAX_TEMPLATE_SEQUENCE = 1_000_000
#: The most characters one render may write, on top of
#: ``OUTPUT_PER_INPUT_CHAR`` per character of text it was given. Every
#: ``{{ }}`` counts, inside a macro or a ``{% set %}`` block too, so text a
#: macro writes counts again where the macro's result is written.
MAX_TEMPLATE_OUTPUT = 4_000_000
OUTPUT_PER_INPUT_CHAR = 4
#: The largest integer, in bits, ``*`` or ``**`` may produce (about 4,900
#: digits, past what Python will print as text anyway).
MAX_TEMPLATE_INT_BITS = 16_384

#: The most steps one render may take, on top of one per
#: ``INPUT_CHARS_PER_STEP`` characters of text it was given (a loop over a
#: long document's lines). A loop iteration or a call is a step; a filter,
#: method, operator, comparison or slice also takes one step per
#: ``STEP_UNIT`` characters or items of the sequence it reads, as it works
#: through all of them. A million steps take at most a few seconds.
MAX_TEMPLATE_STEPS = 1_000_000
INPUT_CHARS_PER_STEP = 4
STEP_UNIT = 100
# A sort reads each item about this many times (log2 of a long list).
_SORT_READS = 20
_SORTING_FILTERS = frozenset({"dictsort", "groupby", "max", "min", "sort", "unique"})

#: Sizing a render's context stops counting here; a larger context still renders.
_INPUT_COUNT_LIMIT = 64_000_000

# Filters that write a container out as text (``[a] * 1000 | string``), so a
# container's text is checked before they run.
_TEXT_FILTERS = frozenset({
    "capitalize", "center", "e", "escape", "forceescape", "indent", "lower", "pprint", "replace", "safe",
    "string", "striptags", "title", "tojson", "trim", "truncate", "upper", "urlencode", "urlize", "wordcount",
    "wordwrap", "xmlattr",
})

# Values whose ``str`` writes out everything they hold.
_CONTAINERS = (list, tuple, set, frozenset, Mapping, MappingView, Namespace)

# One ``%`` conversion: an optional ``(key)``, flags, width, precision, a
# length modifier and the conversion character (``%%`` takes no value).
_PERCENT_SPEC = re.compile(r"%(?:\(([^)]*)\))?[-#0 +]*(\*|\d+)?(?:\.(\*|\d+)?)?[hlL]?(.)", re.DOTALL)


@dataclass
class _RenderBudget:
    """What one render may build and write, sized from the text it was given.

    A long document passed in (a workflow's run inputs) is already in memory,
    so the caps grow with it: a template may build and write its own input,
    never many copies of it.

    Attributes:
        sequence: The longest string or list one step may build.
        output: The most characters the render may write.
        steps: The most steps the render may take.
        written: Characters written so far.
        taken: Steps taken so far.
    """

    sequence: int
    output: int
    steps: int
    written: int = 0
    taken: int = 0

    @classmethod
    def for_context(cls, context: Mapping[str, Any]) -> "_RenderBudget":
        """The budget for a render of ``context``."""
        given = _text_size(context, _INPUT_COUNT_LIMIT, objects=False)
        return cls(
            sequence=MAX_TEMPLATE_SEQUENCE + given,
            output=MAX_TEMPLATE_OUTPUT + OUTPUT_PER_INPUT_CHAR * given,
            steps=MAX_TEMPLATE_STEPS + given // INPUT_CHARS_PER_STEP,
        )


# The running render's budget. Outside a render (compiling, or a template
# rendered straight from the environment) the module caps apply as they are.
_BUDGET: ContextVar[Optional[_RenderBudget]] = ContextVar("template_render_budget", default=None)


@contextlib.contextmanager
def _render_budget(context: Mapping[str, Any]) -> Iterator[_RenderBudget]:
    """Hold a budget for one render of ``context``, so nested and later renders get their own."""
    budget = _RenderBudget.for_context(context)
    token = _BUDGET.set(budget)
    try:
        yield budget
    finally:
        _BUDGET.reset(token)


def _sequence_cap() -> int:
    budget = _BUDGET.get()
    return budget.sequence if budget is not None else MAX_TEMPLATE_SEQUENCE


def _refuse(message: str) -> None:
    raise SecurityError(message)


# Exact types ``_size`` answers without an ``isinstance`` against ``Mapping``,
# which is slow and runs for every operand of every comparison.
_SIZED_TYPES = frozenset({str, bytes, list, tuple, dict, set, frozenset, range})
_UNSIZED_TYPES = frozenset({int, float, bool, type(None)})


def _size(value: Any) -> int:
    """How many characters or items a step reads from ``value``; 0 for a value without a length."""
    kind = type(value)
    if kind in _SIZED_TYPES:
        return len(value)
    if kind in _UNSIZED_TYPES:
        return 0
    return len(value) if isinstance(value, (str, bytes, list, tuple, Mapping, set, frozenset, range)) else 0


def _charge(size: int = 0, base: int = 1) -> None:
    """Count ``base`` steps, and one more per ``STEP_UNIT`` of ``size``, against the running render's budget.

    Raises:
        SecurityError: When the render has taken more steps than its budget.
    """
    budget = _BUDGET.get()
    if budget is None:
        return
    budget.taken += base + size // STEP_UNIT
    if budget.taken > budget.steps:
        _refuse("template took too many steps")


def _counted_iter(items: Any) -> Iterator[Any]:
    """Yield ``items``, a step each: every ``{% for %}`` loop iterates through this."""
    for item in items:
        _charge()
        yield item


def _counted_operand(value: Any) -> Any:
    """``value``, after charging the steps a comparison such as ``in`` takes to read it."""
    size = _size(value)
    if size >= STEP_UNIT:
        _charge(size, base=0)
    return value


def _text_size(value: Any, limit: int, objects: bool = True) -> int:
    """About how long ``str(value)`` is, counted without building it.

    Args:
        value: Any value.
        limit: Counting stops once the total passes this, so a self-containing
            list ends too.
        objects: Count a value that is neither text nor a container by its
            ``str``; False counts it as nothing (sizing a render's context).

    Returns:
        The estimate, never below the real length for text and containers;
        anything past ``limit`` means "too long".
    """
    if isinstance(value, str):
        return len(value)
    total = 0
    pending = [value]
    while pending and total <= limit:
        item = pending.pop()
        if isinstance(item, str):
            total += len(item) + 2
        elif isinstance(item, (bytes, bytearray)):
            total += len(item) + 3
        elif isinstance(item, Namespace):
            total += 12
            pending.append(object.__getattribute__(item, "_Namespace__attrs"))
        elif isinstance(item, Mapping):
            total += 2 + 4 * len(item)
            pending.extend(itertools.chain.from_iterable(item.items()))
        elif isinstance(item, (list, tuple, set, frozenset, MappingView)):
            total += 2 + 2 * len(item)
            pending.extend(item)
        elif isinstance(item, int) and objects:
            total += item.bit_length() // 3 + 2
        elif objects:
            total += len(str(item))
    return total


def _check_size(value: Any) -> Any:
    """Refuse a string or list a step built past the cap.

    Returns:
        ``value``, when it is within the cap.
    """
    if isinstance(value, (str, list, tuple)) and len(value) > _sequence_cap():
        _refuse("result too long")
    return value


def _check_text(value: Any) -> None:
    """Refuse a container whose text would be past the cap, before it is written out."""
    if isinstance(value, _CONTAINERS):
        cap = _sequence_cap()
        if _text_size(value, cap) > cap:
            _refuse("text too long")


def _as_text(value: Any) -> str:
    """``str(value)``, refused when it would be past the cap."""
    if isinstance(value, str):
        return value
    _check_text(value)
    return str(value)


def _bounded_items(items: Iterable[Any]) -> Iterator[Any]:
    """Yield ``items``, refused once there are more than the cap (a generator has no length to check)."""
    cap = _sequence_cap()
    for count, item in enumerate(items, 1):
        if count > cap:
            _refuse("too many items")
        yield item


def _check_number(size: str, cap: int) -> int:
    """A width or precision written in a format, refused past the cap."""
    if len(size) > len(str(cap)) or int(size) > cap:
        _refuse("format width too large")
    return int(size)


def _check_percent_format(fmt: str, args: Any) -> None:
    """Refuse a ``%`` format whose result would be past the cap.

    Counts each conversion as its width or precision, or the text of the
    value it formats, whichever is larger, so many copies of one value
    (``"%(a)s" * 1000``) are refused as surely as a wide field.

    Args:
        fmt: The format string.
        args: The value(s) formatted into it; a ``*`` width reads its number from them.

    Raises:
        SecurityError: When a width, a precision or the whole result is over the cap.
    """
    if "%" not in fmt:
        return
    cap = _sequence_cap()
    values = args if isinstance(args, tuple) else (args,)
    mapping = args if isinstance(args, Mapping) else None
    total = len(fmt)
    # The conversions take their values in order: a ``*`` width or precision
    # takes the next one as its size, then the conversion takes its own, so
    # only the values a ``*`` takes are sizes (``"%*d" % (10, 1234567)``).
    position = 0
    for match in _PERCENT_SPEC.finditer(fmt):
        key, width, precision, conversion = match.groups()
        field = 0
        for size in (width, precision):
            if size == "*":
                value = values[position] if position < len(values) else None
                position += 1
                if isinstance(value, int):
                    if abs(value) > cap:
                        _refuse("format width too large")
                    field = max(field, abs(value))
            elif size:
                field = max(field, _check_number(size, cap))
        if conversion == "%":
            continue
        if key is not None and mapping is not None:
            value = mapping.get(key)
        else:
            value = values[position] if position < len(values) else None
            position += 1
        total += max(field, _text_size(value, cap))
        if total > cap:
            _refuse("formatted text too long")


def _check_width(width: Any) -> None:
    cap = _sequence_cap()
    if isinstance(width, int) and width > cap:
        _refuse("width too large")
    if isinstance(width, str) and len(width) > cap:
        _refuse("width too large")


def _check_indent(text: Any, width: Any) -> None:
    """Refuse an ``indent`` whose prefix, repeated on every line, would be past the cap."""
    if not isinstance(text, str):
        return
    prefix = len(width) if isinstance(width, str) else width if isinstance(width, int) else 0
    if len(text) + max(prefix, 0) * (text.count("\n") + 1) > _sequence_cap():
        _refuse("indented text too long")


def _check_wordwrap(text: Any, width: Any, wrapstring: Any) -> None:
    """Refuse a ``wordwrap`` whose ``wrapstring``, written at every break, would be past the cap."""
    if not isinstance(text, str) or not isinstance(wrapstring, str):
        return
    width = width if isinstance(width, int) and width > 0 else 1
    breaks = len(text) // width + text.count("\n") + 1
    if len(text) + breaks * len(wrapstring) > _sequence_cap():
        _refuse("wrapped text too long")


def _check_json_indent(value: Any, indent: Any) -> None:
    """Refuse a ``tojson`` whose indent, repeated per nesting level on every line, would be past the cap."""
    width = len(indent) if isinstance(indent, str) else indent if isinstance(indent, int) else 0
    if width <= 0:
        return
    cap = _sequence_cap()
    total = _text_size(value, cap)
    pending = [(value, 1)]
    while pending and total <= cap:
        item, depth = pending.pop()
        total += width * depth
        if isinstance(item, Mapping):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend((child, depth + 1) for child in item)
    if total > cap:
        _refuse("indented JSON too long")


def _check_sum(environment: Any, items: Any, attribute: Any = None, start: Any = 0) -> None:
    """Refuse a ``sum`` of lists (``start=[]``) whose result would be past the cap."""
    if not isinstance(start, (list, tuple)) or not isinstance(items, Sized):
        return
    if attribute is not None:
        getter = make_attrgetter(environment, attribute)
        items = [getter(item) for item in items]
    total = len(start)
    for item in items:
        total += len(item) if isinstance(item, Sized) else 1
        if total > _sequence_cap():
            _refuse("sum too long")
    # Each addition copies the running total, so the work grows with the
    # square of the result.
    _charge(len(items) * total // 2)


def _check_replace(value: Any, old: Any = None, new: Any = None, count: Any = None, *_: Any) -> None:
    if not isinstance(value, str) or not isinstance(old, str) or not isinstance(new, str):
        return
    if len(new) <= len(old):
        return
    hits = len(value) + 1 if not old else value.count(old)
    if isinstance(count, int) and count >= 0:
        hits = min(hits, count)
    if len(value) + hits * (len(new) - len(old)) > _sequence_cap():
        _refuse("replace result too long")


def _check_translate(text: str, table: Any = None, *_: Any) -> None:
    """Refuse a ``str.translate`` whose replacements, written for every character, would be past the cap."""
    if not isinstance(table, Mapping):
        return
    longest = max((len(new) for new in table.values() if isinstance(new, str)), default=1)
    if len(text) * longest > _sequence_cap():
        _refuse("translated text too long")


def _check_lipsum(args: tuple, kwargs: Mapping[str, Any]) -> None:
    """Refuse a ``lipsum`` whose paragraphs would be past the cap (a word is at most 12 characters)."""
    paragraphs = args[0] if args else kwargs.get("n", 5)
    words = args[3] if len(args) > 3 else kwargs.get("max", 100)
    if isinstance(paragraphs, int) and isinstance(words, int) and paragraphs * words * 12 > _sequence_cap():
        _refuse("lorem ipsum too long")


# A run of digits in a ``str.format`` field spec: its width or precision (a
# fill character is a single character, so it never joins a run).
_SPEC_NUMBER = re.compile(r"\d+")


def _check_format_spec(spec: str) -> int:
    """Refuse a ``str.format`` field whose width or precision would pad past the cap.

    Returns:
        The field's largest width or precision, 0 without one.
    """
    cap = _sequence_cap()
    return max((_check_number(number, cap) for number in _SPEC_NUMBER.findall(spec or "")), default=0)


def _check_joined(parts: List[Any], separator: Any = "") -> None:
    """Refuse joining ``parts`` when the result would pass the cap."""
    cap = _sequence_cap()
    total = _text_size(separator, cap) * max(len(parts) - 1, 0)
    for part in parts:
        total += _text_size(part, cap)
        if total > cap:
            _refuse("joined text too long")


def _bounded_join(parts: Any) -> str:
    """``str_join`` for the ``~`` operator, refusing a result past the cap."""
    texts = [_as_text(part) for part in parts]
    _check_joined(texts)
    return "".join(texts)


def _bounded_concat(parts: Iterable[str]) -> str:
    """``concat`` for every compiled template: the output of a render, macro or block, refused past the output cap.

    Jinja joins what a ``{% set %}`` block, a macro, a call or filter block
    and the whole render wrote with ``environment.concat``, so a loop
    repeating template text is counted here too, as it is joined.
    """
    budget = _BUDGET.get()
    limit = budget.output if budget is not None else MAX_TEMPLATE_OUTPUT
    texts: List[str] = []
    total = 0
    for part in parts:
        total += len(part)
        if total > limit:
            _refuse("template output too long")
        texts.append(part)
    return "".join(texts)


def _finalize(value: Any) -> str:
    """What a ``{{ }}`` writes: ``value`` as text, counted against the render's output budget.

    Every expression a template writes passes here, in a macro or a
    ``{% set %}`` block too, so a loop of writes into a block is refused
    while it runs, not once the block is joined.
    """
    text = _as_text(value)
    budget = _BUDGET.get()
    if budget is not None:
        budget.written += len(text)
        if budget.written > budget.output:
            _refuse("template wrote too much text")
    return text


class _BoundedFormatter(SandboxedFormatter):
    """The sandbox's ``str.format`` formatter, refusing a field or a whole result past the cap."""

    _total = 0

    def vformat(self, format_string: str, args: Any, kwargs: Any) -> str:
        self._total = len(format_string)
        return super().vformat(format_string, args, kwargs)

    def format_field(self, value: Any, format_spec: str) -> Any:
        cap = _sequence_cap()
        self._total += max(_check_format_spec(format_spec), _text_size(value, cap))
        if self._total > cap:
            _refuse("formatted text too long")
        return super().format_field(value, format_spec)


class _BoundedEscapeFormatter(_BoundedFormatter, SandboxedEscapeFormatter):
    pass


class _BoundedCodeGenerator(CodeGenerator):
    """Compiles ``~`` to a join that refuses a result past the cap, and comparisons to count their steps.

    ``~`` is not an operator the sandbox can intercept: Jinja writes it as a
    call to its own ``str_join``, so doubling a string in a loop reached a
    gigabyte in about thirty steps. A comparison such as ``"y" in big`` reads
    a whole sequence without a call the sandbox sees, so each side goes
    through ``environment.counted_operand``.
    """

    @optimizeconst
    def visit_Compare(self, node: nodes.Compare, frame: Frame) -> None:
        self.write("(environment.counted_operand(")
        self.visit(node.expr, frame)
        self.write(")")
        for operand in node.ops:
            self.visit(operand, frame)
        self.write(")")

    def visit_Operand(self, node: nodes.Operand, frame: Frame) -> None:
        self.write(f" {operators[node.op]} environment.counted_operand(")
        self.visit(node.expr, frame)
        self.write(")")

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
        if isinstance(size, int) and len(text) + text.count("\t") * max(size, 0) > _sequence_cap():
            _refuse("expanded text too long")
    elif name == "replace":
        _check_replace(text, *args, **{k: v for k, v in kwargs.items() if k == "count"})
    elif name == "translate":
        _check_translate(text, *args)


def _check_list_method(name: str, items: list, args: tuple) -> tuple:
    """Refuse a ``list`` method call from a template that would grow the list past the cap.

    Returns:
        The call's arguments; ``extend`` gets a generator read once, as a list.
    """
    if name not in ("append", "insert", "extend"):
        return args
    added = 1
    if name == "extend" and args:
        values = args[0] if isinstance(args[0], Sized) else list(_bounded_items(args[0]))
        args = (values, *args[1:])
        added = len(values)
    if len(items) + added > _sequence_cap():
        _refuse("list too long")
    return args


def _filter_guard(name: str, args: tuple, kwargs: Mapping[str, Any], environment: Any) -> tuple:
    """Refuse a filter call that would build an oversized string before it runs.

    Returns:
        The filter's positional arguments; a generator value comes back
        counted (:func:`_bounded_items`) and ``join`` gets its value as a
        list, read once for the check.
    """
    if args and isinstance(args[0], IteratorABC) and not isinstance(args[0], Undefined):
        args = (_bounded_items(args[0]), *args[1:])
    if name in _TEXT_FILTERS and args and not isinstance(args[0], str):
        _check_text(args[0])
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
    elif name == "indent" and args:
        _check_indent(args[0], args[1] if len(args) > 1 else kwargs.get("width"))
    elif name == "wordwrap" and args:
        _check_wordwrap(
            args[0],
            args[1] if len(args) > 1 else kwargs.get("width", 79),
            args[3] if len(args) > 3 else kwargs.get("wrapstring"),
        )
    elif name == "tojson" and args:
        _check_json_indent(args[0], args[1] if len(args) > 1 else kwargs.get("indent"))
    elif name == "format" and args and isinstance(args[0], str):
        _check_percent_format(args[0], args[1:] if len(args) > 1 else dict(kwargs) if kwargs else ())
    elif name == "replace" and args:
        _check_replace(*args, **{k: v for k, v in kwargs.items() if k in ("old", "new", "count")})
    elif name == "sum" and args:
        _check_sum(environment, *args, **{k: v for k, v in kwargs.items() if k in ("attribute", "start")})
    elif name in ("batch", "slice") and len(args) > 1:
        _check_width(args[1])
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
        A context filter that checks its arguments, calls ``func``, then
        checks what it built.
    """
    pass_arg = _PassArg.from_obj(func)

    @pass_context
    @functools.wraps(func)
    def wrapper(context: Context, *args: Any, **kwargs: Any) -> Any:
        size = _size(args[0]) if args else 0
        _charge(size * _SORT_READS if name in _SORTING_FILTERS else size)
        args = _filter_guard(name, args, kwargs, context.environment)
        if pass_arg is _PassArg.context:
            return _check_size(func(context, *args, **kwargs))
        if pass_arg is _PassArg.eval_context:
            return _check_size(func(context.eval_ctx, *args, **kwargs))
        if pass_arg is _PassArg.environment:
            return _check_size(func(context.environment, *args, **kwargs))
        return _check_size(func(*args, **kwargs))

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

    While it renders, every step that builds a string or list is checked
    against the render's budget (``_RenderBudget``), before it runs where its
    size is known up front and after it runs otherwise, so a loop that
    doubles a string stops one step past the cap; everything written is
    counted (``finalize``) and every join of output is capped (``concat``).
    """

    intercepted_binops = frozenset({"*", "**", "%", "+"})
    code_generator_class = _BoundedCodeGenerator
    #: Joins the output of a render, a macro or a block (bound as ``concat`` in every compiled template).
    concat = staticmethod(_bounded_concat)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["finalize"] = _finalize
        super().__init__(*args, **kwargs)
        self.filters = {name: _runtime_filter(name, func) for name, func in self.filters.items()}

    #: The join compiled templates call for ``~`` (``_BoundedCodeGenerator``).
    bounded_join = staticmethod(_bounded_join)
    #: What every ``{% for %}`` loop iterates (``_parse``), and what reads each side of a comparison.
    counted_iter = staticmethod(_counted_iter)
    counted_operand = staticmethod(_counted_operand)

    def _parse(self, source: str, name: Optional[str], filename: Optional[str]) -> nodes.Template:
        """Parse ``source``, then route every loop's items through a step count.

        A loop's body runs no call or filter the sandbox sees, so nested
        empty loops held a worker for hours.
        """
        template = super()._parse(source, name, filename)
        for loop in list(template.find_all(nodes.For)):
            loop.iter = nodes.Call(
                nodes.EnvironmentAttribute("counted_iter"), [loop.iter], [], None, None, lineno=loop.iter.lineno
            )
        template.set_environment(self)
        return template

    def getitem(self, obj: Any, argument: Any) -> Any:
        """``obj[argument]``; a slice copies, so it takes steps for the sequence it reads."""
        if isinstance(argument, slice):
            _charge(_size(obj))
        return super().getitem(obj, argument)

    def wrap_str_format(self, value: Any) -> Optional[Callable[..., str]]:
        """The sandbox's ``str.format`` / ``format_map``, refusing a field or a result past the cap."""
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
        """Call ``__obj`` from a template, refusing a call that would build an oversized string or list.

        Every call is a step (a macro's too), and a method takes more for the
        string or list it reads; a recursive loop's ``loop(items)`` counts its
        items as a ``{% for %}`` does.
        """
        owner = getattr(__obj, "__self__", None)
        _charge(_size(owner))
        if isinstance(__obj, LoopContext) and args:
            args = (_counted_iter(args[0]), *args[1:])
        if isinstance(owner, str) and not isinstance(__obj, functools.partial):
            name = getattr(__obj, "__name__", "")
            if name == "join" and args:
                parts = list(_bounded_items(args[0]))
                _charge(len(parts))
                _check_joined(parts, owner)
                args = (parts, *args[1:])
            else:
                _check_str_method(name, owner, args, kwargs)
        elif isinstance(owner, list):
            args = _check_list_method(getattr(__obj, "__name__", ""), owner, args)
        elif __obj is generate_lorem_ipsum:
            _check_lipsum(args, kwargs)
        return _check_size(super().call(__context, __obj, *args, **kwargs))

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
        _charge(_size(left) + _size(right))
        if operator == "+":
            sized = (str, bytes, list, tuple)
            if isinstance(left, sized) and isinstance(right, sized) and len(left) + len(right) > _sequence_cap():
                _refuse("joined sequence too long")
        elif operator == "*":
            self._check_multiply(left, right)
        elif operator == "**":
            self._check_power(left, right)
        elif operator == "%" and isinstance(left, str):
            _check_percent_format(left, right)
        return _check_size(super().call_binop(context, operator, left, right))

    @staticmethod
    def _check_multiply(left: Any, right: Any) -> None:
        for seq, times in ((left, right), (right, left)):
            if isinstance(seq, (str, bytes, list, tuple)) and isinstance(times, int):
                if len(seq) * times > _sequence_cap():
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
            with _render_budget(context):
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
