import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DescriptionItem, DescriptionList } from './description-list';

describe('DescriptionList', () => {
  it('puts labels in an 8rem column by default', () => {
    const html = renderToStaticMarkup(
      <DescriptionList>
        <DescriptionItem label="Status">Success</DescriptionItem>
      </DescriptionList>,
    );
    expect(html).toContain('<dl');
    expect(html).toContain('grid-cols-[minmax(0,8rem)_minmax(0,1fr)]');
    expect(html).toContain('text-sm');
    expect(html).toContain('<dt class="text-muted-foreground"');
    expect(html).toContain('text-foreground min-w-0 break-words');
  });

  it('sets xs text and a mono value', () => {
    const html = renderToStaticMarkup(
      <DescriptionList size="xs">
        <DescriptionItem label="Endpoint" mono>
          https://x
        </DescriptionItem>
      </DescriptionList>,
    );
    expect(html).toContain('text-xs');
    expect(html).toContain('font-mono');
  });

  it('justifies values right, optionally in two columns', () => {
    const one = renderToStaticMarkup(
      <DescriptionList layout="justified">
        <DescriptionItem label="Tokens">1,204</DescriptionItem>
      </DescriptionList>,
    );
    expect(one).toContain('flex flex-col gap-2');
    expect(one).toContain('flex items-start justify-between gap-4');
    expect(one).toContain('text-right tabular-nums');
    const two = renderToStaticMarkup(
      <DescriptionList layout="justified" columns={2}>
        <DescriptionItem label="Tokens">1,204</DescriptionItem>
      </DescriptionList>,
    );
    expect(two).toContain('grid grid-cols-2 gap-x-6 gap-y-2');
  });
});
