import { beforeEach, describe, expect, it } from 'vitest';

import {
  isDismissed,
  loadDismissed,
  saveDismissed,
} from './dismissedPersistence';

const KEY = 'test:dismissed';
const TTL = 24 * 60 * 60 * 1000;

describe('dismissedPersistence', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('saveDismissed + loadDismissed round-trips entries', () => {
    const now = Date.now();
    saveDismissed(KEY, [
      { id: 'a', at: now },
      { id: 'b', at: now - 1000 },
    ]);
    const loaded = loadDismissed(KEY, TTL);
    expect(loaded).toEqual([
      { id: 'a', at: now },
      { id: 'b', at: now - 1000 },
    ]);
  });

  it('loadDismissed returns [] when key absent', () => {
    expect(loadDismissed(KEY, TTL)).toEqual([]);
  });

  it('loadDismissed drops entries past the TTL cutoff', () => {
    const now = Date.now();
    saveDismissed(KEY, [
      { id: 'fresh', at: now - 1000 },
      { id: 'stale', at: now - (TTL + 1000) },
    ]);
    const loaded = loadDismissed(KEY, TTL);
    expect(loaded.map((e) => e.id)).toEqual(['fresh']);
  });

  it('loadDismissed returns [] on malformed JSON without throwing', () => {
    localStorage.setItem(KEY, '{not json');
    expect(loadDismissed(KEY, TTL)).toEqual([]);
  });

  it('loadDismissed filters out entries with wrong shape', () => {
    const now = Date.now();
    localStorage.setItem(
      KEY,
      JSON.stringify([
        { id: 'good', at: now },
        { id: 123, at: now },
        { id: 'bad-at', at: 'nope' },
        null,
        'string-entry',
      ]),
    );
    const loaded = loadDismissed(KEY, TTL);
    expect(loaded.map((e) => e.id)).toEqual(['good']);
  });

  it('isDismissed matches by id', () => {
    const list = [{ id: 'a', at: 1 }];
    expect(isDismissed(list, 'a')).toBe(true);
    expect(isDismissed(list, 'b')).toBe(false);
    expect(isDismissed([], 'a')).toBe(false);
  });
});
