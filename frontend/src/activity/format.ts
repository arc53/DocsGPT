import { formatClock, intlLocale } from '../utils/dateTimeUtils';
import type { WorkflowProgress } from './types';

const DAY_MS = 86_400_000;

/**
 * A run time as Activity lists it: the clock time today ("15:00"), with the
 * weekday on another day within a week ("Wed 08:00"), else the date. Times
 * and dates are en-GB (24-hour, DD/MM) in every language, as everywhere in
 * the app; only the weekday's name follows the language.
 *
 * Args:
 *   iso: The time, ISO 8601.
 *   now: The current time in ms (tests).
 *   locale: The language (tests).
 */
export function formatRunTime(
  iso: string | null | undefined,
  now: number = Date.now(),
  locale?: string,
): string {
  if (!iso) return '';
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return '';
  const clock = formatClock(when);
  const today = new Date(now);
  if (when.toDateString() === today.toDateString()) return clock;
  if (Math.abs(when.getTime() - now) < 6 * DAY_MS) {
    const day = new Intl.DateTimeFormat(intlLocale(locale), {
      weekday: 'short',
    }).format(when);
    return `${day} ${clock}`;
  }
  const date = new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: '2-digit',
  }).format(when);
  return `${date} ${clock}`;
}

/**
 * How long something has run, as a stopwatch: "0:42", "3:12", "1:05:09".
 *
 * Args:
 *   startedIso: When it started, ISO 8601.
 *   now: The current time in ms.
 */
export function formatElapsed(
  startedIso: string | null | undefined,
  now: number = Date.now(),
): string {
  if (!startedIso) return '';
  const started = Date.parse(startedIso);
  if (Number.isNaN(started)) return '';
  const total = Math.max(0, Math.floor((now - started) / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, '0');
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}`
    : `${minutes}:${seconds}`;
}

/**
 * The step a running workflow is on, as Now shows it.
 *
 * Args:
 *   progress: The run's `workflow_progress`.
 *
 * Returns:
 *   The 1-based step, the step count (null when the workflow branches), the
 *   step's title, and how far along it is in percent (only with a count); null
 *   before the first step starts.
 */
export function workflowStep(progress: WorkflowProgress | null | undefined): {
  step: number;
  total: number | null;
  title: string | null;
  percent: number | null;
} | null {
  if (!progress?.current) return null;
  const total = progress.total || null;
  const step = total ? Math.min(progress.done + 1, total) : progress.done + 1;
  return {
    step,
    total,
    title: progress.current.title?.trim() || null,
    percent: total ? Math.round((progress.done / total) * 100) : null,
  };
}
