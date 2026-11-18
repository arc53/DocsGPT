import type { TFunction } from 'i18next';

import type { ConnectionPausedFor } from './types';

const TEAM_ERRORS = 'settings.connectors.team.errors';

/**
 * Refusal codes about team connections and the locale key each reads as.
 * The server sends the code in `error` (connection routes) or in `code`
 * (upload, sources, sharing, which keep a sentence in `error`).
 */
export const CONNECTION_ERROR_KEYS: Readonly<Record<string, string>> = {
  account_already_connected: `${TEAM_ERRORS}.accountAlreadyConnected`,
  connect_personal_first: `${TEAM_ERRORS}.connectPersonalFirst`,
  connection_admin_required: `${TEAM_ERRORS}.adminRequired`,
  // A source's account was removed; Knowledge already says it this way.
  connection_missing: 'settings.connectors.detail.syncRefusedConnectionMissing',
  connection_not_found: `${TEAM_ERRORS}.notFound`,
  connection_paused: `${TEAM_ERRORS}.paused`,
  connection_picker_owner_only: `${TEAM_ERRORS}.pickerOwnerOnly`,
  connector_personal_only: `${TEAM_ERRORS}.personalOnly`,
  invalid_owner: `${TEAM_ERRORS}.invalidOwner`,
  member_mode_not_allowed: `${TEAM_ERRORS}.memberModeNotAllowed`,
  team_connection_outside: `${TEAM_ERRORS}.teamConnectionOutside`,
  team_workspace_required: `${TEAM_ERRORS}.teamWorkspaceRequired`,
};

type Body = Record<string, unknown>;

const asBody = (data: unknown): Body | null =>
  data && typeof data === 'object' ? (data as Body) : null;

/**
 * The team connection refusal code in a response body: `code` when it is
 * one, else `error` when it is one.
 *
 * Args:
 *   data: The response's JSON.
 *
 * Returns:
 *   A key of `CONNECTION_ERROR_KEYS`, or null.
 */
export function connectionErrorCode(data: unknown): string | null {
  const body = asBody(data);
  if (!body) return null;
  for (const value of [body.code, body.error]) {
    if (typeof value === 'string' && value in CONNECTION_ERROR_KEYS)
      return value;
  }
  return null;
}

/** A tool that keeps an agent inside its team (`team_connection_outside`). */
export type TeamConnectionTool = {
  id: string;
  name: string;
  connector_name?: string | null;
};

/**
 * The tools a `team_connection_outside` refusal names: owner-mode tools on
 * a team's account, which run only for the team's members in the app.
 *
 * Args:
 *   data: The response's JSON.
 *
 * Returns:
 *   The tools (possibly none), or null for any other body.
 */
export function teamConnectionOutsideTools(
  data: unknown,
): TeamConnectionTool[] | null {
  if (connectionErrorCode(data) !== 'team_connection_outside') return null;
  const tools = asBody(data)?.tools;
  if (!Array.isArray(tools)) return [];
  return tools.flatMap((tool) => {
    const row = asBody(tool);
    if (!row || typeof row.id !== 'string' || typeof row.name !== 'string')
      return [];
    return [
      {
        id: row.id,
        name: row.name,
        connector_name:
          typeof row.connector_name === 'string' ? row.connector_name : null,
      },
    ];
  });
}

/**
 * A `connection_paused` refusal's details: why the team's account is paused
 * and which connection (the upload and sources routes name it).
 *
 * Args:
 *   data: The response's JSON.
 *
 * Returns:
 *   `{paused_for, connection_id}` (each null when absent), or null for any
 *   other body.
 */
export function connectionPausedRefusal(data: unknown): {
  paused_for: ConnectionPausedFor | null;
  connection_id: string | null;
} | null {
  if (connectionErrorCode(data) !== 'connection_paused') return null;
  const body = asBody(data) as Body;
  const paused = asBody(body.paused_for);
  return {
    paused_for:
      paused && typeof paused.reason === 'string'
        ? (paused as ConnectionPausedFor)
        : null,
    connection_id:
      typeof body.connection_id === 'string' ? body.connection_id : null,
  };
}

// A bare code (`workspace_not_found`) is not a sentence to show.
const isCode = (text: string) => /^[a-z0-9_]+$/.test(text);

/**
 * What to say about a refused connection, connector source or team tool
 * call: the app's words for a team connection code, else the server's own
 * sentence (`message`, then `error`), else `fallback`. A server error's text
 * (5xx) is never shown.
 *
 * Args:
 *   t: The translate function.
 *   data: The response's JSON, if it parsed.
 *   options.status: The response's HTTP status.
 *   options.fallback: The generic line; empty when left out.
 *
 * Returns:
 *   The message.
 */
export function connectionErrorMessage(
  t: TFunction,
  data: unknown,
  { status, fallback = '' }: { status?: number; fallback?: string } = {},
): string {
  const code = connectionErrorCode(data);
  if (code === 'team_connection_outside') {
    const names = (teamConnectionOutsideTools(data) ?? []).map(
      (tool) => tool.name,
    );
    if (names.length)
      return t(`${TEAM_ERRORS}.teamConnectionOutsideNamed`, {
        tools: names.join(', '),
        interpolation: { escapeValue: false },
      });
  }
  if (code) return t(CONNECTION_ERROR_KEYS[code]);
  if (status !== undefined && status >= 500) return fallback;
  const body = asBody(data);
  const text = [body?.message, body?.error].find(
    (value): value is string =>
      typeof value === 'string' && !!value.trim() && !isCode(value),
  );
  return text ?? fallback;
}
