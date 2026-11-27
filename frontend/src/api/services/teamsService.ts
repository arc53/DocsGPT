import type { TFunction } from 'i18next';

import { connectionErrorMessage } from '../../connectors/connectionErrors';
import type { OutsideAccess, PersonRef } from '../../payer/types';
import type { ItemOrigin } from '../../workspace/itemOrigin';
import apiClient from '../client';
import { ApiError, apiErrorFrom } from './apiError';
import endpoints from '../endpoints';

/** A person's role in a team: one role on everything the team owns. */
export type TeamRole = 'owner' | 'admin' | 'editor' | 'viewer';
/** The roles a member can be given; the owner changes only by a transfer. */
export type AssignableTeamRole = Exclude<TeamRole, 'owner'>;
/** The two role names older servers send (`role` on members, `member_role` on teams). */
export type LegacyTeamRole = 'team_admin' | 'team_member';
export type AccessLevel = 'viewer' | 'editor';
export type ResourceType = 'agent' | 'source' | 'prompt' | 'tool';

export type TeamMember = {
  user_id: string;
  // Resolved on the server from the user's profile; may be null when the user
  // has never signed in or has no email on record.
  email?: string | null;
  /** The old role name, kept for older clients. */
  role: LegacyTeamRole;
  /** The role (`owner` for the team's owner); absent on older servers. */
  team_role?: TeamRole;
  source?: string;
  granted_by?: string | null;
  granted_at?: string | null;
  /**
   * What the member pays for on the team's agents: running schedules they
   * set, agents whose outside access they pay for, and the team's accounts
   * they connected (whose syncs they pay for; absent on older servers).
   * Sent to the team's owner and admins only.
   */
  pays_for?: {
    schedules: number;
    outside_access: number;
    connections?: number;
  };
  /**
   * How many of the team's custom models the member added; their keys stay
   * in use when the member leaves. Sent to the team's owner and admins only.
   */
  custom_models?: number;
};

const TEAM_ROLES: ReadonlySet<string> = new Set([
  'owner',
  'admin',
  'editor',
  'viewer',
]);

const isTeamRole = (value: unknown): value is TeamRole =>
  typeof value === 'string' && TEAM_ROLES.has(value);

/** An old role name read as a role: an admin stays one, a member reads as Viewer. */
const fromLegacy = (value: unknown): TeamRole | null =>
  value === 'team_admin' ? 'admin' : value === 'team_member' ? 'viewer' : null;

/**
 * A member's role, from `team_role`, else from the old `role` name.
 *
 * Args:
 *   member: A member row.
 *
 * Returns:
 *   The role; Viewer when neither field says.
 */
export function memberTeamRole(member: {
  team_role?: unknown;
  role?: unknown;
}): TeamRole {
  if (isTeamRole(member.team_role)) return member.team_role;
  return fromLegacy(member.role) ?? 'viewer';
}

/**
 * The caller's role in a team row, from `role`, else from `member_role`.
 *
 * Args:
 *   team: A team row (or the grants answer, which carries the same fields).
 *
 * Returns:
 *   The role; Viewer when neither field says.
 */
export function teamRoleOf(team: {
  role?: unknown;
  member_role?: unknown;
}): TeamRole {
  if (isTeamRole(team.role)) return team.role;
  return fromLegacy(team.member_role) ?? 'viewer';
}

/** Whether a role may manage members, edit the team and see its settings. */
export const canManageTeam = (role: TeamRole | null | undefined): boolean =>
  role === 'owner' || role === 'admin';

/**
 * Who may take a team's items outside it: share them with another team, and
 * turn on an agent's API key, widget, public link or webhook. `admins` (the
 * default) is the Admins and the Owner, `editors` adds Editors, `locked` is
 * nobody, and pauses what is already outside.
 */
export type OutsidePolicy = 'admins' | 'editors' | 'locked';

/** The policies in the order the team's setting lists them. */
export const OUTSIDE_POLICIES: readonly OutsidePolicy[] = [
  'admins',
  'editors',
  'locked',
];

/** Whether a value read from the server is a known policy. */
export const isOutsidePolicy = (value: unknown): value is OutsidePolicy =>
  OUTSIDE_POLICIES.includes(value as OutsidePolicy);

/** The policy fields on a team row, the team detail and `/api/workspaces` rows. */
export type OutsidePolicyFields = {
  outside_policy?: OutsidePolicy;
  /** The caller may change it: the Owner, or an Admin while it isn't locked. */
  can_set_outside_policy?: boolean;
};

/** `PUT /api/teams/<id>/outside_policy`; `changed` is false on a repeat. */
export type OutsidePolicyResult = {
  success: boolean;
  changed: boolean;
  outside_policy: OutsidePolicy;
  can_set_outside_policy: boolean;
};

/** A team a payload names; `name` is null when the reader may not see it. */
export type TeamRef = { team_id: string; name: string | null };

/** Why a share with another team gives no access right now. */
export type TeamSharePausedReason = 'team_locked';

/**
 * One of the owning team's items shared with another team (`GET
 * /api/teams/<id>/outside` and a team item's `outside_shares`). `team_id` and
 * `name` are the receiving team's.
 */
export type OutsideShare = {
  id: string;
  resource_type: ResourceType;
  resource_id: string;
  resource_name: string | null;
  team_id: string;
  name: string | null;
  shared_by: PersonRef | null;
  created_at?: string | null;
  /** The reader may stop it: whoever may take items outside, and Admins and the Owner always. */
  can_revoke: boolean;
  /** The receiving team's agents that use it; null for an agent or when it can't be read. */
  used_by_count: number | null;
  paused_reason: TeamSharePausedReason | null;
};

/** A team's agent with an API key, public link or webhook on (read-only on the team page). */
export type PublishedAgent = {
  agent_id: string;
  name: string | null;
  outside_access: OutsideAccess;
};

/** `GET /api/teams/<id>/outside`: what the team takes outside; every member reads it. */
export type TeamOutside = {
  success?: boolean;
  outside_policy: OutsidePolicy;
  can_set_outside_policy: boolean;
  shares: OutsideShare[];
  published: PublishedAgent[];
};

/** The row a share of a team item with another team writes (`POST .../grants`). */
export type TeamItemShare = {
  id: string;
  owner_team_id: string;
  /** The receiving team. */
  team_id: string;
  resource_type: ResourceType;
  resource_id: string;
  shared_by: string;
  created_at?: string | null;
  /** False when that team had it already (nothing was written). */
  created: boolean;
};

/**
 * Which warning a team item's share dialog shows: a tool runs on the owning
 * team's stored account (`tool_stored`) or on each person's own
 * (`tool_member`).
 */
export type ShareWarningKind =
  'agent' | 'source' | 'tool_stored' | 'tool_member' | 'prompt';

/** One team item an agent uses; `name` is null when the reader can't reach it. */
export type TeamItemRef = {
  /** `"<type>:<id>"`. */
  key: string;
  type: 'source' | 'tool' | 'prompt' | 'folder';
  id: string;
  name: string | null;
};

/** The items of one team a personal agent uses (`uses_team_items`). */
export type UsesTeamItems = TeamRef & { items: TeamItemRef[] };

// A single resource-sharing grant as returned by listResourceShares.
// `target_user_id` is null/undefined for a whole-team grant, or a member's
// OIDC sub for a member-specific grant.
export type ResourceShare = {
  team_id: string;
  team_name?: string;
  team_slug?: string;
  access_level: AccessLevel;
  target_user_id?: string | null;
  created_at?: string | null;
};

// A grant row from GET /api/teams/<id>/grants. The server resolves names and
// labels, plus the caller's own access to the resource (`caller`).
export type TeamGrant = {
  /** Set on an item another team shares with this one. */
  id?: string;
  resource_type: ResourceType;
  resource_id: string;
  access_level: AccessLevel;
  target_user_id?: string | null;
  resource_name?: string | null;
  owner_id?: string | null;
  owner_label?: string | null;
  target_user_label?: string | null;
  created_at?: string | null;
  granted_by?: string | null;
  granted_by_label?: string | null;
  /**
   * Why the grant is on hold: `owner_left` while its owner is out of the
   * team (it works again if they're added back), `team_locked` while the
   * team that shares it is locked. Null when it works.
   */
  paused_reason?: 'owner_left' | TeamSharePausedReason | null;
  caller?: {
    access: 'owner' | 'editor' | 'viewer';
    allowed_actions: string[];
  } | null;
  /** `personal_shared`: a member's item; `team_shared`: another team's item shared with this one. */
  origin?: 'personal_shared' | 'team_shared';
  /** `team_shared` rows: the team it comes from. */
  shared_from?: TeamRef | null;
  /** `team_shared` rows: the reader may remove it from this team (its Admins and Owner). */
  can_revoke?: boolean;
  /** `team_shared` rows: this team's agents that stop using it when it goes; null for an agent. */
  used_by?: { id: string; name: string | null }[] | null;
};

/**
 * `GET /api/resource_shares`. A person's item lists its `shares`, and a
 * personal agent the teams' items it uses (`uses_team_items`). A team's item
 * has no per-person shares: it names its `workspace` and size, an agent's
 * `outside_access`, and for the owning team's members its shares with other
 * teams (`outside_shares`), where it may go next (`share_targets`, empty
 * without `share_outside`) and the dialog's `warning_kind`. A team that
 * received it reads only its `workspace` and `shared_from`.
 */
export type ResourceSharesResponse = {
  success?: boolean;
  shares: ResourceShare[];
  uses_team_items?: UsesTeamItems[];
  workspace?: { kind: 'team'; team_id: string; name?: string | null };
  members_count?: number;
  access?: string | null;
  allowed_actions?: string[];
  team_role?: TeamRole | null;
  origin?: ItemOrigin | null;
  shared_from?: TeamRef | null;
  outside_access?: OutsideAccess | null;
  outside_policy?: OutsidePolicy;
  outside_shares?: OutsideShare[];
  share_targets?: TeamRef[];
  warning_kind?: ShareWarningKind;
  /**
   * The owning team's custom models the agent runs on (its workflow's agent
   * nodes too); people the team shares it with run on them. Empty for
   * anything but an agent.
   */
  team_models?: { id: string; name: string }[];
};

// One owner switch on a resource (`resource_share_settings`).
export type ResourceSetting = { key: string; value: boolean; default: boolean };

export type ResourceSettingsResponse = {
  success: boolean;
  resource_type: ResourceType;
  resource_id: string;
  settings: ResourceSetting[];
  access?: 'owner' | 'editor' | 'viewer' | null;
  allowed_actions?: string[];
};

/**
 * A non-2xx teams API response; `message` is the server's own message,
 * `code` its stable `error` code when it sent one, `body` the whole answer
 * (a team that still owns items names them in `counts`).
 */
export class TeamsApiError extends ApiError {
  constructor(...args: ConstructorParameters<typeof ApiError>) {
    super(...args);
    this.name = 'TeamsApiError';
  }
}

/** The app's own words for each refusal code a teams call can answer. */
export const TEAM_ERROR_KEYS: Readonly<Record<string, string>> = {
  borrowed_resource: 'settings.teams.errors.borrowedResource',
  invalid_policy: 'settings.teams.errors.invalidPolicy',
  last_admin: 'settings.teams.errors.lastAdmin',
  owner_must_transfer: 'settings.teams.errors.ownerMustTransfer',
  owner_protected: 'settings.teams.errors.ownerProtected',
  policy_owner_only: 'settings.teams.errors.policyOwnerOnly',
  team_item_shared_outside: 'settings.teams.errors.teamItemSharedOutside',
  team_locked: 'settings.teams.errors.teamLocked',
  team_not_empty: 'settings.teams.errors.teamNotEmpty',
  team_share_not_member: 'settings.teams.errors.shareNotMember',
  team_share_same_team: 'settings.teams.errors.shareSameTeam',
  team_share_viewer_only: 'settings.teams.errors.shareViewerOnly',
  team_share_whole_team_only: 'settings.teams.errors.shareWholeTeamOnly',
  uses_team_items: 'settings.teams.errors.usesTeamItems',
  workspace_role_required: 'settings.teams.errors.roleRequired',
};

/**
 * What to say about a failed teams call: the app's words for a known
 * refusal code, else the server's message, else `fallback`. A refusal over
 * tools on a team's account (`team_connection_outside`) names the tools.
 *
 * Args:
 *   t: The translate function.
 *   error: What the call threw (a `TeamsApiError`, or its serialized form
 *     from a thunk's `unwrap`).
 *   fallback: The text when the error says nothing usable (a network
 *     failure).
 *
 * Returns:
 *   The message to show.
 */
export function teamErrorMessage(
  t: TFunction | ((key: string) => string),
  error: unknown,
  fallback: string,
): string {
  const e = error as { name?: unknown; message?: unknown; code?: unknown };
  if (typeof e !== 'object' || e === null || e.name !== 'TeamsApiError')
    return fallback;
  if (e.code === 'team_connection_outside') {
    const body = (error as { body?: unknown }).body;
    return connectionErrorMessage(
      t as TFunction,
      body && typeof body === 'object' ? body : { error: e.code },
      { fallback },
    );
  }
  const key = typeof e.code === 'string' ? TEAM_ERROR_KEYS[e.code] : undefined;
  if (key) return (t as (key: string) => string)(key);
  return typeof e.message === 'string' && e.message ? e.message : fallback;
}

/** What a refusal over an agent's team items names (see `teamItemsRefusal`). */
export type TeamItemsRefusal = {
  /** The items the share or save would take to people who can't use them. */
  usesTeamItems: UsesTeamItems[];
  /** A team the agent could move to and be shared from, when there is one. */
  moveTo: TeamRef | null;
  /** `team_item_shared_outside`: the teams the agent is shared with. */
  sharedWith: TeamRef[];
};

const TEAM_ITEMS_CODES: ReadonlySet<string> = new Set([
  'uses_team_items',
  'team_item_shared_outside',
]);

/**
 * The details of a `uses_team_items` refusal (sharing a personal agent that
 * uses a team's items with people who can't use them) or a
 * `team_item_shared_outside` one (adding such an item to an agent that is
 * shared with them).
 *
 * Args:
 *   error: A `TeamsApiError`, or a refusal's body (`{error, ...}`).
 *
 * Returns:
 *   The items, the move offer and the teams; null for any other error.
 */
export function teamItemsRefusal(error: unknown): TeamItemsRefusal | null {
  if (!error || typeof error !== 'object') return null;
  const e = error as { code?: unknown; error?: unknown; body?: unknown };
  const code = typeof e.code === 'string' ? e.code : e.error;
  if (typeof code !== 'string' || !TEAM_ITEMS_CODES.has(code)) return null;
  const body = (
    e.body && typeof e.body === 'object' ? e.body : error
  ) as Record<string, unknown>;
  const list = <T>(value: unknown): T[] =>
    Array.isArray(value) ? (value as T[]) : [];
  const moveTo = body.move_to as TeamRef | null | undefined;
  return {
    usesTeamItems: list<UsesTeamItems>(body.uses_team_items),
    moveTo: moveTo && typeof moveTo === 'object' ? moveTo : null,
    sharedWith: list<TeamRef>(body.shared_with),
  };
}

// apiClient resolves to the raw fetch Response (the app convention); services
// consumed by slices/components parse the JSON here so callers get plain data.
// A non-2xx status rejects with the server's message, so callers never mistake
// a 403/404 for success.
const json = async (response: Response | unknown) => {
  const r = response as Response;
  if (!r || !('json' in r) || typeof r.json !== 'function') return r as unknown;
  if (typeof r.ok === 'boolean' && !r.ok) {
    throw await apiErrorFrom(r, TeamsApiError, { codeAsMessage: true });
  }
  return r.json();
};

const teamsService = {
  list: async (token: string | null): Promise<any> =>
    json(await apiClient.get(endpoints.USER.TEAMS, token)),
  create: async (
    data: { name: string; description?: string },
    token: string | null,
  ): Promise<any> =>
    json(await apiClient.post(endpoints.USER.TEAMS, data, token)),
  update: async (
    id: string,
    data: { name?: string; description?: string },
    token: string | null,
  ): Promise<any> =>
    json(await apiClient.put(endpoints.USER.TEAM(id), data, token)),
  remove: async (id: string, token: string | null): Promise<any> =>
    json(await apiClient.delete(endpoints.USER.TEAM(id), token)),

  listMembers: async (
    id: string,
    token: string | null,
    opts?: { q?: string; page?: number; pageSize?: number },
  ): Promise<any> => {
    const params = new URLSearchParams();
    if (opts?.q) params.set('q', opts.q);
    if (opts?.pageSize) {
      params.set('page', String(opts.page ?? 1));
      params.set('page_size', String(opts.pageSize));
    }
    const query = params.toString();
    return json(
      await apiClient.get(
        `${endpoints.USER.TEAM_MEMBERS(id)}${query ? `?${query}` : ''}`,
        token,
      ),
    );
  },
  addMember: async (
    id: string,
    // Pass either an email (resolved to a sub server-side) or a raw user_id.
    data: { email?: string; user_id?: string; role: AssignableTeamRole },
    token: string | null,
  ): Promise<any> =>
    json(await apiClient.post(endpoints.USER.TEAM_MEMBERS(id), data, token)),
  setMemberRole: async (
    id: string,
    memberId: string,
    role: AssignableTeamRole,
    token: string | null,
  ): Promise<any> =>
    json(
      await apiClient.put(
        endpoints.USER.TEAM_MEMBER(id, memberId),
        { role },
        token,
      ),
    ),
  removeMember: async (
    id: string,
    memberId: string,
    token: string | null,
  ): Promise<any> =>
    json(
      await apiClient.delete(endpoints.USER.TEAM_MEMBER(id, memberId), token),
    ),
  transferOwner: async (
    id: string,
    userId: string,
    token: string | null,
  ): Promise<any> =>
    json(
      await apiClient.post(
        endpoints.USER.TEAM_TRANSFER_OWNER(id),
        { user_id: userId },
        token,
      ),
    ),

  listGrants: async (
    id: string,
    resourceType: ResourceType | undefined,
    token: string | null,
  ): Promise<any> =>
    json(
      await apiClient.get(
        `${endpoints.USER.TEAM_GRANTS(id)}${
          resourceType ? `?resource_type=${resourceType}` : ''
        }`,
        token,
      ),
    ),
  share: async (
    id: string,
    data: {
      resource_type: ResourceType;
      resource_id: string;
      access_level?: AccessLevel;
      // Omitted/empty = whole team; a member's OIDC sub = that one member.
      target_user_id?: string | null;
    },
    token: string | null,
  ): Promise<any> =>
    json(await apiClient.post(endpoints.USER.TEAM_GRANTS(id), data, token)),
  unshare: async (
    id: string,
    data: {
      resource_type: ResourceType;
      resource_id: string;
      // Omitted/empty targets the whole-team grant.
      target_user_id?: string | null;
    },
    token: string | null,
  ): Promise<any> => {
    // Identifiers go on the query string — some proxies strip DELETE bodies.
    let query = `${endpoints.USER.TEAM_GRANTS(id)}?resource_type=${
      data.resource_type
    }&resource_id=${encodeURIComponent(data.resource_id)}`;
    if (data.target_user_id) {
      query += `&target_user_id=${encodeURIComponent(data.target_user_id)}`;
    }
    return json(await apiClient.delete(query, token, data));
  },

  /**
   * Shares a team's item with the whole of another team, at Viewer level.
   * The caller needs `share_outside` on the item and a role in `teamId`.
   *
   * Args:
   *   teamId: The receiving team.
   *   item: The item, owned by the caller's team.
   *   token: The session token.
   *
   * Returns:
   *   `{success, share}`; `share.created` is false when the team had it.
   */
  shareTeamItem: async (
    teamId: string,
    item: { resource_type: ResourceType; resource_id: string },
    token: string | null,
  ): Promise<{ success: boolean; share: TeamItemShare }> =>
    json(
      await apiClient.post(
        endpoints.USER.TEAM_GRANTS(teamId),
        { ...item, access_level: 'viewer' },
        token,
      ),
    ) as Promise<{ success: boolean; share: TeamItemShare }>,
  /**
   * Stops sharing a team's item with `teamId`, from the owning team or from
   * the receiving one (its Admins and Owner).
   *
   * Returns:
   *   `{success, side}`: `success` false when there was no such share.
   */
  unshareTeamItem: async (
    teamId: string,
    item: { resource_type: ResourceType; resource_id: string },
    token: string | null,
  ): Promise<{ success: boolean; side: 'owner' | 'receiver' }> =>
    teamsService.unshare(teamId, item, token) as Promise<{
      success: boolean;
      side: 'owner' | 'receiver';
    }>,

  /** Changes who may take the team's items outside; not through an access token. */
  setOutsidePolicy: async (
    id: string,
    policy: OutsidePolicy,
    token: string | null,
  ): Promise<OutsidePolicyResult> =>
    json(
      await apiClient.put(
        endpoints.USER.TEAM_OUTSIDE_POLICY(id),
        { policy },
        token,
      ),
    ) as Promise<OutsidePolicyResult>,
  /** The team's items shared with other teams, and its published agents. */
  getOutside: async (id: string, token: string | null): Promise<TeamOutside> =>
    json(
      await apiClient.get(endpoints.USER.TEAM_OUTSIDE(id), token),
    ) as Promise<TeamOutside>,

  listResourceShares: async (
    resourceType: ResourceType,
    resourceId: string,
    token: string | null,
  ): Promise<any> =>
    json(
      await apiClient.get(
        endpoints.USER.RESOURCE_SHARES(resourceType, resourceId),
        token,
      ),
    ),

  getResourceSettings: async (
    resourceType: ResourceType,
    resourceId: string,
    token: string | null,
  ): Promise<ResourceSettingsResponse> =>
    json(
      await apiClient.get(
        `${endpoints.USER.RESOURCE_SETTINGS}?resource_type=${resourceType}&resource_id=${encodeURIComponent(
          resourceId,
        )}`,
        token,
      ),
    ) as Promise<ResourceSettingsResponse>,
  updateResourceSettings: async (
    resourceType: ResourceType,
    resourceId: string,
    settings: Record<string, boolean>,
    token: string | null,
  ): Promise<ResourceSettingsResponse> =>
    json(
      await apiClient.put(
        endpoints.USER.RESOURCE_SETTINGS,
        {
          resource_type: resourceType,
          resource_id: resourceId,
          settings,
        },
        token,
      ),
    ) as Promise<ResourceSettingsResponse>,

  listAll: async (token: string | null): Promise<any> =>
    json(await apiClient.get(endpoints.USER.ALL_TEAMS, token)),
  /** Admin team search: by name or slug, optionally only teams with no allowance. */
  searchAdminTeams: async (
    token: string | null,
    opts: { q: string; withoutQuota?: boolean; limit?: number },
  ): Promise<any> => {
    const params = new URLSearchParams({ q: opts.q });
    if (opts.withoutQuota) params.set('without_quota', '1');
    if (opts.limit) params.set('limit', String(opts.limit));
    return json(
      await apiClient.get(`${endpoints.USER.ALL_TEAMS}?${params}`, token),
    );
  },
};

export default teamsService;
