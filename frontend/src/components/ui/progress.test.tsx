import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Progress } from './progress';

describe('Progress', () => {
  it('clamps the value and exposes it as a custom property', () => {
    const html = renderToStaticMarkup(
      <Progress value={140} variant="warning" />,
    );
    expect(html).toContain('--progress:100%');
    expect(html).toContain('bg-warning');
    expect(html).toContain('aria-valuenow="100"');
  });

  it('never uses raw palette colours', () => {
    for (const variant of [
      'default',
      'success',
      'warning',
      'destructive',
      'info',
    ] as const) {
      expect(
        renderToStaticMarkup(<Progress value={50} variant={variant} />),
      ).not.toMatch(
        /\b(bg|text)-(red|green|amber|yellow|blue|gray|purple)-\d+/,
      );
    }
  });

  it('exposes its variant and size as data attributes', () => {
    const html = renderToStaticMarkup(
      <Progress value={50} variant="success" size="sm" />,
    );
    expect(html).toContain('data-variant="success"');
    expect(html).toContain('data-size="sm"');
  });
});
