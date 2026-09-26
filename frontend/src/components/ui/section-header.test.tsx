import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { SectionHeader } from './section-header';

describe('SectionHeader', () => {
  it('renders an 18px section title by default', () => {
    const html = renderToStaticMarkup(
      <SectionHeader title="Prompts" description="Saved system prompts." />,
    );
    expect(html).toContain('<h2');
    expect(html).toContain('text-foreground text-lg font-semibold');
    expect(html).toContain('text-muted-foreground text-sm');
  });

  it('renders the muted eyebrow at size sm', () => {
    const html = renderToStaticMarkup(
      <SectionHeader as="h3" size="sm" title="Recurring" />,
    );
    expect(html).toContain('<h3');
    expect(html).toContain(
      'text-muted-foreground text-xs font-semibold tracking-wider uppercase',
    );
  });

  it('renders a 14px sub-heading at size xs, destructive on request', () => {
    const plain = renderToStaticMarkup(
      <SectionHeader as="h3" size="xs" title="Identity" />,
    );
    expect(plain).toContain('text-foreground text-sm font-semibold');
    const danger = renderToStaticMarkup(
      <SectionHeader
        as="h3"
        size="xs"
        tone="destructive"
        title="Danger zone"
      />,
    );
    expect(danger).toContain('text-sm font-semibold text-destructive');
    expect(danger).not.toContain('text-foreground');
  });

  it('puts actions at the end of the row', () => {
    const html = renderToStaticMarkup(
      <SectionHeader
        title="Tools"
        actions={<button type="button">Add</button>}
      />,
    );
    expect(html).toContain('justify-between');
    expect(html).toContain('<button');
    // The row centres the title on its buttons and wraps on phones.
    expect(html).toContain('items-center');
    expect(html).toContain('flex-wrap');
    expect(html).not.toContain('items-start');
  });
});
