import apiClient from '../client';
import endpoints from '../endpoints';

export type TeamRole = 'team_admin' | 'team_member';
export type AccessLevel = 'viewer' | 'editor';
export type ResourceType = 'agent' | 'source' | 'prompt' | 'tool';

export type TeamMember = {
  user_id: string;
  // Resolved on the server from the user's profile; may be null when the user
  // has never signed in or has no email on record.
  email?: string | null;
  role: TeamRole;
  source?: string;
  granted_by?: string | null;
  granted_at?: string | null;
};

// A single resource-sharing grant as returned by listResourceShares.
// `target_user_id` is null/undefined for a whole-team grant, or a member's
// OIDC sub for a member-specific grant.
export type ResourceShare = {
  team_id: string;
  team_name?: string;
  team_slug?: string;
  access_level: AccessLevel;
  target_user_id?: string | null;
};

// apiClient resolves to the raw fetch Response (the app convention); services
// consumed by slices/components parse the JSON here so callers get plain data.
const json = async (response: Response | unknown) => {
  const r = response as Response;
  if (!r || !('json' in r) || typeof r.json !== 'function') return r as unknown;
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

  listMembers: async (id: string, token: string | null): Promise<any> =>
    json(await apiClient.get(endpoints.USER.TEAM_MEMBERS(id), token)),
  addMember: async (
    id: string,
    // Pass either an email (resolved to a sub server-side) or a raw user_id.
    data: { email?: string; user_id?: string; role: TeamRole },
    token: string | null,
  ): Promise<any> =>
    json(await apiClient.post(endpoints.USER.TEAM_MEMBERS(id), data, token)),
  setMemberRole: async (
    id: string,
    memberId: string,
    role: TeamRole,
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

  listAll: async (token: string | null): Promise<any> =>
    json(await apiClient.get(endpoints.USER.ALL_TEAMS, token)),
};

export default teamsService;
