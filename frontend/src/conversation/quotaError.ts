import type { TFunction } from 'i18next';

import { formatDateTime, intlLocale } from '../utils/dateTimeUtils';

export type QuotaErrorBody = {
  error_code?: string;
  dimension?: string;
  usage?: number;
  limit?: number;
  resets_at?: string;
};

export function isQuotaError(body: unknown): body is QuotaErrorBody {
  return (
    !!body &&
    typeof body === 'object' &&
    (body as QuotaErrorBody).error_code === 'quota-exceeded'
  );
}

/** The chat message for a 429 ``quota-exceeded`` body, in the user's language. */
export function quotaErrorMessage(
  body: QuotaErrorBody,
  t: TFunction,
  locale?: string,
): string {
  const isCost = body.dimension === 'cost';
  // `locale` is i18n.language; intlLocale turns a value Intl rejects into en.
  const tag = locale ? intlLocale(locale) : undefined;
  const amount = (value?: number) =>
    isCost
      ? new Intl.NumberFormat(tag, {
          style: 'currency',
          currency: 'USD',
        }).format(value ?? 0)
      : new Intl.NumberFormat(tag).format(value ?? 0);
  const reset = body.resets_at ? new Date(body.resets_at) : null;
  const resetsAt =
    reset && !Number.isNaN(reset.getTime())
      ? formatDateTime(body.resets_at as string)
      : '';
  return t(
    isCost
      ? 'conversation.quotaExceeded.cost'
      : 'conversation.quotaExceeded.tokens',
    { used: amount(body.usage), limit: amount(body.limit), resetsAt },
  );
}

/** A 429 ``agent-limit-exceeded`` body: the agent's own 24-hour limit. */
export type AgentLimitErrorBody = {
  error_code?: string;
  dimension?: string;
  usage?: number;
  limit?: number;
  window_hours?: number;
};

/** The window an agent's limit counts over, when the body leaves it out. */
const AGENT_LIMIT_WINDOW_HOURS = 24;

export function isAgentLimitError(body: unknown): body is AgentLimitErrorBody {
  return (
    !!body &&
    typeof body === 'object' &&
    (body as AgentLimitErrorBody).error_code === 'agent-limit-exceeded'
  );
}

/**
 * The chat message for an agent over its own limit, in the user's language.
 * It names the agent's limit, not the user's quota: the user can't change it.
 *
 * Args:
 *   body: The 429 body.
 *   t: The translate function.
 *   locale: The UI language, for the numbers.
 *
 * Returns:
 *   "This agent has reached its limit: N of M tokens in the last 24 hours…".
 */
export function agentLimitErrorMessage(
  body: AgentLimitErrorBody,
  t: TFunction,
  locale?: string,
): string {
  const tag = locale ? intlLocale(locale) : undefined;
  const count = (value?: number) =>
    new Intl.NumberFormat(tag).format(value ?? 0);
  return t(
    body.dimension === 'requests'
      ? 'conversation.agentLimit.requests'
      : 'conversation.agentLimit.tokens',
    {
      used: count(body.usage),
      limit: count(body.limit),
      hours: body.window_hours ?? AGENT_LIMIT_WINDOW_HOURS,
    },
  );
}
