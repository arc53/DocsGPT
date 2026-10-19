import { describe, expect, it } from 'vitest';

import {
  analyticsOf,
  appendSuggestions,
  DEFAULT_ANALYTICS,
  isDefaultAnalytics,
  nameTaken,
  newTagId,
  units,
} from './analyticsConfig';

describe('units', () => {
  // The server's `schema.units`: CJK x3, Cyrillic x1.2, the rest x1.
  it('counts as the server does', () => {
    expect(units('你好')).toBe(6);
    expect(units('こんにちは')).toBe(15);
    expect(units('한국')).toBe(6);
    expect(units('Docs')).toBe(4);
    expect(units('Привет')).toBeCloseTo(7.2);
    expect(units('ＡＢ')).toBe(6);
    expect(units('')).toBe(0);
  });
});

describe('newTagId', () => {
  it('makes ids the server accepts, different each time', () => {
    const ids = new Set(Array.from({ length: 50 }, newTagId));
    expect(ids.size).toBe(50);
    for (const id of ids) expect(id).toMatch(/^[a-z0-9]{8,32}$/);
  });
});

describe('defaults', () => {
  it('fills an agent saved before analytics with the defaults', () => {
    expect(analyticsOf(undefined)).toEqual(DEFAULT_ANALYTICS);
    expect(isDefaultAnalytics(undefined)).toBe(true);
    expect(isDefaultAnalytics(DEFAULT_ANALYTICS)).toBe(true);
  });

  it('knows an agent with settings of its own', () => {
    expect(isDefaultAnalytics({ ...DEFAULT_ANALYTICS, enabled: false })).toBe(
      false,
    );
    expect(isDefaultAnalytics({ ...DEFAULT_ANALYTICS, digest: true })).toBe(
      false,
    );
    expect(
      isDefaultAnalytics({
        ...DEFAULT_ANALYTICS,
        tags: [{ id: 'a1b2c3d4', name: 'Pricing', description: 'Prices' }],
      }),
    ).toBe(false);
    expect(
      isDefaultAnalytics({
        ...DEFAULT_ANALYTICS,
        topics: { mode: 'off', items: [] },
      }),
    ).toBe(false);
  });

  it('compares names without case or outer spaces', () => {
    expect(nameTaken(' installation ', ['Installation'])).toBe(true);
    expect(nameTaken('Install', ['Installation'])).toBe(false);
  });
});

describe('appendSuggestions', () => {
  const listed = [
    { name: 'Installation', description: 'Pages such as: Docker' },
  ];

  it('appends only names not in the list, never touching existing rows', () => {
    const result = appendSuggestions(
      listed,
      [
        { name: 'installation', description: 'Different text' },
        { name: 'Billing', description: 'Pages such as: Plans' },
        { name: 'None of these', description: 'Reserved' },
      ],
      15,
    );
    expect(result.items).toEqual([
      listed[0],
      { name: 'Billing', description: 'Pages such as: Plans' },
    ]);
    expect(result.note).toBeNull();
  });

  it('says why nothing was added, or that the limit cut some off', () => {
    expect(appendSuggestions(listed, [], 15).note).toBe('none');
    expect(
      appendSuggestions(listed, [{ name: 'INSTALLATION', description: '' }], 15)
        .note,
    ).toBe('noNew');
    const full = appendSuggestions(
      listed,
      [
        { name: 'A', description: '' },
        { name: 'B', description: '' },
      ],
      2,
    );
    expect(full.items.map((item) => item.name)).toEqual(['Installation', 'A']);
    expect(full.note).toBe('full');
  });
});
