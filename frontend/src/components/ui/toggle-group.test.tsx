import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ToggleGroup, ToggleGroupItem } from './toggle-group';

const range = (value: string, size?: 'xs' | 'sm') =>
  renderToStaticMarkup(
    <ToggleGroup type="single" value={value} size={size} aria-label="Range">
      <ToggleGroupItem value="7">7d</ToggleGroupItem>
      <ToggleGroupItem value="30">30d</ToggleGroupItem>
    </ToggleGroup>,
  );

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
    expect(on).toContain('data-[state=on]:border-border');
    expect(off).toContain('text-muted-foreground');
    expect(html).toMatch(/aria-checked="true"[^>]*>30d</);
  });

  it('sizes items sm (32px) by default and xs (28px) on request', () => {
    expect(itemClasses(range('7'), '7d')).toContain('h-8');
    expect(itemClasses(range('7', 'xs'), '7d')).toContain('h-7');
  });
});
