import { describe, expect, it } from 'vitest';

import { mergeFirstPage, uniqueLogs } from './logsPage';
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

describe('mergeFirstPage', () => {
  it('takes the fresh page when nothing was loaded', () => {
    const fresh = [row('a', '2026-10-14T10:05:00Z')];
    expect(mergeFirstPage(undefined, fresh)).toEqual(fresh);
  });

  it('drops runs that ended and keeps finished rows pushed off the page', () => {
    const previous = [
      row('run', '2026-10-14T10:04:00Z', true),
      row('old', '2026-10-14T10:00:00Z'),
    ];
    const fresh = [
      row('new', '2026-10-14T10:06:00Z'),
      row('done', '2026-10-14T10:04:30Z'),
    ];
    expect(mergeFirstPage(previous, fresh).map((log) => log.id)).toEqual([
      'new',
      'done',
      'old',
    ]);
  });
});

describe('uniqueLogs', () => {
  it('keeps the first copy of a row that shows on two pages', () => {
    const a = row('a', '2026-10-14T10:05:00Z');
    const b = row('b', '2026-10-14T10:04:00Z');
    expect(uniqueLogs([[a, b], [b]]).map((log) => log.id)).toEqual(['a', 'b']);
  });
});
