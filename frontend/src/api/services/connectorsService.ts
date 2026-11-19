import type { ConnectionOwner, ReconnectResult } from '../../connectors/types';
import type { SourceConfig } from '../../models/misc';
import { workspaceHeader } from '../../workspace/requestWorkspace';
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
    /** The caller's Knowledge folder to file the new source into. */
    folder_id?: string;
  };
};

/**
 * Whose list to read. `owner: 'team'` reads the team's connections (any
 * member); `workspace` names the team to send it for, so an answer is filed
 * under the team it was asked for even if the user switches meanwhile.
 */
export type ConnectionListOptions = {
  owner?: ConnectionOwner;
  workspace?: string;
};

/** `POST /api/tools/member`: a team tool on each person's own account. */
export type MemberToolBody = {
  /** A catalog key, or `custom_mcp` with `server_url` for a sign-in server. */
  connector_key: string;
  /** `custom_mcp`: the server each person signs in to (OAuth). */
  server_url?: string;
  /** `custom_mcp`: `auto` (the default), `http` or `sse`. */
  transport_type?: 'auto' | 'http' | 'sse';
  /** `custom_mcp`: the tool's name; the server's host when left out. */
  displayName?: string;
  permissions?: Record<string, 'always' | 'ask' | 'off'>;
  /** The team's Tools folder to file it in. */
  folder_id?: string;
  status?: boolean;
};

/**
 * `{success, id}`, or a refusal: 400 `team_workspace_required`, 409
 * `member_mode_not_allowed`, 409 `connect_personal_first` (with
 * `connector_key`), 502 when the service's actions can't be read.
 */
export type MemberToolResult = {
  success: boolean;
  id?: string;
  error?: string;
  message?: string;
  connector_key?: string;
};

const listUrl = (
  personal: string,
  team: string,
  options: ConnectionListOptions,
) => (options.owner === 'team' ? team : personal);

const listHeaders = (options: ConnectionListOptions) =>
  options.workspace ? workspaceHeader(options.workspace) : {};

export type RemoveConnectionBody = {
  sources: 'keep' | 'delete';
  tools: 'keep' | 'delete';
};

const connectorsService = {
  /** The catalog, its card states worked out for whose list `options` names. */
  getCatalog: async (
    token: string | null,
    options: ConnectionListOptions = {},
  ) =>
    json(
      await throttledApiClient.get(
        listUrl(
          endpoints.USER.CONNECTORS_CATALOG,
          endpoints.USER.CONNECTORS_CATALOG_TEAM,
          options,
        ),
        token,
        listHeaders(options),
      ),
    ),
  /** The caller's own connections, or a team's with `owner: 'team'`. */
  listConnections: async (
    token: string | null,
    options: ConnectionListOptions = {},
  ) =>
    json(
      await throttledApiClient.get(
        listUrl(
          endpoints.USER.CONNECTIONS,
          endpoints.USER.CONNECTIONS_TEAM,
          options,
        ),
        token,
        listHeaders(options),
      ),
    ),
  getConnection: async (id: string, token: string | null) =>
    json(await apiClient.get(endpoints.USER.CONNECTION(id), token)),
  /** Pasted credentials; `owner: 'team'` connects them for the team (Admins). */
  createConnection: async (
    body: {
      connector_key: string;
      credentials: Record<string, string>;
      label?: string;
      owner?: ConnectionOwner;
    },
    token: string | null,
  ) => json(await apiClient.post(endpoints.USER.CONNECTIONS, body, token)),
  /** Adds a team tool that runs on each person's own account (Editors). */
  createMemberTool: async (
    body: MemberToolBody,
    token: string | null,
  ): Promise<MemberToolResult> =>
    json(await apiClient.post(endpoints.USER.CREATE_MEMBER_TOOL, body, token)),
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
  /** Signs a connection in again; see `ReconnectResult` for `replace`. */
  reconnect: async (
    id: string,
    body: { credentials?: Record<string, string> },
    token: string | null,
  ): Promise<ReconnectResult> =>
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
