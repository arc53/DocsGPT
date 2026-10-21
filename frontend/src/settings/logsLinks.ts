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

/** Whether a `label` URL value is one the Logs filter can send. */
export function isLogLabel(value: string | null): value is LogLabel {
  if (!value) return false;
  if (value.startsWith('topic:')) {
    const name = value.slice('topic:'.length);
    return name.trim().length > 0 && name.length <= TOPIC_NAME_MAX;
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
