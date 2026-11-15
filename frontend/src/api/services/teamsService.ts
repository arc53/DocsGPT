import type { TFunction } from 'i18next';

import apiClient from '../client';
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
   * team (it works again if they're added back). Null when it works.
   */
  paused_reason?: 'owner_left' | null;
  caller?: {
    access: 'owner' | 'editor' | 'viewer';
    allowed_actions: string[];
  } | null;
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
export class TeamsApiError extends Error {
  status: number;
  code?: string;
  body?: Record<string, unknown>;

  constructor(
    status: number,
    message: string,
    code?: string,
    body?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'TeamsApiError';
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

/** The app's own words for each refusal code a teams call can answer. */
export const TEAM_ERROR_KEYS: Readonly<Record<string, string>> = {
  last_admin: 'settings.teams.errors.lastAdmin',
  owner_must_transfer: 'settings.teams.errors.ownerMustTransfer',
  owner_protected: 'settings.teams.errors.ownerProtected',
  team_not_empty: 'settings.teams.errors.teamNotEmpty',
};

/**
 * What to say about a failed teams call: the app's words for a known
 * refusal code, else the server's message, else `fallback`.
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
  const key = typeof e.code === 'string' ? TEAM_ERROR_KEYS[e.code] : undefined;
  if (key) return (t as (key: string) => string)(key);
  return typeof e.message === 'string' && e.message ? e.message : fallback;
}

// apiClient resolves to the raw fetch Response (the app convention); services
// consumed by slices/components parse the JSON here so callers get plain data.
// A non-2xx status rejects with the server's message, so callers never mistake
// a 403/404 for success.
const json = async (response: Response | unknown) => {
  const r = response as Response;
  if (!r || !('json' in r) || typeof r.json !== 'function') return r as unknown;
  if (typeof r.ok === 'boolean' && !r.ok) {
    let message = `Request failed (${r.status})`;
    let code: string | undefined;
    let parsed: Record<string, unknown> | undefined;
    try {
      const body = await r.json();
      if (body && typeof body === 'object') parsed = body;
      if (body && typeof body.error === 'string' && body.error) {
        code = body.error;
      }
      if (body && typeof body.message === 'string' && body.message) {
        message = body.message;
      } else if (code) {
        message = code;
      }
    } catch {
      // Not JSON: keep the generic message.
    }
    throw new TeamsApiError(r.status, message, code, parsed);
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
  get: async (id: string, token: string | null): Promise<any> =>
    json(await apiClient.get(endpoints.USER.TEAM(id), token)),
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
