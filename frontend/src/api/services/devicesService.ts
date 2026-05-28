import apiClient from '../client';
import endpoints from '../endpoints';

export type ApprovalMode = 'ask' | 'full';

export interface Device {
  id: string;
  name: string;
  hostname?: string | null;
  os?: string | null;
  arch?: string | null;
  cli_version?: string | null;
  approval_mode: ApprovalMode;
  description?: string | null;
  status: 'active' | 'revoked';
  paired_at?: string | null;
  last_seen_at?: string | null;
  revoked_at?: string | null;
}

export interface PairingResponse {
  device_code: string;
  user_code: string;
  verification_uri?: string;
  expires_in: number;
  interval: number;
}

export interface PairingStatus {
  device_code: string;
  user_code?: string;
  status: 'pending' | 'redeemed' | 'cancelled' | 'expired';
  device_id?: string | null;
  device_name?: string | null;
}

export interface AuditEntry {
  id: number;
  device_id: string;
  invocation_id: string;
  command: string;
  working_dir?: string | null;
  approval_mode: string;
  decision: string;
  decision_reason?: string | null;
  exit_code?: number | null;
  duration_ms?: number | null;
  issued_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
}

const json = async (response: Response | unknown) => {
  const r = response as Response;
  if (!('json' in r) || typeof r.json !== 'function') return r as unknown;
  return r.json();
};

const devicesService = {
  list: async (token: string | null): Promise<{ devices: Device[] }> => {
    const r = await apiClient.get(endpoints.USER.DEVICES, token);
    return (await json(r)) as { devices: Device[] };
  },

  get: async (id: string, token: string | null): Promise<Device> => {
    const r = await apiClient.get(endpoints.USER.DEVICE(id), token);
    return (await json(r)) as Device;
  },

  update: async (
    id: string,
    payload: Partial<Pick<Device, 'name' | 'description' | 'approval_mode'>>,
    token: string | null,
  ): Promise<Device> => {
    const r = await apiClient.patch(endpoints.USER.DEVICE(id), payload, token);
    return (await json(r)) as Device;
  },

  revoke: async (
    id: string,
    token: string | null,
  ): Promise<{ success: boolean }> => {
    const r = await apiClient.delete(endpoints.USER.DEVICE(id), token);
    return (await json(r)) as { success: boolean };
  },

  startPairing: async (
    token: string | null,
    body?: {
      name?: string;
      description?: string;
      approval_mode?: ApprovalMode;
    },
  ): Promise<PairingResponse> => {
    const r = await apiClient.post(
      endpoints.USER.DEVICE_PAIRINGS,
      body ?? {},
      token,
    );
    return (await json(r)) as PairingResponse;
  },

  pollPairing: async (
    deviceCode: string,
    token: string | null,
  ): Promise<PairingStatus> => {
    const r = await apiClient.get(
      endpoints.USER.DEVICE_PAIRING(deviceCode),
      token,
    );
    return (await json(r)) as PairingStatus;
  },

  cancelPairing: async (
    deviceCode: string,
    token: string | null,
  ): Promise<{ success: boolean }> => {
    const r = await apiClient.delete(
      endpoints.USER.DEVICE_PAIRING(deviceCode),
      token,
    );
    return (await json(r)) as { success: boolean };
  },

  addAutoApprovePattern: async (
    id: string,
    command: string,
    token: string | null,
  ): Promise<{ pattern: string }> => {
    const r = await apiClient.post(
      endpoints.USER.DEVICE_AUTO_APPROVE(id),
      { command },
      token,
    );
    return (await json(r)) as { pattern: string };
  },

  listAutoApprovePatterns: async (
    id: string,
    token: string | null,
  ): Promise<{ patterns: string[] }> => {
    const r = await apiClient.get(
      endpoints.USER.DEVICE_AUTO_APPROVE(id),
      token,
    );
    return (await json(r)) as { patterns: string[] };
  },

  removeAutoApprovePattern: async (
    id: string,
    pattern: string,
    token: string | null,
  ): Promise<{ success: boolean }> => {
    const r = await apiClient.delete(
      endpoints.USER.DEVICE_AUTO_APPROVE(id),
      token,
      { pattern },
    );
    return (await json(r)) as { success: boolean };
  },

  listAudit: async (
    id: string,
    token: string | null,
  ): Promise<{ entries: AuditEntry[] }> => {
    const r = await apiClient.get(endpoints.USER.DEVICE_AUDIT(id), token);
    return (await json(r)) as { entries: AuditEntry[] };
  },
};

export default devicesService;
