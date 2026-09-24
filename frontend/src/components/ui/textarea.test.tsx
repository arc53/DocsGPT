import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Textarea } from './textarea';

function classesOf(html: string): string[] {
  return (/class="([^"]*)"/.exec(html)?.[1] ?? '').split(' ');
}

describe('Textarea variants', () => {
  it('is transparent by default, so it shows the surface behind it', () => {
    const html = renderToStaticMarkup(<Textarea />);
    expect(classesOf(html)).toContain('bg-transparent');
    expect(html).toContain('data-variant="default"');
  });

  it('variant="filled" gives the field a card fill on a muted panel', () => {
    const html = renderToStaticMarkup(<Textarea variant="filled" size="sm" />);
    const classes = classesOf(html);
    expect(classes).toContain('bg-card');
    expect(classes).not.toContain('bg-transparent');
    expect(html).toContain('data-variant="filled"');
    expect(html).toContain('data-size="sm"');
  });

  it('does not leak the variant props onto the DOM element', () => {
    const html = renderToStaticMarkup(
      <Textarea variant="filled" resize="none" />,
    );
    expect(html).not.toMatch(/\svariant="filled"/);
    expect(html).not.toMatch(/\sresize="none"/);
  });
});
