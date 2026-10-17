import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ToggleGroup, ToggleGroupItem } from './toggle-group';

const range = (value: string, size?: 'xs' | 'sm', fill?: boolean) =>
  renderToStaticMarkup(
    <ToggleGroup
      type="single"
      value={value}
      size={size}
      fill={fill}
      aria-label="Range"
    >
      <ToggleGroupItem value="7">7d</ToggleGroupItem>
      <ToggleGroupItem value="30">30d</ToggleGroupItem>
    </ToggleGroup>,
  );

/** The class attribute of the group (the track). */
function trackClasses(html: string): string {
  return (
    /data-slot="toggle-group"[^>]*class="([^"]*)"|class="([^"]*)"[^>]*data-slot="toggle-group"/
      .exec(html)
      ?.slice(1)
      .find(Boolean) ?? ''
  );
}

/** The class attribute of the item whose text is `label`. */
function itemClasses(html: string, label: string): string {
  const match = new RegExp(`<button[^>]*class="([^"]*)"[^>]*>${label}<`).exec(
    html,
  );
  return match?.[1] ?? '';
}

describe('ToggleGroup', () => {
  it('is a radio group of pills', () => {
    const html = range('30');
    expect(html).toContain('role="radiogroup"');
    expect(html).toContain('aria-label="Range"');
    expect(itemClasses(html, '30d')).toContain('rounded-full');
  });

  it('draws the on item as outline and the off item as ghost-muted', () => {
    const html = range('30');
    const on = itemClasses(html, '30d');
    const off = itemClasses(html, '7d');
    expect(on).toContain('data-[state=on]:bg-background');
    expect(off).toContain('text-muted-foreground');
    expect(html).toMatch(/aria-checked="true"[^>]*>30d</);
  });

  it('sizes items sm (32px) by default and xs (28px) on request', () => {
    expect(itemClasses(range('7'), '7d')).toContain('h-8');
    expect(itemClasses(range('7', 'xs'), '7d')).toContain('h-7');
  });

  it('draws the muted pill track itself: 38px at sm, 36px at xs', () => {
    const sm = trackClasses(range('7')).split(' ');
    expect(sm).toEqual(expect.arrayContaining(['bg-muted', 'rounded-full']));
    expect(sm).toContain('p-0.75');
    const xs = trackClasses(range('7', 'xs')).split(' ');
    expect(xs).toEqual(expect.arrayContaining(['bg-muted', 'rounded-full']));
    expect(xs).toContain('p-1');
  });

  it('hugs its content and never wraps by default', () => {
    const track = trackClasses(range('7')).split(' ');
    expect(track).toContain('w-fit');
    expect(track).toContain('flex-nowrap');
    expect(track).not.toContain('flex-wrap');
    expect(track).not.toContain('w-full');
    expect(itemClasses(range('7'), '7d')).not.toContain('flex-1');
    // Too many items for a phone: the track scrolls sideways, never wraps.
    expect(track).toEqual(
      expect.arrayContaining(['max-w-full', 'overflow-x-auto', 'no-scrollbar']),
    );
  });

  it('spans its row with even items when fill is set', () => {
    const html = range('7', 'sm', true);
    const track = trackClasses(html).split(' ');
    expect(track).toContain('w-full');
    expect(track).toContain('flex-nowrap');
    expect(track).not.toContain('w-fit');
    const item = itemClasses(html, '7d').split(' ');
    expect(item).toEqual(expect.arrayContaining(['flex-1', 'min-w-0', 'px-1']));
    expect(item).not.toContain('px-3');
    expect(html).not.toContain('fill=');
  });

  it('outlines the on item in muted-foreground, one token in both themes', () => {
    const on = itemClasses(range('30'), '30d').split(' ');
    expect(on).toContain('data-[state=on]:border-muted-foreground');
    // No opacity modifier and no dark override for the border.
    expect(on.filter((c) => c.includes('border-') && c.includes('/'))).toEqual(
      [],
    );
    expect(on).not.toContain('data-[state=on]:border-border');
    expect(on).not.toContain('data-[state=on]:dark:border-input');
  });

  it('draws a count after the label: muted, normal weight, tabular', () => {
    const html = renderToStaticMarkup(
      <ToggleGroup type="single" value="all" aria-label="Filter">
        <ToggleGroupItem value="all" count={1234}>
          All
        </ToggleGroupItem>
        <ToggleGroupItem value="some" count="2 of 5">
          Some
        </ToggleGroupItem>
        <ToggleGroupItem value="none">None</ToggleGroupItem>
      </ToggleGroup>,
    );
    const counts = [
      ...html.matchAll(/<span data-slot="count" class="([^"]*)">([^<]*)</g),
    ];
    expect(counts.map((m) => m[2])).toEqual(['1,234', '2 of 5']);
    // Muted on the on item too (the item's own on-colour is foreground).
    expect(counts[0][1].split(' ')).toEqual(
      expect.arrayContaining([
        'text-muted-foreground',
        'font-normal',
        'tabular-nums',
      ]),
    );
    expect(html).toMatch(/aria-checked="true"[^>]*>All<span data-slot="count"/);
    expect(html).toContain('>None</button>');
  });
});
