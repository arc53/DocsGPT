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
  });
});
