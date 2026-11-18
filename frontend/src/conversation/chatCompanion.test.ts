import { describe, expect, it } from 'vitest';

import { relevanceBand, sourceHref } from './chatCompanion';

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

  it('opens a synced file by its link in the service, not its local path', () => {
    expect(
      sourceHref({
        title: 't',
        text: '',
        source: 'Reports/q1.pdf',
        url: 'https://drive.google.com/file/d/1/view',
      }),
    ).toBe('https://drive.google.com/file/d/1/view');
  });

  it('ignores a link that is not a web address', () => {
    expect(
      sourceHref({
        title: 't',
        text: '',
        source: 'docs/a.md',
        url: 'javascript:alert(1)',
      }),
    ).toBe(null);
  });

  it('ignores the placeholder links legacy answers saved', () => {
    expect(sourceHref({ title: 't', text: '', link: 'local' })).toBe(null);
    expect(sourceHref({ title: 't', text: '', link: 'None' })).toBe(null);
  });
});

describe('relevanceBand', () => {
  it('bands a score: strong from 0.7, possible from 0.3, weak below', () => {
    expect(relevanceBand(0.7)).toBe('strong');
    expect(relevanceBand(0.95)).toBe('strong');
    expect(relevanceBand(0.69)).toBe('possible');
    expect(relevanceBand(0.3)).toBe('possible');
    expect(relevanceBand(0.29)).toBe('weak');
    expect(relevanceBand(0)).toBe('weak');
  });

  it('gives no band to a source without a numeric score', () => {
    expect(relevanceBand(undefined)).toBe(null);
    expect(relevanceBand(null)).toBe(null);
    expect(relevanceBand('0.9')).toBe(null);
    expect(relevanceBand(Number.NaN)).toBe(null);
  });
});
