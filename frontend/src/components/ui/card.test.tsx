import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Card, CardAction, CardHeader, CardTitle, cardVariants } from './card';

describe('Card', () => {
  it('is a bordered card surface by default', () => {
    const html = renderToStaticMarkup(<Card>Body</Card>);
    expect(html).toContain('rounded-2xl');
    expect(html).toContain('bg-card');
    expect(html).toContain('p-4');
    expect(html).toContain('data-variant="outline"');
  });

  it('filled variant drops the border', () => {
    const classes = cardVariants({ variant: 'filled' });
    expect(classes).toContain('bg-muted');
    expect(classes).not.toMatch(/(^|\s)border(\s|$)/);
  });

  it('interactive cards get hover, focus and selected styles', () => {
    const html = renderToStaticMarkup(
      <Card interactive selected asChild>
        <button type="button">Pick me</button>
      </Card>,
    );
    expect(html).toContain('<button');
    expect(html).toContain('cursor-pointer');
    expect(html).toContain('data-selected="true"');
    expect(html).toContain('focus-visible:ring-3');
  });

  it('header places the action in the trailing column', () => {
    const html = renderToStaticMarkup(
      <CardHeader>
        <CardTitle>Arc53</CardTitle>
        <CardAction>menu</CardAction>
      </CardHeader>,
    );
    expect(html).toContain('grid-cols-[1fr_auto]');
    expect(html).toContain('col-start-2');
  });
});
