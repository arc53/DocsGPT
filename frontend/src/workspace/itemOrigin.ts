/**
 * How an item reached the current workspace's list: `own` (the caller's, in
 * Personal), `team` (the team's, in a team) or `shared` (someone shared it
 * with the caller; Personal only). `link` is only ever an agent the caller
 * reached by its public link alone (shared-agent and pinned lists), whose
 * publisher pays for its chats.
 */
export type ItemOrigin = 'own' | 'team' | 'shared' | 'link';

/** The workspace fields every item payload carries. */
export type WorkspaceItemFields = {
  origin?: ItemOrigin | null;
  workspace?: { kind: 'personal' | 'team'; team_id?: string | null } | null;
  created_by?: { user_id?: string | null; label?: string | null } | null;
};

/**
 * Splits a list by `origin`, never by `ownership` or `type`. A row without
 * one (an API older than this frontend) counts as the caller's own.
 *
 * Args:
 *   rows: Items from one workspace's list.
 *
 * Returns:
 *   `own`, `team` and `shared` rows, each in the list's order.
 */
export function splitByOrigin<T extends { origin?: ItemOrigin | null }>(
  rows: T[],
): { own: T[]; team: T[]; shared: T[] } {
  const own: T[] = [];
  const team: T[] = [];
  const shared: T[] = [];
  rows.forEach((row) => {
    if (row.origin === 'team') team.push(row);
    else if (row.origin === 'shared') shared.push(row);
    else own.push(row);
  });
  return { own, team, shared };
}
