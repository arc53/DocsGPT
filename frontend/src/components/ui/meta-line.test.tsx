import { Users } from 'lucide-react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { MetaItem, MetaLine } from './meta-line';

describe('MetaLine', () => {
  it('joins its items with a hidden dot and skips empty ones', () => {
    const html = renderToStaticMarkup(
      <MetaLine>
        <MetaItem>8.41k</MetaItem>
        {null}
        {false}
        <MetaItem>1 agent</MetaItem>
      </MetaLine>,
    );
    expect(html).toContain('data-slot="meta-line"');
    expect(html.match(/<span aria-hidden="true">·<\/span>/g)).toHaveLength(1);
    expect(html.indexOf('8.41k')).toBeLessThan(html.indexOf('1 agent'));
  });

  it('draws nothing when no item is left', () => {
    const html = renderToStaticMarkup(
      <MetaLine>
        {null}
        {undefined}
      </MetaLine>,
    );
    expect(html).toBe('');
  });
});

describe('MetaItem', () => {
  it('draws a 14px icon hidden from screen readers and keeps a hover title', () => {
    const html = renderToStaticMarkup(
      <MetaItem icon={<Users />} title="Syncs into Knowledge">
        Syncs
      </MetaItem>,
    );
    expect(html).toContain('title="Syncs into Knowledge"');
    expect(html).toMatch(/<svg[^>]*class="[^"]*size-3\.5[^"]*"/);
    expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
    expect(html).toContain('<span class="min-w-0 truncate">Syncs</span>');
  });
});
