import type { TFunction } from 'i18next';

import { pauseReasonText } from '../payer/pauseReason';
import type { Connection, ConnectionAction } from './types';

type ConnectionLike = Pick<
  Connection,
  'owner' | 'allowed_actions' | 'can_pick' | 'connected_by' | 'paused_for'
> & { status?: string };

const noEscape = { interpolation: { escapeValue: false } };

/** Whether a team owns the connection (`owner=team` on the server). */
export const isTeamConnection = (
  connection: Pick<Connection, 'owner'> | null | undefined,
): boolean => connection?.owner === 'team';

/**
 * Whether the caller may do `action` with a connection, as the server said
 * (`allowed_actions`; `can_pick` for `pick`, which is off while the account
 * is paused). A row without those fields is the caller's own from a server
 * that predates team connections, so everything is allowed; a team row
 * without them allows nothing.
 *
 * Args:
 *   connection: The connection payload.
 *   action: `view`, `sync`, `manage` or `pick`.
 *
 * Returns:
 *   True when the caller may.
 */
export function connectionCan(
  connection: ConnectionLike | null | undefined,
  action: ConnectionAction,
): boolean {
  if (!connection) return false;
  if (action === 'pick' && typeof connection.can_pick === 'boolean')
    return connection.can_pick;
  if (Array.isArray(connection.allowed_actions))
    return connection.allowed_actions.includes(action);
  return !isTeamConnection(connection);
}

/** Whether a team's account is paused (it is not used at all meanwhile). */
export const isConnectionPaused = (
  connection: ConnectionLike | null | undefined,
): boolean => connection?.status === 'paused' || !!connection?.paused_for;

/**
 * "Connected by Lena" (or "Connected by you") for a team's account; empty
 * for a personal one or when nobody is on record.
 *
 * Args:
 *   t: The translate function.
 *   connection: The connection payload.
 *   me: The reader's user id, when known.
 *
 * Returns:
 *   The line, or an empty string.
 */
export function connectedByText(
  t: TFunction,
  connection: ConnectionLike | null | undefined,
  me?: string | null,
): string {
  const person = connection?.connected_by;
  if (!isTeamConnection(connection) || !person) return '';
  if (me && person.user_id === me)
    return t('settings.connectors.team.connectedByYou');
  return t('settings.connectors.team.connectedBy', {
    name: person.label || person.user_id,
    ...noEscape,
  });
}

/**
 * Why a team's account is paused, for its row and drawer: "Paused: Lena
 * left Operations." Just "Paused" when the reason is unknown; empty when it
 * is not paused.
 *
 * Args:
 *   t: The translate function.
 *   connection: The connection payload.
 *   options.teamName: The team's name; "the team" when left out.
 *   options.me: The reader's user id, to say "you" rather than their name.
 *   options.language: The UI language, for an allowance pause's date.
 *
 * Returns:
 *   The line, or an empty string.
 */
export function connectionPauseText(
  t: TFunction,
  connection: ConnectionLike | null | undefined,
  {
    teamName,
    me,
    language,
  }: { teamName?: string | null; me?: string | null; language?: string } = {},
): string {
  if (!isConnectionPaused(connection)) return '';
  const person = connection?.connected_by;
  const reason = pauseReasonText(
    t,
    connection?.paused_for,
    person?.label || person?.user_id,
    teamName,
    { you: !!me && person?.user_id === me, language },
  );
  if (!reason) return t('settings.connectors.team.pausedUnknown');
  return t('settings.connectors.team.paused', { reason, ...noEscape });
}
