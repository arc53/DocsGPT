import type { TFunction } from 'i18next';

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
  const amount = (value?: number) =>
    isCost
      ? new Intl.NumberFormat(locale, {
          style: 'currency',
          currency: 'USD',
        }).format(value ?? 0)
      : new Intl.NumberFormat(locale).format(value ?? 0);
  const reset = body.resets_at ? new Date(body.resets_at) : null;
  const resetsAt =
    reset && !Number.isNaN(reset.getTime())
      ? new Intl.DateTimeFormat(locale, {
          dateStyle: 'medium',
          timeStyle: 'short',
        }).format(reset)
      : '';
  return t(
    isCost
      ? 'conversation.quotaExceeded.cost'
      : 'conversation.quotaExceeded.tokens',
    { used: amount(body.usage), limit: amount(body.limit), resetsAt },
  );
}
