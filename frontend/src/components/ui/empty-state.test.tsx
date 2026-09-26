import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { EmptyState } from './empty-state';

describe('EmptyState', () => {
  it('renders both theme illustrations at 128px by default', () => {
    const html = renderToStaticMarkup(<EmptyState title="No sources" />);
    expect(html).toContain('py-12');
    expect(html).toContain('size-32');
    expect(html).toContain('dark:hidden');
    expect(html).toContain('hidden dark:block');
    expect(html).toContain('text-muted-foreground text-lg');
    expect(html).not.toContain('role="alert"');
  });

  it('shrinks the art and padding at sm and xs', () => {
    expect(renderToStaticMarkup(<EmptyState size="sm" title="x" />)).toContain(
      'size-24',
    );
    const xs = renderToStaticMarkup(<EmptyState size="xs" title="x" />);
    expect(xs).toContain('size-16');
    expect(xs).toContain('py-8');
  });

  it('drops the art with illustration="none"', () => {
    const html = renderToStaticMarkup(
      <EmptyState illustration="none" title="No results" />,
    );
    expect(html).not.toContain('<svg');
  });

  it('turns red and announces itself with tone="destructive"', () => {
    const html = renderToStaticMarkup(
      <EmptyState
        tone="destructive"
        size="sm"
        illustration="none"
        title="Failed to load"
        action={<button type="button">Retry</button>}
      />,
    );
    expect(html).toContain('role="alert"');
    expect(html).toContain('text-destructive mb-3 size-8');
    expect(html).toContain('text-destructive text-base');
    expect(html).not.toContain('text-muted-foreground text-base');
    expect(html).toContain('Retry');
  });

  it('keeps the description in plain muted-foreground', () => {
    const html = renderToStaticMarkup(<EmptyState title="t" description="d" />);
    expect(html).toContain('text-muted-foreground mt-1 max-w-sm text-sm');
    expect(html).not.toContain('/70');
  });
});
