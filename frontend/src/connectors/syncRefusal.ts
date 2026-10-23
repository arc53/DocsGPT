import type { TFunction } from 'i18next';

/** /api/sync_source and /api/connectors/sync refusal codes, and the key each. */
const SYNC_REFUSAL_KEYS = new Map<unknown, string>([
  ['wiki', 'syncRefusedWiki'],
  ['not_syncable', 'syncRefusedNotSyncable'],
  ['connector_source', 'syncRefusedConnector'],
  ['invalid_source', 'syncRefusedInvalid'],
]);

/**
 * A refused Sync now in the user's language: the server's `code` when it has
 * a key, else its own words (`error`, or `message` from /api/sync_source),
 * else the caller's generic failure. A server error's text is never shown.
 *
 * @param t The translate function.
 * @param data The response's JSON, if it parsed.
 * @param options `status`, the response's HTTP status; `fallback`, the
 *   generic line (the drawer's "Couldn't sync" by default).
 * @returns The toast's message.
 */
export function syncRefusal(
  t: TFunction,
  data: unknown,
  { status, fallback }: { status?: number; fallback?: string } = {},
): string {
  const body = (data && typeof data === 'object' ? data : {}) as {
    code?: unknown;
    error?: unknown;
    message?: unknown;
  };
  const key = SYNC_REFUSAL_KEYS.get(body.code);
  if (key) return t(`settings.connectors.detail.${key}`);
  const text =
    status !== undefined && status >= 500
      ? undefined
      : [body.error, body.message].find(
          (value): value is string =>
            typeof value === 'string' && !!value.trim(),
        );
  return text ?? fallback ?? t('settings.connectors.detail.syncFailed');
}
