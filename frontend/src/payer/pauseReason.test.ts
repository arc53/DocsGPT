import { describe, expect, it } from 'vitest';

import { formatPayerDate, paidByText, pauseReasonText } from './pauseReason';

// Echoes the key and its values, so a test sees both.
const t = ((key: string, options?: Record<string, unknown>) => {
  if (!options) return key;
  const values = Object.entries(options)
    .filter(([name]) => name !== 'interpolation')
    .map(([name, value]) => `${name}=${value}`)
    .join(',');
  return `${key}(${values})`;
}) as never;

const until = '2026-12-01T00:00:00+00:00';

describe('pauseReasonText', () => {
  it('says nothing when nothing is paused', () => {
    expect(pauseReasonText(t, null, 'Dana')).toBe('');
    expect(pauseReasonText(t, undefined)).toBe('');
  });

  it('words a deactivated account without naming whose', () => {
    expect(pauseReasonText(t, { reason: 'owner_inactive' }, 'Dana')).toBe(
      'payer.common.pause.ownerInactive',
    );
  });

  it('names who left and the team', () => {
    expect(
      pauseReasonText(t, { reason: 'payer_left' }, 'Ines', 'Operations', {
        language: 'en',
      }),
    ).toBe('payer.common.pause.payerLeft(name=Ines,team=Operations)');
    expect(pauseReasonText(t, { reason: 'payer_left' }, 'Ines')).toBe(
      'payer.common.pause.payerLeftNoTeam(name=Ines)',
    );
    expect(pauseReasonText(t, { reason: 'payer_left' }, null, 'Ops')).toBe(
      'payer.common.pause.payerLeftUnnamed',
    );
  });

  it('says nobody pays', () => {
    expect(pauseReasonText(t, { reason: 'no_payer' })).toBe(
      'payer.common.pause.noPayer',
    );
  });

  it('gives the reset date of an allowance pause in the reader’s language', () => {
    expect(
      pauseReasonText(
        t,
        { reason: 'payer_out_of_allowance', until },
        'Tomas',
        'Ops',
        { language: 'en' },
      ),
    ).toBe('payer.common.pause.outOfAllowance(name=Tomas,date=1 Dec)');
    expect(
      pauseReasonText(
        t,
        { reason: 'payer_out_of_allowance', until },
        'Tomas',
        null,
        { language: 'de' },
      ),
    ).toBe('payer.common.pause.outOfAllowance(name=Tomas,date=1. Dez.)');
  });

  it('speaks to the payer when it is the reader', () => {
    expect(
      pauseReasonText(
        t,
        { reason: 'payer_out_of_allowance', until },
        'Me',
        '',
        {
          you: true,
          language: 'en',
        },
      ),
    ).toBe('payer.common.pause.outOfAllowanceYou(date=1 Dec)');
  });

  it('falls back when the payer or the date is unknown', () => {
    expect(
      pauseReasonText(
        t,
        { reason: 'payer_out_of_allowance', until },
        null,
        '',
        {
          language: 'en',
        },
      ),
    ).toBe('payer.common.pause.outOfAllowanceUnnamed(date=1 Dec)');
    expect(
      pauseReasonText(t, { reason: 'payer_out_of_allowance' }, 'Tomas'),
    ).toBe('payer.common.pause.outOfAllowanceUndated');
  });

  it('adds since when the first skip is known', () => {
    expect(
      pauseReasonText(
        t,
        { reason: 'no_payer', since: '2026-11-12T09:00:00Z' },
        null,
        null,
        { language: 'en' },
      ),
    ).toBe(
      'payer.common.pause.withSince(reason=payer.common.pause.noPayer,date=12 Nov)',
    );
  });
});

describe('formatPayerDate', () => {
  it('reads a window boundary as its UTC day', () => {
    // 1 Dec 00:00 UTC is still 30 Nov west of Greenwich; the window resets
    // on the 1st wherever the reader is.
    expect(formatPayerDate(until, 'en', { utc: true })).toBe('1 Dec');
  });

  it('adds the year when it is not this year', () => {
    expect(formatPayerDate('2020-03-04T00:00:00Z', 'en', { utc: true })).toBe(
      '4 Mar 2020',
    );
  });

  it('reads the Japanese code as Japanese', () => {
    expect(formatPayerDate(until, 'jp', { utc: true })).toBe('12月1日');
  });

  it('returns nothing for a value that does not parse', () => {
    expect(formatPayerDate('soon', 'en')).toBe('');
  });
});

describe('paidByText', () => {
  it('names the payer, or you', () => {
    expect(paidByText(t, { user_id: 'u2', label: 'Dana' }, 'u1')).toBe(
      'payer.common.paidBy(name=Dana)',
    );
    expect(paidByText(t, { user_id: 'u1', label: 'Me' }, 'u1')).toBe(
      'payer.common.paidByYou',
    );
    expect(paidByText(t, null, 'u1')).toBe('');
  });
});
