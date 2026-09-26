import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Separator } from './separator';

describe('Separator', () => {
  it('is a decorative 1px horizontal rule by default', () => {
    const html = renderToStaticMarkup(<Separator />);
    expect(html).toContain('data-orientation="horizontal"');
    expect(html).toContain('role="none"');
    expect(html).toContain('bg-border');
    expect(html).toContain('h-px w-full');
  });

  it('draws a vertical rule', () => {
    const html = renderToStaticMarkup(<Separator orientation="vertical" />);
    expect(html).toContain('data-orientation="vertical"');
    expect(html).toContain('h-full w-px');
  });

  it('keeps layout classes from the caller', () => {
    const html = renderToStaticMarkup(<Separator className="mt-5 mb-8" />);
    expect(html).toContain('mt-5 mb-8');
  });

  it('lets a caller width replace the full width', () => {
    const html = renderToStaticMarkup(<Separator className="w-6" />);
    expect(html).toContain('w-6');
    expect(html).not.toContain('w-full');
  });
});
