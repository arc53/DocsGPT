import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import SourceMarkdown from './SourceMarkdown';

const render = (content: string, highlight?: string) =>
  renderToStaticMarkup(
    <SourceMarkdown content={content} highlight={highlight} />,
  );

describe('SourceMarkdown', () => {
  it('renders headings, lists and tables like a chat answer', () => {
    const html = render(
      '# Title\n\n- one\n- two\n\n| A | B |\n|---|---|\n| 1 | 2 |',
    );
    expect(html).toContain('<h1 class="mt-4 mb-2 text-xl font-semibold">');
    expect(html).toContain('list-outside list-disc pl-5');
    expect(html).toContain('<table');
    expect(html).toContain('overflow-x-auto');
  });

  it('marks every case-insensitive match of the highlight in text, not in code', () => {
    const html = render(
      'Nordhaven Logistics B.V. is a carrier; nordhaven logistics b.v. again. `Nordhaven Logistics B.V.`',
      'Nordhaven Logistics B.V.',
    );
    expect(html.match(/<mark/g)).toHaveLength(2);
    expect(html).toContain('>Nordhaven Logistics B.V.</mark>');
    expect(html).toContain('>nordhaven logistics b.v.</mark>');
    expect(html).toContain('<code');
  });

  it('treats the highlight as literal text, not a pattern', () => {
    const html = render('Assured+ tier and Assured tier', 'Assured+');
    expect(html.match(/<mark/g)).toHaveLength(1);
  });

  it('renders no marks without a highlight or for a blank one', () => {
    expect(render('plain text')).not.toContain('<mark');
    expect(render('plain text', '  ')).not.toContain('<mark');
  });

  it('puts fenced code in a scrolling box, and keeps the pill for inline code', () => {
    const html = render(
      'Run `npm ci` first.\n\n```sh\nnpm ci\nnpm run build\n```',
    );
    const host = document.createElement('div');
    host.innerHTML = html;
    const pre = host.querySelector('pre')!;
    expect(pre.className).toContain('overflow-x-auto');
    expect(pre.className).toContain('border');
    expect(pre.textContent).toContain('npm run build');
    expect(host.querySelector('p code')!.className).toContain('bg-muted');
  });

  it('renders links as text-size links that keep the paragraph type', () => {
    const host = document.createElement('div');
    host.innerHTML = render('See [the guide](https://example.com) now.');
    const link = host.querySelector('a')!;
    expect(link.dataset.size).toBe('text');
    expect(link.className).not.toMatch(/\btext-sm\b|font-medium/);
  });
});
