import apiClient from '../client';
import endpoints from '../endpoints';

const qs = (params: Record<string, string | number | undefined>): string => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') search.append(key, String(value));
  });
  const str = search.toString();
  return str ? `?${str}` : '';
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
  getAudit: (
    params: {
      page?: number;
      page_size?: number;
      event?: string;
      user_id?: string;
    },
    token: string | null,
  ): Promise<any> =>
    apiClient.get(`${endpoints.ADMIN.AUDIT}${qs(params)}`, token),
  getDeviceAudit: (
    params: { page?: number; page_size?: number; decision?: string },
    token: string | null,
  ): Promise<any> =>
    apiClient.get(`${endpoints.ADMIN.DEVICE_AUDIT}${qs(params)}`, token),
};

export default adminService;
