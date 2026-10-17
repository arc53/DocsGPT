import { describe, expect, it } from 'vitest';

import { sourceHref } from './chatCompanion';

describe('sourceHref', () => {
  it('opens a crawled source by its URL', () => {
    expect(
      sourceHref({ title: 't', text: '', source: 'https://example.com/a' }),
    ).toBe('https://example.com/a');
  });

  it('gives no address for an uploaded file path', () => {
    expect(sourceHref({ title: 't', text: '', source: 'docs/a.md' })).toBe(
      null,
    );
  });

  it('falls back to the link a legacy web-search answer saved', () => {
    expect(
      sourceHref({ title: 't', text: '', link: 'https://example.com/b' }),
    ).toBe('https://example.com/b');
  });

  it('ignores the placeholder links legacy answers saved', () => {
    expect(sourceHref({ title: 't', text: '', link: 'local' })).toBe(null);
    expect(sourceHref({ title: 't', text: '', link: 'None' })).toBe(null);
  });
});
