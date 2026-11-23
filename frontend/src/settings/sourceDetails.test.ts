import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import type { Connection } from '../connectors/types';
import type { Doc } from '../models/misc';
import {
  formatTokens,
  sourceCardLine,
  sourceDetailLine,
} from './sourceDetails';

// Enough of the English copy to read the lines the way a user does.
const COPY: Record<string, string> = {
  'settings.sources.website.sites': '{{count}} sites',
  'settings.sources.website.pageCount_one': '{{count}} page',
  'settings.sources.website.pageCount_other': '{{count}} pages',
  'settings.sources.viaConnection': 'via {{name}}',
  'settings.sources.viaConnectionFiles_one': 'via {{name}} · {{files}} file',
  'settings.sources.viaConnectionFiles_other': 'via {{name}} · {{files}} files',
  'settings.sources.syncFrequency.daily': 'Daily',
  'settings.sources.syncFrequency.weekly': 'Weekly',
  'settings.sources.tokenCount': '{{tokens}} tokens',
  'settings.sources.website.synced': '{{frequency}} · synced {{when}}',
};
const t = ((key: string, options: Record<string, unknown> = {}) => {
  const count = options.count as number | undefined;
  const text =
    COPY[
      count === undefined ? key : `${key}_${count === 1 ? 'one' : 'other'}`
    ] ??
    COPY[key] ??
    key;
  return text.replace(/{{(\w+)}}/g, (_, name) => String(options[name]));
}) as unknown as TFunction;

const doc = (fields: Partial<Doc> = {}): Doc => ({
  id: 'src-1',
  name: 'Contracts',
  date: '2026-10-23 13:36',
  model: '',
  ...fields,
});

const s3 = { id: 'conn-1', name: 'Amazon S3', icon: 's3' } as Connection;

describe('formatTokens', () => {
  it.each([
    [224, '224'],
    [13_080, '13.08k'],
    [2_470_000, '2.47m'],
    [3_000_000_000, '3b'],
  ])('%d reads %s', (tokens, expected) => {
    expect(formatTokens(tokens)).toBe(expected);
  });
});

describe('sourceDetailLine', () => {
  const website = { hosts: ['docs.docsgpt.cloud'], pages: 9 };

  it('a website: its host, its pages and its schedule', () => {
    expect(sourceDetailLine(t, doc({ website, syncFrequency: 'weekly' }))).toBe(
      'docs.docsgpt.cloud · 9 pages · Weekly',
    );
  });

  it('a website on several hosts and no schedule', () => {
    expect(
      sourceDetailLine(
        t,
        doc({ website: { hosts: ['a.io', 'b.io'], pages: 1 } }),
      ),
    ).toBe('2 sites · 1 page');
  });

  it('a source from a connection: the connection, its files and schedule', () => {
    expect(
      sourceDetailLine(
        t,
        doc({ connectionId: 'conn-1', files: 1, syncFrequency: 'daily' }),
        s3,
      ),
    ).toBe('via Amazon S3 · 1 file · Daily');
  });

  // The same day, minutes apart and the same size: only the time tells
  // them apart.
  it('an upload: its date with the time, and its tokens', () => {
    const line = sourceDetailLine(t, doc({ tokens: '13080' }));
    expect(line).toBe('23/10/2026, 13:36 · 13.08k tokens');
  });

  it("a team's synced source whose connection the caller can't see", () => {
    expect(
      sourceDetailLine(
        t,
        doc({
          type: 'connector:confluence',
          syncFrequency: 'weekly',
          tokens: '2470000',
        }),
      ),
    ).toBe('Weekly · 2.47m tokens');
  });

  it('leaves out what it does not know', () => {
    expect(sourceDetailLine(t, doc({ date: '', tokens: '' }))).toBe('');
  });
});

describe('sourceCardLine', () => {
  const base: Doc = { id: 'd', name: 'd', date: '', model: 'm' };

  it('says a website by its host and pages, with the last sync', () => {
    const line = sourceCardLine(t, {
      ...base,
      website: { hosts: ['docs.docsgpt.cloud'], pages: 9 },
      syncFrequency: 'weekly',
      date: new Date().toISOString(),
    });
    expect(line).toMatch(/^docs\.docsgpt\.cloud · 9 pages · Weekly · synced /);
  });

  it('leaves the tokens to the meta line', () => {
    const line = sourceCardLine(t, {
      ...base,
      date: '2026-10-23 13:36',
      tokens: '224',
    });
    expect(line).toBe('23/10/2026, 13:36');
  });

  it('says where a synced source comes from', () => {
    const line = sourceCardLine(
      t,
      { ...base, files: 1, syncFrequency: 'daily', date: '' },
      { name: 'Amazon S3' } as Connection,
    );
    expect(line).toBe('via Amazon S3 · 1 file · Daily · synced —');
  });
});
