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
  shareOfDay,
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
  tags: [],
  totals: {},
  series: [],
  ...overrides,
});

const coverage = (
  turns: number,
  labelled: number,
  { recent = turns - labelled, older = 0 } = {},
) => ({
  ...insights().coverage,
  turns,
  labelled_turns: labelled,
  unlabelled_recent_turns: recent,
  unlabelled_older_turns: older,
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

  it('shows figures only with labels', () => {
    expect(showsFigures('partial')).toBe(true);
    expect(showsFigures('ready')).toBe(true);
    expect(showsFigures('analyzing')).toBe(false);
    expect(showsFigures('olderOnly')).toBe(false);
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

  it("reads a day's expected count as its share of the day, an empty day as 0", () => {
    expect(shareOfDay(1.5, 6)).toBe(0.25);
    expect(shareOfDay(0, 0)).toBe(0);
    expect(shareOfDay(0.4, 0)).toBe(0);
    // Rounding in the sums never draws a column past 100%.
    expect(shareOfDay(3.0000001, 3)).toBe(1);
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
});
