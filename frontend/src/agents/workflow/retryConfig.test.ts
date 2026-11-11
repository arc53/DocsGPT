import { describe, expect, it } from 'vitest';

import {
  DEFAULT_RETRY,
  effectiveRetry,
  formatBackoff,
  isValidRetryConfig,
  normalizeRetryConfig,
  parseBackoff,
  withRetryField,
} from './retryConfig';

describe('parseBackoff', () => {
  it('reads delays separated by commas or spaces', () => {
    expect(parseBackoff('2, 10 30')).toEqual({ value: [2, 10, 30] });
    expect(parseBackoff('0.5')).toEqual({ value: [0.5] });
  });

  it('takes a trailing separator, so the field can be typed into', () => {
    expect(parseBackoff('2, ')).toEqual({ value: [2] });
  });

  it('reads a blank field as unset', () => {
    expect(parseBackoff('  ')).toEqual({});
  });

  it('refuses words, negatives and delays over five minutes', () => {
    for (const text of ['2, soon', '-1', '301'])
      expect(parseBackoff(text).error).toBe(
        'agents.workflow.retry.backoffInvalid',
      );
  });

  it('refuses more than ten delays', () => {
    expect(parseBackoff('1 '.repeat(11)).error).toBe(
      'agents.workflow.retry.backoffTooMany',
    );
  });

  it('formats a list back the way it is typed', () => {
    expect(formatBackoff([2, 10, 30])).toBe('2, 10, 30');
    expect(formatBackoff(undefined)).toBe('');
  });
});

describe('effectiveRetry', () => {
  it('never retries when nothing is set', () => {
    expect(effectiveRetry()).toEqual(DEFAULT_RETRY);
    expect(effectiveRetry().max_attempts).toBe(1);
  });

  it('takes each field from the node, then the workflow, then the default', () => {
    expect(
      effectiveRetry(
        { backoff_seconds: [5] },
        { max_attempts: 3, backoff_seconds: [1, 2] },
      ),
    ).toEqual({
      max_attempts: 3,
      backoff_seconds: [5],
      on: ['transient', 'invalid_output'],
    });
  });
});

describe('normalizeRetryConfig', () => {
  it('keeps the fields of the right type', () => {
    expect(
      normalizeRetryConfig({
        max_attempts: 3,
        backoff_seconds: [1, 'x'],
        on: ['invalid_output', 'never', 'transient'],
        extra: true,
      }),
    ).toEqual({ max_attempts: 3, on: ['transient', 'invalid_output'] });
  });

  it('reads a missing or empty policy as unset', () => {
    expect(normalizeRetryConfig(undefined)).toBeUndefined();
    expect(normalizeRetryConfig(null)).toBeUndefined();
    expect(normalizeRetryConfig({})).toBeUndefined();
    expect(normalizeRetryConfig([3])).toBeUndefined();
  });
});

describe('isValidRetryConfig', () => {
  it('accepts an unset policy and one within bounds', () => {
    expect(isValidRetryConfig(undefined)).toBe(true);
    expect(
      isValidRetryConfig({
        max_attempts: 5,
        backoff_seconds: [0, 300],
        on: ['transient'],
      }),
    ).toBe(true);
  });

  it('refuses values out of bounds', () => {
    expect(isValidRetryConfig({ max_attempts: 6 })).toBe(false);
    expect(isValidRetryConfig({ max_attempts: 1.5 })).toBe(false);
    expect(isValidRetryConfig({ backoff_seconds: [] })).toBe(false);
    expect(isValidRetryConfig({ backoff_seconds: [301] })).toBe(false);
    expect(isValidRetryConfig({ on: [] })).toBe(false);
  });
});

describe('withRetryField', () => {
  it('sets a field and drops the policy once nothing is left', () => {
    const set = withRetryField(undefined, 'max_attempts', 3);
    expect(set).toEqual({ max_attempts: 3 });
    expect(withRetryField(set, 'max_attempts', undefined)).toBeUndefined();
  });
});
