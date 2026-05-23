import { describe, expect, it } from 'vitest';

import type { Schedule } from '../types/schedule';
import {
  browserTimezone,
  buildCron,
  buildRunAtUtc,
  formatCron,
  parseCron,
  parseScheduleToFormValues,
  parseTime,
  supportedTimezones,
} from './cronBuilder';

const baseValues = {
  time: '09:00',
  dayOfWeek: 1,
  dayOfMonth: 1,
  month: 1,
};

describe('buildCron', () => {
  it('Daily 22:30 → "30 22 * * *"', () => {
    expect(buildCron('daily', { ...baseValues, time: '22:30' })).toBe(
      '30 22 * * *',
    );
  });

  it('Weekly Mon 09:00 → "0 9 * * 1"', () => {
    expect(
      buildCron('weekly', { ...baseValues, time: '09:00', dayOfWeek: 1 }),
    ).toBe('0 9 * * 1');
  });

  it('Monthly day-15 10:00 → "0 10 15 * *"', () => {
    expect(
      buildCron('monthly', { ...baseValues, time: '10:00', dayOfMonth: 15 }),
    ).toBe('0 10 15 * *');
  });

  it('Yearly March 15 08:00 → "0 8 15 3 *"', () => {
    expect(
      buildCron('yearly', {
        ...baseValues,
        time: '08:00',
        dayOfMonth: 15,
        month: 3,
      }),
    ).toBe('0 8 15 3 *');
  });

  it('Once returns null cron', () => {
    expect(buildCron('once', baseValues)).toBeNull();
  });

  it('clamps out-of-range time inputs', () => {
    expect(buildCron('daily', { ...baseValues, time: '99:99' })).toBe(
      '59 23 * * *',
    );
  });

  it('clamps day-of-month and month for yearly', () => {
    expect(
      buildCron('yearly', {
        ...baseValues,
        time: '00:00',
        dayOfMonth: 99,
        month: 0,
      }),
    ).toBe('0 0 31 1 *');
  });
});

describe('parseTime', () => {
  it('parses "HH:MM"', () => {
    expect(parseTime('07:05')).toEqual({ hour: 7, minute: 5 });
  });

  it('falls back to 09:00 on bad input', () => {
    expect(parseTime('garbage')).toEqual({ hour: 9, minute: 0 });
  });
});

describe('buildRunAtUtc', () => {
  it('UTC noon → UTC noon (no offset)', () => {
    expect(buildRunAtUtc('2026-06-15', '12:00', 'UTC')).toBe(
      '2026-06-15T12:00:00.000Z',
    );
  });

  it('Europe/Warsaw 12:00 in summer (CEST, UTC+2) → 10:00Z', () => {
    expect(buildRunAtUtc('2026-06-15', '12:00', 'Europe/Warsaw')).toBe(
      '2026-06-15T10:00:00.000Z',
    );
  });

  it('Europe/Warsaw 12:00 in winter (CET, UTC+1) → 11:00Z', () => {
    expect(buildRunAtUtc('2026-12-15', '12:00', 'Europe/Warsaw')).toBe(
      '2026-12-15T11:00:00.000Z',
    );
  });

  it('America/Los_Angeles 09:00 in summer (PDT, UTC-7) → 16:00Z', () => {
    expect(buildRunAtUtc('2026-07-04', '09:00', 'America/Los_Angeles')).toBe(
      '2026-07-04T16:00:00.000Z',
    );
  });

  it('Asia/Tokyo 09:00 (JST, UTC+9, no DST) → 00:00Z', () => {
    // System tz is irrelevant here — the helper must honour the tz parameter.
    expect(buildRunAtUtc('2026-06-15', '09:00', 'Asia/Tokyo')).toBe(
      '2026-06-15T00:00:00.000Z',
    );
  });

  it('Australia/Sydney 09:00 in Jul winter (AEST, UTC+10) → 23:00Z prev day', () => {
    expect(buildRunAtUtc('2026-07-15', '09:00', 'Australia/Sydney')).toBe(
      '2026-07-14T23:00:00.000Z',
    );
  });

  it('honours an arbitrary picked tz independently of the system tz', () => {
    // Picking Asia/Singapore (UTC+8, no DST) maps 10:00 local → 02:00Z.
    expect(buildRunAtUtc('2026-03-10', '10:00', 'Asia/Singapore')).toBe(
      '2026-03-10T02:00:00.000Z',
    );
  });

  it('throws on invalid date', () => {
    expect(() => buildRunAtUtc('not-a-date', '12:00', 'UTC')).toThrow();
  });
});

describe('supportedTimezones', () => {
  it('returns a non-empty list of IANA tz strings', () => {
    const list = supportedTimezones();
    expect(Array.isArray(list)).toBe(true);
    expect(list.length).toBeGreaterThan(0);
    // Common zones every fallback / modern engine should expose.
    expect(list).toContain('UTC');
  });

  it('includes the browser zone when modern Intl is available', () => {
    // happy-dom exposes Intl.supportedValuesOf; this is the modern path.
    const list = supportedTimezones();
    expect(list).toContain('Europe/Warsaw');
    expect(list).toContain('Asia/Tokyo');
  });
});

describe('parseCron', () => {
  it('round-trips daily cron', () => {
    expect(parseCron('30 22 * * *')).toMatchObject({
      frequency: 'daily',
      minute: 30,
      hour: 22,
    });
  });

  it('round-trips weekly cron', () => {
    expect(parseCron('0 9 * * 1')).toMatchObject({
      frequency: 'weekly',
      minute: 0,
      hour: 9,
      dow: 1,
    });
  });

  it('round-trips monthly cron', () => {
    expect(parseCron('0 10 15 * *')).toMatchObject({
      frequency: 'monthly',
      minute: 0,
      hour: 10,
      dom: 15,
    });
  });

  it('round-trips yearly cron', () => {
    expect(parseCron('0 8 15 3 *')).toMatchObject({
      frequency: 'yearly',
      minute: 0,
      hour: 8,
      dom: 15,
      mon: 3,
    });
  });

  it('returns null for unsupported shapes (weekday range)', () => {
    expect(parseCron('0 9 * * 1-5')).toBeNull();
  });

  it('returns null for non-5-field input', () => {
    expect(parseCron('* * *')).toBeNull();
  });
});

describe('browserTimezone', () => {
  it('returns a non-empty IANA-looking string', () => {
    const tz = browserTimezone();
    expect(typeof tz).toBe('string');
    expect(tz.length).toBeGreaterThan(0);
  });
});

describe('parseScheduleToFormValues', () => {
  const makeSchedule = (overrides: Partial<Schedule>): Schedule => ({
    id: 's',
    user_id: 'u',
    agent_id: 'a',
    trigger_type: 'recurring',
    instruction: 'do thing',
    status: 'active',
    timezone: 'UTC',
    tool_allowlist: [],
    created_via: 'ui',
    consecutive_failure_count: 0,
    created_at: '2026-05-19T12:00:00Z',
    updated_at: '2026-05-19T12:00:00Z',
    ...overrides,
  });

  it('reconstructs weekly from a cron schedule', () => {
    const s = makeSchedule({ cron: '0 9 * * 1' });
    const v = parseScheduleToFormValues(s, 'UTC');
    expect(v.frequency).toBe('weekly');
    expect(v.time).toBe('09:00');
    expect(v.dayOfWeek).toBe(1);
  });

  it('reconstructs once from run_at', () => {
    const s = makeSchedule({
      trigger_type: 'once',
      cron: null,
      run_at: '2026-06-15T12:00:00Z',
    });
    const v = parseScheduleToFormValues(s, 'UTC');
    expect(v.frequency).toBe('once');
    expect(v.date).toBe('2026-06-15');
    expect(v.time).toBe('12:00');
  });

  it('falls back to daily 09:00 when cron is unrecognized', () => {
    const s = makeSchedule({ cron: '0 9 * * 1-5' });
    const v = parseScheduleToFormValues(s, 'UTC');
    expect(v.frequency).toBe('daily');
  });

  it('round-trips weekly cron → form values → cron', () => {
    const s = makeSchedule({ cron: '30 14 * * 4' });
    const v = parseScheduleToFormValues(s, 'UTC');
    expect(buildCron(v.frequency, v)).toBe('30 14 * * 4');
  });

  it('round-trips monthly cron → form values → cron', () => {
    const s = makeSchedule({ cron: '5 7 22 * *' });
    const v = parseScheduleToFormValues(s, 'UTC');
    expect(buildCron(v.frequency, v)).toBe('5 7 22 * *');
  });

  it('round-trips yearly cron → form values → cron', () => {
    const s = makeSchedule({ cron: '0 8 15 3 *' });
    const v = parseScheduleToFormValues(s, 'UTC');
    expect(buildCron(v.frequency, v)).toBe('0 8 15 3 *');
  });

  it('round-trips daily cron → form values → cron', () => {
    const s = makeSchedule({ cron: '45 6 * * *' });
    const v = parseScheduleToFormValues(s, 'UTC');
    expect(buildCron(v.frequency, v)).toBe('45 6 * * *');
  });

  it('round-trips once schedule → run_at preserved through tz', () => {
    const runAt = '2026-06-15T12:00:00.000Z';
    const s = makeSchedule({
      trigger_type: 'once',
      cron: null,
      run_at: runAt,
    });
    const v = parseScheduleToFormValues(s, 'UTC');
    expect(buildRunAtUtc(v.date, v.time, 'UTC')).toBe(runAt);
  });
});

describe('formatCron', () => {
  it('renders daily 9:00 AM', () => {
    expect(formatCron('0 9 * * *')).toBe('Daily at 9:00 AM');
  });

  it('renders daily 10:30 PM', () => {
    expect(formatCron('30 22 * * *')).toBe('Daily at 10:30 PM');
  });

  it('renders weekly Monday 9:00 AM', () => {
    expect(formatCron('0 9 * * 1')).toBe('Weekly on Monday at 9:00 AM');
  });

  it('renders weekly Sunday', () => {
    expect(formatCron('15 7 * * 0')).toBe('Weekly on Sunday at 7:15 AM');
  });

  it('renders monthly day 15 at 10:00 AM', () => {
    expect(formatCron('0 10 15 * *')).toBe('Monthly on day 15 at 10:00 AM');
  });

  it('renders yearly March 15 8:00 AM', () => {
    expect(formatCron('0 8 15 3 *')).toBe('Yearly on March 15 at 8:00 AM');
  });

  it('renders midnight as 12:00 AM', () => {
    expect(formatCron('0 0 * * *')).toBe('Daily at 12:00 AM');
  });

  it('renders noon as 12:00 PM', () => {
    expect(formatCron('0 12 * * *')).toBe('Daily at 12:00 PM');
  });

  it('falls back to custom for unsupported cron', () => {
    expect(formatCron('0 9 * * 1-5')).toBe('Custom: 0 9 * * 1-5');
  });

  it('returns empty string for null/undefined', () => {
    expect(formatCron(null)).toBe('');
    expect(formatCron(undefined)).toBe('');
  });
});
