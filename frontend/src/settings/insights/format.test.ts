import { describe, expect, it } from 'vitest';

import type { ConversationInsights, InsightLabelTotals } from '../types';
import {
  capitalize,
  formatEstimate,
  formatShare,
  gapChange,
  insightsState,
  optionBars,
  optionName,
  pageNames,
  bucketLabel,
  periodChange,
  readsOverTime,
  showsFigures,
  weakLanguages,
} from './format';

const insights = (
  overrides: Partial<ConversationInsights> = {},
): ConversationInsights => ({
  success: true,
  enabled: true,
  available: true,
  coverage: {
    turns: 120,
    labelled_turns: 118,
    replies: 40,
    labelled_replies: 40,
    conversations: 70,
    labelled_conversations: 61,
    unlabelled_recent_turns: 2,
    unlabelled_older_turns: 0,
  },
  backfill_days: 7,
  labelling_from: '2026-10-13T12:00:00Z',
  languages: { en: 100 },
  language_warnings: [],
  one_pick: [],
  overlapping: [],
  totals: {},
  series: [],
  ...overrides,
});

const coverage = (
  turns: number,
  labelled: number,
  {
    failed = 0,
    recent = turns - labelled - failed,
    older = 0,
  }: { failed?: number; recent?: number; older?: number } = {},
) => ({
  ...insights().coverage,
  turns,
  labelled_turns: labelled,
  unlabelled_recent_turns: recent,
  unlabelled_older_turns: older,
  failed_turns: failed,
});

describe('insightsState', () => {
  it('follows the fetch first', () => {
    expect(insightsState('loading', null)).toBe('loading');
    expect(insightsState('error', null)).toBe('error');
    expect(insightsState('ready', insights({ success: false }))).toBe('error');
  });

  it('tells the server switch from the agent switch', () => {
    expect(
      insightsState('ready', insights({ available: false, enabled: false })),
    ).toBe('serverOff');
    expect(insightsState('ready', insights({ enabled: false }))).toBe(
      'agentOff',
    );
  });

  it('reads coverage: no traffic, partial, ready', () => {
    expect(insightsState('ready', insights({ coverage: coverage(0, 0) }))).toBe(
      'noTraffic',
    );
    expect(
      insightsState('ready', insights({ coverage: coverage(120, 118) })),
    ).toBe('partial');
    expect(
      insightsState('ready', insights({ coverage: coverage(120, 120) })),
    ).toBe('ready');
  });

  // IN-20: "analyzing" only while the sweep still has answers to label;
  // answers older than its window are never labelled, so they say so.
  it('analyzes while unlabelled answers sit inside the labelling window', () => {
    expect(
      insightsState('ready', insights({ coverage: coverage(40, 0) })),
    ).toBe('analyzing');
    // Too few labels for a figure yet, with more on the way.
    expect(
      insightsState('ready', insights({ coverage: coverage(40, 9) })),
    ).toBe('analyzing');
    // Enough for figures: they show, with the coverage count.
    expect(
      insightsState('ready', insights({ coverage: coverage(40, 12) })),
    ).toBe('partial');
  });

  it('tells answers older than the labelling window from ones still to come', () => {
    expect(
      insightsState(
        'ready',
        insights({ coverage: coverage(12, 0, { recent: 0, older: 12 }) }),
      ),
    ).toBe('olderOnly');
    // Some still to come: analyzing, whatever is older.
    expect(
      insightsState(
        'ready',
        insights({ coverage: coverage(12, 0, { recent: 2, older: 10 }) }),
      ),
    ).toBe('analyzing');
    // Labels from before, nothing more to come: figures, complete.
    expect(
      insightsState(
        'ready',
        insights({ coverage: coverage(12, 3, { recent: 0, older: 9 }) }),
      ),
    ).toBe('ready');
  });

  // Coverage counts only what the sweep can still label: older answers
  // never complete it.
  it('is ready once nothing inside the labelling window is left', () => {
    expect(
      insightsState(
        'ready',
        insights({ coverage: coverage(120, 100, { recent: 0, older: 20 }) }),
      ),
    ).toBe('ready');
    expect(
      insightsState(
        'ready',
        insights({ coverage: coverage(120, 100, { recent: 5, older: 15 }) }),
      ),
    ).toBe('partial');
  });

  // Answers whose labelling failed for good are not still to come: they
  // neither hold the section on "analyzing" nor keep it partial.
  it('does not wait on answers that could not be analyzed', () => {
    expect(
      insightsState(
        'ready',
        insights({ coverage: coverage(12, 11, { failed: 1 }) }),
      ),
    ).toBe('ready');
    expect(
      insightsState(
        'ready',
        insights({ coverage: coverage(120, 100, { failed: 15, recent: 5 }) }),
      ),
    ).toBe('partial');
  });

  it('says so when no answer in the window could be analyzed', () => {
    expect(
      insightsState(
        'ready',
        insights({ coverage: coverage(3, 0, { failed: 3 }) }),
      ),
    ).toBe('failedOnly');
    // Failures name the problem over older answers, which are expected.
    expect(
      insightsState(
        'ready',
        insights({
          coverage: coverage(12, 0, { failed: 2, recent: 0, older: 10 }),
        }),
      ),
    ).toBe('failedOnly');
    // Some still to come: analyzing, whatever failed.
    expect(
      insightsState(
        'ready',
        insights({ coverage: coverage(12, 0, { failed: 2, recent: 10 }) }),
      ),
    ).toBe('analyzing');
  });

  // An older server sends no failed_turns: the states read as before.
  it('reads a coverage without failed_turns as none failed', () => {
    const { failed_turns: _failed, ...older } = coverage(12, 0, {
      recent: 0,
      older: 12,
    });
    void _failed;
    expect(insightsState('ready', insights({ coverage: older }))).toBe(
      'olderOnly',
    );
  });

  it('shows figures only with labels', () => {
    expect(showsFigures('partial')).toBe(true);
    expect(showsFigures('ready')).toBe(true);
    expect(showsFigures('analyzing')).toBe(false);
    expect(showsFigures('olderOnly')).toBe(false);
    expect(showsFigures('failedOnly')).toBe(false);
  });
});

describe('numbers', () => {
  it('formats a rate as a whole percent, and a sliver as under one', () => {
    expect(formatShare(0.741, 'en')).toBe('74%');
    expect(formatShare(0, 'en')).toBe('0%');
    expect(formatShare(0.003, 'en')).toBe('<1%');
    expect(formatShare(Number.NaN, 'en')).toBe('—');
  });

  it('never shows an expected count with decimals', () => {
    expect(formatEstimate(6.2, 'en')).toBe('6');
    expect(formatEstimate(1234.6, 'en')).toBe('1,235');
    expect(formatEstimate(0.3, 'en')).toBe('<1');
    expect(formatEstimate(0, 'en')).toBe('0');
  });
});

describe('readsOverTime', () => {
  it('needs three buckets that each hold the sample floor', () => {
    expect(readsOverTime([10, 12, 30])).toBe(true);
    expect(readsOverTime([0, 10, 0, 11, 9, 40])).toBe(true);
    // Plenty in all, but in two buckets: a period figure, not a trend.
    expect(readsOverTime([200, 0, 150])).toBe(false);
    expect(readsOverTime([9, 9, 9, 9])).toBe(false);
    expect(readsOverTime([])).toBe(false);
  });
});

describe('bucketLabel', () => {
  it('names a day, a week clipped to the window, and an hour, read in UTC', () => {
    expect(bucketLabel({ bucket: '2026-10-17' }, 'day', 'en-GB')).toBe(
      '17 Oct',
    );
    expect(
      bucketLabel(
        { bucket: '2026-10-19', bucket_end: '2026-10-24' },
        'week',
        'en-GB',
      ),
    ).toBe('19–24 Oct');
    expect(
      bucketLabel(
        { bucket: '2026-09-28', bucket_end: '2026-10-04' },
        'week',
        'en-GB',
      ),
      // Intl sets the dash between thin spaces.
    ).toMatch(/^28 Sept\s–\s4 Oct$/);
    // A week of one day in the window reads as that day.
    expect(
      bucketLabel(
        { bucket: '2026-10-24', bucket_end: '2026-10-24' },
        'week',
        'en-GB',
      ),
    ).toBe('24 Oct');
    expect(bucketLabel({ bucket: '2026-10-24 13:00' }, 'hour', 'en-GB')).toBe(
      '13:00',
    );
    expect(
      bucketLabel({ bucket: '2026-10-24 13:05:00' }, 'minute', 'en-GB'),
    ).toBe('13:05');
  });

  it('leaves a key it cannot read as it is', () => {
    expect(bucketLabel({ bucket: 'soon' }, 'day', 'en-GB')).toBe('soon');
  });
});

describe('periodChange', () => {
  it('compares whole percents with the previous period', () => {
    expect(periodChange(0.68, { n: 40, rate: 0.62 })).toEqual({
      previous: 0.62,
      direction: 'up',
    });
    expect(periodChange(0.5, { n: 40, rate: 0.61 })).toEqual({
      previous: 0.61,
      direction: 'down',
    });
    // 68.2% and 67.9% both read 68%.
    expect(periodChange(0.682, { n: 40, rate: 0.679 })).toEqual({
      previous: 0.679,
      direction: 'same',
    });
  });

  it('says nothing while the previous period is under the sample floor', () => {
    expect(periodChange(0.68, { n: 9, rate: 0.2 })).toBeNull();
    expect(periodChange(0.68, undefined)).toBeNull();
  });
});

describe('optionBars', () => {
  const totals: InsightLabelTotals = {
    tier: 'estimated',
    n: 118,
    options: {
      other: { expected: 9, rate: 0.4, low: 0.3, high: 0.5 },
      'how-to': { expected: 45, rate: 0.38, low: 0.31, high: 0.45 },
      troubleshooting: { expected: 28, rate: 0.24, low: 0.18, high: 0.31 },
      comparison: { expected: 0.4, rate: 0.003, low: 0, high: 0.02 },
      none: { expected: 30, rate: 0.25, low: 0.2, high: 0.3 },
    },
  };

  it('sorts by rate, puts the catch-all last and drops rounding-to-zero rows', () => {
    const rows = optionBars(totals, (option) => option.toUpperCase(), {
      skip: ['none'],
      last: ['other'],
    });
    expect(rows.map((row) => row.key)).toEqual([
      'how-to',
      'troubleshooting',
      'other',
    ]);
    expect(rows[0]).toEqual({
      key: 'how-to',
      label: 'HOW-TO',
      rate: 0.38,
    });
  });

  it('names model options through their keys and passes unknown ones through', () => {
    const t = (key: string) => `t:${key}`;
    expect(optionName(t, 'request_type', 'how-to')).toBe(
      't:settings.analytics.insights.options.requestType.howTo',
    );
    expect(optionName(t, 'reaction', 'complaint')).toBe(
      't:settings.analytics.insights.options.reaction.pushbackOrComplaint',
    );
    expect(optionName(t, 'request_type', 'brand new')).toBe('brand new');
  });
});

describe('weakLanguages', () => {
  it('counts every language but English and Spanish, other last', () => {
    expect(
      weakLanguages({ en: 100, ru: 12, other: 6, es: 2 }, ['answer_status']),
    ).toEqual({ share: 18 / 120, codes: ['ru', 'other'] });
  });

  it('counts Chinese only while the reaction label is warned about', () => {
    expect(weakLanguages({ en: 90, zh: 10 }, ['answer_status']).codes).toEqual(
      [],
    );
    expect(weakLanguages({ en: 90, zh: 10 }, ['reaction'])).toEqual({
      share: 0.1,
      codes: ['zh'],
    });
  });

  it('upper-cases the list that opens the sentence', () => {
    expect(capitalize('answer status and topic', 'en')).toBe(
      'Answer status and topic',
    );
  });
});

describe('gapChange', () => {
  it('reads new, none, up and down from rounded counts', () => {
    expect(gapChange(3.2, 0.3)).toEqual({ kind: 'new' });
    expect(gapChange(4.2, 3.9)).toEqual({ kind: 'none' });
    expect(gapChange(6.2, 4)).toEqual({ kind: 'up', delta: 2 });
    expect(gapChange(2, 3.4)).toEqual({ kind: 'down', delta: 1 });
    expect(gapChange(0.2, 0)).toEqual({ kind: 'none' });
  });

  it('has no change while the previous period was not labelled', () => {
    expect(gapChange(3.2, 0, false)).toEqual({ kind: 'noEarlier' });
    expect(gapChange(6.2, 4, false)).toEqual({ kind: 'noEarlier' });
    expect(gapChange(3.2, 0, true)).toEqual({ kind: 'new' });
  });
});

describe('pageNames', () => {
  const page = (name: string | null, source: string | null = 'Docs') => ({
    key: name ? `https://x/${name.length}` : null,
    name,
    source,
  });

  it('strips the site tail every named row shares', () => {
    expect(
      pageNames([
        page('App Configuration | DocsGPT Docs'),
        page('Chat Widget | DocsGPT Docs', 'Other'),
        page(null, null),
      ]),
    ).toEqual(['App Configuration', 'Chat Widget', null]);
  });

  it('takes the longest shared tail, by any of the separators', () => {
    expect(
      pageNames([page('Install | Guide · Docs'), page('Run | Guide · Docs')]),
    ).toEqual(['Install', 'Run']);
    expect(
      pageNames([page('A | Setup — Docs'), page('B | Usage — Docs')]),
    ).toEqual(['A | Setup', 'B | Usage']);
    expect(pageNames([page('A – Docs'), page('B – Docs')])).toEqual(['A', 'B']);
  });

  it('needs at least two rows, and never strips a name to nothing', () => {
    expect(pageNames([page('Upgrading | DocsGPT Docs')])).toEqual([
      'Upgrading | DocsGPT Docs',
    ]);
    expect(pageNames([page('Docs | Site'), page('Site')])).toEqual([
      'Docs | Site',
      'Site',
    ]);
  });

  it('falls back to each source when the rows share no tail', () => {
    expect(
      pageNames([
        page('Install | Core', 'Core'),
        page('Deploy | Core', 'Core'),
        page('Upgrade — Old site', 'Old'),
        page('Lone · Third', 'Third'),
      ]),
    ).toEqual(['Install', 'Deploy', 'Upgrade — Old site', 'Lone · Third']);
  });

  it('leaves a page named by its URL alone, and does not count it', () => {
    const url = { key: 'https://x/a', name: 'https://x/a', source: 'Docs' };
    expect(pageNames([page('A | Docs'), page('B | Docs'), url])).toEqual([
      'A',
      'B',
      'https://x/a',
    ]);
  });
});
