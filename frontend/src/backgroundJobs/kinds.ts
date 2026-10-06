/**
 * What woke the agent, and how the app names it. Plain helpers with no
 * imports, so the conversation slice can use them without a cycle.
 */

/** What can wake the agent (`message_metadata.wake.source`); each has its own row label. */
export const WAKE_SOURCES = [
  'job',
  'lost',
  'monitor',
  'trigger',
  'approval',
] as const;

/**
 * `notify_user` kinds with their own heading: every wake source, and the
 * notices a feature sends on its own (a monitor paused by its circuit
 * breaker). Others read generically. Mirrors `docsgpt/notifications/kinds.py`.
 */
export const NOTIFICATION_KINDS = [...WAKE_SOURCES, 'monitor_paused'] as const;

const isIn = (list: readonly string[], value: unknown): value is string =>
  typeof value === 'string' && list.includes(value);

/** Whether a `notification.created` kind has its own heading. */
export function isKnownNotificationKind(kind: unknown): kind is string {
  return isIn(NOTIFICATION_KINDS, kind);
}

/** The toast heading for a `notification.created` kind. */
export function notificationHeadingKey(kind: unknown): string {
  return isKnownNotificationKind(kind)
    ? `backgroundJobs.notify.title.${kind}`
    : 'backgroundJobs.notify.title.default';
}

/** The system row's label for a woken turn's source. */
export function wakeLabelKey(source: string): string {
  return isIn(WAKE_SOURCES, source)
    ? `backgroundJobs.wake.${source}`
    : 'backgroundJobs.wake.default';
}

// The model needs the job id in the event title; the user does not.
const JOB_ID_SUFFIX = /\s*\(job [0-9a-fA-F-]{8,}\)/g;

/** A title as the user reads it: `run_code finished (job 5f0c…)` gives `run_code finished`. */
export function userTitle(title: string | undefined | null): string {
  return (title ?? '').replace(JOB_ID_SUFFIX, '').replace(/\s+/g, ' ').trim();
}

/**
 * A system notification's title and body for a `notification.created`
 * payload, worded like the server's Web Push (`kinds.push_text`): a known
 * kind leads with its heading and moves the title into the body.
 */
export function notificationText(
  payload: { kind?: string; title?: string; body?: string },
  t: (key: string) => string,
): { title: string; body: string } {
  const title = userTitle(payload.title);
  const body = (payload.body ?? '').trim();
  if (!isKnownNotificationKind(payload.kind)) {
    return { title: title || t('backgroundJobs.notify.fallbackTitle'), body };
  }
  const heading = t(notificationHeadingKey(payload.kind));
  return {
    title: heading,
    body: title && body ? `${title}: ${body}` : title || body,
  };
}

/** What woke the agent for a continuation turn (`message_metadata.wake`). */
export type WakeInfo = { source: string; count: number };

const EVENT_HEADER = /^\[Background event[^\]]*\]\s*/;

/** Read `message_metadata` for a woken turn; null for an ordinary user message. */
export function wakeFromMetadata(metadata: unknown): WakeInfo | null {
  if (!metadata || typeof metadata !== 'object') return null;
  const meta = metadata as {
    wake?: { source?: unknown };
    wakes?: unknown[];
    continuation?: unknown;
  };
  if (!meta.wake && meta.continuation !== true) return null;
  const source =
    typeof meta.wake?.source === 'string' ? meta.wake.source : 'event';
  const count = Array.isArray(meta.wakes) ? Math.max(1, meta.wakes.length) : 1;
  return { source, count };
}

/**
 * The event's one-line title from the stored prompt:
 * `[Background event - …] monitor: BTC below $50k` gives `BTC below $50k`.
 */
export function wakeTitle(prompt: string): string {
  const first = (prompt.split('\n', 1)[0] ?? '').replace(EVENT_HEADER, '');
  const colon = first.indexOf(':');
  return userTitle(colon >= 0 ? first.slice(colon + 1) : first);
}
