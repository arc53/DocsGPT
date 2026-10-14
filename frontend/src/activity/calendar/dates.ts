import type { CalendarView } from './types';

/** Local midnight of the day ``date`` falls on. */
export function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/** ``date`` moved by whole calendar days (DST-safe: works on the date fields). */
export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

/** The Monday on or before ``date``: weeks start on Monday, as in en-GB. */
export function startOfWeek(date: Date): Date {
  const day = startOfDay(date);
  return addDays(day, -((day.getDay() + 6) % 7));
}

/** Days an agenda lists from its first day. */
export const AGENDA_DAYS = 14;

/**
 * The days a view shows around ``anchor``: one day, the Monday-to-Sunday
 * week, the six weeks that hold the month, or the agenda's two weeks.
 *
 * Returns:
 *   ``{start, end, days}``: local midnights, ``end`` exclusive.
 */
export function viewWindow(
  view: CalendarView,
  anchor: Date,
): { start: Date; end: Date; days: Date[] } {
  let start: Date;
  let count: number;
  if (view === 'day') {
    start = startOfDay(anchor);
    count = 1;
  } else if (view === 'week') {
    start = startOfWeek(anchor);
    count = 7;
  } else if (view === 'month') {
    start = startOfWeek(new Date(anchor.getFullYear(), anchor.getMonth(), 1));
    count = 42;
  } else {
    start = startOfDay(anchor);
    count = AGENDA_DAYS;
  }
  const days = Array.from({ length: count }, (_, i) => addDays(start, i));
  return { start, end: addDays(start, count), days };
}

/** Where the arrows move the anchor: a day, a week, a month or an agenda page. */
export function stepAnchor(
  view: CalendarView,
  anchor: Date,
  direction: 1 | -1,
): Date {
  if (view === 'day') return addDays(anchor, direction);
  if (view === 'week') return addDays(anchor, 7 * direction);
  if (view === 'month')
    return new Date(anchor.getFullYear(), anchor.getMonth() + direction, 1);
  return addDays(anchor, AGENDA_DAYS * direction);
}

export function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

/** Local day key ("2026-10-13") an event falls on. */
export function dayKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** Hours since local midnight, as a fraction (14:15 → 14.25). */
export function hourOf(date: Date): number {
  return date.getHours() + date.getMinutes() / 60;
}

/** "15:00": en-GB 24-hour, as every time in the app. */
export function formatClock(date: Date): string {
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}
