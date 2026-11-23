import { agentLogsPath } from '../agents/paths';

/** The Logs label filter's values (`label` in /api/get_user_logs). */
export const LOG_LABELS = [
  'not_answered',
  'docs_gap',
  'frustrated',
  'asks_human',
  'negative_reaction',
  'negative_sentiment',
] as const;

export type LogLabel =
  (typeof LOG_LABELS)[number] | `tag:${string}` | `topic:${string}`;

/** A topic name's longest form (the server's `TOPIC_NAME_CHARS`). */
const TOPIC_NAME_MAX = 60;

/**
 * Python's whitespace (`str.isspace`), which the server strips a topic name
 * of. Not `String.prototype.trim`'s: Python also strips U+001C to U+001F and
 * U+0085, and keeps U+FEFF.
 */
const PY_SPACE =
  '\\t\\n\\v\\f\\r\\u001c-\\u001f \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g');

/**
 * A topic name's length as the server measures it (`len(name.strip())`):
 * code points, not UTF-16 units, once stripped.
 */
function topicNameLength(name: string): number {
  return Array.from(name.replace(PY_STRIP, '')).length;
}

/** Whether a `label` URL value is one the Logs filter can send. */
export function isLogLabel(value: string | null): value is LogLabel {
  if (!value) return false;
  if (value.startsWith('topic:')) {
    const length = topicNameLength(value.slice('topic:'.length));
    return length > 0 && length <= TOPIC_NAME_MAX;
  }
  return (
    (LOG_LABELS as readonly string[]).includes(value) ||
    /^tag:[a-z0-9]{8,32}$/.test(value)
  );
}

/**
 * A link into Logs filtered by label, narrowed to one conversation, or
 * opening one message: the agent's Logs section (`#logs`) or the account's
 * Logs page. The filters ride in the URL so the link can be shared and Back
 * returns to where it was opened.
 */
export function logsDrilldownPath({
  agentId,
  label,
  conversationId,
  messageId,
}: {
  agentId?: string;
  label?: LogLabel;
  conversationId?: string;
  messageId?: string;
}): string {
  const params = new URLSearchParams();
  if (label) params.set('label', label);
  if (conversationId) params.set('conversation', conversationId);
  if (messageId) params.set('message', messageId);
  const query = params.toString();
  const search = query ? `?${query}` : '';
  return agentId
    ? `${agentLogsPath(agentId)}${search}#logs`
    : `/settings/logs${search}`;
}

/**
 * Scrolls an element into view, smoothly unless the reader asked for reduced
 * motion.
 */
export function revealElement(
  element: Element | null | undefined,
  block: ScrollLogicalPosition,
): void {
  if (!element || typeof element.scrollIntoView !== 'function') return;
  const reduced =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  element.scrollIntoView({ block, behavior: reduced ? 'auto' : 'smooth' });
}
