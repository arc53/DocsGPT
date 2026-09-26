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
});
