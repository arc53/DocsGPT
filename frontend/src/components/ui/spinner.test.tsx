import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Spinner } from './spinner';

describe('Spinner', () => {
  it('is an accessible status element drawn by the ring utility', () => {
    const html = renderToStaticMarkup(<Spinner size="sm" />);
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-label="Loading"');
    expect(html).toContain('spinner-ring');
    expect(html).toContain('size-5');
    expect(html).toContain('data-size="sm"');
  });

  it('xs is the 16px step for icon-sized spots', () => {
    const html = renderToStaticMarkup(<Spinner size="xs" />);
    expect(html).toContain('size-4');
    expect(html).toContain('data-size="xs"');
  });
});
