/**
 * How an item reached the current workspace's list: `own` (the caller's, in
 * Personal), `team` (the team's, in a team), `shared` (someone shared it
 * with the caller; Personal only) or `team_shared` (another team shared it
 * with this team; a team only, see `shared_from`). `link` is only ever an
 * agent the caller reached by its public link alone (shared-agent and pinned
 * lists).
 */
export type ItemOrigin = 'own' | 'team' | 'shared' | 'team_shared' | 'link';

/** The team a `team_shared` item comes from; `name` null when unknown. */
export type SharedFrom = { team_id: string; name: string | null };

/** The workspace fields every item payload carries. */
export type WorkspaceItemFields = {
  origin?: ItemOrigin | null;
  workspace?: { kind: 'personal' | 'team'; team_id?: string | null } | null;
  created_by?: { user_id?: string | null; label?: string | null } | null;
  /** `team_shared` items: the team that owns and shared it. */
  shared_from?: SharedFrom | null;
};

/**
 * Splits a list by `origin`, never by `ownership` or `type`. A row without
 * one (an API older than this frontend) counts as the caller's own.
 *
 * Args:
 *   rows: Items from one workspace's list.
 *
 * Returns:
 *   `own`, `team`, `shared` and `teamShared` rows, each in the list's
 *   order.
 */
export function splitByOrigin<T extends { origin?: ItemOrigin | null }>(
  rows: T[],
): { own: T[]; team: T[]; shared: T[]; teamShared: T[] } {
  const own: T[] = [];
  const team: T[] = [];
  const shared: T[] = [];
  const teamShared: T[] = [];
  rows.forEach((row) => {
    if (row.origin === 'team') team.push(row);
    else if (row.origin === 'shared') shared.push(row);
    else if (row.origin === 'team_shared') teamShared.push(row);
    else own.push(row);
  });
  return { own, team, shared, teamShared };
}
