import type { CalendarEvent } from './types';

/** How late a slot with no run turns missed (`MISSED_GRACE` in planned.py). */
export const MISSED_GRACE_MS = 10 * 60_000;

/** The shortest wait, so a server clock behind the browser's can't spin reloads. */
export const MIN_REFRESH_MS = 60_000;

/** How often a summed-up day under way reloads: its slots turn missed in turn. */
const SUMMED_REFRESH_MS = 5 * 60_000;

/**
 * When the window's data goes stale on its own, in ms: a planned slot whose
 * run never appears turns missed on the server's clock, and no event says
 * so. `null` when nothing planned is left.
 */
export function nextRefreshAt(
  events: CalendarEvent[],
  now: number,
): number | null {
  let next: number | null = null;
  for (const event of events) {
    if (event.kind !== 'schedule' || event.state !== 'planned') continue;
    let due = Date.parse(event.at) + MISSED_GRACE_MS;
    if (event.until && due <= now) {
      // A summed-up day stands for many slots; past its first, poll.
      if (Date.parse(event.until) + MISSED_GRACE_MS <= now) continue;
      due = now + SUMMED_REFRESH_MS;
    }
    due = Math.max(due, now + MIN_REFRESH_MS);
    if (next === null || due < next) next = due;
  }
  return next;
}
