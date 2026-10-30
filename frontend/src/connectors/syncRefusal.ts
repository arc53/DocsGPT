import type { TFunction } from 'i18next';

import userService from '../api/services/userService';

/** The server's answer to a Sync now (see `requestSync`). */
export type SyncAnswer = {
  /** It took the sync: a 2xx with `success`. */
  accepted: boolean;
  status: number;
  /** The response's JSON, `{}` when it didn't parse. */
  data: Record<string, unknown>;
  /** The sync's task, when the server named one. */
  taskId: string | null;
};

/**
 * Starts a source's sync through the endpoint its type takes: a `connector*`
 * source through the connector one (the server finds its connection), one
 * typed by its loader (S3, GitHub, Reddit) through the remote-source one.
 * A network failure rejects.
 */
export async function requestSync(
  sourceId: string,
  sourceType: string | undefined,
  token: string | null,
): Promise<SyncAnswer> {
  const response = sourceType?.startsWith('connector')
    ? await userService.syncConnector(sourceId, token)
    : await userService.syncSource({ source_id: sourceId }, token);
  let data: Record<string, unknown>;
  try {
    data = (await response.json()) ?? {};
  } catch {
    data = {};
  }
  return {
    accepted: response.ok !== false && !!data.success,
    status: response.status,
    data,
    taskId: typeof data.task_id === 'string' ? data.task_id : null,
  };
}

/** /api/sync_source, /api/connectors/sync and reingest refusal codes, and the key each. */
const SYNC_REFUSAL_KEYS = new Map<unknown, string>([
  ['wiki', 'syncRefusedWiki'],
  ['not_syncable', 'syncRefusedNotSyncable'],
  ['connector_source', 'syncRefusedConnector'],
  ['invalid_source', 'syncRefusedInvalid'],
  ['reconnect_needed', 'syncRefusedReconnect'],
  // The source's account connection was removed.
  ['connection_missing', 'syncRefusedConnectionMissing'],
]);

/**
 * A refused Sync now in the user's language: the server's `code` when it has
 * a key (a 404 without one reads as `invalid_source`), else its own words
 * (`error`, or `message` from /api/sync_source), else the caller's generic
 * failure. A server error's text is never shown.
 *
 * @param t The translate function.
 * @param data The response's JSON, if it parsed.
 * @param options `status`, the response's HTTP status; `fallback`, the
 *   generic line (the drawer's "Couldn't sync" by default); `forbidden`, a
 *   403 reads as Knowledge's "not allowed" line whatever its body.
 * @returns The toast's message.
 */
export function syncRefusal(
  t: TFunction,
  data: unknown,
  {
    status,
    fallback,
    forbidden = false,
  }: { status?: number; fallback?: string; forbidden?: boolean } = {},
): string {
  if (forbidden && status === 403)
    return t('settings.sources.errors.forbidden');
  const body = (data && typeof data === 'object' ? data : {}) as {
    code?: unknown;
    error?: unknown;
    message?: unknown;
  };
  // A 404 without a code is a source deleted since the page loaded.
  const key =
    SYNC_REFUSAL_KEYS.get(body.code) ??
    (status === 404 ? 'syncRefusedInvalid' : undefined);
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
