import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { BreadcrumbLink } from './breadcrumb';

describe('BreadcrumbLink', () => {
  it('shows the standard focus ring on an anchor', () => {
    const html = renderToStaticMarkup(
      <BreadcrumbLink href="/agents">Agents</BreadcrumbLink>,
    );
    expect(html).toContain('focus-visible:ring-3');
    expect(html).toContain('focus-visible:ring-ring/50');
    expect(html).toContain('outline-none');
  });

  it('passes the focus ring through asChild to a button crumb', () => {
    const html = renderToStaticMarkup(
      <BreadcrumbLink asChild>
        <button type="button">My Drive</button>
      </BreadcrumbLink>,
    );
    expect(html).toMatch(/<button[^>]*focus-visible:ring-3/);
  });
});
