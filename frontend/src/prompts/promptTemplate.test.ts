import { templateBroken } from './promptTemplate';

describe('templateBroken', () => {
  it('passes a plain prompt and one that only looks like a template', () => {
    expect(templateBroken('Be brief.')).toBe(false);
    // No {{ }}: the prompt is used as text, never parsed.
    expect(templateBroken('{% if x %} without an end')).toBe(false);
  });

  it('passes balanced blocks, whitespace control and raw text', () => {
    expect(
      templateBroken(
        [
          '{{ source.content }}',
          '{%- if source.count > 0 -%}Cite.{% elif x %}No.{% else %}Hm.{% endif %}',
          '{% for doc in source.documents %}{{ doc }}{% else %}none{% endfor %}',
          '{% set note %}Hi{% endset %}{% set y = 1 %}',
          '{# a comment with {% if %} #}',
          '{% raw %}{% if %}{{ {% endraw %}',
        ].join('\n'),
      ),
    ).toBe(false);
  });

  it('catches a block left open, an end without its start, and a stray else', () => {
    expect(templateBroken('{{ a }}{% if x %}Hi')).toBe(true);
    expect(templateBroken('{{ a }}Hi{% endif %}')).toBe(true);
    expect(templateBroken('{{ a }}{% for x in y %}{% endif %}')).toBe(true);
    expect(templateBroken('{{ a }}{% else %}')).toBe(true);
    expect(
      templateBroken('{{ a }}{% for x in y %}{% elif z %}{% endfor %}'),
    ).toBe(true);
  });

  it('catches a tag, variable or comment that never closes', () => {
    expect(templateBroken('{{ a }} {{ b')).toBe(true);
    expect(templateBroken('{{ a }} {% if x')).toBe(true);
    expect(templateBroken('{{ a }} {# note')).toBe(true);
    expect(templateBroken('{{ a }} {% raw %} text')).toBe(true);
  });

  it("leaves a tag named like an object's own property alone", () => {
    for (const tag of [
      'constructor',
      'toString',
      'hasOwnProperty',
      '__proto__',
    ]) {
      expect(() =>
        templateBroken(`{{ source.content }}{% ${tag} %}`),
      ).not.toThrow();
      expect(templateBroken(`{{ source.content }}{% ${tag} %}`)).toBe(false);
      expect(templateBroken(`{{ a }}{% end${tag} %}`)).toBe(false);
    }
  });

  it('reads a tag name that runs into a bracket or a trim modifier', () => {
    // Each of these parses in the chat's Jinja environment.
    for (const text of [
      '{% if(source.count) %}{{ source.content }}{% endif %}',
      '{{ a }}{% call(user) m() %}{{ user }}{% endcall %}',
      '{{ a }}{% if x %}y{% endif +%}',
      '{{ a }}{% if x %}y{% endif+%}',
      '{{ a }}{%+ if x +%}y{%+endif-%}',
      '{{ a }}{% if x %}y{% elif(z) %}w{% else-%}v{%endif%}',
      '{{ a }}{% for(x) in y %}{{x}}{% endfor %}',
    ]) {
      expect(templateBroken(text)).toBe(false);
    }
    expect(templateBroken('{{ a }}{% if(x) %}y')).toBe(true);
    expect(templateBroken('{{ a }}{% endif+%}')).toBe(true);
  });

  it('opens a set block with a filter, whose arguments may hold an =', () => {
    // Each of these parses in the chat's Jinja environment.
    for (const text of [
      '{% set note | wordwrap(width=80) %}Hi {{ x }}{% endset %}{{ note }}',
      '{% set note|upper %}{{ x }}{% endset %}',
      '{% set note | replace("=", "-") %}{{ x }}{% endset %}',
      '{% set x = a | default(b=1) %}{{ x }}',
      '{% set x = "a|b" %}{{ x }}',
      '{% set ns = namespace(n=0) %}{% set ns.n = 1 %}{{ ns.n }}',
      '{% set a, b = 1, 2 %}{{ a }}',
      '{% set (a, b) = (1, 2) %}{{ a }}',
    ]) {
      expect(templateBroken(text)).toBe(false);
    }
    expect(templateBroken('{{ a }}{% set note | upper %}Hi')).toBe(true);
    expect(templateBroken('{{ a }}{% set x = a | f(b=1) %}{% endset %}')).toBe(
      true,
    );
  });

  it('reads past a delimiter inside a quoted string', () => {
    // Each of these parses in the chat's Jinja environment.
    for (const text of [
      '{{ "}} {% if x %}" }}',
      "{{ '}} {% if x %}' }}",
      '{{ "a \\" }} {% if %}" }}',
      "{{ 'it\\'s {% if %}' }}",
      '{% if x == "%}" %}{{ y }}{% endif %}',
      '{{ x }}{% if y %}{{ "{% endif %}" }}{% endif %}',
      '{{ x }}{% if y %}{{ "{{" }}{% endif %}',
      // A comment holds no strings.
      '{{ x }}{# a "comment #}{{ y }}',
      // Nor does the text around the tags.
      '"{{ x }}" isn\'t {{ y }}',
      // A closer inside brackets is part of the expression.
      "{{ {'a': {'b': 1}} }}",
      "{{ {'a': 1}}}",
      "{% set d = {'a': 1}%}{{ d }}",
    ]) {
      expect(templateBroken(text)).toBe(false);
    }
    // A block closed only inside a string is still open.
    expect(templateBroken('{{ x }}{% if y %}{{ "{% endif %}" }}')).toBe(true);
    // A string that never closes takes the rest of the text with it.
    expect(templateBroken('{{ "abc }}')).toBe(true);
    expect(templateBroken('{{ x }}{% if x == "a %}{% endif %}')).toBe(true);
  });
});
