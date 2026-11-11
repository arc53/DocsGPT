"""Size limits on the template sandbox: nothing a prompt writes is computed while it compiles."""

import time

import pytest

from docsgpt.templates.template_engine import TemplateEngine, TemplateRenderError

# Each of these is a couple of dozen characters that, folded at compile time,
# built hundreds of megabytes or a 200,000-digit number.
AMPLIFIERS = [
    '{{ "x" * 100000000 }}',
    "{{ [1] * 100000000 }}",
    "{{ 10 ** 200000 }}",
    "{{ (-7) ** 100000 }}",
    '{{ "%0100000000d" % 1 }}',
    '{{ "%*d" % (100000000, 1) }}',
    '{{ "%d %*d" % (1, 100000000, 1) }}',
    '{{ "%.*f" % (100000000, 1.5) }}',
    '{{ "%%%*d" % (100000000, 1) }}',
    '{{ "x" | center(100000000) }}',
    '{{ "x" | indent(100000000, true) }}',
    '{{ "%0100000000d" | format(1) }}',
    '{{ "ab" | replace("", "xxxxxxxxxx") | replace("", "xxxxxxxxxx") | replace("", "xxxxxxxxxx")'
    ' | replace("", "xxxxxxxxxx") | replace("", "xxxxxxxxxx") | replace("", "xxxxxxxxxx") }}',
]

# Render-time builders the operators and filters above don't cover: each
# would build a gigabyte while the template renders.
RENDER_BUILDERS = [
    '{{ "{:>999999999}".format("x") }}',
    '{{ "{:.999999999f}".format(1.5) }}',
    '{{ "{v:{w}}".format(v="x", w=999999999) }}',
    '{{ "{x:>999999999}".format_map({"x": "y"}) }}',
    '{{ "x".ljust(999999999) }}',
    '{{ "x".rjust(999999999) }}',
    '{{ "x".center(999999999) }}',
    '{{ "1".zfill(999999999) }}',
    '{{ ("\\t" * 1000).expandtabs(1000000) }}',
    '{% set r = "x" * 1000 %}{{ "ab".replace("", r).replace("", r).replace("", r) }}',
    '{% set a = "x" * 1000000 %}{{ a + a }}',
    '{% set a = "x" * 1000000 %}{{ a ~ a }}',
    '{% set a = "x" * 1000000 %}{{ "".join([a, a]) }}',
    '{{ (["x" * 999999] * 1000) | join }}',
    '{{ ([{"a": "x" * 999999}] * 1000) | join(attribute="a") }}',
]


@pytest.fixture
def engine() -> TemplateEngine:
    return TemplateEngine()


@pytest.mark.unit
class TestNoCompileTimeAmplification:
    @pytest.mark.parametrize("template", AMPLIFIERS)
    def test_validate_is_cheap(self, engine: TemplateEngine, template: str) -> None:
        started = time.perf_counter()
        engine.validate_template(template)
        assert time.perf_counter() - started < 0.2

    @pytest.mark.parametrize("template", AMPLIFIERS)
    def test_render_is_refused_cheaply(self, engine: TemplateEngine, template: str) -> None:
        started = time.perf_counter()
        with pytest.raises(TemplateRenderError):
            engine.render(template, {})
        assert time.perf_counter() - started < 0.2

    @pytest.mark.parametrize("template", RENDER_BUILDERS)
    def test_render_time_builders_are_refused_cheaply(self, engine: TemplateEngine, template: str) -> None:
        started = time.perf_counter()
        with pytest.raises(TemplateRenderError):
            engine.render(template, {})
        assert time.perf_counter() - started < 0.5

    def test_folding_is_off_for_the_operators_and_filters(self, engine: TemplateEngine) -> None:
        source = engine._env.compile('{{ "x" * 3 }}{{ 2 ** 3 }}{{ "y" | center(5) }}', raw=True)
        assert "xxx" not in source
        assert "'  y  '" not in source


@pytest.mark.unit
class TestOrdinaryTemplatesStillWork:
    @pytest.mark.parametrize(
        ("template", "expected"),
        [
            ("{{ 2 * 3 }}", "6"),
            ("{{ 2 ** 10 }}", "1024"),
            ("{{ 2.5 * 2 }}", "5.0"),
            ("{{ 7 % 3 }}", "1"),
            ('{{ "-" * 5 }}', "-----"),
            ("{{ [0] * 3 }}", "[0, 0, 0]"),
            ('{{ "%05.1f" % 3.14159 }}', "003.1"),
            ('{{ "%s and %s" % ("a", "b") }}', "a and b"),
            ('{{ "%(n)s!" % {"n": "hi"} }}', "hi!"),
            # Only the values a ``*`` takes are sizes, not the numbers formatted.
            ("{{ '%*d' % (10, 1234567) }}", "   1234567"),
            ("{{ '%d%%' % 1234567 }}", "1234567%"),
            ("{{ '%s / %*.*f' % (1234567, 8, 2, 3.14159) }}", "1234567 /     3.14"),
            ("{{ '%*d' | format(10, 1234567) }}", "   1234567"),
            ('{{ "x" | center(5) }}', "  x  "),
            ('{{ "a\nb" | indent(2) }}', "a\n  b"),
            ('{{ "%d items" | format(3) }}', "3 items"),
            ('{{ "a-b" | replace("-", "+") }}', "a+b"),
            ("{{ items | join(', ') }}", "1, 2"),
            ("{{ name | upper }}", "ADA"),
            ("{{ missing | default('none') }}", "none"),
            ("{% for i in range(3) %}{{ i }}{% endfor %}", "012"),
            ("{{ n * 2 }}", "42"),
            ("{{ n + 1 }}", "22"),
            ('{{ "a" + "b" }}', "ab"),
            ("{{ [1] + [2] }}", "[1, 2]"),
            ('{{ name ~ "!" ~ n }}', "Ada!21"),
            ('{{ "{:>5}|{:.2f}".format("x", 3.14159) }}', "    x|3.14"),
            ('{{ "{n:{w}}".format(n=7, w=3) }}', "  7"),
            ('{{ "{a}".format_map({"a": 1}) }}', "1"),
            ('{{ "x".ljust(3) ~ "|" ~ "7".zfill(3) }}', "x  |007"),
            ('{{ "a\tb".expandtabs(4) }}', "a   b"),
            ('{{ "a-b".replace("-", "+") }}', "a+b"),
            ('{{ "-".join(["a", "b"]) }}', "a-b"),
            ('{{ [{"a": 1}, {"a": 2}] | join(",", attribute="a") }}', "1,2"),
            ("{{ range(3) | join }}", "012"),
        ],
    )
    def test_renders(self, engine: TemplateEngine, template: str, expected: str) -> None:
        assert engine.render(template, {"items": [1, 2], "name": "Ada", "n": 21}) == expected

    def test_validate_still_rejects_bad_syntax_and_unknown_filters(self, engine: TemplateEngine) -> None:
        assert engine.validate_template("{{ 2 * 3 }}") is True
        assert engine.validate_template("{{ unclosed") is False
        assert engine.validate_template("{{ x | no_such_filter }}") is False

    def test_range_cap_still_holds(self, engine: TemplateEngine) -> None:
        with pytest.raises(TemplateRenderError):
            engine.render("{{ range(100000000) | list | length }}", {})

    def test_repeated_squaring_is_capped(self, engine: TemplateEngine) -> None:
        template = (
            "{% set ns = namespace(x=10) %}{% for i in range(40) %}{% set ns.x = ns.x * ns.x %}{% endfor %}{{ ns.x }}"
        )
        started = time.perf_counter()
        with pytest.raises(TemplateRenderError):
            engine.render(template, {})
        assert time.perf_counter() - started < 0.2


# A loop or a recursion that doubles a string (or a list) every step: each
# step stays small, but 24 of them reached 16.7 million characters.
SELF_DOUBLING = [
    "{% set ns = namespace(x='a') %}{% for i in range(24) %}{% set ns.x = '%s%s' % (ns.x, ns.x) %}{% endfor %}",
    "{% set ns = namespace(x='a') %}{% for i in range(24) %}{% set ns.x = '{0}{0}'.format(ns.x) %}{% endfor %}",
    "{% set ns = namespace(x='a') %}{% for i in range(24) %}{% set ns.x = '%s%s'|format(ns.x, ns.x) %}{% endfor %}",
    "{% set ns = namespace(x='a') %}{% for i in range(24) %}{% set y %}{{ ns.x }}{{ ns.x }}{% endset %}"
    "{% set ns.x = y %}{% endfor %}",
    "{% macro d(n) %}{% if n %}{% set y = d(n - 1) %}{{ y }}{{ y }}{% else %}a{% endif %}{% endmacro %}{{ d(24) }}",
    "{% set a = ['x'] %}{% for i in range(40) %}{{ a.extend(a) or '' }}{% endfor %}{{ a | length }}",
]

# One step that builds a giant result from inputs under the cap: many copies
# of one value, a width applied per line, or a container written out as text.
ONE_STEP_BUILDERS = [
    '{% set a = "x" * 1000000 %}{{ ("{0}" * 1000).format(a) }}',
    '{% set a = "x" * 1000000 %}{{ ("%(a)s" * 1000) % {"a": a} }}',
    '{% set a = "x" * 1000000 %}{{ ("%s" * 1000) % ((a,) * 1000) }}',
    '{% set a = "x" * 1000000 %}{{ ("%s" * 1000) | format(*((a,) * 1000)) }}',
    '{{ ("a\\n" * 1000) | indent(1000000) }}',
    '{{ ("a\\n" * 1000) | indent("x" * 1000000) }}',
    '{{ ("a " * 400000) | wordwrap(1, wrapstring="x" * 1000) }}',
    '{% set a = "x" * 1000000 %}{{ [a] * 1000 }}',
    '{% set a = "x" * 1000000 %}{{ ([a] * 1000) | string }}',
    '{% set a = "x" * 1000000 %}{{ ([a] * 1000) | tojson }}',
    '{% set a = "x" * 1000000 %}{{ ([a] * 1000) | pprint }}',
    '{% set a = "x" * 1000000 %}{{ "" ~ ([a] * 1000) }}',
    '{% set a = "x" * 1000000 %}{{ "%s" % (([a] * 1000),) }}',
    '{% set a = "x" * 1000000 %}{{ "{}".format([a] * 1000) }}',
    '{% set a = "x" * 1000000 %}{{ [[a] * 1000] | join }}',
    "{{ lipsum(100000000) }}",
]

# Writing more than a render may: a loop of large writes, at the top or into
# a ``{% set %}`` block or a macro, and template text repeated by a loop.
OUTPUT_FLOODS = [
    '{% set s = "a" * 1000000 %}{% for i in range(30) %}{{ s }}{% endfor %}',
    '{% for i in range(100) %}{{ "a" * 1000000 }}{% endfor %}',
    '{% set y %}{% for i in range(100) %}{{ "a" * 1000000 }}{% endfor %}{% endset %}',
    "{% set y %}{% for i in range(100000) %}" + "x" * 100 + "{% endfor %}{% endset %}",
    "{% macro m() %}{% for i in range(100000) %}" + "x" * 100 + "{% endfor %}{% endmacro %}{{ m() | length }}",
]

# A context as large as a long document a workflow passes in.
BIG_DOC = "line of text\n" * 250_000


@pytest.mark.unit
class TestRenderSizeCaps:
    @pytest.mark.parametrize("template", SELF_DOUBLING + ONE_STEP_BUILDERS + OUTPUT_FLOODS)
    def test_refused_cheaply(self, engine: TemplateEngine, template: str) -> None:
        started = time.perf_counter()
        with pytest.raises(TemplateRenderError):
            engine.render(template, {})
        assert time.perf_counter() - started < 0.5

    @pytest.mark.parametrize(
        "template",
        [
            "{{ doc }}",
            "{{ doc | trim }}",
            "{{ doc | indent(2) }}",
            "{{ doc | upper }}",
            '{{ "%s\\n%s" % (doc, "end") }}',
            "{{ '{}!'.format(doc) }}",
            '{{ doc ~ "!" }}',
            "{{ doc + '!' }}",
            "{% for d in docs %}{{ d }}{% endfor %}",
            "{% set s %}{{ doc }}{% endset %}{{ s }}",
            "{% macro m() %}{{ doc }}{% endmacro %}{{ m() }}",
            "{{ docs | join('\\n') }}",
            "{{ docs }}",
        ],
    )
    def test_large_context_still_renders(self, engine: TemplateEngine, template: str) -> None:
        docs = [BIG_DOC[:1_000_000], BIG_DOC[1_000_000:2_000_000], BIG_DOC[2_000_000:]]
        assert len(engine.render(template, {"doc": BIG_DOC, "docs": docs})) >= len(BIG_DOC) - 1

    def test_a_refused_render_leaves_the_next_one_alone(self, engine: TemplateEngine) -> None:
        with pytest.raises(TemplateRenderError):
            engine.render(OUTPUT_FLOODS[0], {})
        assert engine.render("{% for i in range(3) %}{{ s }}{% endfor %}", {"s": "x" * 900_000}) == "x" * 2_700_000

    def test_writes_within_the_budget_render(self, engine: TemplateEngine) -> None:
        template = '{% set s = "a" * 1000000 %}{% for i in range(3) %}{{ s }}{% endfor %}'
        assert len(engine.render(template, {})) == 3_000_000
