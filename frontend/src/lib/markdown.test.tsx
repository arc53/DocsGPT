import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { describe, expect, it } from 'vitest';

import { markdownHeadings, markdownTables } from './markdown';

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

const TABLE = `| Lane | Carrier |
| --- | --- |
| Rotterdam – Oslo | Baltic Star |
| Rotterdam – Milan | Rhinehaul |`;

const render = () => {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownTables}>
      {TABLE}
    </ReactMarkdown>,
  );
  return host;
};

describe('markdownTables', () => {
  // One table style across the app: markdown tables (chat answers, wiki
  // pages, chunks, previews) are the ui/table parts, not a copy of them.
  it('renders the ui/table parts in their bordered, scrolling frame', () => {
    const host = render();
    expect(host.querySelector('[data-slot="table-container"]')).not.toBeNull();
    expect(host.querySelector('[data-slot="table"]')).not.toBeNull();
    expect(host.querySelector('thead')!.dataset.slot).toBe('table-head');
    expect(host.querySelectorAll('[data-slot="table-header"]')).toHaveLength(2);
    expect(host.querySelectorAll('[data-slot="table-cell"]')).toHaveLength(4);
    expect(host.querySelector('th')!.textContent).toBe('Lane');
  });

  it('keeps the GFM column alignment', () => {
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownTables}>
        {'| A | B | C |\n| :-- | :-: | --: |\n| 1 | 2 | 3 |'}
      </ReactMarkdown>,
    );
    const cells = host.querySelectorAll('[data-slot="table-cell"]');
    expect(cells[0].className).toContain('text-left');
    expect(cells[1].className).toContain('text-center');
    expect(cells[2].className).toContain('text-right');
    expect(
      host.querySelectorAll('[data-slot="table-header"]')[2].className,
    ).toContain('text-right');
  });

  it('keeps the authors’ capitals and lets a narrow table shrink', () => {
    const host = render();
    expect(host.innerHTML).not.toContain('uppercase');
    expect(host.innerHTML).not.toContain('even:bg-muted');
    expect(host.querySelector('table')!.className).toContain('min-w-0');
  });
});
