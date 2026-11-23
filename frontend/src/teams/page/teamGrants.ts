import type { ResourceType, TeamGrant } from '../../api/services/teamsService';

/**
 * All of one team's grants on one resource: the whole-team grant (if any)
 * and the per-member grants, shown as a single row.
 */
export type SharedResource = {
  key: string;
  type: ResourceType;
  id: string;
  grants: TeamGrant[];
  teamGrant: TeamGrant | null;
  memberGrants: TeamGrant[];
};

export const resourceKey = (
  g: Pick<TeamGrant, 'resource_type' | 'resource_id'>,
): string => `${g.resource_type}:${g.resource_id}`;

export const grantKey = (g: TeamGrant): string =>
  `${resourceKey(g)}:${g.target_user_id ?? ''}`;

/**
 * Whether a grants row is another team's item shared with this team, not a
 * member's personal item.
 */
export const isFromTeam = (g: TeamGrant): boolean => g.origin === 'team_shared';

/**
 * Groups grants by resource, keeping the server's order of first sighting.
 *
 * Args:
 *   grants: The team's grants.
 *
 * Returns:
 *   One entry per resource.
 */
export function groupGrants(grants: TeamGrant[]): SharedResource[] {
  const byKey = new Map<string, SharedResource>();
  grants.forEach((g) => {
    const key = resourceKey(g);
    let entry = byKey.get(key);
    if (!entry) {
      entry = {
        key,
        type: g.resource_type,
        id: g.resource_id,
        grants: [],
        teamGrant: null,
        memberGrants: [],
      };
      byKey.set(key, entry);
    }
    entry.grants.push(g);
    if (g.target_user_id) entry.memberGrants.push(g);
    else entry.teamGrant = g;
  });
  return Array.from(byKey.values());
}

/**
 * The personal items one person shares with the team.
 *
 * Args:
 *   grants: The team's grants.
 *   userId: The person.
 *
 * Returns:
 *   One entry per item the person owns, however many grants it has.
 */
export function sharedBy(
  grants: TeamGrant[],
  userId: string,
): SharedResource[] {
  return groupGrants(
    grants.filter((g) => !isFromTeam(g) && g.owner_id === userId),
  );
}

// Member subs (OIDC subs) can be long; truncate the middle for readability
// while keeping the ends identifiable when no name is available.
export const truncateSub = (sub: string): string =>
  sub.length > 24 ? `${sub.slice(0, 12)}…${sub.slice(-8)}` : sub;

/** The item's sharing is on hold because its owner left the team. */
export const isPaused = (r: SharedResource): boolean =>
  r.grants.some((g) => g.paused_reason === 'owner_left');

/** A grant's item name, or its shortened id when the server sent none. */
export const grantResourceName = (g: TeamGrant): string =>
  g.resource_name || truncateSub(g.resource_id);

/** First character of a label, uppercased, for initial avatars. */
export const initialOf = (label: string): string => {
  const trimmed = label.trim();
  return trimmed ? trimmed[0].toUpperCase() : '?';
};
