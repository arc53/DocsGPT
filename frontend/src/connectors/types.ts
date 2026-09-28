export type ConnectorCategory =
  | 'files'
  | 'knowledge'
  | 'dev'
  | 'messaging'
  | 'database'
  | 'search'
  | 'custom';

export type Capability = 'sync' | 'read' | 'write';

export type ConnectorAuthKind =
  'oauth' | 'mcp_oauth' | 'api_key' | 'none' | 'mcp';

export type ConnectionStatus =
  'connected' | 'reconnect_needed' | 'disconnected' | 'error' | 'pending';

/** What a catalog card shows, worked out on the server. */
export type ConnectorCardState =
  | 'available'
  | 'connected'
  | 'reconnect'
  | 'needs_setup'
  | 'disabled'
  | 'custom';

export type CredentialMode = 'owner' | 'member';

export type CredentialField = {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
};

export type ConnectorDefinition = {
  key: string;
  name: string;
  description: string;
  icon: string;
  category: ConnectorCategory;
  auth_kind: ConnectorAuthKind;
  capabilities: Capability[];
  credential_fields: CredentialField[];
  setup_fields: CredentialField[];
  sync_ingestor: string | null;
  default_sync_frequency: string;
  tool_templates: string[];
  setup: { tools: 'auto' | 'ask' | 'off'; sync: 'auto' | 'ask' | 'off' };
  mcp_url: string | null;
  publisher: 'built_in' | 'preset' | 'custom';
  docs_url: string | null;
  oauth_scopes: string[];
  /** Shown under this connector's card (one service offered two ways). */
  part_of?: string | null;
  available: boolean;
  disabled: boolean;
  needs_setup: boolean;
  missing_settings: string[];
  connected_count: number;
  connection_count: number;
  status: ConnectionStatus | null;
  state: ConnectorCardState;
  credential_policy: 'choose' | CredentialMode;
};

export type Connection = {
  id: string;
  connector_key: string;
  name: string;
  display_name: string | null;
  icon: string;
  account_label: string;
  auth_kind: ConnectorAuthKind | null;
  status: ConnectionStatus;
  server_url: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
  last_used_at: string | null;
  source_count: number;
  tool_count: number;
};

export type ActionAccess = 'read' | 'write';
export type ActionPermission = 'always' | 'ask' | 'off';

export type ConnectionToolAction = {
  name: string;
  description: string;
  access: ActionAccess;
  permission: ActionPermission;
};

export type ConnectionTool = {
  id: string;
  name: string;
  display_name: string;
  status: boolean;
  credential_mode: CredentialMode;
  actions: ConnectionToolAction[];
};

export type ConnectionSource = {
  id: string;
  name: string;
  type: string;
  last_sync: string | null;
  sync_frequency: string;
  sync_state: 'active' | 'paused_reconnect';
};

export type ConnectionDetail = Connection & {
  sources: ConnectionSource[];
  tools: ConnectionTool[];
};
