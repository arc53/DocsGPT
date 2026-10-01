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

  it('renders the 20px page or panel title at size title', () => {
    const html = renderToStaticMarkup(
      <SectionHeader size="title" title="Ops jump host" />,
    );
    expect(html).toContain(
      'text-foreground text-xl leading-tight font-semibold',
    );
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

  it('renders deeper heading levels for nested panel sections', () => {
    expect(
      renderToStaticMarkup(<SectionHeader as="h5" size="xs" title="Tester" />),
    ).toContain('<h5');
    expect(
      renderToStaticMarkup(
        <SectionHeader as="h6" size="xs" title="Takes actions · 2" />,
      ),
    ).toContain('<h6');
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

  it('draws a count after the title: muted, normal weight, tabular, not uppercased', () => {
    const html = renderToStaticMarkup(
      <SectionHeader size="sm" title="Members" count={7} />,
    );
    const m =
      /<h2[^>]*>Members<span data-slot="count" class="([^"]*)">7<\/span><\/h2>/.exec(
        html,
      );
    expect(m).not.toBeNull();
    expect(m![1].split(' ')).toEqual(
      expect.arrayContaining([
        'text-muted-foreground',
        'font-normal',
        'tabular-nums',
        'normal-case',
        'tracking-normal',
      ]),
    );
  });

  it('formats a numeric count and accepts text', () => {
    expect(
      renderToStaticMarkup(<SectionHeader title="Rows" count={12345} />),
    ).toContain('>12,345</span>');
    expect(
      renderToStaticMarkup(
        <SectionHeader
          size="xs"
          title="Carrier TMS API"
          count="2 of 5 allowed"
        />,
      ),
    ).toContain('>2 of 5 allowed</span>');
    expect(renderToStaticMarkup(<SectionHeader title="Rows" />)).not.toContain(
      'data-slot="count"',
    );
  });
});
