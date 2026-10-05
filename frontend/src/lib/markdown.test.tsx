import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { markdownCode, markdownHeadings, markdownTables } from './markdown';

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

const CODE_MD = 'Call `GET /v1` now.\n\n```python\nprint(1)\n```\n';

const renderCode = (options: Parameters<typeof markdownCode>[0]) => {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(
    <ReactMarkdown components={markdownCode(options)}>{CODE_MD}</ReactMarkdown>,
  );
  return host;
};

describe('markdownCode', () => {
  // One inline chip for every renderer (chat, preview, artifact, source view).
  it('renders inline code as the chat chip', () => {
    const chip = renderCode({ surface: 'answer' }).querySelector('p code')!;
    for (const cls of ['bg-accent', 'rounded-md', 'px-2', 'py-1', 'text-xs']) {
      expect(chip.className).toContain(cls);
    }
    const sourceChip = renderCode({}).querySelector('p code')!;
    expect(sourceChip.className).toBe(chip.className);
  });

  it('frames a fenced block with the answer-surface header and a copy button', () => {
    const host = renderCode({ surface: 'answer' });
    const header = host.querySelector('.bg-answer-surface')!;
    expect(header.textContent).toContain('python');
    expect(
      header.querySelector('button[aria-label="conversation.copy"]'),
    ).not.toBeNull();
    expect(host.textContent).toContain('print(1)');
  });

  it('uses the muted header outside chat', () => {
    const host = renderCode({ surface: 'muted' });
    expect(host.querySelector('.bg-answer-surface')).toBeNull();
    expect(host.querySelector('.bg-muted')!.textContent).toContain('python');
  });

  it('leaves fenced code to the caller without a surface', () => {
    const host = renderCode({});
    expect(host.querySelector('button')).toBeNull();
    expect(host.querySelector('pre code')!.textContent).toContain('print(1)');
  });
});
