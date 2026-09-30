import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from './breadcrumb';

const classesOf = (html: string, slot: string, index = 0) =>
  [...html.matchAll(new RegExp(`<[^>]*data-slot="${slot}"[^>]*>`, 'g'))][
    index
  ][0]
    .match(/class="([^"]*)"/)![1]
    .split(' ');

describe('BreadcrumbLink', () => {
  it('shows the standard focus ring on an anchor', () => {
    const html = renderToStaticMarkup(
      <BreadcrumbLink href="/agents">Agents</BreadcrumbLink>,
    );
    expect(html).toContain('focus-visible:ring-3');
    expect(html).toContain('focus-visible:ring-ring/50');
    expect(html).toContain('outline-none');
  });

  it('passes the focus ring through asChild to a button crumb', () => {
    const html = renderToStaticMarkup(
      <BreadcrumbLink asChild>
        <button type="button">My Drive</button>
      </BreadcrumbLink>,
    );
    expect(html).toMatch(/<button[^>]*focus-visible:ring-3/);
  });
});

describe('Breadcrumb truncation policy', () => {
  const crumbs = (
    <>
      <BreadcrumbItem>
        <BreadcrumbLink href="/">My Drive</BreadcrumbLink>
      </BreadcrumbItem>
      <BreadcrumbSeparator />
      <BreadcrumbItem>
        <BreadcrumbLink href="/a">A long parent folder name</BreadcrumbLink>
      </BreadcrumbItem>
      <BreadcrumbSeparator />
      <BreadcrumbItem>
        <BreadcrumbPage>Q3 renewals &amp; more</BreadcrumbPage>
      </BreadcrumbItem>
    </>
  );
  const trail = (wrap = false) =>
    renderToStaticMarkup(
      <Breadcrumb>
        {wrap ? (
          <BreadcrumbList className="flex-wrap">{crumbs}</BreadcrumbList>
        ) : (
          <BreadcrumbList>{crumbs}</BreadcrumbList>
        )}
      </Breadcrumb>,
    );

  it('keeps the trail on one line by default', () => {
    const list = classesOf(trail(), 'breadcrumb-list');
    expect(list).toContain('flex-nowrap');
    expect(list).not.toContain('flex-wrap');
  });

  it('lets a page wrap the trail (AgentsList)', () => {
    const list = classesOf(trail(true), 'breadcrumb-list');
    expect(list).toContain('flex-wrap');
    expect(list).not.toContain('flex-nowrap');
  });

  it('lets items shrink, except the first, which stays whole', () => {
    const item = classesOf(trail(), 'breadcrumb-item', 1);
    expect(item).toContain('min-w-0');
    expect(item).toContain('first:shrink-0');
  });

  it('caps parents at 16ch and the current crumb at 32ch', () => {
    const html = trail();
    expect(classesOf(html, 'breadcrumb-link')).toEqual(
      expect.arrayContaining(['max-w-[16ch]', 'truncate']),
    );
    expect(classesOf(html, 'breadcrumb-page')).toEqual(
      expect.arrayContaining(['max-w-[32ch]', 'truncate']),
    );
  });

  it('titles the current crumb with its text', () => {
    expect(trail()).toContain('title="Q3 renewals &amp; more"');
    const nodeChild = renderToStaticMarkup(
      <BreadcrumbPage>
        <span>x</span>
      </BreadcrumbPage>,
    );
    expect(nodeChild).not.toContain('title=');
    const explicit = renderToStaticMarkup(
      <BreadcrumbPage title="Full name">Short</BreadcrumbPage>,
    );
    expect(explicit).toContain('title="Full name"');
  });
});
