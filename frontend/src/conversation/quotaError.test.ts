import { describe, expect, it } from 'vitest';

import { isQuotaError, quotaErrorMessage } from './quotaError';

const t = ((key: string, values: Record<string, string>) =>
  `${key}|${values.used}|${values.limit}|${values.resetsAt}`) as any;

describe('isQuotaError', () => {
  it('matches only the quota error code', () => {
    expect(isQuotaError({ error_code: 'quota-exceeded' })).toBe(true);
    expect(isQuotaError({ message: 'Exceeding usage limit' })).toBe(false);
    expect(isQuotaError(null)).toBe(false);
    expect(isQuotaError('quota-exceeded')).toBe(false);
  });
});

describe('quotaErrorMessage', () => {
  it('formats token budgets as numbers', () => {
    const message = quotaErrorMessage(
      {
        dimension: 'tokens',
        usage: 1200000,
        limit: 1000000,
        resets_at: '2026-10-01T00:00:00+00:00',
      },
      t,
      'en-US',
    );
    const [key, used, limit, resetsAt] = message.split('|');
    expect(key).toBe('conversation.quotaExceeded.tokens');
    expect([used, limit]).toEqual(['1,200,000', '1,000,000']);
    // Dates are en-GB everywhere, whatever the UI language.
    expect(resetsAt).toMatch(/^\d{2}\/\d{2}\/\d{4}, \d{2}:\d{2}$/);
  });

  it('formats cost budgets as dollars', () => {
    const message = quotaErrorMessage(
      { dimension: 'cost', usage: 5.25, limit: 5 },
      t,
      'en-US',
    );
    expect(message).toBe('conversation.quotaExceeded.cost|$5.25|$5.00|');
  });

  it('tolerates a malformed reset time', () => {
    const message = quotaErrorMessage(
      { dimension: 'tokens', usage: 1, limit: 1, resets_at: 'soon' },
      t,
      'en-US',
    );
    expect(message.endsWith('|')).toBe(true);
  });
});
