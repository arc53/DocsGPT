import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Skeleton } from './skeleton';

describe('Skeleton', () => {
  it('is a pulsing muted block hidden from assistive tech', () => {
    const html = renderToStaticMarkup(<Skeleton className="h-4 w-32" />);
    expect(html).toContain('animate-pulse');
    expect(html).toContain('bg-muted');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('w-32');
    expect(html).toContain('rounded-sm');
  });

  it('draws visible bars on a muted surface', () => {
    const html = renderToStaticMarkup(
      <Skeleton surface="muted" className="h-4 w-32" />,
    );
    expect(html).toContain('bg-muted-foreground/20');
    expect(html).not.toMatch(/(^|\s)bg-muted(\s|")/);
    expect(html).toContain('data-surface="muted"');
  });
});
