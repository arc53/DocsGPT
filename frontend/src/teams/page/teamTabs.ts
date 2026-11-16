import type { TeamRole } from '../../api/services/teamsService';

/** Where the teams list lives; a team's page is under it. */
export const TEAMS_ROOT = '/teams';

export type TeamTabKey = 'members' | 'shared' | 'usage' | 'settings';

export type TeamTab = {
  key: TeamTabKey;
  labelKey: string;
  /** Off for a tab that isn't built yet: it never shows and its path goes to Members. */
  enabled: boolean;
  /** The weakest role that sees the tab. */
  minRole: TeamRole;
};

/** The team page's tabs, in order. Members is the team's root path. */
export const TEAM_TABS: ReadonlyArray<TeamTab> = [
  {
    key: 'members',
    labelKey: 'settings.teams.tabs.members',
    enabled: true,
    minRole: 'viewer',
  },
  {
    key: 'shared',
    labelKey: 'settings.teams.tabs.shared',
    enabled: true,
    minRole: 'viewer',
  },
  // The team's usage report, for its owner and admins.
  {
    key: 'usage',
    labelKey: 'settings.teams.tabs.usage',
    enabled: true,
    minRole: 'admin',
  },
  {
    key: 'settings',
    labelKey: 'settings.teams.tabs.settings',
    enabled: true,
    minRole: 'admin',
  },
];

const RANK: Record<TeamRole, number> = {
  viewer: 0,
  editor: 1,
  admin: 2,
  owner: 3,
};

/**
 * The tabs a role sees.
 *
 * Args:
 *   role: The caller's role in the team.
 *
 * Returns:
 *   The enabled tabs whose minimum role the caller has, in order.
 */
export function visibleTeamTabs(role: TeamRole): TeamTab[] {
  return TEAM_TABS.filter(
    (tab) => tab.enabled && RANK[role] >= RANK[tab.minRole],
  );
}

/**
 * The path of a team's page, on one tab.
 *
 * Args:
 *   teamId: The team's id.
 *   tab: The tab; Members (the default) is the team's root path.
 *
 * Returns:
 *   `/teams/<id>` or `/teams/<id>/<tab>`.
 */
export function teamPath(teamId: string, tab: TeamTabKey = 'members'): string {
  const root = `${TEAMS_ROOT}/${encodeURIComponent(teamId)}`;
  return tab === 'members' ? root : `${root}/${tab}`;
}
