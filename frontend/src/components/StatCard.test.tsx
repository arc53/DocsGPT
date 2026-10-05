import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import StatCard from './StatCard';

describe('StatCard', () => {
  it('renders a subtle, large-padded Card with label and value', () => {
    const html = renderToStaticMarkup(<StatCard label="Users" value="42" />);
    expect(html).toContain('data-slot="card"');
    expect(html).toContain('data-variant="subtle"');
    expect(html).toContain('data-padding="lg"');
    expect(html).toContain('gap-1');
    expect(html).not.toContain('gap-3');
    expect(html).toContain('text-muted-foreground text-sm');
    expect(html).toContain('>Users<');
    expect(html).toContain('text-2xl font-bold tabular-nums');
    expect(html).toContain('>42<');
    expect(html).not.toMatch(/\bmt-1\b/);
  });

  it('renders the sub line only when given', () => {
    expect(
      renderToStaticMarkup(<StatCard label="A" value="1" />),
    ).not.toContain('text-xs');
    const html = renderToStaticMarkup(
      <StatCard label="A" value="1" sub="last 30 days" />,
    );
    expect(html).toContain('text-muted-foreground text-xs');
    expect(html).toContain('>last 30 days<');
  });

  it('turns a hint into a native tooltip with a help cursor', () => {
    const html = renderToStaticMarkup(
      <StatCard label="A" value="1" hint="How this is counted" />,
    );
    expect(html).toContain('title="How this is counted"');
    expect(html).toContain('cursor-help');
    expect(
      renderToStaticMarkup(<StatCard label="A" value="1" />),
    ).not.toContain('cursor-help');
  });

  it('passes layout classes and data attributes through', () => {
    const html = renderToStaticMarkup(
      <StatCard label="A" value="1" className="col-span-2" data-testid="t" />,
    );
    expect(html).toContain('col-span-2');
    expect(html).toContain('data-testid="t"');
  });

  it('defaults to subtle and takes outline for tiles inside a modal', () => {
    expect(renderToStaticMarkup(<StatCard label="A" value="1" />)).toContain(
      'data-variant="subtle"',
    );
    const html = renderToStaticMarkup(
      <StatCard label="A" value="1" variant="outline" />,
    );
    expect(html).toContain('data-variant="outline"');
    expect(html).toContain('bg-card');
    expect(html).not.toContain('bg-background');
  });

  it('passes a destructive tone to the Card', () => {
    const html = renderToStaticMarkup(
      <StatCard label="A" value="1" tone="destructive" />,
    );
    expect(html).toContain('data-tone="destructive"');
    expect(html).toContain('bg-destructive/10');
    expect(
      renderToStaticMarkup(<StatCard label="A" value="1" />),
    ).not.toContain('data-tone');
  });

  it.each([
    ['destructive', 'text-destructive'],
    ['warning', 'text-warning'],
    ['info', 'text-info'],
    ['muted', 'text-muted-foreground'],
  ] as const)('colours the figure with valueTone=%s', (valueTone, cls) => {
    const html = renderToStaticMarkup(
      <StatCard label="A" value="1" valueTone={valueTone} />,
    );
    expect(html).toContain(`text-2xl font-bold tabular-nums ${cls}`);
  });

  it('renders a figure-sized Skeleton instead of the value while loading', () => {
    const html = renderToStaticMarkup(
      <StatCard label="A" value="99" loading />,
    );
    expect(html).toContain('data-slot="skeleton"');
    expect(html).toContain('h-8 w-12');
    expect(html).not.toContain('>99<');
    expect(html).not.toContain('tabular-nums');
    expect(html).toContain('>A<');
  });
});
