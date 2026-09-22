import apiClient from '../client';
import endpoints from '../endpoints';

type QueryValue = string | number | string[] | undefined;

const qs = (params: Record<string, QueryValue>): string => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === '') return;
    // Array facets repeat the key; the API accumulates repeats.
    if (Array.isArray(value)) {
      value.forEach((item) => item && search.append(key, item));
      return;
    }
    search.append(key, String(value));
  });
  const str = search.toString();
  return str ? `?${str}` : '';
};

export type ActivityFilters = {
  page?: number;
  page_size?: number;
  category?: string[];
  event?: string[];
  feed?: string[];
  actor_id?: string;
  user_id?: string;
  since?: string;
  until?: string;
  search?: string;
};

export type QuotaScope = 'instance' | 'team' | 'user';

const quotaUrl = (scope: QuotaScope, subjectId?: string | null): string => {
  if (scope === 'team') return endpoints.ADMIN.QUOTA_TEAM(subjectId ?? '');
  if (scope === 'user') return endpoints.ADMIN.QUOTA_USER(subjectId ?? '');
  return endpoints.ADMIN.QUOTA_INSTANCE;
};

const adminService = {
  getOverview: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.ADMIN.OVERVIEW, token),
  getUsers: (
    params: { page?: number; page_size?: number; user_id?: string },
    token: string | null,
  ): Promise<any> =>
    apiClient.get(`${endpoints.ADMIN.USERS}${qs(params)}`, token),
  getUser: (userId: string, token: string | null): Promise<any> =>
    apiClient.get(endpoints.ADMIN.USER(userId), token),
  grantAdmin: (userId: string, token: string | null): Promise<any> =>
    apiClient.post(endpoints.ADMIN.USER_ROLE(userId), {}, token),
  revokeAdmin: (userId: string, token: string | null): Promise<any> =>
    apiClient.delete(endpoints.ADMIN.USER_ROLE(userId), token),
  setUserActive: (
    userId: string,
    active: boolean,
    token: string | null,
  ): Promise<any> =>
    apiClient.patch(endpoints.ADMIN.USER(userId), { active }, token),
  revokeSessions: (userId: string, token: string | null): Promise<any> =>
    apiClient.post(endpoints.ADMIN.USER_REVOKE_SESSIONS(userId), {}, token),
  getAdmins: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.ADMIN.ADMINS, token),
  getUsage: (
    params: { days?: number; group_by?: string; bucket?: string },
    token: string | null,
  ): Promise<any> =>
    apiClient.get(`${endpoints.ADMIN.USAGE}${qs(params)}`, token),
  getUserUsage: (
    userId: string,
    params: { days?: number },
    token: string | null,
  ): Promise<any> =>
    apiClient.get(`${endpoints.ADMIN.USER_USAGE(userId)}${qs(params)}`, token),
  getActivity: (filters: ActivityFilters, token: string | null): Promise<any> =>
    apiClient.get(`${endpoints.ADMIN.ACTIVITY}${qs(filters)}`, token),
  getActivityEvents: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.ADMIN.ACTIVITY_EVENTS, token),
  exportActivity: (
    filters: ActivityFilters,
    format: 'csv' | 'ndjson',
    token: string | null,
  ): Promise<any> =>
    apiClient.get(
      `${endpoints.ADMIN.ACTIVITY_EXPORT}${qs({ ...filters, format })}`,
      token,
    ),
  getQuotas: (token: string | null): Promise<any> =>
    apiClient.get(endpoints.ADMIN.QUOTAS, token),
  getUserQuota: (userId: string, token: string | null): Promise<any> =>
    apiClient.get(endpoints.ADMIN.QUOTA_USER(userId), token),
  setQuota: (
    scope: QuotaScope,
    subjectId: string | null,
    policy: Record<string, unknown>,
    token: string | null,
  ): Promise<any> => apiClient.put(quotaUrl(scope, subjectId), policy, token),
  deleteQuota: (
    scope: QuotaScope,
    subjectId: string | null,
    bucket: string,
    token: string | null,
  ): Promise<any> =>
    apiClient.delete(`${quotaUrl(scope, subjectId)}${qs({ bucket })}`, token),
};

export default adminService;
