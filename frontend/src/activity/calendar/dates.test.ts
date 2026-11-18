import { describe, expect, it } from 'vitest';

import { dayKey, startOfWeek, stepAnchor, viewWindow } from './dates';

// Tue 13 Oct 2026, local time.
const TUESDAY = new Date(2026, 9, 13, 14, 20);

describe('calendar dates', () => {
  it('starts weeks on Monday', () => {
    expect(dayKey(startOfWeek(TUESDAY))).toBe('2026-10-12');
    expect(dayKey(startOfWeek(new Date(2026, 9, 18)))).toBe('2026-10-12');
  });

  it('gives each view its days', () => {
    expect(viewWindow('day', TUESDAY).days.map(dayKey)).toEqual(['2026-10-13']);
    const week = viewWindow('week', TUESDAY);
    expect(week.days).toHaveLength(7);
    expect(dayKey(week.end)).toBe('2026-10-19');
    const month = viewWindow('month', TUESDAY);
    expect(month.days).toHaveLength(42);
    // October 2026 starts on a Thursday: the grid starts the Monday before.
    expect(dayKey(month.start)).toBe('2026-09-28');
    expect(viewWindow('agenda', TUESDAY).days).toHaveLength(14);
  });

  it('steps by the view’s length', () => {
    expect(dayKey(stepAnchor('week', TUESDAY, 1))).toBe('2026-10-20');
    expect(dayKey(stepAnchor('month', TUESDAY, -1))).toBe('2026-09-01');
    expect(dayKey(stepAnchor('day', TUESDAY, -1))).toBe('2026-10-12');
  });
});
