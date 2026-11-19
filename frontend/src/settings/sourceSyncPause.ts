import type { TFunction } from 'i18next';
import { useSelector } from 'react-redux';

import { selectCurrentTeamConnectors } from '../connectors/connectorsSlice';
import { connectionCan } from '../connectors/teamConnections';
import type { Connection } from '../connectors/types';
import type { Doc } from '../models/misc';
import { formatPayerDate, pauseReasonText } from '../payer/pauseReason';
import {
  PAUSE_REASONS,
  type PauseReason,
  type PausedFor,
  type SourceSyncPaused,
} from '../payer/types';
import {
  roleAtLeast,
  selectCurrentWorkspace,
  selectWorkspaceRoleOrNull,
  type WorkspaceState,
} from '../workspace/workspaceSlice';
import { selectInTeam } from './workspaceAccess';

const noEscape = { interpolation: { escapeValue: false } };

/**
 * Why a source doesn't sync now, from its `sync_paused`. A team account's
 * pause names whoever connected it: an account pause ("Syncing paused: Lena
 * left Operations.") stops every sync of it, an allowance pause ("Scheduled
 * sync paused: Lena is out of allowance until 1 Dec.") only the schedule,
 * since a person's Sync now is theirs to pay. A team source nobody can pay
 * for reads as before; a reason the app doesn't know still reads as paused.
 *
 * Args:
 *   t: The translate function.
 *   paused: The source's `sync_paused`; null or undefined while it syncs.
 *   options.connection: The team connection it syncs through, when listed.
 *   options.teamName: The current team's name.
 *   options.me: The reader's user id, to say "you".
 *   options.language: The UI language, for dates.
 *
 * Returns:
 *   The line, or an empty string while it syncs.
 */
export function sourceSyncPausedText(
  t: TFunction,
  paused: SourceSyncPaused | null | undefined,
  {
    connection,
    teamName,
    me,
    language,
  }: {
    connection?: Pick<Connection, 'connected_by'> | null;
    teamName?: string | null;
    me?: string | null;
    language?: string;
  } = {},
): string {
  if (!paused) return '';
  if (PAUSE_REASONS.includes(paused.reason as PauseReason)) {
    const person = connection?.connected_by;
    const reason = pauseReasonText(
      t,
      paused as PausedFor,
      person?.label || person?.user_id,
      teamName,
      { you: !!me && person?.user_id === me, language },
    );
    if (reason)
      return paused.reason === 'payer_out_of_allowance'
        ? t('settings.sources.syncPaused.scheduled', { reason, ...noEscape })
        : t('settings.sources.syncPaused.account', { reason, ...noEscape });
  }
  const kind = paused.reason === 'sync_no_payer' ? 'noPayer' : 'other';
  const date = formatPayerDate(paused.since, language);
  return date
    ? t(`settings.sources.syncPaused.${kind}Since`, { date })
    : t(`settings.sources.syncPaused.${kind}`);
}

/** The current team's name; null in Personal or a store without workspaces. */
export const useCurrentTeamName = (): string | null =>
  useSelector((state: { workspace?: WorkspaceState }) => {
    if (!state.workspace) return null;
    const row = selectCurrentWorkspace({ workspace: state.workspace });
    return row.kind === 'team' ? row.name || null : null;
  });

/** The current team's connections; none in Personal. */
const NO_CONNECTIONS: Connection[] = [];
export const useTeamConnections = (): Connection[] =>
  useSelector(selectCurrentTeamConnectors)?.connections ?? NO_CONNECTIONS;

/**
 * Whether the caller may change how often a source syncs. A team's source
 * that syncs through an account connected for the team spends the allowance
 * of whoever connected it, so its schedule is the team Admins' to set (the
 * connection's `manage`, or Admin while the team's list hasn't loaded); any
 * other source follows `edit`, which the caller checks.
 *
 * Args:
 *   doc: The source.
 *
 * Returns:
 *   False only for a team connection's source the caller can't manage.
 */
export function useCanChangeSyncSchedule(doc: Doc | null | undefined): boolean {
  const inTeam = useSelector(selectInTeam);
  const role = useSelector(selectWorkspaceRoleOrNull);
  const connections = useTeamConnections();
  if (!inTeam || !doc?.connectionId) return true;
  const connection = connections.find((c) => c.id === doc.connectionId);
  return connection
    ? connectionCan(connection, 'manage')
    : roleAtLeast(role, 'admin');
}
