import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import { describe, expect, it } from 'vitest';

import { markdownHeadings } from './markdown';

describe('markdownHeadings', () => {
  it('maps h1-h3 to the shared semibold sizes with margins', () => {
    const html = renderToStaticMarkup(
      <ReactMarkdown components={markdownHeadings}>
        {'# One\n\n## Two\n\n### Three'}
      </ReactMarkdown>,
    );
    expect(html).toContain(
      '<h1 class="mt-4 mb-2 text-xl font-semibold">One</h1>',
    );
    expect(html).toContain(
      '<h2 class="mt-4 mb-2 text-lg font-semibold">Two</h2>',
    );
    expect(html).toContain(
      '<h3 class="mt-3 mb-2 text-base font-semibold">Three</h3>',
    );
  });
});
