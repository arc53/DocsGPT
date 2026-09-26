import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Tabs, TabsList, TabsTrigger } from './tabs';

describe('TabsTrigger', () => {
  it('uses the DESIGN.md 3px keyboard ring', () => {
    const html = renderToStaticMarkup(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTrigger value="a">Overview</TabsTrigger>
        </TabsList>
      </Tabs>,
    );
    const tag = /<button[^>]*data-slot="tabs-trigger"[^>]*>/.exec(html)![0];
    expect(tag).toContain('focus-visible:ring-3');
    expect(tag).not.toContain('focus-visible:ring-2');
  });
});

describe('Tabs variants', () => {
  const render = (variant?: 'default' | 'underline') =>
    renderToStaticMarkup(
      <Tabs defaultValue="a">
        <TabsList variant={variant}>
          <TabsTrigger variant={variant} value="a">
            My Files
          </TabsTrigger>
          <TabsTrigger variant={variant} value="b">
            Shared with Me
          </TabsTrigger>
        </TabsList>
      </Tabs>,
    );
  const tag = (html: string, slot: string) =>
    /class="([^"]*)"/
      .exec(new RegExp(`<[^>]*data-slot="${slot}"[^>]*>`).exec(html)![0])![1]
      .split(' ');

  it('keeps the pill trigger as the default', () => {
    const html = render();
    const trigger = tag(html, 'tabs-trigger');
    expect(trigger).toEqual(
      expect.arrayContaining([
        'rounded-3xl',
        'font-bold',
        'data-[state=active]:bg-muted',
      ]),
    );
    expect(html).toContain('data-variant="default"');
    expect(tag(html, 'tabs-list')).toContain('overflow-x-auto');
  });

  it('draws underline tabs with the Button tab look, keyed on the active state', () => {
    const html = render('underline');
    const trigger = tag(html, 'tabs-trigger');
    expect(trigger).toEqual(
      expect.arrayContaining([
        'border-b-2',
        'border-transparent',
        'text-muted-foreground',
        'hover:text-foreground',
        'hover:border-border',
        'data-[state=active]:border-primary',
        'data-[state=active]:text-foreground',
        'rounded-none',
        'h-9',
        'px-4',
        'font-medium',
        'focus-visible:ring-3',
      ]),
    );
    expect(trigger).not.toContain('rounded-3xl');
    expect(trigger).not.toContain('font-bold');
    const list = tag(html, 'tabs-list');
    expect(list).toEqual(expect.arrayContaining(['border-border', 'border-b']));
    // No scroll container: it would clip the focus ring.
    expect(list).not.toContain('overflow-x-auto');
    expect(html).toContain('data-variant="underline"');
    expect(html).toContain('role="tablist"');
    expect(html).toContain('aria-selected="true"');
  });
});
