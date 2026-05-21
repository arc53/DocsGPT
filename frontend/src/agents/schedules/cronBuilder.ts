import type { Schedule } from '../types/schedule';

export type ScheduleFrequency =
  | 'once'
  | 'daily'
  | 'weekly'
  | 'monthly'
  | 'yearly';

export type ScheduleFormValues = {
  frequency: ScheduleFrequency;
  date: string; // YYYY-MM-DD (used by 'once')
  time: string; // HH:MM (24h)
  dayOfWeek: number; // 0=Sun … 6=Sat (used by 'weekly')
  dayOfMonth: number; // 1..31 (used by 'monthly' / 'yearly')
  month: number; // 1..12 (used by 'yearly')
};

const clamp = (n: number, lo: number, hi: number): number =>
  Math.max(lo, Math.min(hi, Math.floor(n)));

const pad2 = (n: number): string => String(n).padStart(2, '0');

/** Parse "HH:MM" into [hour, minute]; defaults on bad input. */
export function parseTime(time: string): { hour: number; minute: number } {
  const m = /^(\d{1,2}):(\d{1,2})$/.exec(time?.trim() ?? '');
  if (!m) return { hour: 9, minute: 0 };
  return {
    hour: clamp(Number(m[1]), 0, 23),
    minute: clamp(Number(m[2]), 0, 59),
  };
}

/** Detect the browser's IANA timezone (e.g. ``Europe/Warsaw``). */
export function browserTimezone(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tz || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** Build a 5-field cron expression for recurring frequencies; ``null`` for 'once'. */
export function buildCron(
  frequency: ScheduleFrequency,
  values: Pick<
    ScheduleFormValues,
    'time' | 'dayOfWeek' | 'dayOfMonth' | 'month'
  >,
): string | null {
  if (frequency === 'once') return null;
  const { hour, minute } = parseTime(values.time);
  switch (frequency) {
    case 'daily':
      return `${minute} ${hour} * * *`;
    case 'weekly':
      return `${minute} ${hour} * * ${clamp(values.dayOfWeek, 0, 6)}`;
    case 'monthly':
      return `${minute} ${hour} ${clamp(values.dayOfMonth, 1, 31)} * *`;
    case 'yearly':
      return `${minute} ${hour} ${clamp(values.dayOfMonth, 1, 31)} ${clamp(values.month, 1, 12)} *`;
    default:
      return null;
  }
}

/** Convert a local date/time + IANA tz to a UTC ISO 8601 string. */
export function buildRunAtUtc(
  date: string,
  time: string,
  timezone: string,
): string {
  const { hour, minute } = parseTime(time);
  const dm = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(date?.trim() ?? '');
  if (!dm) throw new Error('invalid date');
  const year = Number(dm[1]);
  const month = clamp(Number(dm[2]), 1, 12);
  const day = clamp(Number(dm[3]), 1, 31);
  // Compute UTC offset of the chosen tz at the chosen wall-clock instant by
  // formatting an interim UTC date and reading back the tz parts.
  const guess = Date.UTC(year, month - 1, day, hour, minute, 0);
  const parts = formatInTimeZone(guess, timezone);
  const wallUtc = Date.UTC(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute,
    0,
  );
  const offset = wallUtc - guess;
  return new Date(guess - offset).toISOString();
}

type TzParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
};

const formatInTimeZone = (utcMs: number, timezone: string): TzParts => {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  const map: Record<string, string> = {};
  for (const p of fmt.formatToParts(new Date(utcMs))) {
    if (p.type !== 'literal') map[p.type] = p.value;
  }
  return {
    year: Number(map.year),
    month: Number(map.month),
    day: Number(map.day),
    // Intl returns "24" at midnight in some engines; normalize to 0.
    hour: Number(map.hour) % 24,
    minute: Number(map.minute),
  };
};

/** Derive form initial values from an existing schedule (edit mode). */
export function parseScheduleToFormValues(
  schedule: Schedule,
  timezone: string,
): ScheduleFormValues {
  const fallback: ScheduleFormValues = {
    frequency: 'daily',
    date: todayDate(timezone),
    time: '09:00',
    dayOfWeek: 1,
    dayOfMonth: 1,
    month: 1,
  };
  if (schedule.trigger_type === 'once' && schedule.run_at) {
    const parts = formatInTimeZone(
      new Date(schedule.run_at).getTime(),
      timezone,
    );
    return {
      ...fallback,
      frequency: 'once',
      date: `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`,
      time: `${pad2(parts.hour)}:${pad2(parts.minute)}`,
    };
  }
  if (!schedule.cron) return fallback;
  const parsed = parseCron(schedule.cron);
  if (!parsed) return fallback;
  const { frequency, minute, hour, dom, mon, dow } = parsed;
  return {
    frequency,
    date: fallback.date,
    time: `${pad2(hour)}:${pad2(minute)}`,
    dayOfWeek: dow ?? 1,
    dayOfMonth: dom ?? 1,
    month: mon ?? 1,
  };
}

type ParsedCron = {
  frequency: Exclude<ScheduleFrequency, 'once'>;
  minute: number;
  hour: number;
  dom: number | null;
  mon: number | null;
  dow: number | null;
};

/** Recognize the cron shapes ``buildCron`` produces; otherwise ``null``. */
export function parseCron(expression: string): ParsedCron | null {
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [mn, hr, dom, mon, dow] = parts;
  const m = Number(mn);
  const h = Number(hr);
  if (!Number.isFinite(m) || !Number.isFinite(h)) return null;
  // yearly: explicit dom + explicit mon
  if (dom !== '*' && mon !== '*' && dow === '*') {
    const d = Number(dom);
    const mm = Number(mon);
    if (!Number.isFinite(d) || !Number.isFinite(mm)) return null;
    return {
      frequency: 'yearly',
      minute: m,
      hour: h,
      dom: d,
      mon: mm,
      dow: null,
    };
  }
  // monthly: explicit dom, * mon, * dow
  if (dom !== '*' && mon === '*' && dow === '*') {
    const d = Number(dom);
    if (!Number.isFinite(d)) return null;
    return {
      frequency: 'monthly',
      minute: m,
      hour: h,
      dom: d,
      mon: null,
      dow: null,
    };
  }
  // weekly: * dom, * mon, explicit dow (single value)
  if (dom === '*' && mon === '*' && dow !== '*' && !dow.includes(',')) {
    const d = Number(dow);
    if (!Number.isFinite(d)) return null;
    return {
      frequency: 'weekly',
      minute: m,
      hour: h,
      dom: null,
      mon: null,
      dow: d,
    };
  }
  // daily: * dom, * mon, * dow
  if (dom === '*' && mon === '*' && dow === '*') {
    return {
      frequency: 'daily',
      minute: m,
      hour: h,
      dom: null,
      mon: null,
      dow: null,
    };
  }
  return null;
}

/** Today's date in ``YYYY-MM-DD`` for the given IANA timezone. */
export function todayDate(timezone: string): string {
  const p = formatInTimeZone(Date.now(), timezone);
  return `${p.year}-${pad2(p.month)}-${pad2(p.day)}`;
}
