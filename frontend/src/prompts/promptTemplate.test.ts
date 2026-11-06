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
});
