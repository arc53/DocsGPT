import { describe, expect, it } from 'vitest';

import {
  describeBudget,
  formToPolicy,
  isEmptyForm,
  policyToForm,
  sourceLabel,
  usagePercent,
  type QuotaPolicy,
} from './quotaUtils';

const policy = (fields: Partial<QuotaPolicy>): QuotaPolicy => ({
  scope: 'user',
  subject_id: 'u1',
  bucket: 'all',
  token_limit: null,
  token_unlimited: false,
  cost_limit_usd: null,
  cost_unlimited: false,
  enabled: true,
  ...fields,
});

describe('policyToForm', () => {
  it('starts a missing policy as inherit', () => {
    const form = policyToForm(null);
    expect(form.tokenMode).toBe('inherit');
    expect(form.costMode).toBe('inherit');
    expect(isEmptyForm(form)).toBe(true);
  });

  it('keeps zero as a limit, not as inherit', () => {
    const form = policyToForm(policy({ token_limit: 0, cost_unlimited: true }));
    expect(form.tokenMode).toBe('limit');
    expect(form.tokenLimit).toBe('0');
    expect(form.costMode).toBe('unlimited');
  });
});

describe('formToPolicy', () => {
  const base = policyToForm(null);

  it('round-trips limits and trims the note', () => {
    const result = formToPolicy({
      ...base,
      tokenMode: 'limit',
      tokenLimit: ' 5000 ',
      costMode: 'limit',
      costLimit: '2.5',
      note: '  trial  ',
    });
    expect(result).toEqual({
      ok: true,
      policy: {
        bucket: 'all',
        token_limit: 5000,
        token_unlimited: false,
        cost_limit_usd: 2.5,
        cost_unlimited: false,
        note: 'trial',
      },
    });
  });

  it('sends unlimited without a limit', () => {
    const result = formToPolicy({
      ...base,
      tokenMode: 'unlimited',
      tokenLimit: '99',
    });
    expect(result.ok && result.policy.token_limit).toBeNull();
    expect(result.ok && result.policy.token_unlimited).toBe(true);
  });

  it.each(['', '1.5', '-1', 'abc', '1e3'])(
    'rejects token limit %j',
    (tokenLimit) => {
      expect(formToPolicy({ ...base, tokenMode: 'limit', tokenLimit }).ok).toBe(
        false,
      );
    },
  );

  it.each(['', '-0.01', 'abc', 'Infinity'])(
    'rejects cost limit %j',
    (costLimit) => {
      expect(formToPolicy({ ...base, costMode: 'limit', costLimit }).ok).toBe(
        false,
      );
    },
  );
});

describe('usagePercent', () => {
  it('handles unlimited, zero and overshoot', () => {
    expect(usagePercent(50, null)).toBe(0);
    expect(usagePercent(0, 0)).toBe(100);
    expect(usagePercent(25, 100)).toBe(25);
    expect(usagePercent(500, 100)).toBe(100);
  });
});

describe('labels', () => {
  it('describes budgets', () => {
    expect(describeBudget(null, true, 'tokens')).toBe('Unlimited');
    expect(describeBudget(null, false, 'cost')).toBe('—');
    expect(describeBudget(1000, false, 'tokens')).toContain('tokens');
  });

  it('names the layer a limit came from', () => {
    expect(sourceLabel({ limit: null, used: 0 })).toBe('No limit set');
    expect(sourceLabel({ limit: 1, used: 0, source: 'team' }, 'Eng')).toBe(
      'Team: Eng',
    );
    expect(sourceLabel({ limit: 1, used: 0, source: 'default' })).toBe(
      'Plan default',
    );
  });
});
