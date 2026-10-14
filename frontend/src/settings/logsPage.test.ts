import { describe, expect, it } from 'vitest';

import { mergeLoadedPages, uniqueLogs } from './logsPage';
import type { LogData } from './types';

const row = (id: string, timestamp: string, running = false): LogData => ({
  id,
  action: 'answer',
  level: 'info',
  user: 'u',
  question: id,
  timestamp,
  running,
});

describe('mergeLoadedPages', () => {
  it('refreshes every loaded page in place', () => {
    const previous = {
      1: [row('b', '2026-10-14T10:05:00Z'), row('a', '2026-10-14T10:04:00Z')],
      2: [
        row('run', '2026-10-14T10:03:00Z', true),
        row('old', '2026-10-14T10:00:00Z'),
      ],
    };
    // Two new rows came in on top; the run on page 2 ended.
    const fresh = [
      row('d', '2026-10-14T10:07:00Z'),
      row('c', '2026-10-14T10:06:00Z'),
      row('b', '2026-10-14T10:05:00Z'),
      row('a', '2026-10-14T10:04:00Z'),
    ];
    const next = mergeLoadedPages(previous, fresh, 2, 2);
    expect(next[1].map((log) => log.id)).toEqual(['d', 'c']);
    // The run gives way; a finished row pushed past the pages stays.
    expect(next[2].map((log) => log.id)).toEqual(['b', 'a', 'old']);
  });

  it('keeps every row the refresh returned, a running webhook included', () => {
    // The server adds running webhook rows to page 1 after paging, so a page
    // can hold more rows than the page size.
    const fresh = [
      row('d2', '2026-10-14T10:07:00Z'),
      row('d1', '2026-10-14T10:06:00Z'),
      row('webhook-run-1', '2026-10-14T09:00:00Z', true),
    ];
    const next = mergeLoadedPages({ 1: [] }, fresh, 1, 2);
    expect(next[1].map((log) => log.id)).toEqual([
      'd2',
      'd1',
      'webhook-run-1',
    ]);
  });

  it('leaves pages past the refreshed ones as they are', () => {
    const third = [row('z', '2026-10-14T09:00:00Z')];
    const next = mergeLoadedPages(
      { 1: [row('a', '2026-10-14T10:04:00Z')], 3: third },
      [row('a', '2026-10-14T10:04:00Z')],
      1,
      10,
    );
    expect(next[3]).toBe(third);
  });
});

describe('uniqueLogs', () => {
  it('keeps the first copy of a row that shows on two pages', () => {
    const a = row('a', '2026-10-14T10:05:00Z');
    const b = row('b', '2026-10-14T10:04:00Z');
    expect(uniqueLogs([[a, b], [b]]).map((log) => log.id)).toEqual(['a', 'b']);
  });
});
