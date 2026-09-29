import type { SourceConfig } from '../../models/misc';
import apiClient, { throttledApiClient } from '../client';
import endpoints from '../endpoints';

// apiClient resolves to the raw fetch Response; parse it here so the slice and
// components get plain data. A non-2xx body still parses (``success: false``).
const json = async (response: Response) => {
  try {
    return await response.json();
  } catch {
    return { success: false };
  }
};

export type ConnectionSetupBody = {
  create_tools?: boolean;
  /** GitHub: let agents make changes, not only read. */
  allow_writes?: boolean;
  tool_permissions?: Record<string, 'always' | 'ask' | 'off'>;
  sync?: {
    items: Record<string, unknown>;
    frequency?: string;
    name?: string;
    /** The source's retrieval settings, as an upload sends them. */
    config?: SourceConfig;
  };
};

export type RemoveConnectionBody = {
  sources: 'keep' | 'delete';
  tools: 'keep' | 'delete';
};

const connectorsService = {
  getCatalog: async (token: string | null) =>
    json(
      await throttledApiClient.get(endpoints.USER.CONNECTORS_CATALOG, token),
    ),
  listConnections: async (token: string | null) =>
    json(await throttledApiClient.get(endpoints.USER.CONNECTIONS, token)),
  getConnection: async (id: string, token: string | null) =>
    json(await apiClient.get(endpoints.USER.CONNECTION(id), token)),
  createConnection: async (
    body: {
      connector_key: string;
      credentials: Record<string, string>;
      label?: string;
    },
    token: string | null,
  ) => json(await apiClient.post(endpoints.USER.CONNECTIONS, body, token)),
  setup: async (
    id: string,
    body: ConnectionSetupBody,
    token: string | null,
    idempotencyKey?: string,
  ) =>
    json(
      await apiClient.post(
        endpoints.USER.CONNECTION_SETUP(id),
        body,
        token,
        idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {},
      ),
    ),
  reconnect: async (
    id: string,
    body: { credentials?: Record<string, string> },
    token: string | null,
  ) =>
    json(
      await apiClient.post(
        endpoints.USER.CONNECTION_RECONNECT(id),
        body,
        token,
      ),
    ),
  /** Name an account ("Alerts bot"); an empty name clears it. */
  renameConnection: async (id: string, name: string, token: string | null) =>
    json(await apiClient.patch(endpoints.USER.CONNECTION(id), { name }, token)),
  disconnect: async (id: string, token: string | null) =>
    json(
      await apiClient.post(endpoints.USER.CONNECTION_DISCONNECT(id), {}, token),
    ),
  remove: async (
    id: string,
    body: RemoveConnectionBody,
    token: string | null,
  ) => json(await apiClient.delete(endpoints.USER.CONNECTION(id), token, body)),
  pickerToken: async (id: string, token: string | null) =>
    json(
      await apiClient.post(
        endpoints.USER.CONNECTION_PICKER_TOKEN(id),
        {},
        token,
      ),
    ),
  repositories: async (id: string, token: string | null) =>
    json(
      await apiClient.get(endpoints.USER.CONNECTION_REPOSITORIES(id), token),
    ),
  /** Linear: the teams and projects a connection can sync. */
  linearWorkspace: async (id: string, token: string | null) =>
    json(await apiClient.get(endpoints.USER.CONNECTION_LINEAR(id), token)),
  refreshTools: async (id: string, token: string | null) =>
    json(
      await apiClient.post(
        endpoints.USER.CONNECTION_REFRESH_TOOLS(id),
        {},
        token,
      ),
    ),
  /** GitHub: let agents make changes through a connection, or only read. */
  setWrites: async (id: string, allow: boolean, token: string | null) =>
    json(
      await apiClient.put(
        endpoints.USER.CONNECTION_WRITES(id),
        { allow },
        token,
      ),
    ),
  setToolPermissions: async (
    id: string,
    toolId: string,
    permissions: Record<string, 'always' | 'ask' | 'off'>,
    token: string | null,
  ) =>
    json(
      await apiClient.put(
        endpoints.USER.CONNECTION_TOOL_PERMISSIONS(id, toolId),
        { permissions },
        token,
      ),
    ),
  /** Fix parameters to a value (`null` lets the AI decide again). */
  setToolParameters: async (
    id: string,
    toolId: string,
    action: string,
    parameters: Record<string, string | number | boolean | null>,
    token: string | null,
  ) =>
    json(
      await apiClient.put(
        endpoints.USER.CONNECTION_TOOL_PARAMETERS(id, toolId),
        { action, parameters },
        token,
      ),
    ),
  setCredentialMode: async (
    toolId: string,
    mode: 'owner' | 'member',
    token: string | null,
  ) =>
    json(
      await apiClient.put(
        endpoints.USER.TOOL_CREDENTIAL_MODE(toolId),
        { mode },
        token,
      ),
    ),
  getAdmin: async (token: string | null) =>
    json(await apiClient.get(endpoints.USER.ADMIN_CONNECTORS, token)),
  updateAdmin: async (body: Record<string, unknown>, token: string | null) =>
    json(await apiClient.put(endpoints.USER.ADMIN_CONNECTORS, body, token)),
  claim: async (provider: string, sessionToken: string, token: string | null) =>
    json(
      await apiClient.post(
        endpoints.USER.CONNECTIONS_CLAIM,
        { provider, session_token: sessionToken },
        token,
      ),
    ),
};

export default connectorsService;
