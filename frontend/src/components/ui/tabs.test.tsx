import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  NavTab,
  Tabs,
  TabsList,
  TabsTrigger,
  tabsTriggerVariants,
} from './tabs';

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

describe('Tabs look', () => {
  const html = renderToStaticMarkup(
    <Tabs defaultValue="a">
      <TabsList>
        <TabsTrigger value="a">My Files</TabsTrigger>
        <TabsTrigger value="b">Shared with Me</TabsTrigger>
      </TabsList>
    </Tabs>,
  );
  const tag = (slot: string) =>
    /class="([^"]*)"/
      .exec(new RegExp(`<[^>]*data-slot="${slot}"[^>]*>`).exec(html)![0])![1]
      .split(' ');

  it('draws underline tabs by default, keyed on the active state', () => {
    const trigger = tag('tabs-trigger');
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
    const list = tag('tabs-list');
    expect(list).toEqual(expect.arrayContaining(['border-border', 'border-b']));
    // No scroll container: it would clip the focus ring.
    expect(list).not.toContain('overflow-x-auto');
    expect(html).not.toContain('data-variant');
    expect(html).toContain('role="tablist"');
    expect(html).toContain('aria-selected="true"');
  });

  it('has no variant prop', () => {
    renderToStaticMarkup(
      <Tabs defaultValue="a">
        {/* @ts-expect-error the pill variant and the prop are gone */}
        <TabsList variant="underline">
          {/* @ts-expect-error the pill variant and the prop are gone */}
          <TabsTrigger variant="underline" value="a">
            a
          </TabsTrigger>
        </TabsList>
      </Tabs>,
    );
  });

  it('exports the trigger recipe for route tabs', () => {
    const classes = tabsTriggerVariants().split(' ');
    expect(classes).toContain('border-b-2');
    expect(classes).toContain('aria-[current=page]:border-primary');
    expect(classes).toContain('aria-[current=page]:text-foreground');
  });
});

describe('NavTab', () => {
  const render = (current?: boolean) => {
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(
      <nav>
        <NavTab current={current}>
          <a href="/agents/1/logs">Logs</a>
        </NavTab>
      </nav>,
    );
    return host.querySelector('a')!;
  };

  it('renders its child (a router Link) with the tab recipe', () => {
    const link = render();
    expect(link.dataset.slot).toBe('nav-tab');
    expect(link.getAttribute('href')).toBe('/agents/1/logs');
    const classes = link.className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'h-9',
        'px-4',
        'border-b-2',
        'text-muted-foreground',
        'focus-visible:ring-3',
      ]),
    );
    expect(link.hasAttribute('aria-current')).toBe(false);
    expect(link.getAttribute('role')).toBeNull();
  });

  it('current marks the page and draws the underline via aria-current', () => {
    const link = render(true);
    expect(link.getAttribute('aria-current')).toBe('page');
    expect(link.className).toContain('aria-[current=page]:border-primary');
  });
});
