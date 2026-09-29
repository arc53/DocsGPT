export type ConnectorCategory =
  | 'files'
  | 'knowledge'
  | 'projects'
  | 'dev'
  | 'business'
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
  /** A tool parameter this field sets for every call (Telegram's chat). */
  parameter?: string | null;
  /** English help under the field; translated when the locale has it. */
  hint?: string | null;
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
  /** Its tool can also make changes, when a connection opts in (GitHub). */
  writes_opt_in?: boolean;
  publisher: 'built_in' | 'preset' | 'custom';
  docs_url: string | null;
  oauth_scopes: string[];
  /** Shown under this connector's card (one service offered two ways). */
  part_of?: string | null;
  /**
   * How a user can connect, preferred first. GitHub offers `oauth` (Sign in
   * with GitHub, once an admin sets up the GitHub App) before `api_key`.
   */
  sign_in_methods?: ConnectorAuthKind[];
  available: boolean;
  disabled: boolean;
  needs_setup: boolean;
  missing_settings: string[];
  connected_count: number;
  connection_count: number;
  status: ConnectionStatus | null;
  state: ConnectorCardState;
  credential_policy: 'choose' | CredentialMode;
  /** A connection may opt into changes: offered, and no admin forbade it. */
  writes_allowed?: boolean;
};

export type Connection = {
  id: string;
  connector_key: string;
  name: string;
  display_name: string | null;
  icon: string;
  account_label: string;
  /** What the owner calls the account; `account_label` stays its identity. */
  account_name?: string | null;
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

export type ActionParameter = {
  name: string;
  description: string;
  type: string;
  required: boolean;
  /** Sent with `value` on every call; the AI never sees it. */
  fixed: boolean;
  value: string | number | boolean | null;
  /** Who fixed it: the tool's own setting, or the account (a default chat). */
  set_by?: 'tool' | 'account' | null;
};

export type ConnectionToolAction = {
  name: string;
  description: string;
  access: ActionAccess;
  permission: ActionPermission;
  parameters?: ActionParameter[];
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

/** A repository a GitHub connection can read, for the sync picker. */
export type GitHubRepository = {
  full_name: string;
  private: boolean;
  description: string;
  default_branch: string;
  updated_at: string | null;
  html_url: string;
};

export type ConnectionDetail = Connection & {
  sources: ConnectionSource[];
  tools: ConnectionTool[];
  /**
   * Whether its tool can make changes (GitHub's write endpoint); null when
   * the connector offers no such choice or the tool is not added yet.
   */
  writes?: boolean | null;
};
