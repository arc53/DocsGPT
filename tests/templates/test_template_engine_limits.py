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
