import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ListRow, ListRows } from './list-row';

describe('ListRow', () => {
  it('lays out leading, a truncating title and meta, and trailing', () => {
    const html = renderToStaticMarkup(
      <ListRows>
        <ListRow
          leading={<span>L</span>}
          title="lena@example.com"
          description="Added manually"
          trailing={<button type="button">Remove</button>}
        />
      </ListRows>,
    );
    expect(html).toContain('<ul');
    expect(html).toContain('divide-border divide-y');
    expect(html).toContain('<li');
    expect(html).toContain('flex items-center gap-3 px-4 py-3');
    expect(html).toContain('text-foreground truncate text-sm font-medium');
    expect(html).toContain('text-muted-foreground truncate text-xs');
  });

  it('hovers to accent with an inset ring when interactive', () => {
    const html = renderToStaticMarkup(
      <ListRow interactive asChild title="Sources">
        <a href="/settings/sources" />
      </ListRow>,
    );
    expect(html).toContain('<a href="/settings/sources"');
    expect(html).toContain('hover:bg-accent');
    expect(html).toContain('focus-visible:ring-inset');
    expect(html).toContain('Sources');
  });

  it('is dense, rounded and top-aligned at size sm', () => {
    const html = renderToStaticMarkup(
      <ListRow size="sm" interactive asChild title="Duisport">
        <button type="button" />
      </ListRow>,
    );
    expect(html).toContain('items-start gap-2.5 rounded-md px-2 py-1.5');
    expect(html).not.toContain('px-4 py-3');
    expect(html).toContain('focus-visible:ring-inset');
  });

  it('keeps the brand tint on a selected row, hover included', () => {
    const html = renderToStaticMarkup(
      <ListRow interactive selected asChild title="Carrier Rates MCP">
        <button type="button" />
      </ListRow>,
    );
    expect(html).toContain('bg-secondary hover:bg-secondary');
    expect(html).not.toContain('hover:bg-accent');
    expect(html).toContain('aria-current="true"');
  });

  it('titles a string title and description with their full value', () => {
    const html = renderToStaticMarkup(
      <ListRow title="lena@example.com" description="Added by SCIM sync" />,
    );
    expect(html).toContain(
      '<p class="text-foreground truncate text-sm font-medium" title="lena@example.com">',
    );
    expect(html).toContain(
      '<p class="text-muted-foreground truncate text-xs" title="Added by SCIM sync">',
    );
  });

  it('leaves a node title to the caller', () => {
    const html = renderToStaticMarkup(
      <ListRow
        title={<span title="Carrier Rates MCP">Carrier Rates MCP</span>}
        description={<span>2 tools</span>}
      />,
    );
    expect(html).toContain(
      '<p class="text-foreground truncate text-sm font-medium"><span title="Carrier Rates MCP">',
    );
    expect(html).toContain(
      '<p class="text-muted-foreground truncate text-xs"><span>',
    );
  });
});
